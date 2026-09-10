"""
Передача заявки менеджеру. По умолчанию — в Telegram (совпадает со
стеком, на котором обычно поднимаются такие уведомления), плюс
запись в лог-файл на диске в любом случае — на случай, если Telegram
не настроен или временно недоступен, заявка не потеряется.
"""
import json
import os
import time
from pathlib import Path

import httpx

LOG_PATH = Path(__file__).parent / "logs" / "handoffs.jsonl"
LOG_PATH.parent.mkdir(exist_ok=True)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_MANAGER_CHAT_ID = os.environ.get("TELEGRAM_MANAGER_CHAT_ID")


def _write_log(payload: dict) -> None:
    payload = {**payload, "ts": time.time()}
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def send_to_manager(session_id: str, segment: str, name: str, contact: str, question: str) -> bool:
    """Возвращает True, если уведомление доставлено (или хотя бы залогировано)."""
    _write_log({
        "session_id": session_id,
        "segment": segment,
        "name": name,
        "contact": contact,
        "question": question,
    })

    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_MANAGER_CHAT_ID):
        # Телеграм не настроен — заявка всё равно сохранена в логе выше.
        return True

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
            return r.status_code == 200
    except httpx.HTTPError:
        return False
