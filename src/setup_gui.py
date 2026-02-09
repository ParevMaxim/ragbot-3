import sys
import shutil
import urllib.request
import subprocess
import os
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QMessageBox, QProgressBar
from PySide6.QtCore import QThread, Signal, Qt

class OllamaInstaller(QThread):
    progress = Signal(int, str)
    finished = Signal(str)

    def run(self):
        # 1. Проверка
        if shutil.which("ollama"):
            self.progress.emit(100, "Ollama уже установлена!")
            self.finished.emit("")
            return

        # 2. Скачивание
        url = "https://ollama.com/download/OllamaSetup.exe"
        dest = Path(os.environ["TEMP"]) / "OllamaSetup.exe"
        
        try:
            self.progress.emit(10, "Скачивание Ollama (это может занять время)...")
            
            def report(block_num, block_size, total_size):
                if total_size > 0:
                    percent = int(block_num * block_size / total_size * 100)
                    # Масштабируем до 80%
                    self.progress.emit(int(percent * 0.8), f"Скачивание: {percent}%")

            urllib.request.urlretrieve(url, dest, reporthook=report)
            
            # 3. Установка
            self.progress.emit(90, "Запуск установки... Нажмите Install в окне.")
            subprocess.run([str(dest)], check=True)
            
            # 4. Проверка после установки
            if shutil.which("ollama"):
                self.finished.emit("")
            else:
                self.finished.emit("Кажется, установка не была завершена.")
                
        except Exception as e:
            self.finished.emit(str(e))

class SetupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Installer RAG Chat")
        self.setFixedSize(450, 250)
        
        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout(w)
        layout.setSpacing(15)
        
        layout.addWidget(QLabel("Шаг 1: Установка движка нейросети (Ollama)", alignment=Qt.AlignCenter))
        
        self.status = QLabel("Нажмите кнопку ниже")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status)
        
        self.bar = QProgressBar()
        layout.addWidget(self.bar)
        
        self.btn = QPushButton("Начать установку")
        self.btn.setMinimumHeight(40)
        self.btn.clicked.connect(self.start)
        layout.addWidget(self.btn)

    def start(self):
        self.btn.setEnabled(False)
        self.worker = OllamaInstaller()
        self.worker.progress.connect(lambda p, s: (self.bar.setValue(p), self.status.setText(s)))
        self.worker.finished.connect(self.done)
        self.worker.start()

    def done(self, err):
        self.btn.setEnabled(True)
        if err:
            QMessageBox.critical(self, "Ошибка", err)
            self.status.setText("Ошибка.")
        else: 
            QMessageBox.information(self, "Готово", "Движок установлен!\n\nТеперь запустите RAGChat_App.exe\nОн автоматически скачает нужные модели.")
            self.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    SetupWindow().show()
    sys.exit(app.exec())