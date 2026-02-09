# rag/models.py
from dataclasses import dataclass, asdict
from typing import List, Dict, Any


@dataclass
class Chunk:
    """
    Один фрагмент (чанк) документа в базе знаний.
    """
    text: str
    embedding: List[float]
    source: str        # путь к файлу / имя файла
    section: str       # раздел, страница и т.п.
    project: str       # проект / система
    version: str       # версия документации
    tags: List[str]    # произвольные теги

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Chunk":
        return Chunk(
            text=d["text"],
            embedding=d["embedding"],
            source=d.get("source", ""),
            section=d.get("section", ""),
            project=d.get("project", ""),
            version=d.get("version", ""),
            tags=d.get("tags", []),
        )