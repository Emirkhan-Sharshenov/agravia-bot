"""
Ранжирование фактов базы знаний под запрос пользователя.

Роль и тему вопроса определяет router.py (LLM). Здесь остаётся только
"какие из подходящих фактов ближе к формулировке": внутри уже отобранных по
теме элементов базы (kb_store.items_for_topics) либо, для произвольных
вопросов ("other"), по всей базе в сегментах роли.

Стратегия скоринга:
  1. Основная: embedding-векторы (GigaChat Embeddings, llm.embed_texts) +
     косинусная близость. Векторы считаются один раз и кэшируются на диске
     (kb_embeddings_cache.json).
  2. Fallback (нет ключа/сбой сети): fuzzy-скоринг (rapidfuzz/difflib) со
     стеммингом (snowballstemmer) — без него "билеты" и "билет" совпадают
     лишь частично по буквам, потому что русский язык сильно
     словоизменяемый. Хуже "переживает" перефразировки, чем embeddings, но
     не даёт сервису упасть без ключа.

Порог "ничего подходящего не нашли" (для вопросов вне размеченных тем)
берётся через переменные окружения и должен калиброваться на тестовом
наборе (раздел 11/21 ТЗ v1).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
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

# Минимальный скор лучшего кандидата, ниже которого вопрос "other" считаем
# не найденным в базе. Масштаб 0..1; для embeddings и fuzzy разные.
EMB_LOW = float(os.environ.get("SEMANTIC_LOW_THRESHOLD", "0.55"))
FUZZY_LOW = float(os.environ.get("FUZZY_LOW_THRESHOLD", "0.62"))

# Сколько предыдущих реплик пользователя учитывать, чтобы короткие
# follow-up-вопросы ("а на второй день?") ранжировались в контексте темы.
CONTEXT_TURNS = int(os.environ.get("CONTEXT_TURNS", "2"))
# Вес текущего сообщения против контекста; для очень коротких сообщений
# (<= SHORT_REPLY_WORD_THRESHOLD слов) контекст важнее.
CURRENT_MESSAGE_WEIGHT = float(os.environ.get("CURRENT_MESSAGE_WEIGHT", "0.75"))
SHORT_REPLY_WORD_THRESHOLD = int(os.environ.get("SHORT_REPLY_WORD_THRESHOLD", "3"))
SHORT_REPLY_CURRENT_WEIGHT = float(os.environ.get("SHORT_REPLY_CURRENT_WEIGHT", "0.45"))

EMBED_BATCH_SIZE = 32


@dataclass
class Candidate:
    segment: str
    intent: str
    category: str
    question: str
    answer: str
    score: float


def _item_variants(item: dict) -> list[str]:
    """Вопрос и каждый пример-перефразировка скорятся ОТДЕЛЬНО (максимум по
    элементу): склейка в одну строку размывает похожесть."""
    variants = [f'{item["category"]}. {item["question"]}']
    variants.extend(item.get("examples", []))
    return variants


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Служебные слова случайно совпадают почти со всем в базе и дают ложные
# fuzzy-совпадения; embeddings этой проблемы не имеют.
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
    if _RU_STEMMER is None:
        return text
    words = text.split()
    return " ".join(_RU_STEMMER.stemWords(words)) if words else text


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
    """Индекс на уровне вариантов формулировок: текст + (опционально)
    embedding-вектор; скор элемента = максимум по его вариантам."""

    def __init__(self):
        self.items: list[dict] = kb_store.all_items()
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
            return json.loads(EMBEDDINGS_CACHE_PATH.read_text(encoding="utf-8")).get("vectors", {})
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
                vectors = llm.embed_texts([self.variant_texts[i] for i in batch_idx])
                if vectors is None:  # embeddings недоступны — переходим на fuzzy
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
    prior_user = [h["content"] for h in (history or []) if h.get("role") == "user"]
    prior_user = prior_user[-CONTEXT_TURNS:]
    if not prior_user:
        return None
    return f"{' '.join(prior_user)} {message}"


def _aggregate_per_item(variant_scores: list[float]) -> list[float]:
    item_scores = [0.0] * len(_index.items)
    for variant_score, item_idx in zip(variant_scores, _index.variant_item_idx):
        if variant_score > item_scores[item_idx]:
            item_scores[item_idx] = variant_score
    return item_scores


def _score_all(message: str, history: list[dict] | None) -> tuple[list[float], bool]:
    """Скор по каждому item базы. Текущее сообщение и контекст эмбеддятся
    одним батч-запросом (один HTTP-round-trip, и оба либо через embeddings,
    либо оба через fuzzy — шкалы не смешиваются)."""
    _index.build()
    context = _context_text(message, history)
    queries = [message] if context is None else [message, context]

    per_query: list[list[float]] | None = None
    used_semantic = False
    if _index.vectors is not None:
        qvecs = llm.embed_texts(queries)
        if qvecs is not None and len(qvecs) == len(queries):
            used_semantic = True
            per_query = [[_cosine(qv, v) for v in _index.vectors] for qv in qvecs]
    if per_query is None:
        per_query = [[_fuzzy_score(q, t) for t in _index.variant_texts] for q in queries]

    item_scores = [_aggregate_per_item(vs) for vs in per_query]
    if len(queries) == 1:
        return item_scores[0], used_semantic

    weight = (
        SHORT_REPLY_CURRENT_WEIGHT
        if len(message.split()) <= SHORT_REPLY_WORD_THRESHOLD
        else CURRENT_MESSAGE_WEIGHT
    )
    current, context_scores = item_scores
    return [weight * c + (1 - weight) * x for c, x in zip(current, context_scores)], used_semantic


def rank(
    message: str,
    history: list[dict] | None = None,
    items: list[dict] | None = None,
    segments: set[str] | None = None,
) -> tuple[list[Candidate], float]:
    """
    Кандидаты по убыванию скора и порог "ничего подходящего" для текущего
    метода скоринга. Ограничение: либо конкретные элементы (items — обычно
    отобранные по теме), либо сегменты базы.
    """
    scores, used_semantic = _score_all(message, history)
    allowed = {it["intent"] for it in items} if items is not None else None
    out = []
    for item, score in zip(_index.items, scores):
        if allowed is not None and item["intent"] not in allowed:
            continue
        if segments is not None and item["segment"] not in segments:
            continue
        out.append(
            Candidate(
                segment=item["segment"],
                intent=item["intent"],
                category=item["category"],
                question=item["question"],
                answer=item["answer"],
                score=score,
            )
        )
    out.sort(key=lambda c: c.score, reverse=True)
    return out, (EMB_LOW if used_semantic else FUZZY_LOW)
