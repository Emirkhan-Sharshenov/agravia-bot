"""
Передача заявки менеджеру. По умолчанию — в Telegram (совпадает со
стеком, на котором обычно поднимаются такие уведомления), плюс
запись в лог-файл на диске в любом случае — на случай, если Telegram
не настроен или временно недоступен, заявка не потеряется.
"""
import json
import os
import time

import httpx

from log_paths import LOG_DIR

LOG_PATH = LOG_DIR / "handoffs.jsonl"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_MANAGER_CHAT_ID = os.environ.get("TELEGRAM_MANAGER_CHAT_ID")


def _write_log(payload: dict) -> bool:
    payload = {**payload, "ts": time.time()}
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except OSError:
        # read-only FS (напр. serverless) — заявку всё равно попробуем
        # доставить через Telegram ниже, просто не крашим запрос из-за лога.
        return False


async def send_to_manager(session_id: str, segment: str, name: str, contact: str, question: str) -> bool:
    """Возвращает True, если уведомление доставлено (или хотя бы залогировано)."""
    logged = _write_log({
        "session_id": session_id,
        "segment": segment,
        "name": name,
        "contact": contact,
        "question": question,
    })

    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_MANAGER_CHAT_ID):
        # Телеграм не настроен — считаем успехом, только если лог реально записан.
        return logged

    text = (
        "🔔 Новая заявка с сайта AGRAVIA\n"
        f"Сегмент: {segment}\n"
        f"Имя: {name}\n"
        f"Контакт: {contact}\n"
        f"Вопрос: {question}\n"
        f"Session: {session_id}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": TELEGRAM_MANAGER_CHAT_ID, "text": text})
            return logged or r.status_code == 200
    except httpx.HTTPError:
        return logged
