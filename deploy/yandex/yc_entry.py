"""
Точка входа Yandex Cloud Functions (HTTP-вызов) для FastAPI-приложения backend/main.py.

Cloud Functions не умеет ASGI напрямую: handler получает событие
{httpMethod, path, headers, queryStringParameters, body, isBase64Encoded, ...}
и возвращает {statusCode, headers, body, isBase64Encoded}. Здесь событие
превращается в обычный HTTP-запрос к ASGI-приложению (через httpx.ASGITransport),
так что вся логика остаётся в backend/ без изменений.

Entrypoint функции: yc_entry.handler
"""
import asyncio
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from main import app  # noqa: E402

# Прямая ссылка функции вида https://functions.yandexcloud.net/<id>/путь: на всякий
# случай срезаем идентификатор функции, если он попал в путь.
_FUNCTION_ID_PREFIX = re.compile(r"^/d4[a-z0-9]{17,}(?=/|$)")
_TEXT_TYPES = ("text/", "application/json", "application/javascript", "application/xml")


async def _call(event: dict) -> dict:
    method = event.get("httpMethod") or "GET"
    path = event.get("path") or event.get("url") or "/"
    path = _FUNCTION_ID_PREFIX.sub("", path.split("?", 1)[0]) or "/"
    headers = {k: v for k, v in (event.get("headers") or {}).items() if k.lower() != "host"}
    params = event.get("queryStringParameters") or {}
    body = event.get("body") or b""
    if isinstance(body, str):
        body = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://function") as client:
        resp = await client.request(method, path, params=params, headers=headers, content=body)

    content_type = resp.headers.get("content-type", "")
    is_text = content_type.startswith(_TEXT_TYPES)
    return {
        "statusCode": resp.status_code,
        "headers": {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "transfer-encoding")},
        "body": resp.text if is_text else base64.b64encode(resp.content).decode("ascii"),
        "isBase64Encoded": not is_text,
    }


def handler(event, context):
    return asyncio.run(_call(event))
