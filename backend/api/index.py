"""
Точка входа для Vercel Python runtime — на случай, если Vercel-проект
настроен с Root Directory = "backend" (а не корень репозитория, где уже
есть свой api/index.py + vercel.json). main.py лежит рядом на уровне
проекта, поэтому дополнительных манипуляций с sys.path не нужно.
"""
from main import app  # noqa: F401 — реэкспорт: Vercel ищет переменную `app`
