"""
Точка входа для Vercel Python runtime (@vercel/python — ASGI-приложение
как переменная `app` в этом файле). Сам бэкенд живёт в backend/, чтобы
его можно было запускать локально через `uvicorn main:app` без Vercel —
здесь только добавляем backend/ в sys.path и реэкспортируем FastAPI app.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from main import app  # noqa: E402,F401 — реэкспорт: Vercel ищет переменную `app`
