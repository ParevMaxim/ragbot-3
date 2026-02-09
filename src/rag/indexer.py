# rag/indexer.py
from pathlib import Path
from typing import List, Optional, Callable
import os
import zipfile

from pypdf import PdfReader
from bs4 import BeautifulSoup

from .llm import embed_texts
from .models import Chunk
from .storage import add_chunks

# progress(stage: str, current: int, total: int)
ProgressFn = Callable[[str, int, int], None]


def split_into_blocks(text: str) -> List[str]:
    """
    Разбиваем текст на логические блоки по пустым строкам.
    Каждый блок — абзац / кусок кода / таблица, мы их не рвём.
    """
    raw_blocks = text.replace("\r\n", "\n").split("\n\n")
    blocks = []
    for blk in raw_blocks:
        blk = "\n".join(line.strip() for line in blk.split("\n")).strip()
        if blk:
            blocks.append(blk)
    return blocks


def make_chunks_from_blocks(blocks: List[str], max_chars: int = 1500) -> List[str]:
    """
    Структурный чанкинг:
    - собираем чанки из целых блоков (абзацев),
    - не превышаем max_chars по длине чанка;
    - если один блок сам длиннее max_chars — режем его внутри.
    """
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for blk in blocks:
        if len(blk) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0

            start = 0
            text = blk
            while start < len(text):
                end = start + max_chars
                part = text[start:end]
                chunks.append(part)
                start = end
            continue

        blk_len = len(blk) + 2
        if current and current_len + blk_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [blk]
            current_len = blk_len
        else:
            current.append(blk)
            current_len += blk_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def html_to_blocks(html_content: str) -> List[str]:
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup(["nav", "footer", "header", "script", "style"]):
        tag.decompose()

    body = soup.body or soup
    blocks: List[str] = []

    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6",
                             "p", "li", "pre", "code", "table"]):
        text = el.get_text(separator=" ", strip=True)
        if text:
            if el.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(el.name[1])
                prefix = "#" * level
                blocks.append(f"{prefix} {text}")
            else:
                blocks.append(text)

    return blocks


def index_pdf_file(
    file_path: str,
    kb_name: str,
    project: str,
    version: str,
    progress: Optional[ProgressFn] = None,
):
    p = Path(file_path)
    if progress:
        progress(f"PDF {p.name}: читаю документ", 0, 1)

    reader = PdfReader(str(p))
    total_pages = len(reader.pages)

    texts: List[str] = []
    metas: List[dict] = []

    if progress:
        progress(f"PDF {p.name}: разбиение на страницы", 0, total_pages)

    for page_num, page in enumerate(reader.pages, start=1):
        raw = page.extract_text()
        if not raw:
            continue

        blocks = split_into_blocks(raw)
        chunks = make_chunks_from_blocks(blocks)

        for ch in chunks:
            texts.append(ch)
            metas.append({
                "source": p.name,
                "section": f"page {page_num}",
                "project": project,
                "version": version,
                "tags": ["pdf"],
            })

        if progress:
            progress(f"PDF {p.name}: обработка страниц", page_num, total_pages)

    if not texts:
        if progress:
            progress(f"PDF {p.name}: не удалось извлечь текст", 1, 1)
        return

    if progress:
        def emb_prog(i: int, total: int):
            progress(f"PDF {p.name}: вычисление эмбеддингов", i, total)

        vectors = embed_texts(texts, progress=emb_prog)
    else:
        vectors = embed_texts(texts)

    chunks: List[Chunk] = []
    for vec, meta, text in zip(vectors, metas, texts):
        chunks.append(Chunk(
            text=text,
            embedding=vec,
            source=meta["source"],
            section=meta["section"],
            project=meta["project"],
            version=meta["version"],
            tags=meta["tags"],
        ))

    add_chunks(kb_name, chunks)

    if progress:
        progress(f"PDF {p.name}: индексация завершена", 1, 1)


def index_html_file(
    file_path: str,
    kb_name: str,
    project: str,
    version: str,
    root: Optional[str] = None,
    progress: Optional[ProgressFn] = None,
):
    p = Path(file_path)
    if progress:
        progress(f"HTML {p.name}: читаю файл", 0, 1)

    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    blocks = html_to_blocks(html)
    chunks_text = make_chunks_from_blocks(blocks)

    rel = os.path.relpath(str(p), root) if root else p.name

    if not chunks_text:
        if progress:
            progress(f"HTML {p.name}: текст не найден", 1, 1)
        return

    if progress:
        def emb_prog(i: int, total: int):
            progress(f"HTML {p.name}: вычисление эмбеддингов", i, total)

        vectors = embed_texts(chunks_text, progress=emb_prog)
    else:
        vectors = embed_texts(chunks_text)

    chunks: List[Chunk] = []
    for vec, text in zip(vectors, chunks_text):
        chunks.append(Chunk(
            text=text,
            embedding=vec,
            source=str(rel),
            section="",
            project=project,
            version=version,
            tags=["html"],
        ))

    add_chunks(kb_name, chunks)

    if progress:
        progress(f"HTML {p.name}: индексация завершена", 1, 1)


def index_md_file(
    file_path: str,
    kb_name: str,
    project: str,
    version: str,
    progress: Optional[ProgressFn] = None,
):
    """
    Простой парсер Markdown: читаем файл как текст, режем по блокам.
    """
    p = Path(file_path)
    if progress:
        progress(f"MD {p.name}: читаю файл", 0, 1)

    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    blocks = split_into_blocks(text)
    chunks_text = make_chunks_from_blocks(blocks)

    if not chunks_text:
        if progress:
            progress(f"MD {p.name}: текст не найден", 1, 1)
        return

    if progress:
        def emb_prog(i: int, total: int):
            progress(f"MD {p.name}: вычисление эмбеддингов", i, total)

        vectors = embed_texts(chunks_text, progress=emb_prog)
    else:
        vectors = embed_texts(chunks_text)

    chunks: List[Chunk] = []
    for vec, ch_text in zip(vectors, chunks_text):
        chunks.append(Chunk(
            text=ch_text,
            embedding=vec,
            source=p.name,
            section="",
            project=project,
            version=version,
            tags=["md"],
        ))

    add_chunks(kb_name, chunks)

    if progress:
        progress(f"MD {p.name}: индексация завершена", 1, 1)


def index_zip_with_html(
    zip_path: str,
    kb_name: str,
    project: str,
    version: str,
    progress: Optional[ProgressFn] = None,
):
    base = Path(zip_path)
    extract_dir = base.with_suffix("")
    extract_dir.mkdir(parents=True, exist_ok=True)

    if progress:
        progress(f"ZIP {base.name}: распаковка архива", 0, 1)

    with zipfile.ZipFile(str(base), "r") as z:
        z.extractall(str(extract_dir))

    # рекурсивно индексируем все HTML внутри
    html_files = list(extract_dir.rglob("*.html")) + list(extract_dir.rglob("*.htm"))
    total_files = len(html_files)

    if progress:
        progress(f"ZIP {base.name}: найдено {total_files} HTML-файлов", 0, total_files or 1)

    for idx, file_path in enumerate(html_files, start=1):
        if progress:
            progress(f"ZIP {base.name}: обработка HTML-файлов", idx, total_files or 1)
        index_html_file(
            str(file_path),
            kb_name=kb_name,
            project=project,
            version=version,
            root=str(extract_dir),
            progress=progress,
        )

    if progress:
        progress(f"ZIP {base.name}: индексация завершена", 1, 1)


def index_path(
    input_path: str,
    kb_name: str,
    project: str,
    version: str,
    progress: Optional[ProgressFn] = None,
):
    """
    Высокоуровневая функция:
    - если input_path — файл → индексируем его;
    - если папка → рекурсивно ищем PDF/HTML/MD и индексируем все.
    """
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Путь не найден: {input_path}")

    if p.is_file():
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            index_pdf_file(str(p), kb_name, project, version, progress=progress)
        elif suffix in (".html", ".htm"):
            index_html_file(str(p), kb_name, project, version, progress=progress)
        elif suffix in (".md", ".markdown"):
            index_md_file(str(p), kb_name, project, version, progress=progress)
        elif suffix == ".zip":
            index_zip_with_html(str(p), kb_name, project, version, progress=progress)
        else:
            raise ValueError(f"Неподдерживаемый тип файла: {p.name}")
        return

    # если директория → рекурсивно индексируем все поддерживаемые файлы
    files = list(p.rglob("*.pdf")) + list(p.rglob("*.html")) + list(p.rglob("*.htm")) \
            + list(p.rglob("*.md")) + list(p.rglob("*.markdown")) + list(p.rglob("*.zip"))

    total_files = len(files)
    if progress:
        progress(f"Индексирование директории: найдено {total_files} файлов", 0, total_files or 1)

    for idx, f in enumerate(files, start=1):
        if progress:
            progress(f"Индексирование файлов", idx, total_files or 1)

        suffix = f.suffix.lower()
        if suffix == ".pdf":
            index_pdf_file(str(f), kb_name, project, version, progress=progress)
        elif suffix in (".html", ".htm"):
            index_html_file(str(f), kb_name, project, version, progress=progress)
        elif suffix in (".md", ".markdown"):
            index_md_file(str(f), kb_name, project, version, progress=progress)
        elif suffix == ".zip":
            index_zip_with_html(str(f), kb_name, project, version, progress=progress)