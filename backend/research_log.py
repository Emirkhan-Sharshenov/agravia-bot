"""Opt-in research archive. Disabled until storage and notice are configured.

Records are pseudonymized, NOT guaranteed anonymous. Never log raw text on
failure. The bucket must be private with a verified 30-day lifecycle rule.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx
import privacy
from router import mentions_secret

NOTICE_VERSION = "assistant-research-2026-11-06-v1"
_token = {"value": "", "expires": 0.0}
_lock = threading.Lock()
_diagnostics = threading.local()


def diagnostic() -> str:
    return getattr(_diagnostics, "value", "")


def config() -> dict:
    mode = os.getenv("RESEARCH_MODE", "off")
    bucket = os.getenv("RESEARCH_BUCKET", "")
    notice = os.getenv("RESEARCH_NOTICE_URL", "")
    parsed = urlparse(notice)
    ready = (mode in {"pilot", "production"}
             and bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket))
             and parsed.scheme == "https" and parsed.hostname in {
                 "agravia.org", "d5daon1oep4l58a9tuca.jki8ffxa.apigw.yandexcloud.net"}
             and os.getenv("RESEARCH_RETENTION_VERIFIED") == "30")
    return {"enabled": ready, "mode": mode if ready else "off",
            "notice_version": NOTICE_VERSION, "notice_url": notice if ready else None,
            "retention_days": 30, "sample_percent": 100 if mode == "pilot" else 10}


def session_key(session_id: str) -> str:
    # No raw session identifier, IP, cookie identifiers, or tester name in archive.
    return hashlib.sha256(("agravia-research-v1:" + session_id).encode()).hexdigest()


def selected(session_id: str, mode: str) -> bool:
    return mode == "pilot" or int(session_key(session_id)[:8], 16) % 100 < 10


def _iam_token() -> str:
    with _lock:
        if time.time() >= _token["expires"] - 60:
            r = httpx.get(
                "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"}, timeout=1.0)
            r.raise_for_status()
            data = r.json()
            _token.update(value=data["access_token"],
                          expires=time.time() + float(data.get("expires_in", 600)))
        return _token["value"]


def _put(key: str, payload: dict) -> None:
    bucket = os.environ["RESEARCH_BUCKET"]
    url = "https://storage.yandexcloud.net/" + bucket + "/" + quote(key, safe="/")
    r = httpx.put(url, headers={"Authorization": "Bearer " + _iam_token(),
                               "Content-Type": "application/json; charset=utf-8"},
                  content=json.dumps(payload, ensure_ascii=False).encode(), timeout=1.5)
    r.raise_for_status()


def record_turn(*, session_id: str, consent: bool, notice_version: str | None,
                message: str, reply: str, turn: int, intent: str | None,
                fallback: bool) -> str:
    _diagnostics.value = ""
    cfg = config()
    if not cfg["enabled"]:
        return "disabled"
    if consent is not True or notice_version != NOTICE_VERSION:
        return "not_consented"
    if not selected(session_id, cfg["mode"]):
        return "not_selected"
    now = time.time()
    key = session_key(session_id)
    event_id = uuid.uuid4().hex
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y/%m/%d")
    sensitive = intent == "secrets" or mentions_secret(message)
    payload = {
        "schema": 1, "event_id": event_id, "session_key": key,
        "mode": cfg["mode"], "ts": now, "expires_at": now + 30 * 86400,
        "turn": max(0, int(turn)), "intent": intent, "fallback": bool(fallback),
        "consent": {"accepted": True, "notice_version": NOTICE_VERSION,
                    "notice_url": cfg["notice_url"], "recorded_at": now},
        # Apply masking to replies too: a model can echo user-supplied contacts.
        "message": ("[сообщение с возможными секретными данными скрыто]"
                    if sensitive
                    else privacy.redact(message)[:12000]),
        "reply": "[ответ на сообщение с возможными секретами скрыт]" if sensitive else privacy.redact(reply)[:24000],
    }
    try:
        _put(f"research/{cfg['mode']}/{day}/{key}/{event_id}.json", payload)
        return "stored"
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        _diagnostics.value = type(exc).__name__ + (f":HTTP{status}" if status else "")
        print(json.dumps({"event": "research_archive_write_failed",
                          "error_type": type(exc).__name__, "http_status": status}))
        return "storage_error"
