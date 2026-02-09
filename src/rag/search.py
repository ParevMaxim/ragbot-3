# rag/search.py
from typing import List, Dict
import math

import numpy as np
from rank_bm25 import BM25Okapi

from .llm import embed_texts, rewrite_query, answer_with_context
from .storage import load_kb


from typing import List, Dict
import math
import time

import numpy as np
from rank_bm25 import BM25Okapi

from .llm import embed_texts, rewrite_query, answer_with_context
from .storage import load_kb


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-8
    nb = math.sqrt(sum(x * x for x in b)) or 1e-8
    return dot / (na * nb)


def _tokenize(text: str) -> List[str]:
    return text.lower().split()


def answer_question(kb_name: str, question: str, top_k: int = 8) -> str:
    """
    RAG-пайплайн с простым профилингом по шагам.
    """
    t0 = time.perf_counter()

    # 1) переписывание запроса
    rewritten = rewrite_query(question)
    t1 = time.perf_counter()

    kb = load_kb(kb_name)
    if not kb:
        print("[RAG] KB пустая, ответить нельзя.")
        return (
            "Запрос для поиска по документации:\n"
            f"{rewritten}\n\n"
            f"База знаний '{kb_name}' пуста. Сначала проиндексируйте документацию."
        )

    texts = [ch.text for ch in kb]
    sources = [ch.source for ch in kb]
    sections = [ch.section for ch in kb]
    embeddings = [ch.embedding for ch in kb]

    n_docs = len(texts)

    # 2) эмбеддинг переписанного запроса
    query_vec = embed_texts([rewritten])[0]
    t2 = time.perf_counter()

    # 3) семантический скор
    sem_scores = np.array([_cosine_sim(query_vec, emb) for emb in embeddings], dtype=float)

    # 4) лексический скор (BM25)
    corpus_tokens = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus_tokens)
    lex_scores = np.array(bm25.get_scores(_tokenize(question)), dtype=float)
    t3 = time.perf_counter()

    # нормализация
    def normalize(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return arr
        mn, mx = float(arr.min()), float(arr.max())
        if mx - mn < 1e-8:
            return np.ones_like(arr) * 0.5
        return (arr - mn) / (mx - mn)

    sem_norm = normalize(sem_scores)
    lex_norm = normalize(lex_scores)

    alpha = 0.7
    final_scores = alpha * sem_norm + (1.0 - alpha) * lex_norm

    if float(final_scores.max()) < 0.2:
        print("[RAG] Релевантных фрагментов почти нет (final_scores.max < 0.2).")
        return (
            "Запрос для поиска по документации:\n"
            f"{rewritten}\n\n"
            "Не удалось найти релевантные фрагменты в базе знаний. "
            "Видимо, в документации нет прямого ответа на этот вопрос."
        )

    top_k = min(top_k, n_docs)
    order = np.argsort(-final_scores)[:top_k]

    hits = []
    for idx in order:
        hits.append(
            {
                "text": texts[int(idx)],
                "source": sources[int(idx)],
                "section": sections[int(idx)],
                "score": float(final_scores[int(idx)]),
            }
        )

    # 5) генерация ответа LLM
    t4 = time.perf_counter()
    answer = answer_with_context(question, hits)
    t5 = time.perf_counter()

    # Выводим профилинг в консоль
    print(f"[RAG] rewrite_query: {t1 - t0:.2f} s")
    print(f"[RAG] embed_texts (query): {t2 - t1:.2f} s")
    print(f"[RAG] search (cosine+BM25): {t3 - t2:.2f} s")
    print(f"[RAG] prep hits: {t4 - t3:.2f} s")
    print(f"[RAG] answer_with_context (LLM): {t5 - t4:.2f} s")
    print(f"[RAG] TOTAL: {t5 - t0:.2f} s  (docs={n_docs})")

    return (
        "Запрос для поиска по документации:\n"
        f"{rewritten}\n\n"
        f"{answer}"
    )


def debug_retrieval(kb_name: str, question: str, top_k: int = 10) -> List[Dict]:
    """
    Диагностика: возвращает top-K чанков с их скором и текстом.
    Никакого LLM-ответа здесь нет, только поиск.
    """
    rewritten = rewrite_query(question)

    kb = load_kb(kb_name)
    if not kb:
        return []

    texts = [ch.text for ch in kb]
    sources = [ch.source for ch in kb]
    sections = [ch.section for ch in kb]
    embeddings = [ch.embedding for ch in kb]

    n_docs = len(texts)
    if n_docs == 0:
        return []

    # Эмбеддинг запроса
    query_vec = embed_texts([rewritten])[0]

    # Семантические скора
    sem_scores = np.array([_cosine_sim(query_vec, emb) for emb in embeddings], dtype=float)

    # Лексические скора
    corpus_tokens = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus_tokens)
    lex_scores = np.array(bm25.get_scores(_tokenize(question)), dtype=float)

    # Нормализация
    def normalize(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return arr
        mn, mx = float(arr.min()), float(arr.max())
        if mx - mn < 1e-8:
            return np.ones_like(arr) * 0.5
        return (arr - mn) / (mx - mn)

    sem_norm = normalize(sem_scores)
    lex_norm = normalize(lex_scores)

    alpha = 0.7
    final_scores = alpha * sem_norm + (1.0 - alpha) * lex_norm

    top_k = min(top_k, n_docs)
    order = np.argsort(-final_scores)[:top_k]

    results = []
    for idx in order:
        i = int(idx)
        results.append(
            {
                "index": i,
                "score": float(final_scores[i]),
                "semantic": float(sem_norm[i]),
                "lexical": float(lex_norm[i]),
                "source": sources[i],
                "section": sections[i],
                "text": texts[i][:400] + ("..." if len(texts[i]) > 400 else ""),
            }
        )
    return results


