"""
Передача заявки менеджеру (форма «Отправить менеджеру» — отделена от AI-контура:
контактные данные в языковую модель не попадают).

Заявка считается отправленной ТОЛЬКО если она реально доставлена по настроенному
каналу — иначе виджет не должен говорить пользователю «Отправлено»:
  - Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_MANAGER_CHAT_ID;
  - webhook (CRM, почтовый релей, Make/Zapier и т.п.): HANDOFF_WEBHOOK_URL —
    на него уходит POST с JSON {session_id, segment, name, contact, question}.
Запись в лог (handoffs.jsonl) — только резервная копия и доставкой не считается:
на serverless-хостинге (Vercel) файловая система эфемерна, там заявка из файла
пропадёт. Для локальной разработки без каналов можно разрешить успех по одному
логу: HANDOFF_ALLOW_LOG_ONLY=true.
"""
import json
import os
import time

import httpx

from log_paths import LOG_DIR

LOG_PATH = LOG_DIR / "handoffs.jsonl"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_MANAGER_CHAT_ID = os.environ.get("TELEGRAM_MANAGER_CHAT_ID")
HANDOFF_WEBHOOK_URL = os.environ.get("HANDOFF_WEBHOOK_URL")
ALLOW_LOG_ONLY = os.environ.get("HANDOFF_ALLOW_LOG_ONLY", "").lower() == "true"


def _write_log(payload: dict) -> bool:
    payload = {**payload, "ts": time.time()}
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


async def _send_telegram(client: httpx.AsyncClient, text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = await client.post(url, json={"chat_id": TELEGRAM_MANAGER_CHAT_ID, "text": text})
    return r.status_code == 200


async def _send_webhook(client: httpx.AsyncClient, payload: dict) -> bool:
    r = await client.post(HANDOFF_WEBHOOK_URL, json=payload)
    return 200 <= r.status_code < 300


async def send_to_manager(session_id: str, segment: str, name: str, contact: str, question: str) -> bool:
    """True — только если заявка доставлена хотя бы по одному настроенному каналу."""
    payload = {
        "session_id": session_id,
        "segment": segment,
        "name": name,
        "contact": contact,
        "question": question,
    }
    logged = _write_log(payload)

    telegram = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_MANAGER_CHAT_ID)
    webhook = bool(HANDOFF_WEBHOOK_URL)
    if not (telegram or webhook):
        return logged and ALLOW_LOG_ONLY

    text = (
        "🔔 Новая заявка с сайта AGRAVIA\n"
        f"Сегмент: {segment}\n"
        f"Имя: {name}\n"
        f"Контакт: {contact}\n"
        f"Вопрос: {question}\n"
        f"Session: {session_id}"
    )
    delivered = False
    async with httpx.AsyncClient(timeout=10) as client:
        for enabled, send, arg in (
            (telegram, _send_telegram, text),
            (webhook, _send_webhook, payload),
        ):
            if not enabled:
                continue
            try:
                delivered = await send(client, arg) or delivered
            except httpx.HTTPError:
                pass
    return delivered
