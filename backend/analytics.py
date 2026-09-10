"""
Локальная аналитика работы бота (раздел 18 ТЗ) и лог "вопросов без ответа"
(раздел 19 ТЗ) — используется для регулярного расширения базы знаний.

Оба лога — обезличенные jsonl-файлы на диске. Полный текст сообщения
пользователя в analytics.jsonl НЕ пишем по умолчанию (раздел 18: "Персональные
данные не должны попадать в аналитический лог без необходимости") — только
факт совпадения/уточнения/fallback, сегмент, intent и confidence. Для
unanswered.jsonl текст сохраняется намеренно (раздел 19 явно требует
query/anonymized_query), т.к. он нужен людям, чтобы дополнять базу знаний;
если политика хранения этого не допускает, замените query на anonymized_query
на вызывающей стороне перед логированием.
"""
import json
import time
from pathlib import Path

from log_paths import LOG_DIR

ANALYTICS_LOG = LOG_DIR / "analytics.jsonl"
UNANSWERED_LOG = LOG_DIR / "unanswered.jsonl"


def _append(path: Path, payload: dict) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass  # best-effort: read-only FS (напр. serverless) не должен ронять ответ пользователю


def log_event(
    *,
    session_id: str,
    segment: str,
    intent: str | None,
    confidence: str,
    matched: bool,
    clarified: bool,
    fallback: bool,
) -> None:
    """Раздел 18 ТЗ: дата/время, session ID, сегмент, intent, confidence,
    найден ли ответ, было ли уточнение, был ли fallback."""
    _append(ANALYTICS_LOG, {
        "ts": time.time(),
        "session_id": session_id,
        "segment": segment,
        "intent": intent,
        "confidence": confidence,
        "matched": matched,
        "clarified": clarified,
        "fallback": fallback,
        "handoff_opened": False,  # проставляется отдельным вызовом log_handoff_opened
    })


def log_handoff_opened(session_id: str) -> None:
    _append(ANALYTICS_LOG, {
        "ts": time.time(),
        "session_id": session_id,
        "event": "handoff_form_opened",
    })


def log_unanswered(
    *,
    query: str,
    segment: str,
    closest_intent: str | None,
    confidence: str,
) -> None:
    """Раздел 19 ТЗ: отдельный лог вопросов без уверенного ответа."""
    _append(UNANSWERED_LOG, {
        "date": time.time(),
        "query": query,
        "segment": segment,
        "closest_intent": closest_intent,
        "confidence": confidence,
        "result": "unanswered",
    })
