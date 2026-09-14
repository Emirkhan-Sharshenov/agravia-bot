"""
Единая логика диалога (раздел 3 ТЗ AI-бот AGRAVIA 2027):

  сообщение → сегментация (без обязательного выбора роли) → учёт истории →
  семантический поиск → confidence → ответ / уточнение / fallback

Используется и вебхуком сайта (main.py: /api/chat), и навыком Алисы
(alice.py), чтобы поведение не расходилось между каналами.

Итерация "состояние и маршрутизация" (2026-09-14, фидбэк Егора):
  - segment_hint — роль, уже установленная в этом диалоге (фронтенд
    присылает её обратно, main.py/alice.py прокидывают сюда), чтобы
    короткие follow-up-вопросы не переопределяли роль с нуля.
  - Запрет повторного уточнения подряд: если предыдущий ход бота уже был
    уточняющим вопросом (retrieval.last_bot_turn_is_clarifying), система
    обязана в этот раз либо ответить, либо признать, что данных нет —
    не задавать второй уточняющий вопрос подряд.
  - Коммерческий intent "хочу стать экспонентом" маршрутизируется
    отдельно от обычного RAG по базе (см. _BECOME_EXHIBITOR_*), чтобы не
    попадать в несвязанные конкретные FAQ (конкурс продукции, пропуска и
    т.п.) только по совпадению слова "участие".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import analytics
import llm
import retrieval

NO_MATCH_REPLY = (
    "К сожалению, у меня нет подтверждённой информации по этому вопросу.\n"
    "Хотите, я передам его менеджеру? Он свяжется с вами."
)

ROLE_CLARIFY_REPLY = (
    "Уточните, пожалуйста: вы посетитель выставки или экспонент (участник)?"
)

# Раздел 10 ТЗ ожидает КОРОТКИЙ уточняющий вопрос, но если LLM вдруг вернёт
# пустую строку (например, reasoning-модель израсходовала весь бюджет
# токенов на скрытые рассуждения, не оставив ничего на сам ответ) — лучше
# показать общий вопрос, чем пустое сообщение в чате.
GENERIC_CLARIFY_REPLY = (
    "Уточните, пожалуйста, ваш вопрос — так я смогу подобрать точный ответ."
)

# --- Коммерческий intent "стать экспонентом" ------------------------------
# Не КБ-факт, а маршрутизация: фразы явно о намерении САМОГО пользователя
# стать участником выставки. Не путать с нейтральными вопросами вроде
# "условия участия?" без такой рамки — для них по-прежнему работает
# обычная (в т.ч. ролевая) логика ниже, раз это неоднозначно само по себе.
_BECOME_EXHIBITOR_TRIGGERS = [
    "хочу стать участником", "хочу стать экспонентом", "хочу принять участие",
    "как принять участие", "хочу стенд", "хочу выставиться", "хочу участвовать",
    "стать экспонентом", "стать участником выставки", "участвовать в выставке",
    "сколько стоит участие", "стоимость участия",
]
_BECOME_EXHIBITOR_PATTERN = re.compile(
    "|".join(re.escape(p) for p in _BECOME_EXHIBITOR_TRIGGERS), re.IGNORECASE
)

BECOME_EXHIBITOR_PITCH = (
    "Да, вы можете принять участие в AGRAVIA 2027 со стендом. Расскажу об основных "
    "форматах и передам заявку менеджеру для точного расчёта.\n"
    "Подскажите, пожалуйста: вас интересует готовый стенд (оборудованная площадь) "
    "или необорудованная площадь под индивидуальную застройку?"
)
# Используется и как ответ, и как маркер "мы в этом сценарии" для
# следующего хода (см. _in_become_exhibitor_flow) — фраза должна быть
# достаточно специфичной, чтобы не совпасть случайно с чем-то другим.
_BECOME_EXHIBITOR_FLOW_MARKER = "необорудованная площадь под индивидуальную застройку"

BECOME_EXHIBITOR_FOLLOWUP = (
    "Понял, спасибо! Чтобы посчитать точные условия и стоимость участия, "
    "давайте я передам заявку менеджеру — он свяжется с вами и уточнит детали."
)


def _is_become_exhibitor_trigger(message: str) -> bool:
    return bool(_BECOME_EXHIBITOR_PATTERN.search(message))


def _in_become_exhibitor_flow(history: list[dict] | None) -> bool:
    for turn in reversed(history or []):
        if turn.get("role") == "assistant":
            return _BECOME_EXHIBITOR_FLOW_MARKER in turn.get("content", "")
    return False


# "Условия участия?" сам по себе, без рамки "я хочу..."/"как экспоненту"
# (это уже покрыто become_exhibitor выше) — реально двусмысленная фраза:
# может спрашивать и посетитель (условия посещения), и потенциальный
# экспонент. Обычная content-логика её не ловит как ролевую неоднозначность
# (visitor почти не имеет совпадений, exhibitor — слабо, но не "близко" к
# visitor, поэтому эвристика относительной близости молчит). Узкий паттерн
# только на "голую" фразу, чтобы не задевать другие вопросы.
_GENERIC_PARTICIPATION_PATTERN = re.compile(
    r"^\s*услови[а-яё]*\s+участи[а-яё]*\s*\??\s*$|^\s*участи[а-яё]*\s*\??\s*$",
    re.IGNORECASE,
)


def _is_generic_participation_phrase(message: str) -> bool:
    return bool(_GENERIC_PARTICIPATION_PATTERN.match(message))


@dataclass
class EngineResult:
    reply: str
    segment: str
    intent: str | None
    confidence: str
    matched: bool
    clarified: bool
    fallback: bool


def _answer_or_fallback(
    segment: str, message: str, candidates, history: list[dict], top_intent: str | None
) -> EngineResult:
    """HIGH-тир: спросить LLM ответ по текущим кандидатам, иначе fallback."""
    answer = llm.answer(segment, message, candidates, history=history)
    if answer is None:
        return EngineResult(
            reply=NO_MATCH_REPLY,
            segment=segment,
            intent=top_intent,
            confidence="LOW",
            matched=False,
            clarified=False,
            fallback=True,
        )
    return EngineResult(
        reply=answer,
        segment=segment,
        intent=top_intent,
        confidence="HIGH",
        matched=True,
        clarified=False,
        fallback=False,
    )


def handle_message(
    session_id: str,
    message: str,
    history: list[dict] | None = None,
    segment_hint: str | None = None,
) -> EngineResult:
    history = history or []

    # --- Коммерческий сценарий "стать экспонентом" — до обычного поиска ---
    if _in_become_exhibitor_flow(history):
        out = EngineResult(
            reply=BECOME_EXHIBITOR_FOLLOWUP,
            segment="exhibitor",
            intent="commercial.become_exhibitor",
            confidence="HIGH",
            matched=True,
            clarified=False,
            fallback=True,  # предлагаем менеджера — лид уже квалифицирован
        )
        _log(session_id, out, message)
        return out

    if _is_become_exhibitor_trigger(message):
        out = EngineResult(
            reply=BECOME_EXHIBITOR_PITCH,
            segment="exhibitor",
            intent="commercial.become_exhibitor",
            confidence="HIGH",
            matched=True,
            clarified=True,
            fallback=False,
        )
        _log(session_id, out, message)
        return out

    # "Условия участия?" сам по себе — ролево неоднозначная фраза (см.
    # docstring _is_generic_participation_phrase), но только если роль ещё
    # не установлена и мы ещё ничего не уточняли в этом диалоге — иначе
    # это нарушило бы правило "не переспрашивать дважды подряд".
    already_clarified = retrieval.last_bot_turn_is_clarifying(history)
    if (
        segment_hint not in ("visitor", "exhibitor")
        and not already_clarified
        and _is_generic_participation_phrase(message)
    ):
        out = EngineResult(
            reply=ROLE_CLARIFY_REPLY,
            segment="uncertain",
            intent=None,
            confidence="MEDIUM",
            matched=False,
            clarified=True,
            fallback=False,
        )
        _log(session_id, out, message)
        return out

    # --- Обычный маршрут: сегментация → confidence → ответ/уточнение ---
    result = retrieval.search(message, history, segment_hint=segment_hint)
    top_intent = result.candidates[0].intent if result.candidates else None

    if result.ambiguous_role and not already_clarified:
        out = EngineResult(
            reply=ROLE_CLARIFY_REPLY,
            segment="uncertain",
            intent=None,
            confidence=result.confidence,
            matched=False,
            clarified=True,
            fallback=False,
        )
    elif result.confidence == "LOW":
        out = EngineResult(
            reply=NO_MATCH_REPLY,
            segment=result.segment,
            intent=top_intent,
            confidence=result.confidence,
            matched=False,
            clarified=False,
            fallback=True,
        )
    elif result.confidence == "MEDIUM" and not already_clarified:
        clarifying_question = llm.clarify(result.candidates).strip() or GENERIC_CLARIFY_REPLY
        out = EngineResult(
            reply=clarifying_question,
            segment=result.segment,
            intent=top_intent,
            confidence=result.confidence,
            matched=False,
            clarified=True,
            fallback=False,
        )
    else:
        # Либо обычный HIGH-путь, либо (ambiguous_role/MEDIUM +
        # already_clarified=True): раздел 4.4/10 ТЗ — после ОДНОГО
        # уточнения система обязана либо ответить, либо признать, что
        # данных нет, а не спрашивать снова. Роль к этому моменту уже
        # разрешена (explicit_role reply в retrieval.py, если пользователь
        # ответил "посетитель"/"экспонент") либо остаётся неопределённой —
        # в обоих случаях отвечаем по лучшим текущим кандидатам.
        out = _answer_or_fallback(result.segment, message, result.candidates, history, top_intent)

    _log(session_id, out, message)
    return out


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
