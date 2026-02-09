# rag/llm.py
from typing import List, Dict, Callable, Optional
import ollama

from config import (
    OLLAMA_HOST,
    EMBEDDING_MODEL,
    DOC_LANGUAGE,
    CHAT_MODEL_MAIN as CFG_CHAT_MODEL_MAIN,
    CHAT_MODEL_SECONDARY as CFG_CHAT_MODEL_SECONDARY,
    REWRITE_MODEL as CFG_REWRITE_MODEL,
    AGGREGATE_MODEL as CFG_AGGREGATE_MODEL,
)

ollama_client = ollama.Client(host=OLLAMA_HOST)

# Текущие модели (можно менять из приложения)
CHAT_MODEL_MAIN = CFG_CHAT_MODEL_MAIN
CHAT_MODEL_SECONDARY = CFG_CHAT_MODEL_SECONDARY
REWRITE_MODEL = CFG_REWRITE_MODEL
AGGREGATE_MODEL = CFG_AGGREGATE_MODEL

# максимально допустимая длина текста для эмбеддинга (символы)
MAX_EMBED_CHARS = 4000  # ~1300 токенов, безопасно для nomic-embed-text


def set_llm_main(model_name: str):
    """
    Устанавливает основную модель LLM.
    Используется и как основная, и как secondary/aggregate/rewrite (по умолчанию).
    """
    global CHAT_MODEL_MAIN, CHAT_MODEL_SECONDARY, REWRITE_MODEL, AGGREGATE_MODEL
    CHAT_MODEL_MAIN = model_name
    CHAT_MODEL_SECONDARY = model_name
    REWRITE_MODEL = model_name
    AGGREGATE_MODEL = model_name


def get_llm_main() -> str:
    return CHAT_MODEL_MAIN


def embed_texts(
    texts: List[str],
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[List[float]]:
    """
    Считает эмбеддинги для списка текстов через Ollama embeddings.
    Если передан progress(i, total), будет вызываться после каждого текста.
    Текст усечётся до MAX_EMBED_CHARS символов.
    """
    vectors: List[List[float]] = []
    total = len(texts)

    for i, t in enumerate(texts, start=1):
        if len(t) > MAX_EMBED_CHARS:
            t = t[:MAX_EMBED_CHARS]

        resp = ollama_client.embeddings(
            model=EMBEDDING_MODEL,
            prompt=t
        )
        vectors.append(resp["embedding"])

        if progress:
            try:
                progress(i, total)
            except Exception:
                pass

    return vectors


def _ollama_chat(model_name: str, messages: List[Dict[str, str]]) -> str:
    resp = ollama_client.chat(
        model=model_name,
        messages=messages,
    )
    return resp["message"]["content"].strip()


def rewrite_query(question: str, doc_language: str | None = None) -> str:
    """
    Переписывает/переводит запрос в канонический технический запрос.
    Жёстко требуем КРАТКИЙ ТЕКСТ БЕЗ КОДА.
    """
    target = (doc_language or DOC_LANGUAGE or "same").lower()

    if target == "same":
        system = (
            "Ты модуль нормализации поисковых запросов.\n"
            "Получаешь вопрос пользователя на ЛЮБОМ языке.\n"
            "Требования к ответу:\n"
            "- ОДНА короткая строка текста (1 предложение).\n"
            "- Без примеров кода, без форматирования, без маркеров списка.\n"
            "- Не используй ``` и переносы строк.\n"
            "- Сохрани исходный язык вопроса.\n"
            "НЕ отвечай на сам вопрос, только переформулируй его как поисковый запрос."
        )
        user = f"Перепиши этот запрос в виде краткого поискового запроса:\n{question}"
    else:
        system = (
            "Ты модуль нормализации и перевода поисковых запросов для RAG-системы.\n"
            f"Документация в основном на языке с кодом: {target}.\n"
            "Требования к ответу:\n"
            "- ОДНА короткая строка текста (1 предложение) на языке документации.\n"
            "- Без примеров кода, без форматирования, без маркеров списка.\n"
            "- Не используй ``` и переносы строк.\n"
            "НЕ отвечай на сам вопрос, только переформулируй его как поисковый запрос "
            "на языке документации."
        )
        user = f"Вопрос пользователя:\n{question}\n\nДай итоговый поисковый запрос:"

    rewritten = _ollama_chat(
        REWRITE_MODEL,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    # Пост-обработка: убираем переносы и всё, что похоже на код
    rewritten = rewritten.replace("\n", " ").replace("```", " ").strip()
    # На всякий случай ограничим длину
    if len(rewritten) > 200:
        rewritten = rewritten[:200]

    return rewritten


def answer_with_context(question: str, context_chunks: List[Dict]) -> str:
    """
    Ансамбль моделей для ответа:
    - CHAT_MODEL_MAIN даёт ответ по контексту;
    - CHAT_MODEL_SECONDARY (если отличается) тоже отвечает;
    - AGGREGATE_MODEL сверяет ответы и выдаёт итоговый.
    context_chunks: [{text, source, section, ...}, ...]
    """
    context_text = ""
    for i, ch in enumerate(context_chunks, start=1):
        src = ch.get("source", "")
        sec = ch.get("section", "")
        meta = f"{src}" + (f" — {sec}" if sec else "")
        context_text += f"[Фрагмент {i} — {meta}]\n{ch['text']}\n\n"

    base_system = (
        "Ты помощник по технической документации.\n"
        "- Определи язык вопроса и отвечай на нём.\n"
        "- Отвечай строго на основе переданного контекста.\n"
        "- Если нужной информации нет — прямо скажи об этом и не выдумывай.\n"
        "- Можно перефразировать и обобщать текст из контекста, "
        "но не добавляй факты, которых там нет."
    )

    base_user = (
        f"Вопрос пользователя:\n{question}\n\n"
        f"Контекст из документации:\n{context_text}"
    )

    answer_main = _ollama_chat(
        CHAT_MODEL_MAIN,
        [
            {"role": "system", "content": base_system},
            {"role": "user", "content": base_user},
        ],
    )

    answer_secondary = ""
    if CHAT_MODEL_SECONDARY and CHAT_MODEL_SECONDARY != CHAT_MODEL_MAIN:
        answer_secondary = _ollama_chat(
            CHAT_MODEL_SECONDARY,
            [
                {"role": "system", "content": base_system},
                {"role": "user", "content": base_user},
            ],
        )

    agg_system = (
        "Ты агрегатор ответов нескольких моделей.\n"
        "У тебя есть вопрос, контекст и 1–2 ответа моделей.\n"
        "Сверь ответы с контекстом, убери выдумки, при противоречиях опирайся только "
        "на то, что явно следует из контекста. "
        "Верни один, максимально точный ответ на языке пользователя."
    )

    agg_user = (
        f"Вопрос пользователя:\n{question}\n\n"
        f"Контекст:\n{context_text}\n\n"
        f"Ответ модели A ({CHAT_MODEL_MAIN}):\n{answer_main}\n\n"
        f"Ответ модели B ({CHAT_MODEL_SECONDARY}):\n"
        f"{answer_secondary or '(нет второго ответа)'}\n\n"
        "Дай итоговый проверенный ответ:"
    )

    final_answer = _ollama_chat(
        AGGREGATE_MODEL,
        [
            {"role": "system", "content": agg_system},
            {"role": "user", "content": agg_user},
        ],
    )

    return final_answer