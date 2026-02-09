import os
import sys
import time
import shutil
import subprocess
import threading
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# --- КОНФИГУРАЦИЯ ---
APP_NAME = "RAG Chat Bot"
EXE_NAME = "RAGChatBot.exe"  # Имя твоего бота
OLLAMA_URL = "https://ollama.com/download/OllamaSetup.exe"

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_resource_path(relative_path):
    """ Получает путь к файлу, зашитому внутри установщика """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def create_shortcut(target, shortcut_path, description):
    """ Создает ярлык через VBScript (работает везде без доп. библиотек) """
    vbs = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    Set oLink = oWS.CreateShortcut("{shortcut_path}")
    oLink.TargetPath = "{target}"
    oLink.Description = "{description}"
    oLink.WorkingDirectory = "{os.path.dirname(target)}"
    oLink.Save
    """
    vbs_path = os.path.join(os.getenv("TEMP"), "mk_shortcut.vbs")
    with open(vbs_path, "w") as f:
        f.write(vbs)
    subprocess.call(["cscript", "/nologo", vbs_path])
    if os.path.exists(vbs_path):
        os.remove(vbs_path)

# --- GUI ПРИЛОЖЕНИЕ ---

class WebInstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Установка {APP_NAME}")
        self.geometry("500x400")
        self.resizable(False, False)
        
        # Стили
        style = ttk.Style()
        style.theme_use('vista')
        
        # Заголовок
        lbl_title = tk.Label(self, text=f"Установка {APP_NAME}", font=("Segoe UI", 16, "bold"))
        lbl_title.pack(pady=15)

        # Статус
        self.lbl_status = tk.Label(self, text="Нажмите 'Установить' для начала...", font=("Segoe UI", 10))
        self.lbl_status.pack(pady=5)

        # Прогресс бар
        self.progress = ttk.Progressbar(self, orient="horizontal", length=400, mode="determinate")
        self.progress.pack(pady=10)

        # Лог действий
        self.txt_log = tk.Text(self, height=10, width=58, font=("Consolas", 8), state="disabled")
        self.txt_log.pack(pady=5)

        # Кнопка
        self.btn_install = tk.Button(self, text="Установить", command=self.start_install, 
                                     bg="#0078D7", fg="white", font=("Segoe UI", 11, "bold"), 
                                     width=20, height=1)
        self.btn_install.pack(pady=15)

    def log(self, msg):
        """ Вывод текста в лог """
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, ">> " + msg + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")
        self.update()

    def set_status(self, msg):
        self.lbl_status.config(text=msg)
        self.update()

    def start_install(self):
        self.btn_install.config(state="disabled")
        threading.Thread(target=self.run_process, daemon=True).start()

    def download_file(self, url, dest):
        """ Скачивание файла с отображением прогресса """
        try:
            with urllib.request.urlopen(url) as response:
                total_size = int(response.info().get('Content-Length').strip())
                downloaded = 0
                block_size = 1024 * 8 # 8KB blocks
                
                with open(dest, "wb") as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        f.write(buffer)
                        
                        # Обновляем прогресс (только для скачивания Ollama берем 30% от шкалы)
                        percent = (downloaded / total_size) * 100
                        # Это просто визуализация загрузки внутри этапа
                        # self.set_status(f"Скачивание: {int(percent)}%")
        except Exception as e:
            raise Exception(f"Ошибка загрузки: {e}")

    def run_process(self):
        try:
            # 1. ПОДГОТОВКА ПАПОК
            self.progress['value'] = 5
            local_programs = os.path.join(os.getenv("LOCALAPPDATA"), "Programs", "RAGChatBot")
            os.makedirs(local_programs, exist_ok=True)
            self.log(f"Папка установки: {local_programs}")

            # 2. ИЗВЛЕЧЕНИЕ БОТА (изнутри exe)
            self.set_status("Копирование файлов приложения...")
            self.log("Извлечение RAGChatBot.exe...")
            
            src_exe = get_resource_path(EXE_NAME) 
            dst_exe = os.path.join(local_programs, EXE_NAME)
            
            # Проверка, что файл внутри есть (важно для отладки)
            if not os.path.exists(src_exe):
                # Если запускаем скрипт .py, ищем в dist
                src_exe = os.path.join("dist", EXE_NAME)
            
            shutil.copy2(src_exe, dst_exe)
            self.progress['value'] = 20

            # 3. ЯРЛЫК
            self.log("Создание ярлыка...")
            desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
            shortcut_path = os.path.join(desktop, f"{APP_NAME}.lnk")
            create_shortcut(dst_exe, shortcut_path, "Запустить AI Чат")
            self.progress['value'] = 30

            # 4. УСТАНОВКА OLLAMA
            if shutil.which("ollama"):
                self.log("Ollama уже установлена. Пропуск.")
            else:
                self.set_status("Скачивание Ollama (это может занять время)...")
                self.log("Скачивание установщика Ollama...")
                
                installer_path = os.path.join(os.getenv("TEMP"), "OllamaSetup.exe")
                self.download_file(OLLAMA_URL, installer_path)
                
                self.set_status("Установка Ollama...")
                self.log("Запуск установки Ollama...")
                # Запускаем тихо (/silent)
                subprocess.run([installer_path, "/silent"], check=True)
                self.log("Ollama установлена.")
            
            self.progress['value'] = 50

            # 5. СКАЧИВАНИЕ МОДЕЛЕЙ
            self.set_status("Настройка нейросетей (5-10 мин)...")
            self.log("Запуск сервера Ollama...")
            
            # Фоновый запуск сервера (без окна)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["ollama", "serve"], startupinfo=si)
            
            time.sleep(5) # Даем время на старт

            models = ["llama3.1", "nomic-embed-text"]
            step = 40 / len(models) # Оставшиеся 40% прогресса делим на модели

            for model in models:
                self.set_status(f"Загрузка модели {model}...")
                self.log(f"Начинаю скачивание {model}. Пожалуйста, ждите...")
                
                # Запускаем pull. Это блокирующая операция.
                # Чтобы не зависал GUI, subprocess работает, а мы ждем.
                # Можно было бы читать вывод, но для простоты просто ждем завершения.
                
                # ВАЖНО: Тут мы скрываем черное окно, прогресс не виден детально,
                # но пользователь видит статус в нашем окне.
                subprocess.run(["ollama", "pull", model], shell=True, check=True)
                
                self.log(f"Модель {model} готова.")
                self.progress['value'] += step

            self.progress['value'] = 100
            self.set_status("Готово!")
            self.log("Установка успешно завершена.")
            
            messagebox.showinfo("Успех", "Установка завершена!\nЯрлык создан на рабочем столе.")
            self.destroy()

        except Exception as e:
            self.log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{e}")
            self.btn_install.config(state="normal")

if __name__ == "__main__":
    app = WebInstaller()
    app.mainloop()