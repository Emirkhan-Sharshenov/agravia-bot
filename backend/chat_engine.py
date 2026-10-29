"""
Единая логика диалога.

  запрос -> тема, роль, проект и язык (router.py, LLM, с учётом состояния) ->
  при необходимости ОДНО уточнение -> маршрут:
      • шаблонный ответ со ссылкой из routes.py (билет, заявка, каталог, программа…) —
        без выдумок и без вызова ответной модели;
      • либо факты базы знаний по теме и роли -> короткий ответ модели без Markdown;
  -> только если по теме данных нет — честное "данных нет" и контакт организатора.

Состояние диалога явное и хранится на клиенте (виджет присылает его обратно каждым
запросом, Алиса держит у себя в сессии):
    {"role": visitor|exhibitor|prospect|builder|None,   # роль автора сообщений
     "project": agravia|iagri|None,                    # о каком проекте идёт речь
     "intent": тема прошлого хода,
     "pending": None | {"kind": "role"|"topic", "intent": тема, по которой спросили}}
Роль сохраняется, пока пользователь не назовёт другую (в том числе исправлением
"нет, я про билет"); вопрос "за коллегу" роль автора не меняет. Повторно то же
уточнение не задаётся — после одного вопроса бот отвечает или честно говорит, что
данных нет.

Персональные данные (e-mail, телефоны) маскируются перед отправкой в модель
(privacy.py). Используется и вебхуком сайта (main.py), и навыком Алисы (alice.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import analytics
import handoff
import kb_store
import llm
import privacy
import retrieval
import router
import routes
from text_format import clean_markdown, shorten

ROLE_QUESTIONS = {
    "pass": {
        "ru": "Уточните, пожалуйста: пропуск нужен посетителю, экспоненту или для монтажа/демонтажа?",
        "en": "Please clarify: is the pass for a visitor, an exhibitor, or for set-up/dismantling?",
    },
    "badge": {
        "ru": "Уточните, пожалуйста: бейдж нужен посетителю или экспоненту?",
        "en": "Please clarify: is the badge for a visitor or an exhibitor?",
    },
    "entry": {
        "ru": "Уточните, пожалуйста: вы спрашиваете про заезд экспонентов, монтажной команды или завоз оборудования?",
        "en": "Please clarify: do you mean arrival of exhibitors, the set-up crew, or bringing in equipment?",
    },
}
ROLE_ACK = {
    "visitor": "Хорошо, вы посетитель. Могу помочь с билетом и регистрацией, как добраться, деловой программой.",
    "exhibitor": "Хорошо, вы экспонент. Могу помочь с монтажом и заездом, пропусками, ввозом оборудования, личным кабинетом.",
    "prospect": "Хорошо, вы хотите принять участие. Могу подсказать, как подать заявку на стенд.",
    "builder": "Хорошо, вы застройщик. Могу помочь с монтажом, допуском на площадку и пропусками.",
}
TOPIC_CLARIFY_REPLY = {
    "ru": "Не уверена, что правильно поняла вопрос. Уточните, пожалуйста: речь о посещении выставки, об участии "
          "со стендом, о поиске компании или продукции, о монтаже и заезде или о деловой программе?",
    "en": "I'm not sure I understood. Is it about visiting, exhibiting with a stand, finding a company or "
          "product, set-up logistics, or the business program?",
}
OFFER_CONTACT = {
    "ru": "Или оставьте контакт — менеджер свяжется с вами.",
    "en": "Or leave your contact — a manager will get in touch.",
}
OFFER_QUESTION = {
    "ru": "Могу передать вопрос менеджеру — он свяжется с вами.",
    "en": "I can pass your question to a manager — they will contact you.",
}

# Подсказки для ответной модели по теме — общие требования к содержанию, не
# привязанные к конкретным формулировкам вопросов.
INTENT_HINTS = {
    "ticket_info": "Отвечай только на заданное по правилам билета. Не пересказывай всю процедуру регистрации.",
    "cabinet": "Ссылку на кабинет не придумывай: если её нет в данных — скажи об этом и дай то, что есть.",
    "montage": (
        "Монтаж (сборка и застройка стендов) — это подготовка ДО открытия выставки. Даты и "
        "порядок — только из данных; если нужной даты или режима нет, скажи об этом."
    ),
    "demontage": (
        "Демонтаж (разборка стендов) — после закрытия выставки. Даты и порядок — только из "
        "данных; если нужной даты или режима нет, скажи об этом."
    ),
    "equipment_in": (
        "Завоз оборудования происходит в дни монтажа; для автомобиля в зону ПРР нужен платный "
        "пропуск. Порядок и документы — только из данных, без выводов о том, когда лучше привозить."
    ),
    "equipment_out": (
        "Конкретные часы вывоза не называй (утверждённого графика нет): скажи, что вывоз возможен "
        "только после закрытия выставки для посетителей, и что точный график уточняется у организатора."
    ),
    "pass": "Дай понятную инструкцию, как получить такой пропуск, только по данным.",
    "general": (
        "Если спрашивают про АГРОС/АГРОТЕХ — корректно объясни объединение брендов в AGRAVIA, не "
        "объявляй выставку закрытой. Про общий доступ на AGRAVIA и iAGRI — по одному билету, но не "
        "обещай, что можно осмотреть всё за один день."
    ),
}

_DIRECT_TOPICS = {
    "location": ["location"],
    "ticket_info": ["visitor_reg"],
    "montage": ["montage"],
    "demontage": ["demontage"],
    "equipment_in": ["equipment_in"],
    "equipment_out": ["equipment_out"],
    "cabinet": ["cabinet"],
    "general": ["general"],
}

MAX_CANDIDATES = 6
MAX_HISTORY = 8
# Без модели ответ берём дословно из базы только при почти точном совпадении с
# вопросом (иначе fuzzy легко подсовывает соседний, но неверный факт).
DEGRADED_MIN_SCORE = float(os.environ.get("DEGRADED_MIN_SCORE", "0.9"))
DEGRADED_TOPIC_MIN_SCORE = float(os.environ.get("DEGRADED_TOPIC_MIN_SCORE", "0.7"))
BRIEF_LIMIT = 220

_MONTHS = (
    ("феврал", "феврале"), ("март", "марте"), ("апрел", "апреле"), ("мая", "мае"),
    ("июн", "июне"), ("июл", "июле"), ("август", "августе"), ("сентябр", "сентябре"),
    ("октябр", "октябре"), ("ноябр", "ноябре"), ("декабр", "декабре"),
)


def topics_for(intent: str, role: str | None) -> list[str]:
    """Какие темы базы (поле topics в kb.json) отвечают за интент при данной роли."""
    if intent in ("pass", "badge"):
        by_role = {"exhibitor": ["pass_exhibitor"], "builder": ["pass_builder"]}
        return by_role.get(role or "", ["pass_exhibitor", "pass_builder"])
    if intent == "entry":
        return ["entry"]
    if intent == "vehicle_access":
        # Парковка "практически всегда посетитель" (ТЗ 28.10): без роли — про
        # парковку посетителей; экспоненту/застройщику — про транспорт и ПРР.
        return ["vehicle"] if role in ("exhibitor", "builder", "prospect") else ["visitor_car"]
    return _DIRECT_TOPICS.get(intent, [])


def segments_for_role(role: str | None) -> set[str] | None:
    if role == "visitor":
        return {"visitor", "common"}
    if role in ("exhibitor", "builder", "prospect"):
        return {"exhibitor", "common"}
    return None  # роль неизвестна — ищем по всей базе


def _legacy_segment(role: str | None, pending: bool) -> str:
    if role == "visitor":
        return "visitor"
    if role in ("exhibitor", "builder", "prospect"):
        return "exhibitor"
    return "uncertain" if pending else "common"


@dataclass
class EngineResult:
    reply: str
    segment: str
    intent: str | None
    role: str | None
    confidence: str  # HIGH — ответили, MEDIUM — уточнили, LOW — данных нет
    matched: bool
    clarified: bool
    fallback: bool
    offer_manager: bool
    state: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)  # диагностика (ошибки провайдера), не для пользователя


def normalize_state(state: dict | None, segment_hint: str | None = None) -> dict:
    """Приводит присланное клиентом состояние к безопасному виду. Старые клиенты
    присылали только segment_hint — из него берём роль."""
    state = state if isinstance(state, dict) else {}
    role = state.get("role")
    if role not in router.ROLES:
        role = segment_hint if segment_hint in ("visitor", "exhibitor") else None
    pending = state.get("pending")
    if not (isinstance(pending, dict) and pending.get("kind") in ("role", "topic")):
        pending = None
    intent = state.get("intent") if state.get("intent") in router.INTENT_DESCRIPTIONS else None
    project = state.get("project") if state.get("project") in router.PROJECTS else None
    return {"role": role, "intent": intent, "pending": pending, "project": project}


def _result(reply, intent, role, confidence, *, state, matched=False, clarified=False,
            fallback=False, offer_manager=False) -> EngineResult:
    return EngineResult(
        reply=reply,
        segment=_legacy_segment(role, state.get("pending") is not None),
        intent=intent,
        role=role,
        confidence=confidence,
        matched=matched,
        clarified=clarified,
        fallback=fallback,
        offer_manager=offer_manager,
        state=state,
    )


def _wrong_month_prefix(message: str, lang: str) -> str:
    """"Выставка в феврале?" — уверенно называем верные даты, а не подстраиваемся."""
    if lang != "ru":
        return ""
    low = message.lower()
    for stem, prepositional in _MONTHS:
        if stem in low:
            return f"Не в {prepositional}: "
    return ""


def handle_message(
    session_id: str,
    message: str,
    history: list[dict] | None = None,
    state: dict | None = None,
    segment_hint: str | None = None,
) -> EngineResult:
    history = (history or [])[-MAX_HISTORY:]
    state = normalize_state(state, segment_hint)

    # В модель уходит только замаскированный текст (e-mail/телефоны -> заглушки).
    safe_message = privacy.redact(message)
    safe_history = privacy.redact_history(history)

    notes: list[str] = []
    degraded = False
    try:
        route = router.classify(safe_message, safe_history, state)
    except Exception as exc:
        # Модель недоступна (лимит провайдера, сеть, нечитаемый ответ) — не падаем:
        # основные коммерческие маршруты определяем по корням слов, остальное ищем по
        # базе без LLM и отдаём подтверждённый факт как есть (см. _from_kb).
        degraded = True
        notes.append(f"router: {exc!r}"[:500])
        route = router.fallback_classify(message) or router.Route(
            intent="other", role=None, lang=router.detect_lang(message)
        )

    intent = route.intent
    if intent != "secrets" and router.mentions_secret(message):
        # безопасность важнее классификации: пароль/код из СМС в сообщении -> предупреждение
        intent = "secrets"
    if route.for_other:
        # вопрос "за коллегу": роль этого человека действует только в этом ответе,
        # роль автора диалога не меняется
        eff_role, author_role = route.role, state["role"]
    else:
        eff_role = route.role or state["role"]
        author_role = eff_role
    if eff_role is None and intent in router.ROLE_DEPENDENT:
        # Страховка: тип пропуска/бейджа или роль названы словом в самом сообщении,
        # а LLM на низких рассуждениях это пропустила.
        eff_role = router.role_from_words(message)
        if not route.for_other:
            author_role = eff_role

    pending = state["pending"]
    # Ответ на наш уточняющий вопрос ("Я экспонент") — это ответ по ТОЙ же теме, о
    # которой спрашивали, а не новая тема role_only.
    if pending and intent == "role_only":
        intent = pending["intent"]

    project = route.project or state["project"]
    ctx = {
        "message": message, "history": safe_history, "safe_message": safe_message,
        "pending": pending, "lang": route.lang, "brief": route.brief, "degraded": degraded,
        "eff_role": eff_role, "notes": notes,
        "new_state": {"role": author_role, "intent": intent, "pending": None, "project": project},
    }
    out = _route(intent, ctx)
    out.notes = notes
    _log(session_id, out, message)
    return out


def _route(intent: str, ctx: dict) -> EngineResult:
    lang, eff_role, new_state = ctx["lang"], ctx["eff_role"], ctx["new_state"]
    author_role = new_state["role"]

    def reply_template(key: str, *, confidence="HIGH", matched=True, clarified=False,
                       prefix="", suffix="", offer=False) -> EngineResult:
        text = prefix + routes.render(key, lang)
        if suffix:
            text = f"{text} {suffix}"
        return _result(text, intent, author_role, confidence, state=new_state, matched=matched,
                       clarified=clarified, offer_manager=offer)

    # --- Не по базе: приветствие, помощь, вне темы, мусор, только роль ------
    if intent in ("greeting", "offtopic"):
        return reply_template(intent)
    if intent == "gibberish":
        return reply_template("gibberish", confidence="MEDIUM", matched=False)
    if intent == "help" or (intent == "role_only" and eff_role is None):
        return reply_template("help", confidence="MEDIUM", matched=False, clarified=True)
    if intent == "role_only":
        return _result(ROLE_ACK[eff_role], intent, author_role, "HIGH", state=new_state, matched=True)

    # --- Пропуск/бейдж/заезд: роль известна -> прямой маршрут ----------------
    if intent in router.ROLE_DEPENDENT:
        if eff_role == "visitor":
            intent = "visitor_registration"
        elif eff_role == "prospect":
            intent = "participation"
        elif eff_role is None and not ctx["pending"]:
            new_state["pending"] = {"kind": "role", "intent": intent}
            return _result(ROLE_QUESTIONS[intent][lang], intent, author_role, "MEDIUM",
                           state=new_state, clarified=True)
    new_state["intent"] = intent

    # --- Шаблонные маршруты со ссылками (routes.py) -----------------------------
    if intent in routes.TEMPLATE_INTENTS:
        key, prefix, suffix, offer = intent, "", "", False
        if intent == "visitor_registration" and new_state["project"] == "iagri":
            key = "iagri_registration"
        elif intent == "dates":
            prefix = _wrong_month_prefix(ctx["message"], lang)
        elif intent == "contact" and handoff.is_configured():
            suffix, offer = OFFER_CONTACT[lang], True
        elif intent == "materials":
            new_state["pending"] = {"kind": "topic", "intent": "materials"}
            return reply_template(key, confidence="MEDIUM", matched=False, clarified=True)
        return reply_template(key, prefix=prefix, suffix=suffix, offer=offer)

    # --- Факты базы знаний -------------------------------------------------------
    return _kb_answer(intent, ctx)


def _kb_answer(intent: str, ctx: dict) -> EngineResult:
    lang, eff_role, new_state = ctx["lang"], ctx["eff_role"], ctx["new_state"]
    author_role = new_state["role"]
    message, history, degraded = ctx["safe_message"], ctx["history"], ctx["degraded"]
    pending, notes = ctx["pending"], ctx["notes"]

    if intent == "other":
        candidates, low = retrieval.rank(message, history, segments=segments_for_role(eff_role))
        threshold = max(low, DEGRADED_MIN_SCORE) if degraded else low
        if not candidates or candidates[0].score < threshold:
            if degraded:  # без модели не поняли — не гоняем пользователя по кругу уточнений
                return _unavailable(intent, author_role, new_state, lang)
            if pending:  # уже уточняли — честно говорим, что данных нет
                return _no_data(intent, author_role, new_state, lang)
            new_state["pending"] = {"kind": "topic", "intent": intent}
            return _result(TOPIC_CLARIFY_REPLY[lang], intent, author_role, "MEDIUM",
                           state=new_state, clarified=True)
    else:
        items = kb_store.items_for_topics(topics_for(intent, eff_role))
        if not items:
            return _no_data(intent, author_role, new_state, lang)
        candidates, _ = retrieval.rank(message, history, items=items)

    candidates = candidates[:MAX_CANDIDATES]
    if degraded:
        return _from_kb(candidates, intent, author_role, new_state, lang)

    hint, brief = INTENT_HINTS.get(intent, ""), ctx["brief"]
    try:
        answer = llm.answer(eff_role, message, candidates, history, hint, lang=lang, brief=brief)
        if answer is None and intent != "other":
            # Тема определена и факты отобраны по ней: "данных нет" почти всегда лишняя
            # осторожность модели. Повторяем с запретом NO_MATCH — пусть скажет, чего
            # именно нет, и даст ближайшее из данных.
            answer = llm.answer(eff_role, message, candidates, history, hint,
                                allow_no_match=False, lang=lang, brief=brief)
    except Exception as exc:
        notes.append(f"answer: {exc!r}"[:500])
        return _from_kb(candidates, intent, author_role, new_state, lang)
    if answer is None:
        return _no_data(intent, author_role, new_state, lang)
    return _answer_result(answer, intent, author_role, new_state, lang, brief)


def _answer_result(text, intent, role, state, lang, brief=False) -> EngineResult:
    reply = clean_markdown(text)
    reply = shorten(reply, BRIEF_LIMIT if brief else 650)
    extra = routes.link_after(intent, lang)
    if extra and extra.split(": ", 1)[-1] not in reply:  # ссылка уже в ответе — не дублируем
        reply = f"{reply}\n\n{extra}"
    return _result(reply, intent, role, "HIGH", state=state, matched=True)


def _from_kb(candidates, intent, role, state, lang) -> EngineResult:
    """Режим без модели: самый близкий подтверждённый факт базы дословно. Ничего не
    выдумываем и не оставляем пользователя без ответа, если провайдер LLM недоступен."""
    if not candidates or candidates[0].score < DEGRADED_TOPIC_MIN_SCORE:
        return _unavailable(intent, role, state, lang)
    return _answer_result(candidates[0].answer, intent, role, state, lang)


def _no_data(intent, role, state, lang) -> EngineResult:
    # Менеджера предлагаем только если заявка реально дойдёт (ТЗ 28.10, п.6.4)
    offer = handoff.is_configured()
    text = routes.render("no_data", lang) + (f" {OFFER_QUESTION[lang]}" if offer else "")
    return _result(text, intent, role, "LOW", state=state, fallback=True, offer_manager=offer)


def _unavailable(intent, role, state, lang) -> EngineResult:
    offer = handoff.is_configured()
    text = routes.render("unavailable", lang) + (f" {OFFER_QUESTION[lang]}" if offer else "")
    return _result(text, intent, role, "LOW", state=state, fallback=True, offer_manager=offer)


def error_result(state: dict | None) -> EngineResult:
    """Ответ на случай внутренней ошибки (вызывает main.py). Технических деталей
    пользователю не показываем (ТЗ 28.10, п.6.3)."""
    state = normalize_state(state)
    return _unavailable("error", state["role"], state, "ru")


def _log(session_id: str, out: EngineResult, message: str) -> None:
    analytics.log_event(
        session_id=session_id,
        segment=out.segment,
        intent=out.intent,
        confidence=out.confidence,
        matched=out.matched,
        clarified=out.clarified,
        fallback=out.fallback,
    )
    if out.fallback:
        analytics.log_unanswered(
            query=privacy.redact(message),
            segment=out.segment,
            closest_intent=out.intent,
            confidence=out.confidence,
        )
