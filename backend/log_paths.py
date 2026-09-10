"""
Каталог для jsonl-логов (dialogs/analytics/unanswered/handoffs).

Обычно это backend/logs — так удобно смотреть логи локально и они
переживают рестарт процесса. Но на serverless-хостингах (например,
Vercel) файловая система деплоя read-only везде, кроме /tmp — попытка
писать в backend/logs там упадёт с OSError. Такие логи там всё равно не
персистентны между вызовами функции (каждый вызов может попасть в новый
контейнер), поэтому в этом случае просто откатываемся на системный
temp-каталог, чтобы запрос не падал, а не пытаемся эмулировать
персистентность, которой в этой среде нет.
"""
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _resolve() -> Path:
    preferred = BASE_DIR / "logs"
    try:
        preferred.mkdir(exist_ok=True, parents=True)
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "agravia-bot-logs"
        fallback.mkdir(exist_ok=True, parents=True)
        return fallback


LOG_DIR = _resolve()
