import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
KB = json.loads((BASE_DIR / "kb.json").read_text(encoding="utf-8"))
SEGMENTS = set(KB.keys())  # {"common", "exhibitor", "visitor"}
ROLE_SEGMENTS = SEGMENTS - {"common"}  # {"exhibitor", "visitor"} — сегменты-роли


def all_items() -> list[dict]:
    """Плоский список всех элементов базы знаний с проставленным сегментом.

    Каждый элемент: {segment, intent, category, question, examples, answer}.
    """
    items: list[dict] = []
    for segment, entries in KB.items():
        for entry in entries:
            items.append({"segment": segment, **entry})
    return items
