import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import chat_engine
import kb_store
from alice import router as alice_router
from handoff import send_to_manager
from log_paths import LOG_DIR
import analytics

BASE_DIR = Path(__file__).parent
KB = kb_store.KB
DIALOG_LOG = LOG_DIR / "dialogs.jsonl"

app = FastAPI(title="AGRAVIA AI Chat Bot «Алиса»")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # сузьте до домена сайта в проде
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    # Раздел 2.1 ТЗ: выбор роли больше не обязателен перед началом диалога —
    # сегмент определяется автоматически внутри chat_engine. Поле оставлено
    # опциональным на случай, если фронтенд захочет передать подсказку
    # (например, пользователь нажал быструю кнопку "Стать участником"), но
    # сейчас не используется как жёсткий гейт.
    segment_hint: str | None = None
    message: str
    history: list[dict] = []  # [{"role": "user"/"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    segment: str
    confidence: str
    clarify: bool = False
    offer_manager: bool = False


class HandoffRequest(BaseModel):
    session_id: str
    segment: str
    name: str
    contact: str
    question: str


def _log_dialog(**kwargs) -> None:
    try:
        with DIALOG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**kwargs, "ts": time.time()}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # best-effort: read-only FS (напр. serverless) не должен ронять ответ пользователю


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "common_qa": len(KB["common"]),
        "exhibitor_qa": len(KB["exhibitor"]),
        "visitor_qa": len(KB["visitor"]),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    result = chat_engine.handle_message(session_id, req.message, history=req.history)

    _log_dialog(
        session_id=session_id,
        segment=result.segment,
        intent=result.intent,
        confidence=result.confidence,
        message=req.message,
        reply=result.reply,
        matched=result.matched,
        clarified=result.clarified,
        fallback=result.fallback,
    )

    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        segment=result.segment,
        confidence=result.confidence,
        clarify=result.clarified,
        offer_manager=result.fallback,
    )


@app.post("/api/handoff")
async def handoff(req: HandoffRequest):
    # Раздел 14 ТЗ: форма обратной связи отделена от AI-контура — контактные
    # данные уходят напрямую менеджеру/в лог, а не в языковую модель.
    analytics.log_handoff_opened(req.session_id)
    ok = await send_to_manager(req.session_id, req.segment, req.name, req.contact, req.question)
    if not ok:
        raise HTTPException(502, "Не удалось передать заявку менеджеру, но она сохранена в логе")
    return {"ok": True}


# Навык Яндекс.Алисы — вебхук на /alice/webhook, логика внутри alice.py
app.include_router(alice_router)

# Отдаём файлы виджета (widget.js, demo.html) с того же бэкенда для простоты,
# в проде их обычно кладут на CDN/сам сайт. StaticFiles падает с RuntimeError
# на старте, если каталога нет (например, деплой с Root Directory=backend/ —
# widget/ на уровень выше и не попадает в бандл) — это крашило бы ВЕСЬ app,
# а не только /widget, поэтому монтируем только если каталог реально на месте.
_WIDGET_DIR = BASE_DIR.parent / "widget"
if _WIDGET_DIR.is_dir():
    app.mount("/widget", StaticFiles(directory=str(_WIDGET_DIR)), name="widget")
