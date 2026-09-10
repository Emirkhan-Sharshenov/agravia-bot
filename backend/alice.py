"""
Вебхук для навыка Яндекс.Алисы (Yandex Dialogs).

Протокол: Алиса шлёт POST с JSON вида
{
  "meta": {...}, "version": "1.0",
  "session": {"session_id": "...", "message_id": 0, "new": true, "user_id": "..."},
  "request": {"command": "текст без знаков препинания", "original_utterance": "...",
              "type": "SimpleUtterance" | "ButtonPressed", "payload": {...}, "nlu": {...}}
}
и ждёт ответ вида
{
  "version": "1.0", "session": {...},
  "response": {"text": "...", "tts": "...", "end_session": false, "buttons": [...]}
}

Важно: у навыка есть жёсткий тайм-аут на ответ (несколько секунд —
актуальное значение см. в документации Яндекса, оно может меняться).
LLM-вызов у нас с ограниченным max_tokens именно поэтому — чтобы
не выйти за лимит.

Состояние диалога хранится в памяти процесса, ключ — session_id.
Это ОК для одного инстанса и для теста; при масштабировании на
несколько инстансов backend'а перенесите SESSIONS в Redis/Postgres,
иначе разные реплики одного разговора могут попасть на разные
процессы и потерять контекст.

Раздел 2.1 ТЗ: обязательный выбор роли ("я экспонент"/"я посетитель")
перед началом диалога убран — навык сразу принимает свободный вопрос,
сегмент определяет chat_engine.handle_message (общая логика с /api/chat
на сайте, см. chat_engine.py), поэтому поведение в Алисе и в виджете не
расходится.
"""
from __future__ import annotations
import time

from fastapi import APIRouter, Request

import chat_engine
from handoff import send_to_manager

router = APIRouter()

SESSIONS: dict[str, dict] = {}
SESSION_TTL_SECONDS = 60 * 30  # чистим сессии старше 30 минут, чтобы не текла память

MAX_TEXT_LEN = 1000  # запас от лимита Алисы в 1024 символа
MAX_HISTORY_TURNS = 8  # держим короткую историю ради скорости ответа/контекста

GREETING = (
    "Здравствуйте! Я — Алиса, помощник выставки AGRAVIA. Могу помочь с "
    "посещением выставки, билетами, программой, участием, стендами, "
    "монтажом и другими вопросами. Просто скажите, что хотите узнать."
)

YES_WORDS = {"да", "давай", "хочу", "конечно", "соедини", "соединить", "нужно"}
EXIT_WORDS = {"выход", "хватит", "стоп", "закончи", "пока"}


def _new_state() -> dict:
    return {
        "stage": "chat",  # chat -> handoff_consent -> handoff_name -> handoff_contact -> chat
        "segment": "uncertain",
        "history": [],
        "pending_question": None,
        "handoff_name": None,
        "ts": time.time(),
    }


def _gc_sessions() -> None:
    now = time.time()
    stale = [sid for sid, s in SESSIONS.items() if now - s["ts"] > SESSION_TTL_SECONDS]
    for sid in stale:
        SESSIONS.pop(sid, None)


def _truncate(text: str) -> str:
    if len(text) <= MAX_TEXT_LEN:
        return text
    return text[: MAX_TEXT_LEN - 1].rsplit(" ", 1)[0] + "…"


def _reply(session_obj: dict, text: str, buttons: list | None = None, end_session: bool = False) -> dict:
    text = _truncate(text)
    return {
        "version": "1.0",
        "session": session_obj,
        "response": {
            "text": text,
            "tts": text,
            "end_session": end_session,
            "buttons": buttons or [],
        },
    }


@router.post("/alice/webhook")
async def alice_webhook(request: Request):
    body = await request.json()
    session_meta = body["session"]
    req = body["request"]
    session_id = session_meta["session_id"]
    command = (req.get("command") or "").strip()

    _gc_sessions()

    if session_meta.get("new") or session_id not in SESSIONS:
        SESSIONS[session_id] = _new_state()
        return _reply(session_meta, GREETING)

    state = SESSIONS[session_id]
    state["ts"] = time.time()
    low = command.lower()

    if low in EXIT_WORDS:
        SESSIONS.pop(session_id, None)
        return _reply(session_meta, "Спасибо, что заглянули! До встречи на AGRAVIA.", end_session=True)

    # --- этап: согласие на передачу менеджеру ---
    if state["stage"] == "handoff_consent":
        if low in YES_WORDS or low == "да":
            state["stage"] = "handoff_name"
            return _reply(session_meta, "Как к вам обращаться?")
        state["stage"] = "chat"
        return _reply(session_meta, "Хорошо, задайте другой вопрос.")

    if state["stage"] == "handoff_name":
        state["handoff_name"] = command or "Без имени"
        state["stage"] = "handoff_contact"
        return _reply(session_meta, "Оставьте, пожалуйста, телефон или e-mail для связи.")

    if state["stage"] == "handoff_contact":
        contact = command
        await send_to_manager(
            session_id=session_id,
            segment=state["segment"] or "uncertain",
            name=state["handoff_name"] or "Без имени",
            contact=contact,
            question=state["pending_question"] or "(не указан)",
        )
        state["stage"] = "chat"
        return _reply(session_meta, "Спасибо! Менеджер свяжется с вами в ближайшее время.")

    # --- этап: обычный чат по базе знаний (сегмент определяется автоматически) ---
    if state["stage"] == "chat":
        result = chat_engine.handle_message(session_id, command, history=state["history"])
        state["segment"] = result.segment

        if result.fallback:
            state["stage"] = "handoff_consent"
            state["pending_question"] = command
            return _reply(
                session_meta,
                result.reply,
                buttons=[{"title": "Да", "hide": True}, {"title": "Нет", "hide": True}],
            )

        state["history"].append({"role": "user", "content": command})
        state["history"].append({"role": "assistant", "content": result.reply})
        state["history"] = state["history"][-MAX_HISTORY_TURNS:]

        buttons = None
        if result.clarified and result.segment == "uncertain":
            buttons = [
                {"title": "Я посетитель", "hide": True},
                {"title": "Я экспонент", "hide": True},
            ]
        return _reply(session_meta, result.reply, buttons=buttons)

    # fallback — не должны сюда попасть, но на всякий случай сбрасываем стейт
    SESSIONS[session_id] = _new_state()
    return _reply(session_meta, GREETING)
