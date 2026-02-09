# config.py
import os
from dotenv import load_dotenv

load_dotenv()


def default_data_dir() -> str:
    """
    Базовая папка данных приложения в Windows:
    %LOCALAPPDATA%\RAGChat
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.expanduser("~")
    return os.path.join(base, "RAGChat")


# Ollama
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

# Модели LLM
CHAT_MODEL_MAIN = os.getenv("CHAT_MODEL_MAIN") or os.getenv("CHAT_MODEL") or "llama3.1"
CHAT_MODEL_SECONDARY = os.getenv("CHAT_MODEL_SECONDARY", CHAT_MODEL_MAIN)
AGGREGATE_MODEL = os.getenv("AGGREGATE_MODEL", CHAT_MODEL_MAIN)
REWRITE_MODEL = os.getenv("REWRITE_MODEL", CHAT_MODEL_MAIN)

# Эмбеддинги
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

# Язык документации:
#   "en"/"ru"/... → переписываем и переводим на этот язык
#   "same"        → оставляем язык пользователя
DOC_LANGUAGE = os.getenv("DOC_LANGUAGE", "same")

# Директории (данные приложения)
# По умолчанию храним KB в профиле пользователя, чтобы не требовать прав администратора.
KB_DIR = os.getenv("KB_DIR", os.path.join(default_data_dir(), "kb"))