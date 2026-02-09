# rag/storage.py
from pathlib import Path
from typing import List
import pickle

from .models import Chunk
from config import KB_DIR

KB_DIR_PATH = Path(KB_DIR)
KB_DIR_PATH.mkdir(parents=True, exist_ok=True)


def kb_file_path(kb_name: str) -> Path:
    """
    kb_name — произвольное имя базы знаний (без пути).
    Физический файл: KB_DIR / (kb_name + ".pkl")
    """
    if kb_name.endswith(".pkl"):
        kb_name = kb_name[:-4]
    return KB_DIR_PATH / f"{kb_name}.pkl"


def load_kb(kb_name: str) -> List[Chunk]:
    path = kb_file_path(kb_name)
    if not path.exists():
        return []
    with open(path, "rb") as f:
        raw = pickle.load(f)
    return [Chunk.from_dict(d) for d in raw]


def save_kb(kb_name: str, chunks: List[Chunk]) -> None:
    path = kb_file_path(kb_name)
    data = [ch.to_dict() for ch in chunks]
    with open(path, "wb") as f:
        pickle.dump(data, f)


def add_chunks(kb_name: str, new_chunks: List[Chunk]) -> None:
    kb = load_kb(kb_name)
    kb.extend(new_chunks)
    save_kb(kb_name, kb)