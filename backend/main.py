import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import chat_engine
import kb_store
from alice import router as alice_router
from handoff import send_to_manager
import analytics
import research_log

BASE_DIR = Path(__file__).parent
KB = kb_store.KB

app = FastAPI(title="ИИ-помощник АГРАВИИ")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # сузьте до домена сайта в проде
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=20)
    # Состояние диалога (роль, прошлая тема, ожидаемое уточнение). Сервер ничего
    # не хранит: клиент присылает назад то, что получил в прошлом ответе.
    state: dict | None = None
    # Совместимость со старыми версиями виджета, присылавшими только роль.
    segment_hint: str | None = None
    debug: bool = False  # вернуть в ответе диагностику ошибок провайдера (для QA)
    research_consent: bool = False
    research_notice_version: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    segment: str
    confidence: str
    clarify: bool = False
    offer_manager: bool = False
    intent: str | None = None
    role: str | None = None
    state: dict = {}
    debug: list[str] | None = None
    research_recording: str = "disabled"


class HandoffRequest(BaseModel):
    session_id: str
    segment: str
    name: str
    contact: str
    question: str


@app.get("/api/research-config")
def research_config():
    return research_log.config()


@app.get("/api/research-notice", include_in_schema=False)
def research_notice():
    return FileResponse(BASE_DIR.parent / "research-notice.html", media_type="text/html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "common_qa": len(KB["common"]),
        "exhibitor_qa": len(KB["exhibitor"]),
        "visitor_qa": len(KB["visitor"]),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # Обычная (не async) функция: внутри блокирующие HTTP-вызовы к LLM,
    # FastAPI выполнит её в пуле потоков, не блокируя event loop.
    session_id = req.session_id or str(uuid.uuid4())
    history = []
    remaining = 20000
    for turn in reversed(req.history):
        content = turn.get("content")
        if turn.get("role") not in {"user", "assistant"} or not isinstance(content, str):
            continue
        content = content[-min(4000, remaining):]
        if content:
            history.append({"role": turn["role"], "content": content})
            remaining -= len(content)
        if remaining <= 0:
            break
    history.reverse()

    try:
        result = chat_engine.handle_message(
            session_id, req.message, history=history,
            state=req.state, segment_hint=req.segment_hint,
        )
    except Exception as exc:  # LLM-провайдер недоступен и т.п. — не отдаём 500 в виджет
        result = chat_engine.error_result(req.state)
        result.notes.append(f"answer: {exc!r}"[:500])

    recording = research_log.record_turn(
        session_id=session_id,
        consent=req.research_consent,
        notice_version=req.research_notice_version,
        intent=result.intent,
        message=req.message,
        reply=result.reply,
        turn=len(req.history) // 2,
        fallback=result.fallback,
    )
    if req.debug and recording == "storage_error":
        result.notes.append("research: " + research_log.diagnostic())

    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        segment=result.segment,
        confidence=result.confidence,
        clarify=result.clarified,
        offer_manager=result.offer_manager,
        intent=result.intent,
        role=result.role,
        state=result.state,
        debug=result.notes if req.debug else None,
        research_recording=recording,
    )


@app.post("/api/handoff")
async def handoff(req: HandoffRequest):
    # Раздел 14 ТЗ: форма обратной связи отделена от AI-контура — контактные
    # данные уходят напрямую менеджеру/в лог, а не в языковую модель.
    if not req.name.strip() or not req.contact.strip():
        raise HTTPException(422, "Укажите имя и телефон или e-mail")
    analytics.log_handoff_opened(req.session_id)
    ok = await send_to_manager(req.session_id, req.segment, req.name, req.contact, req.question)
    if not ok:
        # Не доставлено ни по одному каналу — виджет не должен писать "Отправлено".
        raise HTTPException(502, "Не удалось передать заявку менеджеру")
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

