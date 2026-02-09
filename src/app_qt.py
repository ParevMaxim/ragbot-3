from __future__ import annotations
import sys
import os
import shutil
import urllib.request
import subprocess
from bootstrap_ollama import ensure_ollama_running
import time
from pathlib import Path
from typing import Optional, List

# ВАЖНО: Добавил этот импорт, чтобы PyInstaller точно зашил библиотеку внутрь
import ollama 

# Импорты PySide6
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QProgressBar,
    QFrame,
    QSizePolicy,
    QMessageBox,
    QSpacerItem,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCheckBox,
    QScrollArea,
)

# Импорты твоих модулей
from config import CHAT_MODEL_MAIN, EMBEDDING_MODEL, OLLAMA_HOST, KB_DIR
from rag.indexer import index_path
from rag.search import answer_question, debug_retrieval
from rag.storage import kb_file_path
from rag.llm import get_llm_main, set_llm_main

def install_ollama_if_missing():
    """
    Проверяет наличие Ollama. Если нет — предлагает установить.
    (Оставил эту функцию как защиту, если пользователь запустит программу без Setup.exe)
    """
    if shutil.which("ollama"):
        return True

    if os.name != "nt":
        QMessageBox.warning(None, "Ollama не найдена", "Пожалуйста, установите Ollama вручную.")
        return False

    reply = QMessageBox.question(
        None, 
        "Установка компонентов", 
        "Для работы программы требуется компонент Ollama (локальная нейросеть).\n\n"
        "Скачать и установить его сейчас?",
        QMessageBox.Yes | QMessageBox.No
    )
    
    if reply == QMessageBox.No:
        return False

    installer_path = Path(os.environ["TEMP"]) / "OllamaSetup.exe"
    url = "https://ollama.com/download/OllamaSetup.exe"
    
    progress = QDialog(None)
    progress.setWindowTitle("Скачивание Ollama...")
    progress.setFixedSize(300, 100)
    layout = QVBoxLayout(progress)
    label = QLabel("Скачивание (около 200 МБ)... Подождите.")
    layout.addWidget(label)
    progress.show()
    QApplication.processEvents()

    try:
        urllib.request.urlretrieve(url, installer_path)
    except Exception as e:
        progress.close()
        QMessageBox.critical(None, "Ошибка", f"Не удалось скачать Ollama:\n{e}")
        return False
    
    progress.close()

    QMessageBox.information(None, "Установка", "Сейчас запустится установка Ollama.\nПожалуйста, нажмите 'Install' в появившемся окне.")
    
    try:
        subprocess.run([str(installer_path)], check=True)
    except Exception as e:
        QMessageBox.critical(None, "Ошибка", f"Ошибка при установке:\n{e}")
        return False

    if shutil.which("ollama"):
        QMessageBox.information(None, "Успех", "Ollama успешно установлена!")
        return True
    else:
        QMessageBox.warning(None, "Внимание", "Кажется, установка не завершилась или требуется перезагрузка.")
        return False

# ---------- фоновые потоки ----------

class IndexWorker(QThread):
    progress_signal = Signal(str, int)
    finished_signal = Signal(object)

    def __init__(self, input_path: str, kb_name: str, project: str = "default", version: str = "v1"):
        super().__init__()
        self.input_path = input_path
        self.kb_name = kb_name
        self.project = project
        self.version = version

    def run(self):
        def progress_cb(stage: str, current: int, total: int):
            percent = int(current * 100 / (total or 1))
            self.progress_signal.emit(stage, percent)

        try:
            index_path(
                input_path=self.input_path,
                kb_name=self.kb_name,
                project=self.project,
                version=self.version,
                progress=progress_cb,
            )
            self.finished_signal.emit(None)
        except Exception as e:
            self.finished_signal.emit(str(e))


class AnswerWorker(QThread):
    finished_signal = Signal(str, object)

    def __init__(self, kb_name: str, question: str, top_k: int = 4):
        super().__init__()
        self.kb_name = kb_name
        self.question = question
        self.top_k = top_k

    def run(self):
        try:
            answer = answer_question(self.kb_name, self.question, top_k=self.top_k)
            self.finished_signal.emit(answer, None)
        except Exception as e:
            self.finished_signal.emit("", e)


class DebugWorker(QThread):
    finished_signal = Signal(list, object)

    def __init__(self, kb_name: str, question: str, top_k: int = 5):
        super().__init__()
        self.kb_name = kb_name
        self.question = question
        self.top_k = top_k

    def run(self):
        try:
            hits = debug_retrieval(self.kb_name, self.question, top_k=self.top_k)
            self.finished_signal.emit(hits, None)
        except Exception as e:
            self.finished_signal.emit([], e)


class ModelPullWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(object)

    def __init__(self, models: List[str], host: str):
        super().__init__()
        self.models = models
        self.host = host

    def run(self):
        try:
            import ollama
            client = ollama.Client(host=self.host)
            for model in self.models:
                for status in client.pull(model, stream=True):
                    text = status.get("status", "")
                    completed = status.get("completed")
                    total = status.get("total")
                    if completed is not None and total:
                        pct = int(completed * 100 / total)
                        msg = f"{model}: {text} ({pct}%)"
                    else:
                        msg = f"{model}: {text}"
                    self.progress_signal.emit(msg)

            self.finished_signal.emit(None)
        except Exception as e:
            self.finished_signal.emit(str(e))


# ---------- диалог настроек ----------

class SettingsDialog(QDialog):
    def __init__(self, parent, current_model: str, show_debug: bool):
        super().__init__(parent)
        self.setWindowTitle("Настройки вывода")
        self.setModal(True)
        self.resize(420, 220)

        self.selected_model = current_model
        self.show_debug = show_debug

        self._build_ui()
        self._apply_styles()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Настройки вывода и модели LLM")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        model_label = QLabel("Модель LLM (Ollama):")
        layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setObjectName("modelCombo")
        self.model_combo.addItem(self.selected_model)
        layout.addWidget(self.model_combo)

        self.debug_checkbox = QCheckBox("Показывать найденные чанки (debug) под ответом")
        self.debug_checkbox.setChecked(self.show_debug)
        layout.addWidget(self.debug_checkbox)

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QDialog {
                background-color: #f5f7fb;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            #settingsTitle {
                font-size: 13pt;
                font-weight: 600;
                color: #4a4d76;
            }
            #modelCombo {
                border-radius: 999px;
                padding: 6px 12px;
                border: 1px solid #ced0e5;
                background-color: #ffffff;
            }
            QCheckBox {
                color: #4c4f6b;
            }
            QDialogButtonBox QPushButton {
                border-radius: 999px;
                padding: 6px 14px;
            }
            """
        )

    def get_values(self) -> tuple[str, bool]:
        model = self.model_combo.currentText().strip()
        show_debug = self.debug_checkbox.isChecked()
        return model, show_debug


# ---------- главное окно ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("AI ассистент для работы с конфиденциальной информацией")
        self.setMinimumSize(1160, 720)

        self.kb_name: str = "default"
        self.show_debug_chunks: bool = False
        self.last_question: str = ""

        self.index_thread: Optional[IndexWorker] = None
        self.answer_thread: Optional[AnswerWorker] = None
        self.debug_thread: Optional[DebugWorker] = None
        self.models_thread: Optional[ModelPullWorker] = None

        self._build_ui()
        self._apply_styles()

        self.check_models_on_start()

    # UI -------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_left_panel(main_layout)
        self._build_right_panel(main_layout)

        self.setCentralWidget(central)

    def _build_left_panel(self, main_layout: QHBoxLayout):
        left = QFrame()
        left.setObjectName("leftPanel")
        left.setFixedWidth(260)

        v = QVBoxLayout(left)
        v.setContentsMargins(22, 22, 22, 22)
        v.setSpacing(18)

        logo_label = QLabel("AI ассистент")
        logo_font = QFont("Segoe UI", 22, QFont.Bold)
        logo_label.setFont(logo_font)
        logo_label.setObjectName("logoLabel")
        v.addWidget(logo_label)
        v.addSpacing(20)

        self.btn_nav_load_file = QPushButton("📄   Загрузить файл")
        self.btn_nav_load_file.setObjectName("navMain")
        self.btn_nav_load_file.clicked.connect(self.on_choose_file)
        v.addWidget(self.btn_nav_load_file)

        self.btn_nav_load_dir = QPushButton("📁   Загрузить папку")
        self.btn_nav_load_dir.setObjectName("navMain")
        self.btn_nav_load_dir.clicked.connect(self.on_choose_folder)
        v.addWidget(self.btn_nav_load_dir)

        self.btn_nav_settings = QPushButton("⚙   Настройки")
        self.btn_nav_settings.setObjectName("navMain")
        self.btn_nav_settings.clicked.connect(self.on_open_settings)
        v.addWidget(self.btn_nav_settings)

        v.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        main_layout.addWidget(left)

    def _build_right_panel(self, main_layout: QHBoxLayout):
        right = QFrame()
        right.setObjectName("rightPanel")

        v = QVBoxLayout(right)
        v.setContentsMargins(40, 28, 40, 28)
        v.setSpacing(18)

        title = QLabel("Задайте вопрос вашей Базе знаний")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        v.addWidget(title)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(15)

        self.status_label = QLabel("Проверяю модели Ollama...")
        self.status_label.setObjectName("statusLabel")
        status_layout.addWidget(self.status_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setFixedWidth(260)
        self.progress_bar.setObjectName("progressBar")
        status_layout.addWidget(self.progress_bar, 0, Qt.AlignRight)

        v.addLayout(status_layout)
        v.addSpacing(8)

        chat_card = QFrame()
        chat_card.setObjectName("chatCard")
        card_layout = QVBoxLayout(chat_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch(1)

        self.chat_scroll.setWidget(self.chat_container)
        card_layout.addWidget(self.chat_scroll)

        v.addWidget(chat_card, 1)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)

        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText("Задайте вопрос по вашей документации...")
        self.question_edit.returnPressed.connect(self.on_send_clicked)
        self.question_edit.setObjectName("questionEdit")
        input_layout.addWidget(self.question_edit, 1)

        self.send_button = QPushButton("➤  Отправить")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.on_send_clicked)
        input_layout.addWidget(self.send_button, 0)

        v.addLayout(input_layout)

        main_layout.addWidget(right, 1)

        self.append_system(
            "Загрузите документацию (PDF/HTML/MD/ZIP с HTML), затем задавайте вопросы.\n"
            "Ответы формируются строго на основе вашей базы знаний."
        )

    def _apply_styles(self):
        QApplication.instance().setFont(QFont("Segoe UI", 10))

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f0f3fb;
            }

            QPushButton {
                border-radius: 999px;
                padding: 8px 16px;
                border: none;
                background-color: #f4f5fc;
                color: #4C4F6B;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #e3e5ff;
            }

            #leftPanel {
                background-color: #ffffff;
                border-right: 1px solid #e0e0f0;
            }

            #rightPanel {
                border-top-left-radius: 32px;
                border-bottom-left-radius: 32px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #d6f1ff,
                    stop:0.5 #f4f6ff,
                    stop:1 #fef9ff
                );
            }

            #logoLabel {
                color: #3c3c65;
            }

            #navMainActive {
                background-color:#e1e6ff;
                color:#303349;
                font-weight:600;
                text-align:left;
                padding-left:16px;
            }
            #navMain {
                background-color:transparent;
                text-align:left;
                padding-left:16px;
            }
            #navMain:hover {
                background-color:#f0f2ff;
            }

            #infoLabel {
                color: #9a9bb8;
                font-size: 9pt;
            }

            #heroTitle {
                font-size: 24pt;
                font-weight: 600;
                color: #4a4d76;
            }

            #statusLabel {
                color: #6b6f8a;
                font-size: 10pt;
            }

            #progressBar {
                border-radius: 999px;
                background-color: #e1e4f0;
            }
            #progressBar::chunk {
                border-radius: 999px;
                background-color: #4caf50;
            }

            #chatCard {
                background-color: #f7f2e8;
                border-radius: 24px;
                border: 1px solid #e2e4f4;
            }

            #questionEdit {
                border-radius: 999px;
                padding: 10px 16px;
                border: 1px solid #ced0e5;
                background-color: #ffffff;
            }

            #sendButton {
                background-color: #2f8cff;
                color: white;
                font-weight: 600;
                padding: 10px 22px;
            }
            #sendButton:disabled {
                background-color: #9cc2ff;
            }
            #sendButton:hover:!disabled {
                background-color: #2974d5;
            }
            """
        )

    # --------- автопроверка и загрузка моделей ----------
    def check_models_on_start(self):
        needed = {CHAT_MODEL_MAIN, EMBEDDING_MODEL}
        needed = {m for m in needed if m}

        try:
            import ollama
            client = ollama.Client(host=OLLAMA_HOST)
            have = {m.get("name", "") for m in client.list().get("models", [])}
        except Exception as e:
            self.status_label.setText(
                "Не удалось подключиться к Ollama. Убедитесь, что Ollama установлен и запущен."
            )
            self.append_system(f"Ошибка подключения к Ollama: {e}")
            return

        missing = []
        for n in needed:
            found = False
            for h in have:
                if n == h or h.startswith(n + ":"):
                    found = True
                    break
            if not found:
                missing.append(n)

        if not missing:
            self.status_label.setText("Модели Ollama найдены. Можно загружать документацию.")
            self.progress_bar.setValue(100)
            return

        self.append_system("Не найдены модели Ollama: " + ", ".join(missing))
        self.append_system("Автоматически загружаю недостающие модели из Ollama…")
        self.status_label.setText("Загрузка моделей Ollama...")
        self.progress_bar.setRange(0, 0)

        self.models_thread = ModelPullWorker(missing, OLLAMA_HOST)
        self.models_thread.progress_signal.connect(self.on_models_progress)
        self.models_thread.finished_signal.connect(self.on_models_finished)
        self.models_thread.start()

    def on_models_progress(self, text: str):
        self.status_label.setText(text)

    def on_models_finished(self, error: Optional[str]):
        self.progress_bar.setRange(0, 100)
        if error:
            self.status_label.setText("Ошибка загрузки моделей.")
            self.progress_bar.setValue(0)
            self.append_system(f"Ошибка загрузки моделей Ollama: {error}")
            QMessageBox.critical(
                self,
                "Ошибка Ollama",
                f"Не удалось автоматически скачать модели.\n\n{error}",
            )
        else:
            self.status_label.setText("Модели Ollama успешно загружены. Можно загружать документацию.")
            self.progress_bar.setValue(100)
            self.append_system("Модели Ollama успешно загружены.")

    # ---------- вспомогательные (чат) ----------
    def _add_message_widget(self, widget: QWidget):
        index = self.chat_layout.count() - 1
        self.chat_layout.insertWidget(index, widget)
        self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        )

    def append_system(self, text: str):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        chip = QLabel(text.replace("\n", " "))
        chip.setWordWrap(True)
        chip.setAlignment(Qt.AlignCenter)
        chip.setStyleSheet(
            """
            QLabel {
                background-color:#eef0ff;
                color:#7a7da0;
                border-radius:16px;
                padding:4px 10px;
                font-size:9pt;
            }
            """
        )

        layout.addStretch(1)
        layout.addWidget(chip)
        layout.addStretch(1)

        self._add_message_widget(w)

    def append_user(self, text: str):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setStyleSheet(
            """
            QLabel {
                background-color:#2f8cff;
                color:#ffffff;
                border-radius:18px;
                padding:10px 16px;
                font-size:10pt;
                max-width:480px;
            }
            """
        )

        layout.addStretch(1)
        layout.addWidget(bubble)

        self._add_message_widget(w)

    def append_bot(self, text: str):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setStyleSheet(
            """
            QLabel {
                background-color:#ffffff;
                color:#222222;
                border-radius:18px;
                padding:10px 16px;
                font-size:10pt;
                border:1px solid #e0e3f0;
                max-width:600px;
            }
            """
        )

        layout.addWidget(bubble)
        layout.addStretch(1)

        self._add_message_widget(w)

    def append_debug_chunks(self, hits: List[dict]):
        if not hits:
            return

        self.append_system("Чанки (debug):")
        for h in hits:
            src = str(h.get("source", ""))
            sec = str(h.get("section", ""))
            score = h.get("score", 0.0)
            text = h.get("text", "")
            snippet = text.replace("\n", " ")
            if len(snippet) > 220:
                snippet = snippet[:220] + "…"
            meta = src + (f" — {sec}" if sec else "")

            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(0, 0, 0, 0)

            bubble = QLabel(f"{meta}\nscore={score:.3f}\n\n{snippet}")
            bubble.setWordWrap(True)
            bubble.setStyleSheet(
                """
                QLabel {
                    background-color:#ffffff;
                    color:#4c4f6b;
                    border-radius:16px;
                    padding:6px 10px;
                    font-size:9pt;
                    border:1px solid #e2e3f5;
                    max-width:650px;
                }
                """
            )

            layout.addWidget(bubble)
            layout.addStretch(1)

            self._add_message_widget(w)

    # ---------- действия ----------

    def on_choose_file(self):
        self._choose_path_and_index(is_dir=False)

    def on_choose_folder(self):
        self._choose_path_and_index(is_dir=True)

    def _choose_path_and_index(self, is_dir: bool):
        if self.index_thread and self.index_thread.isRunning():
            QMessageBox.information(self, "Индексация", "Индексация уже выполняется.")
            return

        if is_dir:
            path = QFileDialog.getExistingDirectory(self, "Выберите папку с документацией")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Выберите файл документации",
                filter="Документация (*.pdf *.html *.htm *.md *.markdown *.zip);;Все файлы (*.*)",
            )
        
        if not path:
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Ошибка", f"Путь не найден: {path}")
            return

        self.status_label.setText("Индексация запущена...")
        self.progress_bar.setValue(0)
        self.append_system(f"Начинаю индексацию '{path}' в KB 'default'.")

        self.index_thread = IndexWorker(str(p), self.kb_name)
        self.index_thread.progress_signal.connect(self.on_index_progress)
        self.index_thread.finished_signal.connect(self.on_index_finished)
        self.index_thread.start()

    def on_index_progress(self, stage: str, percent: int):
        self.status_label.setText(stage)
        self.progress_bar.setValue(percent)

    def on_index_finished(self, error: Optional[str]):
        if error:
            self.status_label.setText("Ошибка индексации.")
            self.progress_bar.setValue(0)
            self.append_system(f"Ошибка индексации: {error}")
            QMessageBox.critical(self, "Ошибка индексации", error)
        else:
            self.status_label.setText("Индексация завершена.")
            self.progress_bar.setValue(100)
            self.append_system(
                f"Индексация завершена. Файл KB: {kb_file_path(self.kb_name)}"
            )

    def on_send_clicked(self):
        if self.answer_thread and self.answer_thread.isRunning():
            return

        question = self.question_edit.text().strip()
        if not question:
            return

        self.last_question = question
        self.append_user(question)
        self.question_edit.clear()
        self.send_button.setEnabled(False)

        self.answer_thread = AnswerWorker(self.kb_name, question, top_k=4)
        self.answer_thread.finished_signal.connect(self.on_answer_finished)
        self.answer_thread.start()

    def on_answer_finished(self, answer: str, error: Optional[Exception]):
        self.send_button.setEnabled(True)
        if error:
            msg = (
                "Ошибка при получении ответа.\n"
                "Проверьте, что Ollama запущен и модели скачаны, а KB проиндексирована.\n\n"
                f"Тех. детали: {error}"
            )
            self.append_system(msg)
            QMessageBox.critical(self, "Ошибка ответа", msg)
            return

        self.append_bot(answer)

        if self.show_debug_chunks:
            self.debug_thread = DebugWorker(self.kb_name, self.last_question, top_k=5)
            self.debug_thread.finished_signal.connect(self.on_debug_finished)
            self.debug_thread.start()

    def on_debug_finished(self, hits: List[dict], error: Optional[Exception]):
        if error:
            self.append_system(f"Ошибка debug-поиска: {error}")
            return
        self.append_debug_chunks(hits)

    def on_open_settings(self):
        current_model = get_llm_main()
        dlg = SettingsDialog(self, current_model, self.show_debug_chunks)
        if dlg.exec() == QDialog.Accepted:
            model, show_debug = dlg.get_values()
            if model:
                set_llm_main(model)
                self.append_system(f"Модель LLM изменена на '{model}'.")
            self.show_debug_chunks = show_debug
            self.append_system(
                f"Показ чанков (debug): {'включён' if show_debug else 'выключен'}."
            )


def main():
    app = QApplication(sys.argv)

    if not install_ollama_if_missing():
        sys.exit(0)

    # Запускаем ollama serve в фоне и ждём, пока API станет доступным
    if not ensure_ollama_running(OLLAMA_HOST, wait_seconds=30):
        QMessageBox.critical(
            None,
            "Ollama не запущена",
            "Не удалось запустить/подключиться к Ollama за 30 секунд.\n"
            "Убедитесь, что Ollama установлена и запущена."
        )
        sys.exit(1)

    Path(KB_DIR).mkdir(parents=True, exist_ok=True)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()