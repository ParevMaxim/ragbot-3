# main.py
import argparse
import sys
from typing import Optional

from tqdm import tqdm

from rag.indexer import index_path
from rag.search import answer_question, debug_retrieval
from rag.storage import kb_file_path


def make_progress_bar(desc: str) -> callable:
    """
    Создаёт progress_callback для indexer'а на базе tqdm.
    progress(stage, current, total).
    """
    pbar: Optional[tqdm] = None
    last_stage = {"name": None}

    def progress(stage: str, current: int, total: int):
        nonlocal pbar
        # Если стадия сменилась — закрываем старый бар и создаём новый
        if last_stage["name"] != stage:
            if pbar is not None:
                pbar.close()
            pbar = tqdm(total=total or 1,
                        desc=stage,
                        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")
            last_stage["name"] = stage
        # Обновляем позицию
        if pbar is not None:
            pbar.total = total or 1
            pbar.n = min(current, pbar.total)
            pbar.refresh()

    return progress


def cmd_index(args: argparse.Namespace):
    kb_name = args.kb
    input_path = args.input
    project = args.project
    version = args.version

    print(f"Индексирую '{input_path}' в базу '{kb_name}' (проект={project}, версия={version})")
    progress = make_progress_bar("Индексация")

    try:
        index_path(
            input_path=input_path,
            kb_name=kb_name,
            project=project,
            version=version,
            progress=progress,
        )
        print(f"\nГотово. Файл базы знаний: {kb_file_path(kb_name)}")
    except Exception as e:
        print(f"\nОшибка индексации: {e}")
        sys.exit(1)


def cmd_ask(args: argparse.Namespace):
    kb_name = args.kb
    question = args.question

    print(f"KB: {kb_name}")
    print(f"Вопрос: {question}\n")

    try:
        answer = answer_question(kb_name, question, top_k=args.top_k)
        print("Ответ:\n")
        print(answer)
    except Exception as e:
        print(f"Ошибка при получении ответа: {e}")
        sys.exit(1)


def cmd_debug(args: argparse.Namespace):
    """
    Показать, какие чанки выбирает поиск для данного вопроса.
    Только retrieval, без LLM-ответа.
    """
    kb_name = args.kb
    question = args.question

    print(f"KB: {kb_name}")
    print(f"Вопрос: {question}\n")

    try:
        results = debug_retrieval(kb_name, question, top_k=args.top_k)
    except Exception as e:
        print(f"Ошибка при debug-поиске: {e}")
        sys.exit(1)

    if not results:
        print("KB пуста или ничего не найдено.")
        return

    for r in results:
        print("=" * 80)
        print(f"Документ #{r['index']} | score={r['score']:.3f} "
              f"(sem={r['semantic']:.3f}, lex={r['lexical']:.3f})")
        print(f"Источник: {r['source']} [{r['section']}]")
        print("-" * 80)
        print(r["text"])
        print()


def main():
    parser = argparse.ArgumentParser(description="Локальный RAG по документации (Ollama).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = subparsers.add_parser("index", help="Проиндексировать файлы/директорию в базу знаний")
    p_index.add_argument("--input", "-i", required=True, help="Путь к файлу или директории с документацией")
    p_index.add_argument("--kb", "-k", required=True, help="Имя базы знаний (имя файла без пути)")
    p_index.add_argument("--project", "-p", default="default", help="Имя проекта/сервиса (метаданные)")
    p_index.add_argument("--version", "-v", default="v1", help="Версия документации (метаданные)")
    p_index.set_defaults(func=cmd_index)

    # ask
    p_ask = subparsers.add_parser("ask", help="Задать вопрос к базе знаний")
    p_ask.add_argument("--kb", "-k", required=True, help="Имя базы знаний")
    p_ask.add_argument("--question", "-q", required=True, help="Текст вопроса")
    p_ask.add_argument("--top-k", type=int, default=8, help="Сколько фрагментов использовать в контексте")
    p_ask.set_defaults(func=cmd_ask)

    # debug
    p_debug = subparsers.add_parser("debug", help="Посмотреть, какие чанки выбирает поиск")
    p_debug.add_argument("--kb", "-k", required=True, help="Имя базы знаний")
    p_debug.add_argument("--question", "-q", required=True, help="Текст вопроса")
    p_debug.add_argument("--top-k", type=int, default=10, help="Сколько фрагментов показать")
    p_debug.set_defaults(func=cmd_debug)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()