"""
Единая логика диалога (ТЗ v2, раздел 2):

  запрос -> тема и роль (router.py, LLM, с учётом состояния диалога) ->
  при необходимости ОДНО уточнение -> факты базы по теме и роли -> короткий
  ответ без Markdown -> только если по теме в базе ничего нет, честное
  "данных нет" и предложение менеджера.

Состояние диалога явное и хранится на клиенте (виджет присылает его обратно
каждым запросом, Алиса держит у себя в сессии):
    {"role": visitor|exhibitor|prospect|builder|None,
     "intent": тема прошлого хода,
     "pending": None | {"kind": "role"|"topic", "intent": тема, по которой спросили}}
Роль, однажды определённая, сохраняется, пока пользователь не назовёт другую
(в том числе исправлением "нет, я про билет"); повторно то же уточнение не
задаётся — после одного вопроса бот отвечает или честно говорит, что данных нет.

Используется и вебхуком сайта (main.py), и навыком Алисы (alice.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import analytics
import kb_store
import llm
import retrieval
import router
from text_format import clean_markdown

NO_DATA_REPLY = (
    "В моих данных нет подтверждённой информации по этому вопросу. "
    "Могу передать его менеджеру — он свяжется с вами."
)
ERROR_REPLY = (
    "Сейчас я не могу ответить на этот вопрос. Оставьте, пожалуйста, контакт — "
    "менеджер свяжется с вами."
)
GREETING_REPLY = (
    "Здравствуйте! Я помощник AGRAVIA. Помогу с посещением выставки, участием, "
    "монтажом и логистикой, деловой программой. Что вас интересует?"
)
OFFTOPIC_REPLY = (
    "Это вне моей темы — я помогаю по вопросам выставки AGRAVIA 2027: даты и место, "
    "билеты и регистрация, участие и стенды, монтаж и заезд, деловая программа. "
    "С чем помочь?"
)
HELP_REPLY = (
    "Подскажите, что вам нужно: прийти на выставку как посетитель, участвовать как "
    "экспонент, монтаж и заезд или деловая программа?"
)
GIBBERISH_REPLY = (
    "Не поняла запрос. Попробуйте переформулировать — например, про даты, билеты, "
    "участие или монтаж."
)
TOPIC_CLARIFY_REPLY = (
    "Не уверена, что правильно поняла вопрос. Уточните, пожалуйста: речь о посещении "
    "выставки, об участии в ней, о монтаже и заезде или о деловой программе?"
)
ROLE_QUESTIONS = {
    "pass": "Уточните, пожалуйста: пропуск нужен посетителю, экспоненту или для монтажа/демонтажа?",
    "badge": "Уточните, пожалуйста: бейдж нужен посетителю или экспоненту?",
    "entry": "Уточните, пожалуйста: вы спрашиваете про заезд экспонентов, монтажной команды или завоз оборудования?",
    "vehicle_access": "Уточните, пожалуйста: вы приезжаете как посетитель (парковка) или везёте оборудование на стенд?",
}
ROLE_ACK = {
    "visitor": "Хорошо, вы посетитель. Могу помочь с билетом и регистрацией, как добраться, деловой программой.",
    "exhibitor": "Хорошо, вы экспонент. Могу помочь с монтажом и заездом, пропусками, ввозом оборудования, личным кабинетом.",
    "prospect": "Хорошо, вы хотите принять участие. Могу рассказать, как это оформить, и передать заявку менеджеру.",
    "builder": "Хорошо, вы застройщик. Могу помочь с монтажом, допуском на площадку и пропусками.",
}
OFFER_MANAGER_SUFFIX = {
    "participation": "Хотите, передам вашу заявку менеджеру?",
    "contact": "Могу также передать ваш вопрос менеджеру — он свяжется с вами.",
}

# Подсказки для ответной модели по теме — общие требования к содержанию,
# не привязанные к конкретным формулировкам вопросов.
INTENT_HINTS = {
    "participation": (
        "Пользователь хочет стать участником. Дай подтверждённый путь: связаться с "
        "организатором (контакты есть в данных). Цен, условий оплаты и формы заявки в "
        "данных может не быть — тогда прямо скажи, что их в данных нет, и не называй сумм. "
        "Не рассказывай про пропуска, страхование и конкурсы."
    ),
    "visitor_registration": "Это сценарий посетителя: дай инструкцию по билету/регистрации и сайт из данных.",
    "dates": "Дай даты проведения (и часы работы, если спрошено).",
    "contact": "Дай подтверждённые контакты организатора из данных.",
    "business_program": (
        "Не придумывай расписание и время мероприятий: если расписания по дням в данных "
        "нет — скажи об этом и дай то, что есть."
    ),
    "cabinet": "Ссылку на кабинет не придумывай: если её нет в данных — скажи об этом и дай то, что есть.",
    "montage": "Даты и порядок — только из данных; если нужной даты или режима нет, скажи об этом.",
    "demontage": "Даты и порядок — только из данных; если нужной даты или режима нет, скажи об этом.",
    "equipment_in": "Порядок и документы — только из данных; не выдумывай недостающее.",
    "equipment_out": "Порядок и сроки — только из данных; не выдумывай недостающее.",
}

_DIRECT_TOPICS = {
    "dates": ["dates"],
    "location": ["location"],
    "visitor_registration": ["visitor_reg"],
    "participation": ["participation"],
    "montage": ["montage"],
    "demontage": ["demontage"],
    "equipment_in": ["equipment_in"],
    "equipment_out": ["equipment_out"],
    "business_program": ["program"],
    "cabinet": ["cabinet"],
    "contact": ["contact"],
    "general": ["general"],
}

MAX_CANDIDATES = 8
MAX_HISTORY = 8


def topics_for(intent: str, role: str | None) -> list[str]:
    """Какие темы базы (поле topics в kb.json) отвечают за интент при данной роли."""
    if intent in ("pass", "badge"):
        by_role = {
            "visitor": ["visitor_reg"],
            "exhibitor": ["pass_exhibitor"],
            "builder": ["pass_builder"],
            "prospect": ["participation"],
        }
        return by_role.get(role or "", ["visitor_reg", "pass_exhibitor", "pass_builder"])
    if intent == "entry":
        if role == "visitor":
            return ["visitor_reg"]
        if role == "prospect":
            return ["participation"]
        return ["entry"]
    if intent == "vehicle_access":
        if role == "visitor":
            return ["visitor_car"]
        if role in ("exhibitor", "builder", "prospect"):
            return ["vehicle"]
        return ["vehicle", "visitor_car"]
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


def normalize_state(state: dict | None, segment_hint: str | None = None) -> dict:
    """Приводит присланное клиентом состояние к безопасному виду. Старые
    клиенты присылали только segment_hint — из него берём роль."""
    state = state if isinstance(state, dict) else {}
    role = state.get("role")
    if role not in router.ROLES:
        role = segment_hint if segment_hint in ("visitor", "exhibitor") else None
    pending = state.get("pending")
    if not (isinstance(pending, dict) and pending.get("kind") in ("role", "topic")):
        pending = None
    intent = state.get("intent") if state.get("intent") in router.INTENT_DESCRIPTIONS else None
    return {"role": role, "intent": intent, "pending": pending}


def _result(reply, intent, role, confidence, *, state, matched=False, clarified=False,
            fallback=False, offer_manager=False) -> EngineResult:
    pending = state.get("pending")
    return EngineResult(
        reply=reply,
        segment=_legacy_segment(role, pending is not None),
        intent=intent,
        role=role,
        confidence=confidence,
        matched=matched,
        clarified=clarified,
        fallback=fallback,
        offer_manager=offer_manager,
        state=state,
    )


def handle_message(
    session_id: str,
    message: str,
    history: list[dict] | None = None,
    state: dict | None = None,
    segment_hint: str | None = None,
) -> EngineResult:
    history = (history or [])[-MAX_HISTORY:]
    state = normalize_state(state, segment_hint)

    try:
        route = router.classify(message, history, state)
        intent, role = route.intent, route.role or state["role"]
    except Exception:
        # Классификатор недоступен/ответил нечитаемо — не падаем: ведём как
        # обычный вопрос по базе с ранее известной ролью.
        intent, role = "other", state["role"]

    pending = state["pending"]
    # Ответ на наш уточняющий вопрос ("Я экспонент") — это ответ по ТОЙ же
    # теме, о которой спрашивали, а не новая тема role_only.
    if pending and intent == "role_only":
        intent = pending["intent"]

    out = _route(session_id, message, history, state, intent, role)
    _log(session_id, out, message)
    return out


def _route(session_id, message, history, state, intent, role) -> EngineResult:
    pending = state["pending"]
    new_state = {"role": role, "intent": intent, "pending": None}

    # --- Не по базе: приветствие, помощь, вне темы, мусор, только роль ------
    if intent == "greeting":
        return _result(GREETING_REPLY, intent, role, "HIGH", state=new_state, matched=True)
    if intent == "gibberish":
        return _result(GIBBERISH_REPLY, intent, role, "MEDIUM", state=new_state)
    if intent == "offtopic":
        # Не отправляем к менеджеру автоматически (ТЗ 3.7) — возвращаем к теме.
        return _result(OFFTOPIC_REPLY, intent, role, "HIGH", state=new_state, matched=True)
    if intent == "help" or (intent == "role_only" and role is None):
        return _result(HELP_REPLY, intent, role, "MEDIUM", state=new_state, clarified=True)
    if intent == "role_only":
        return _result(ROLE_ACK[role], intent, role, "HIGH", state=new_state, matched=True)

    # --- Роль определяет ответ, а она неизвестна: одно уточнение ------------
    if intent in router.ROLE_DEPENDENT and role is None and not pending:
        new_state["pending"] = {"kind": "role", "intent": intent}
        return _result(
            ROLE_QUESTIONS[intent], intent, role, "MEDIUM", state=new_state, clarified=True
        )

    # --- Факты базы -----------------------------------------------------------
    if intent == "other":
        segments = segments_for_role(role)
        candidates, low = retrieval.rank(message, history, segments=segments)
        if not candidates or candidates[0].score < low:
            if pending:  # уже уточняли — честно говорим, что данных нет
                return _no_data(intent, role, new_state)
            new_state["pending"] = {"kind": "topic", "intent": intent}
            return _result(
                TOPIC_CLARIFY_REPLY, intent, role, "MEDIUM", state=new_state, clarified=True
            )
    else:
        topics = topics_for(intent, role)
        items = kb_store.items_for_topics(topics)
        if not items:
            return _no_data(intent, role, new_state)
        candidates, _ = retrieval.rank(message, history, items=items)

    candidates = candidates[:MAX_CANDIDATES]
    answer = llm.answer(role, message, candidates, history, INTENT_HINTS.get(intent, ""))
    if answer is None:
        return _no_data(intent, role, new_state)

    reply = clean_markdown(answer)
    suffix = OFFER_MANAGER_SUFFIX.get(intent)
    if suffix:
        reply = f"{reply}\n\n{suffix}"
    return _result(
        reply, intent, role, "HIGH", state=new_state, matched=True, offer_manager=bool(suffix)
    )


def _no_data(intent, role, state) -> EngineResult:
    return _result(
        NO_DATA_REPLY, intent, role, "LOW", state=state, fallback=True, offer_manager=True
    )


def error_result(state: dict | None) -> EngineResult:
    """Ответ на случай, когда LLM-провайдер недоступен (вызывает main.py)."""
    state = normalize_state(state)
    return _result(
        ERROR_REPLY, "error", state["role"], "LOW", state=state, fallback=True, offer_manager=True
    )


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
            query=message,
            segment=out.segment,
            closest_intent=out.intent,
            confidence=out.confidence,
        )
