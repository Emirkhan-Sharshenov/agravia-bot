"""
Единая логика диалога (раздел 3 ТЗ AI-бот AGRAVIA 2027):

  сообщение → сегментация (без обязательного выбора роли) → учёт истории →
  семантический поиск → confidence → ответ / уточнение / fallback

Используется и вебхуком сайта (main.py: /api/chat), и навыком Алисы
(alice.py), чтобы поведение не расходилось между каналами.
"""
from __future__ import annotations

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


@dataclass
class EngineResult:
    reply: str
    segment: str
    intent: str | None
    confidence: str
    matched: bool
    clarified: bool
    fallback: bool


def handle_message(session_id: str, message: str, history: list[dict] | None = None) -> EngineResult:
    history = history or []
    result = retrieval.search(message, history)
    top_intent = result.candidates[0].intent if result.candidates else None

    if result.ambiguous_role:
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
    elif result.confidence == "MEDIUM":
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
    else:  # HIGH
        answer = llm.answer(result.segment, message, result.candidates, history=history)
        if answer is None:
            # Второй барьер (в LLM) всё же посчитал, что фрагментов
            # недостаточно/не по теме — фолбэк, несмотря на HIGH со стороны
            # retrieval (например, семантически близко, но не то же самое).
            out = EngineResult(
                reply=NO_MATCH_REPLY,
                segment=result.segment,
                intent=top_intent,
                confidence=result.confidence,
                matched=False,
                clarified=False,
                fallback=True,
            )
        else:
            out = EngineResult(
                reply=answer,
                segment=result.segment,
                intent=top_intent,
                confidence=result.confidence,
                matched=True,
                clarified=False,
                fallback=False,
            )

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
            closest_intent=top_intent,
            confidence=out.confidence,
        )

    return out
