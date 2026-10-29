"""
Определение намерения (intent), роли, проекта и языка (ТЗ v2 п.3.1-3.3; ТЗ от
28.10.2026 п.6.1-6.2).

Сопоставление по словам не годится как основной механизм понимания:
разговорные и перефразированные формулировки одного вопроса оно распознаёт
нестабильно. Поэтому намерение определяет LLM по ОПИСАНИЯМ тем (без примеров
конкретных фраз — ни одна формулировка не зашита в код), с учётом состояния
диалога: ранее установленной роли, проекта (AGRAVIA / iAGRI), прошлой темы и
уточняющего вопроса, на который пользователь сейчас отвечает.

Если LLM недоступна, работает запасной классификатор по корням слов
(fallback_classify) — только для основных коммерческих маршрутов, чтобы бот не
терял билет, заявку на стенд и каталог при сбое провайдера.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import llm

ROLES = ("visitor", "exhibitor", "prospect", "builder")

# intent -> описание для классификатора.
INTENT_DESCRIPTIONS = {
    "dates": "даты и часы работы выставки, проверка даты (например «а не в другом месяце?»)",
    "location": "где проходит выставка, адрес, павильон, зал, этаж, как добраться и найти зал",
    "visitor_registration": "как получить билет, зарегистрироваться или попасть на выставку посетителем/гостем, где билет, бейдж или пропуск ПОСЕТИТЕЛЯ, ссылка на регистрацию, просьба прислать билет",
    "ticket_info": "правила билета: платный ли, электронный QR на телефоне, на сколько дней, можно ли с ребёнком, один e-mail на двоих, без предварительной регистрации, регистрация иностранцев",
    "reg_support": "проблема с регистрацией: письмо не пришло, ошибка в e-mail, не получается получить билет",
    "iagri_registration": "билет или регистрация именно на iAGRI",
    "participation": "стать экспонентом, участвовать со стендом, заявка, аренда и бронь стенда, цена и условия участия, «мы компания, хотим выставляться»",
    "exhibit_or_visit": "неясно или сразу оба: участвовать со стендом или прийти посетителем (в том числе две разные компании или «участвовать» без уточнения)",
    "stand_find_or_book": "«посмотреть готовый стенд» — неясно, заказать стенд для себя или найти стенд участника",
    "catalog": "список участников, участвует ли конкретная компания, кто представляет товар или кто поставщик, номер стенда, карта залов, почему список изменился",
    "industry_feed": "корма, кормовые добавки, ветпрепараты, ветеринария, комбикорма",
    "industry_horti": "декоративные растения, питомники, саженцы, озеленение",
    "industry_ai": "нейросети, цифровизация, умное сельское хозяйство",
    "industry_other": "любая другая отраслевая потребность посетителя (ферма, свинокомплекс, хранение зерна, семена, техника, переработка, молочное оборудование)",
    "pass": "пропуск, когда не названо, кому он нужен и какого он типа (посетитель, экспонент, монтаж)",
    "badge": "бейдж, когда не ясно, для кого он (посетитель или экспонент)",
    "montage": "даты и режим монтажа / застройки / сборки стенда",
    "demontage": "даты и режим демонтажа / разборки стенда",
    "entry": "заезд, допуск на площадку, когда можно заходить или приезжать, если не ясно чей заезд",
    "equipment_in": "ввоз, завоз и разгрузка оборудования и экспонатов, куда ехать машине с грузом, зона погрузки-разгрузки, документы на ввоз",
    "equipment_out": "вывоз оборудования и экспонатов",
    "vehicle_access": "парковка, въезд на территорию на автомобиле (без привоза груза)",
    "business_program": "деловая программа, конференции и мероприятия внутри выставки: расписание, время начала, спикеры, предложить спикера",
    "competition": "конкурс «Лучший продукт AGRAVIA»: заявки, номинанты, победители, итоги",
    "iagri_award": "отдельная премия/конкурс iAGRI (не «Лучший продукт AGRAVIA»)",
    "banners": "готовые баннеры и промоматериалы для приглашения клиентов экспонентом",
    "promo_campaign": "акция «Встречаемся на AGRAVIA», видео вместо персональной ссылки, UTM-ссылки для клиентов",
    "materials": "просьба о «материалах» без уточнения, каких именно (баннеры для клиентов или материалы для застройки)",
    "media": "аккредитация СМИ, журналисты",
    "tourist": "проживание, гостиницы, туристические услуги, поездка",
    "tourist_invite": "визовое/туристическое приглашение в РФ",
    "cabinet": "личный кабинет экспонента/участника, доступ к нему, ссылка",
    "contact": "просьба связать с менеджером, оператором или живым человеком вместо бота, телефон, e-mail, кому написать",
    "privacy_delete": "просьба удалить свои персональные данные",
    "privacy_storage": "вопросы о хранении переписки, передаче данных за рубеж, обработке персональных данных",
    "pd_request": "просьба показать или выдать чужие персональные данные (телефоны, почты других людей)",
    "secrets": "пользователь собирается прислать пароль, код из СМС или другой секрет",
    "general": "что такое AGRAVIA или iAGRI, ребрендинг АГРОС/АГРОТЕХ, организатор, можно ли успеть обе выставки, для кого выставка, кафе, командировочный лист, доступная среда",
    "other": "любой другой вопрос о выставке, не подходящий под темы выше (стенды, электричество, штрафы, правила, Wi-Fi и т.п.)",
    "role_only": "пользователь только сообщил о себе (кто он), конкретного вопроса нет",
    "greeting": "приветствие или small talk",
    "help": "просит помощи без конкретики либо не понимает, что делать",
    "offtopic": "вне темы выставки: шутки, погода, спорт, политика, общие знания и т.п.",
    "gibberish": "бессмысленный набор символов, нераспознаваемый ввод",
}

# Темы, ответ на которые зависит от роли: если роль неизвестна — сначала
# уточняем (ТЗ 3.2), а не угадываем. Парковка — "практически всегда
# посетитель" (ТЗ 28.10), поэтому в этот набор не входит.
ROLE_DEPENDENT = {"pass", "badge", "entry"}

ROUTER_SYSTEM = """Ты — классификатор сообщений чат-бота выставки AGRAVIA 2027 (и сопутствующей iAGRI). По \
сообщению пользователя, истории и состоянию диалога верни ТОЛЬКО JSON без пояснений:
{{"intent": "<тема>", "role": "<роль>", "project": "<проект>", "lang": "<язык>", "for_other": false, "brief": false}}

role — роль того, о ком идёт речь в запросе: visitor (посетитель/гость), exhibitor (действующий экспонент), \
prospect (хочет стать участником, ещё не участвует), builder (застройщик, монтажная команда, подрядчик; в том \
числе тот, кому нужен монтажный пропуск), none (неизвестна). Не угадывай: слова «пропуск», «бейдж», «заезд» сами \
по себе роль не определяют. Если тип пропуска/бейджа назван («монтажный», «экспонентский», «гостевой») — он \
определяет роль. Если роль названа явно — она заменяет прежнюю; иначе возьми её из состояния диалога.
for_other — true, если пользователь спрашивает за другого человека (коллегу, клиента): тогда role — роль ЭТОГО \
человека, а не автора сообщения.
project — о каком проекте речь: iagri, если пользователь хочет именно на iAGRI; agravia, если на AGRAVIA или явно \
переключился на неё; иначе значение из состояния диалога (none, если проект не назван).
lang — язык сообщения: ru или en.
brief — true, если просит ответить коротко.

ТЕМЫ (intent):
{intents}

ПРАВИЛА ТЕМЫ:
- Короткое согласие, «а точно?», «а сколько?», «а кому написать?», «коротко» или ответ на вопрос бота продолжают \
тему из состояния: если бот задал уточняющий вопрос — это pending_intent, иначе тема прошлого хода.
- Если пользователь исправляет себя («нет, я про …») — тема, роль и проект берутся из исправления.
- Переход к соседнему аспекту — выбирай тему этого аспекта. Конкретная тема важнее help.
- Опечатки, шум и эмоции не мешают: определи суть запроса.

СОСТОЯНИЕ ДИАЛОГА:
{state}

ИСТОРИЯ (последние сообщения):
{history}
"""

PROJECTS = ("agravia", "iagri")


@dataclass
class Route:
    intent: str
    role: str | None  # None — роль неизвестна
    project: str | None = None
    lang: str = "ru"
    for_other: bool = False
    brief: bool = False


# --- запасные лексические механизмы --------------------------------------------

_ROLE_STEMS = (
    ("builder", ("застройщик", "монтажник", "монтажн")),
    ("exhibitor", ("экспонент",)),
    ("visitor", ("посетител", "гост")),
)


def role_from_words(message: str) -> str | None:
    """Роль, если в сообщении названа ровно одна (по корням слов), иначе None.
    Страховка поверх LLM для тем, где ответ зависит от роли."""
    low = message.lower()
    found = {role for role, stems in _ROLE_STEMS if any(st in low for st in stems)}
    return found.pop() if len(found) == 1 else None


def detect_lang(message: str) -> str:
    letters = [c for c in message if c.isalpha()]
    if not letters:
        return "ru"
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return "en" if latin / len(letters) > 0.7 else "ru"


# Порядок важен: первое совпавшее правило побеждает. Только основные коммерческие
# маршруты — для работы без LLM.
_FALLBACK_RULES = (
    ("secrets", re.compile(r"парол|password|смс|sms", re.I)),
    ("iagri_registration", re.compile(r"(iagri|айагри|ай-?агри).*(рег|билет|register|ticket)|(рег|билет|register|ticket).*(iagri|айагри)", re.I)),
    ("participation", re.compile(r"стенд|экспонент|выставл|exhibit|stand|заявк\w* на участ|участ\w* в выставк|стать участник", re.I)),
    ("catalog", re.compile(r"каталог|список участник|кто участвует|поставщик|participants", re.I)),
    ("business_program", re.compile(r"программ|конференц|спикер|program|speaker", re.I)),
    ("competition", re.compile(r"конкурс|лучший продукт|competition", re.I)),
    ("banners", re.compile(r"баннер|banner", re.I)),
    ("visitor_registration", re.compile(r"билет|регистр|попасть|посетит|ticket|register|visit", re.I)),
    ("contact", re.compile(r"менеджер|телефон|контакт|человек|phone|contact", re.I)),
    ("dates", re.compile(r"когда|даты|дата|числ|when|dates", re.I)),
)


_SECRET_RE = re.compile(r"парол|password|код\w* из (смс|sms|сообщен)|cvv|пин-?код", re.I)


def mentions_secret(message: str) -> bool:
    return bool(_SECRET_RE.search(message))


def fallback_classify(message: str) -> Route | None:
    for intent, pattern in _FALLBACK_RULES:
        if pattern.search(message):
            return Route(intent=intent, role=None, lang=detect_lang(message))
    return None


# --- классификация LLM -----------------------------------------------------------

def _describe_state(state: dict) -> str:
    lines = [
        f"role: {state.get('role') or 'none'}",
        f"project: {state.get('project') or 'none'}",
        f"предыдущая тема: {state.get('intent') or 'нет'}",
    ]
    pending = state.get("pending")
    if pending:
        lines.append(
            f"бот только что задал уточняющий вопрос ({pending['kind']}) по теме "
            f"pending_intent={pending.get('intent')}; сообщение пользователя — ответ на него"
        )
    return "\n".join(lines)


def _describe_history(history: list[dict]) -> str:
    if not history:
        return "(пусто)"
    lines = []
    for turn in history[-4:]:
        who = "пользователь" if turn.get("role") == "user" else "бот"
        text = (turn.get("content") or "").replace("\n", " ")
        lines.append(f"{who}: {text[:160]}")
    return "\n".join(lines)


def _parse(text: str) -> dict | None:
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def classify(message: str, history: list[dict] | None, state: dict) -> Route:
    """Определяет тему, роль, проект и язык. Бросает исключение, если LLM
    недоступна или вернула нечитаемый ответ — вызывающий код сам решает, как
    деградировать (fallback_classify)."""
    system = ROUTER_SYSTEM.format(
        intents="\n".join(f"{k} — {v}" for k, v in INTENT_DESCRIPTIONS.items()),
        state=_describe_state(state),
        history=_describe_history(history or []),
    )
    text = llm.complete(system, [{"role": "user", "content": message}], max_tokens=300, temperature=0.0)
    data = _parse(text)
    if data is None:
        raise ValueError(f"router: нечитаемый ответ модели: {text[:200]!r}")

    intent = str(data.get("intent", "")).strip()
    if intent not in INTENT_DESCRIPTIONS:
        intent = "other"
    role = str(data.get("role", "")).strip().lower()
    if role not in ROLES:
        role = None
    project = str(data.get("project", "")).strip().lower()
    if project not in PROJECTS:
        project = None
    lang = "en" if str(data.get("lang", "")).strip().lower() == "en" else "ru"
    return Route(
        intent=intent,
        role=role,
        project=project,
        lang=lang,
        for_other=data.get("for_other") is True,
        brief=data.get("brief") is True,
    )
