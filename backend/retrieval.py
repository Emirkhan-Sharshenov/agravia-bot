"""
Поиск релевантных элементов базы знаний (раздел 6-8 ТЗ AI-бот AGRAVIA 2027):
семантический поиск через embedding-векторы вместо точного совпадения слов,
плюс автоматическое определение сегмента пользователя (common / visitor /
exhibitor / uncertain — раздел 4 ТЗ) без обязательного выбора роли.

Стратегия:
  1. Основная: embedding-векторы (GigaChat Embeddings, см. llm.embed_texts)
     + косинусная близость запроса ко всем элементам базы. Векторы
     считаются один раз при старте и кэшируются на диске
     (kb_embeddings_cache.json), чтобы не тратить лимит токенов на
     каждый рестарт бэкенда.
  2. Fallback (если embedding-провайдер недоступен — нет ключа или сбой
     сети): fuzzy-скоринг (rapidfuzz/difflib) со стеммингом (snowballstemmer,
     если установлен) — без него сравнение "билеты" со словом "билет" в
     базе даёт совпадение только по 5 из 6 букв, а не 100%, потому что
     русский язык сильно словоизменяемый (падежи, числа). Это всё равно
     хуже "переживает" перефразировки, чем реальные embeddings, но не даёт
     сервису упасть целиком без интернета/ключа при локальной разработке.

Пороги confidence (HIGH/MEDIUM/LOW, раздел 11 ТЗ) заданы через переменные
окружения с дефолтами ниже. ТЗ прямо требует калибровать их по тестовому
набору не менее 200 вопросов (раздел 21), а не "на глаз" — дефолты здесь
ориентировочные, откалиброванные вручную на десятке примеров, и их нужно
пересмотреть по результатам полного тестового прогона перед продакшеном.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import kb_store

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - fallback path
    import difflib
    _HAS_RAPIDFUZZ = False

try:
    import snowballstemmer
    _RU_STEMMER = snowballstemmer.stemmer("russian")
except ImportError:  # pragma: no cover - fallback path
    _RU_STEMMER = None

import llm

BASE_DIR = Path(__file__).parent
EMBEDDINGS_CACHE_PATH = BASE_DIR / "kb_embeddings_cache.json"

# --- Пороги confidence, см. docstring выше. Масштаб 0..1. -----------------
# Для embedding-косинуса и для fuzzy(/100) пороги разные, т.к. распределения
# похожести у этих двух методов разные (fuzzy обычно даёт более высокие
# числа даже для слабо связанных фраз).
EMB_HIGH = float(os.environ.get("SEMANTIC_HIGH_THRESHOLD", "0.78"))
EMB_LOW = float(os.environ.get("SEMANTIC_LOW_THRESHOLD", "0.55"))
FUZZY_HIGH = float(os.environ.get("FUZZY_HIGH_THRESHOLD", "0.72"))
# Стемминг (см. _stem ниже) заметно поднимает fuzzy-скор в среднем — слова
# сравниваются по основе, а не по точной форме — поэтому нижний порог тоже
# пришлось поднять, иначе посторонние темы стали давать MEDIUM вместо LOW.
FUZZY_LOW = float(os.environ.get("FUZZY_LOW_THRESHOLD", "0.62"))

# Если топ-скор двух ролевых сегментов (visitor/exhibitor) отличается не
# больше, чем на эту величину — считаем, что роль пользователя неоднозначна
# (раздел 4.4 ТЗ), и просим один уточняющий вопрос вместо угадывания.
ROLE_AMBIGUITY_MARGIN = float(os.environ.get("ROLE_AMBIGUITY_MARGIN", "0.08"))

# Сколько предыдущих реплик пользователя учитывать при построении
# поискового запроса, чтобы разрешать контекст ("а воду как подключить?"
# после "у нас необорудованная площадь" — раздел 5 ТЗ).
CONTEXT_TURNS = int(os.environ.get("CONTEXT_TURNS", "2"))

TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "6"))
EMBED_BATCH_SIZE = 32


@dataclass
class Candidate:
    segment: str
    intent: str
    category: str
    question: str
    answer: str
    score: float


@dataclass
class SearchResult:
    segment: str  # "common" | "visitor" | "exhibitor" | "uncertain"
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    candidates: list[Candidate]
    top_score: float
    ambiguous_role: bool = False
    used_semantic: bool = field(default=False)


def _item_variants(item: dict) -> list[str]:
    """
    Раздел 7 ТЗ: каждый элемент базы — это интент с примерами перефразировок.
    Разные перефразировки одного интента — это разные, самостоятельные
    формулировки одного и того же смысла, а не единый "мешок слов". Поэтому
    скорим запрос против каждого варианта ОТДЕЛЬНО и берём максимум —
    склеивание всех вариантов в одну длинную строку размывает похожесть
    (особенно для token-based fuzzy-скоринга) и портит совпадение с самым
    близким по смыслу вариантом.
    """
    variants = [f'{item["category"]}. {item["question"]}']
    variants.extend(item.get("examples", []))
    return variants


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Короткие вопросы почти целиком состоят из служебных слов ("как", "и",
# "на"...), которые случайно совпадают почти со всем в базе и создают
# ложные fuzzy-совпадения ("как зарегистрироваться" может "зацепиться" за
# "как связаться с организатором" только через "как"). embeddings этой
# проблемы не имеют (они оперируют смыслом, а не токенами), поэтому фильтр
# нужен только fuzzy-fallback'у.
_FUZZY_STOPWORDS = {
    "как", "и", "а", "в", "во", "на", "с", "со", "по", "для", "что", "это",
    "у", "к", "ко", "о", "об", "от", "до", "за", "не", "ли", "же", "то",
    "там", "тут", "мне", "нам", "он", "она", "они", "я", "мы", "вы", "ты",
    "его", "её", "их", "или", "вот", "быть", "есть", "нужно", "нужен",
    "нужна", "можно", "если",
}


def _strip_stopwords(text: str) -> str:
    cleaned = [w.strip(".,!?;:()«»\"'") for w in text.split()]
    words = [w for w in cleaned if w and w not in _FUZZY_STOPWORDS]
    return " ".join(words) if words else text


def _stem(text: str) -> str:
    """Приводит слова к основе (падежи/числа/времена), если доступен
    snowballstemmer — "билеты" и "билет", "дате" и "даты" иначе совпадают
    лишь частично по буквам, а не как одно и то же слово."""
    if _RU_STEMMER is None:
        return text
    words = text.split()
    if not words:
        return text
    return " ".join(_RU_STEMMER.stemWords(words))


def _fuzzy_score(a: str, b: str) -> float:
    a = _stem(_strip_stopwords(a.lower().strip()))
    b = _stem(_strip_stopwords(b.lower().strip()))
    if _HAS_RAPIDFUZZ:
        return fuzz.token_set_ratio(a, b) / 100.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _Index:
    """
    Ленивый индекс базы знаний на уровне вариантов формулировок (вопрос +
    каждый пример-перефразировка отдельно, см. _item_variants). У каждого
    варианта есть свой embedding-вектор; при поиске элемент базы получает
    итоговый скор = максимум по своим вариантам.
    """

    def __init__(self):
        self.items: list[dict] = kb_store.all_items()
        # variant_texts[i] относится к элементу items[variant_item_idx[i]]
        self.variant_texts: list[str] = []
        self.variant_item_idx: list[int] = []
        for item_idx, item in enumerate(self.items):
            for variant in _item_variants(item):
                self.variant_texts.append(variant)
                self.variant_item_idx.append(item_idx)
        self.vectors: list[list[float]] | None = None
        self.ready = False

    def _load_cache(self) -> dict[str, list[float]]:
        if not EMBEDDINGS_CACHE_PATH.exists():
            return {}
        try:
            raw = json.loads(EMBEDDINGS_CACHE_PATH.read_text(encoding="utf-8"))
            return raw.get("vectors", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, cache: dict[str, list[float]]) -> None:
        try:
            EMBEDDINGS_CACHE_PATH.write_text(
                json.dumps({"vectors": cache}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def build(self) -> None:
        if self.ready:
            return
        cache = self._load_cache()
        hashes = [_text_hash(t) for t in self.variant_texts]
        missing_idx = [i for i, h in enumerate(hashes) if h not in cache]

        if missing_idx:
            for start in range(0, len(missing_idx), EMBED_BATCH_SIZE):
                batch_idx = missing_idx[start:start + EMBED_BATCH_SIZE]
                batch_texts = [self.variant_texts[i] for i in batch_idx]
                vectors = llm.embed_texts(batch_texts)
                if vectors is None:
                    # Embedding-провайдер недоступен — переходим на fuzzy.
                    self.vectors = None
                    self.ready = True
                    return
                for i, vec in zip(batch_idx, vectors):
                    cache[hashes[i]] = vec
            self._save_cache(cache)

        self.vectors = [cache[h] for h in hashes]
        self.ready = True

_index = _Index()


def _context_text(message: str, history: list[dict] | None) -> str | None:
    """Раздел 5 ТЗ: учитывать предыдущие реплики для разрешения контекста.

    Возвращает None, если истории нет — тогда отдельный контекст-скоринг
    просто не нужен.
    """
    history = history or []
    prior_user = [h["content"] for h in history if h.get("role") == "user"]
    prior_user = prior_user[-CONTEXT_TURNS:]
    if not prior_user:
        return None
    context = " ".join(prior_user)
    return f"{context} {message}"


# Вес текущего сообщения при объединении с контекстным скором. Специально
# НЕ склеиваем историю и текущий вопрос в одну строку для скоринга — это
# размывает совпадение с текущей темой (старые слова из истории "тянут"
# скор к прошлой теме, особенно у token-based fuzzy-метода). Вместо этого
# скорим текущее сообщение и контекст ОТДЕЛЬНО и берём взвешенную сумму:
# текущий вопрос почти всегда важнее, контекст лишь помогает разрешать
# местоимения ("там", "воду" после "необорудованная площадь").
CURRENT_MESSAGE_WEIGHT = float(os.environ.get("CURRENT_MESSAGE_WEIGHT", "0.75"))

# Но короткие "эллиптические" ответы (раздел 4.4 ТЗ: "Уточните — вы
# посетитель или экспонент?" -> "посетитель") почти не несут собственного
# смысла сами по себе — это ответ на предыдущий уточняющий вопрос бота, а
# не новая тема. Если веса не поменять местами, такая короткая реплика
# "перевешивает" настоящий вопрос из предыдущего хода и топит его.
#
# ВАЖНО: короткая длина сама по себе — плохой признак. "о дате" или "что
# насчёт билетов" тоже короткие, но это самостоятельные новые вопросы, а
# не ответ на уточнение — им, наоборот, нужен полный вес на себя. Поэтому
# инверсию весов включаем ТОЛЬКО когда предыдущая реплика БОТА похожа на
# уточняющий вопрос (заканчивается на "?" — так оканчиваются и
# ROLE_CLARIFY_REPLY, и llm.clarify(), но не обычные ответы по базе и не
# NO_MATCH_REPLY). Без этого условия короткие самостоятельные вопросы
# после любого предыдущего хода ошибочно "тонут" в чужом контексте.
SHORT_REPLY_WORD_THRESHOLD = int(os.environ.get("SHORT_REPLY_WORD_THRESHOLD", "3"))
SHORT_REPLY_CURRENT_WEIGHT = float(os.environ.get("SHORT_REPLY_CURRENT_WEIGHT", "0.3"))


def _last_bot_turn_is_clarifying(history: list[dict] | None) -> bool:
    for turn in reversed(history or []):
        if turn.get("role") == "assistant":
            return turn.get("content", "").strip().endswith("?")
    return False


def _effective_current_weight(message: str, history: list[dict] | None) -> float:
    is_short = len(message.split()) <= SHORT_REPLY_WORD_THRESHOLD
    if is_short and _last_bot_turn_is_clarifying(history):
        return SHORT_REPLY_CURRENT_WEIGHT
    return CURRENT_MESSAGE_WEIGHT


# Раздел 4.4 ТЗ: после уточняющего вопроса про роль ("вы посетитель или
# экспонент?") пользователь обычно отвечает коротко и прямо. Такой ответ
# однозначен по своей природе — его не нужно прогонять через content-скоринг
# наравне с обычными вопросами (там он снова может попасть в "uncertain" по
# сырым скорам темы, как это уже было исправлено выше весами контекста).
_VISITOR_ROLE_WORDS = {"посетитель", "посетителя", "посетителем", "гость", "гостем"}
_EXHIBITOR_ROLE_WORDS = {
    "экспонент", "экспонента", "экспонентом", "участник", "участника", "участником",
}


def _explicit_role_reply(message: str) -> str | None:
    words = message.lower().split()
    if len(words) > SHORT_REPLY_WORD_THRESHOLD:
        return None
    cleaned = {w.strip(".,!?;:()«»\"'") for w in words}
    if cleaned & _VISITOR_ROLE_WORDS:
        return "visitor"
    if cleaned & _EXHIBITOR_ROLE_WORDS:
        return "exhibitor"
    return None


def build_search_query(message: str, history: list[dict] | None) -> str:
    """Оставлено для обратной совместимости/отладки — человекочитаемое
    представление того, что видит поиск. Сам скоринг использует
    _context_text и message раздельно, см. search()."""
    context = _context_text(message, history)
    return message if context is None else context


def _aggregate_per_item(variant_scores: list[float]) -> list[float]:
    item_scores = [0.0] * len(_index.items)
    for variant_score, item_idx in zip(variant_scores, _index.variant_item_idx):
        if variant_score > item_scores[item_idx]:
            item_scores[item_idx] = variant_score
    return item_scores


def _score_all(message: str, history: list[dict] | None) -> tuple[list[float], bool]:
    """
    Скор по каждому item базы для запроса пользователя. Если есть история,
    текущее сообщение и контекст (см. _context_text) эмбеддятся ОДНИМ
    батч-запросом — это и быстрее (один HTTP-round-trip вместо двух), и
    исключает рассинхрон, при котором один запрос уйдёт через embeddings,
    а другой при сетевом сбое откатится на fuzzy (тогда пришлось бы
    складывать несравнимые шкалы похожести).
    """
    _index.build()
    context = _context_text(message, history)
    queries = [message] if context is None else [message, context]

    variant_scores_per_query: list[list[float]] | None = None
    used_semantic = False
    if _index.vectors is not None:
        qvecs = llm.embed_texts(queries)
        if qvecs is not None and len(qvecs) == len(queries):
            used_semantic = True
            variant_scores_per_query = [
                [_cosine(qvec, v) for v in _index.vectors] for qvec in qvecs
            ]

    if variant_scores_per_query is None:
        variant_scores_per_query = [
            [_fuzzy_score(q, t) for t in _index.variant_texts] for q in queries
        ]

    per_query_item_scores = [_aggregate_per_item(vs) for vs in variant_scores_per_query]
    if len(queries) == 1:
        return per_query_item_scores[0], used_semantic

    current_scores, context_scores = per_query_item_scores
    weight = _effective_current_weight(message, history)
    combined = [
        weight * cs + (1 - weight) * xs
        for cs, xs in zip(current_scores, context_scores)
    ]
    return combined, used_semantic


def search(message: str, history: list[dict] | None = None) -> SearchResult:
    scores, used_semantic = _score_all(message, history)
    high = EMB_HIGH if used_semantic else FUZZY_HIGH
    low = EMB_LOW if used_semantic else FUZZY_LOW

    all_candidates = [
        Candidate(
            segment=item["segment"],
            intent=item["intent"],
            category=item["category"],
            question=item["question"],
            answer=item["answer"],
            score=score,
        )
        for item, score in zip(_index.items, scores)
    ]
    all_candidates.sort(key=lambda c: c.score, reverse=True)

    def top_score(segment: str) -> float:
        seg_scores = [c.score for c in all_candidates if c.segment == segment]
        return max(seg_scores) if seg_scores else 0.0

    common_top = top_score("common")
    visitor_top = top_score("visitor")
    exhibitor_top = top_score("exhibitor")

    # Порядок проверок важен. Сначала смотрим, не является ли роль
    # неоднозначной (visitor vs exhibitor почти одинаковый скор) — раздел
    # 4.4 ТЗ. "common" разрешаем перехватить решение только тогда, когда
    # он выигрывает с заметным отрывом (см. ROLE_AMBIGUITY_MARGIN) — иначе
    # случайный шумовой скор common-факта (например, оба слова "как" и "и"
    # совпали с контактами организатора) не должен маскировать настоящую
    # ролевую неопределённость слабым, но формальным перевесом.
    ambiguous_role = False
    role_max = max(visitor_top, exhibitor_top)
    role_ambiguous_now = abs(visitor_top - exhibitor_top) <= ROLE_AMBIGUITY_MARGIN and role_max >= low
    explicit_role = _explicit_role_reply(message)

    if explicit_role is not None:
        segment = explicit_role
    elif common_top >= role_max + ROLE_AMBIGUITY_MARGIN:
        segment = "common"
    elif role_ambiguous_now:
        segment = "uncertain"
        ambiguous_role = True
    elif common_top >= role_max:
        segment = "common"
    else:
        segment = "visitor" if visitor_top > exhibitor_top else "exhibitor"

    if segment == "uncertain":
        relevant_segments = {"visitor", "exhibitor"}
        seg_top = max(visitor_top, exhibitor_top)
    elif segment == "common":
        relevant_segments = {"common"}
        seg_top = common_top
    else:
        relevant_segments = {segment, "common"}
        seg_top = top_score(segment)

    candidates = [c for c in all_candidates if c.segment in relevant_segments][:TOP_K]

    if seg_top >= high:
        confidence = "HIGH"
    elif seg_top >= low:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Дополнительный признак неоднозначности темы (не только роли): топ-1 и
    # топ-2 кандидата из РАЗНЫХ КАТЕГОРИЙ близки друг к другу по скору —
    # снижаем уверенность до MEDIUM, даже если сам скор высокий. Сравниваем
    # именно категорию, а не intent: два разных intent-а из одной категории
    # (например, "как заказать электричество на стенде" и "как подключить
    # стенд к электричеству на необорудованной площади" — оба из
    # "Электропитание") — это не неоднозначность, а несколько релевантных
    # фактов по одной теме, которые LLM и так объединит в ответе (раздел 8
    # ТЗ, RAG). Порог относительный (доля от топ-1), а не абсолютный, чтобы
    # работать и на высоких, и на средних скорах. NB: с fuzzy-fallback (без
    # embeddings) этот эвристический сигнал слабее, чем с реальным semantic
    # search — см. docstring модуля и раздел 11 ТЗ про калибровку порогов.
    # Второй сигнал неоднозначности: даже в ОДНОЙ категории генерическое
    # слово ("пропуск") может дать МНОГО (3+) равно правдоподобных, но
    # взаимоисключающих кандидатов (бейдж / монтажный пропуск / пропуск
    # ПРР — раздел 10 ТЗ, обязательный пример уточнения) — это не "несколько
    # дополняющих друг друга фактов", а реальный выбор между вариантами.
    # Отличается от электропитания тем, что там кандидатов с высоким
    # скором всего два, а тут — сразу пять-шесть.
    if confidence == "HIGH" and len(candidates) >= 2:
        top1, top2 = candidates[0], candidates[1]
        near_top_count = sum(1 for c in candidates if top1.score > 0 and c.score / top1.score >= 0.75)
        if top1.score > 0 and (
            (top1.category != top2.category and (top2.score / top1.score) >= 0.75)
            or near_top_count >= 3
        ):
            confidence = "MEDIUM"

    return SearchResult(
        segment=segment,
        confidence=confidence,
        candidates=candidates,
        top_score=seg_top,
        ambiguous_role=ambiguous_role,
        used_semantic=used_semantic,
    )
