import os
import sys
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import winshell  # Если нет, удалим (ниже код без внешних зависимостей для ярлыков)
from pathlib import Path

# Конфигурация
APP_NAME = "RAG Chat Bot"
EXE_NAME = "RAGChatBot.exe"
INSTALL_DIR_NAME = "RAGChatBot"

def resource_path(relative_path):
    """Находит файлы внутри exe установщика"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def create_shortcut(target_exe, shortcut_path, description):
    """Создает ярлык через VBScript (чтобы не требовать библиотек)"""
    vbs_script = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    Set oLink = oWS.CreateShortcut("{shortcut_path}")
    oLink.TargetPath = "{target_exe}"
    oLink.Description = "{description}"
    oLink.WorkingDirectory = "{os.path.dirname(target_exe)}"
    oLink.Save
    """
    vbs_file = os.path.join(os.getenv("TEMP"), "create_shortcut.vbs")
    with open(vbs_file, "w") as f:
        f.write(vbs_script)
    subprocess.call(["cscript", "/nologo", vbs_file])
    os.remove(vbs_file)

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Установка {APP_NAME}")
        self.geometry("450x350")
        self.resizable(False, False)
        
        # Центрирование
        self.eval('tk::PlaceWindow . center')

        self.label = tk.Label(self, text=f"Установка {APP_NAME}", font=("Segoe UI", 16, "bold"))
        self.label.pack(pady=20)

        self.status_label = tk.Label(self, text="Готов к установке...", font=("Segoe UI", 10), wraplength=400)
        self.status_label.pack(pady=10)

        self.progress = ttk.Progressbar(self, orient="horizontal", length=350, mode="determinate")
        self.progress.pack(pady=20)

        self.log_text = tk.Text(self, height=8, width=50, font=("Consolas", 8), state="disabled")
        self.log_text.pack(pady=5)

        self.install_btn = tk.Button(self, text="Начать установку", command=self.start_installation, bg="#007bff", fg="white", font=("Segoe UI", 10, "bold"), padx=20, pady=5)
        self.install_btn.pack(pady=10)

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.status_label.config(text=message)
        self.update()

    def start_installation(self):
        self.install_btn.config(state="disabled")
        threading.Thread(target=self.run_install_process, daemon=True).start()

    def run_install_process(self):
        try:
            # 1. Папка установки (AppData/Local/Programs/RAGChatBot)
            local_app_data = os.getenv("LOCALAPPDATA")
            install_path = os.path.join(local_app_data, "Programs", INSTALL_DIR_NAME)
            
            self.log(f"Создание папки: {install_path}")
            os.makedirs(install_path, exist_ok=True)
            self.progress["value"] = 10

            # 2. Копирование EXE
            self.log("Копирование файлов приложения...")
            src_exe = resource_path(os.path.join("installer_assets", EXE_NAME))
            dst_exe = os.path.join(install_path, EXE_NAME)
            shutil.copy2(src_exe, dst_exe)
            self.progress["value"] = 30

            # 3. Создание ярлыка на рабочем столе
            self.log("Создание ярлыка на рабочем столе...")
            desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
            shortcut_path = os.path.join(desktop, f"{APP_NAME}.lnk")
            create_shortcut(dst_exe, shortcut_path, "Запустить RAG Чат Бот")
            self.progress["value"] = 40

            # 4. Проверка и установка Ollama
            if not shutil.which("ollama"):
                self.log("Ollama не найдена. Установка...")
                ollama_setup_src = resource_path(os.path.join("installer_assets", "OllamaSetup.exe"))
                
                # Запуск установки Ollama (ждем завершения)
                # /silent ставит тихо, если поддерживается, иначе откроет окно
                subprocess.run([ollama_setup_src], check=True)
                self.log("Ollama установлена.")
            else:
                self.log("Ollama уже установлена.")
            
            self.progress["value"] = 60

            # 5. Скачивание моделей
            self.log("Подготовка к загрузке моделей (это может занять время)...")
            
            # Запускаем сервер
            self.log("Запуск сервера Ollama...")
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            time.sleep(5) 

            models = ["llama3.1", "nomic-embed-text"]
            step = 20 / len(models)
            
            for model in models:
                self.log(f"Скачивание модели: {model} ...")
                # Запускаем в новом окне, чтобы пользователь видел прогресс,
                # или используем subprocess.run и висим, пока качается.
                # Лучше показать окно консоли, чтобы было видно гигабайты
                subprocess.run(["ollama", "pull", model], shell=True)
                self.progress["value"] += step

            self.progress["value"] = 100
            self.log("Установка успешно завершена!")
            messagebox.showinfo("Успех", f"{APP_NAME} успешно установлен!\nЯрлык создан на рабочем столе.")
            self.destroy()

        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка при установке:\n{e}")
            self.install_btn.config(state="normal")

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()