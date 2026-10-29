"""
Маскирование персональных данных перед отправкой в языковую модель (ТЗ от
28.10.2026, п.4.5: «не отправлять в модель реальные персональные данные
пользователя»). Если человек в чате написал e-mail или телефон, во внешний LLM-сервис
уходит заглушка, а не сами данные. Форма «Отправить менеджеру» этим не затрагивается:
она идёт отдельным каналом (handoff.py) и в модель не попадает.
"""
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{8,}\d(?![\w/])")


def _mask_phone(match: re.Match) -> str:
    # дата вроде 20.01.2027 тоже подходит под шаблон — маскируем только
    # последовательности, где реально 10+ цифр
    return "[телефон]" if sum(c.isdigit() for c in match.group(0)) >= 10 else match.group(0)


def redact(text: str) -> str:
    return _PHONE.sub(_mask_phone, _EMAIL.sub("[e-mail]", text))


def redact_history(history: list[dict]) -> list[dict]:
    """Сообщения пользователя маскируем; ответы бота (там контакты организатора) не трогаем."""
    return [
        {**turn, "content": redact(turn.get("content", ""))} if turn.get("role") == "user" else turn
        for turn in history
    ]
