from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from constants import APP_NAME

EXECUTABLE_NAME = f"{APP_NAME}.exe"
INSTALL_MARKER = ".passwordSafe-install"
INVALID_WINDOWS_PATH_CHARACTERS = frozenset('<>:"|?*')


class InstallerError(RuntimeError):
    pass


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Programs" / APP_NAME


def bundled_payload_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "payload"
    return Path(__file__).resolve().parent / "dist" / APP_NAME


def validate_install_dir(value: str) -> Path:
    raw_value = value.strip().strip('"')
    if not raw_value:
        raise InstallerError("Укажите папку для установки")

    destination = Path(raw_value).expanduser()
    if not destination.is_absolute():
        raise InstallerError("Укажите полный путь к папке установки")
    destination = destination.resolve(strict=False)
    if destination.parent == destination:
        raise InstallerError("Нельзя устанавливать приложение в корень диска")
    if any(
        character in INVALID_WINDOWS_PATH_CHARACTERS
        for part in destination.parts[1:]
        for character in part
    ):
        raise InstallerError("Путь содержит недопустимые символы")
    return destination


def install_payload(payload_dir: Path, destination: Path) -> Path:
    payload = Path(payload_dir).resolve()
    target = Path(destination).resolve(strict=False)
    source_executable = payload / EXECUTABLE_NAME
    if not source_executable.is_file():
        raise InstallerError("В установщике отсутствуют файлы passwordSafe")
    if target == payload or payload in target.parents:
        raise InstallerError("Папка установки не может находиться внутри файлов установщика")
    if target.exists() and not target.is_dir():
        raise InstallerError("По указанному пути уже находится файл")
    if target.is_dir() and any(target.iterdir()):
        is_existing_install = (target / EXECUTABLE_NAME).is_file() or (target / INSTALL_MARKER).is_file()
        if not is_existing_install:
            raise InstallerError("Выбранная папка не пуста и не является установкой passwordSafe")

    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(payload, target, dirs_exist_ok=True)
        (target / INSTALL_MARKER).write_text("passwordSafe\n", encoding="utf-8")
    except PermissionError as exc:
        raise InstallerError("Нет доступа для записи. Выберите другую папку") from exc
    except OSError as exc:
        raise InstallerError("Не удалось скопировать файлы. Закройте passwordSafe и попробуйте снова") from exc

    installed_executable = target / EXECUTABLE_NAME
    if not installed_executable.is_file():
        raise InstallerError("Установка не завершена: исполняемый файл не найден")
    return installed_executable


class InstallerUi(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Установка {APP_NAME}")
        self.geometry("560x250")
        self.resizable(False, False)

        container = ttk.Frame(self, padding=18)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text=f"Установка {APP_NAME}", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            container,
            text="Приложение будет скопировано в выбранную папку. Сохранённые пароли останутся нетронутыми.",
            wraplength=515,
        ).pack(anchor="w", pady=(5, 12))

        ttk.Label(container, text="Папка установки:").pack(anchor="w")
        path_row = ttk.Frame(container)
        path_row.pack(fill="x", pady=(3, 8))
        self.path_var = tk.StringVar(value=str(default_install_dir()))
        self.path_entry = ttk.Entry(path_row, textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(path_row, text="Обзор...", command=self._browse)
        self.browse_button.pack(side="left", padx=(6, 0))

        self.launch_var = tk.BooleanVar(value=True)
        self.launch_checkbox = ttk.Checkbutton(
            container,
            text=f"Запустить {APP_NAME} после установки",
            variable=self.launch_var,
        )
        self.launch_checkbox.pack(anchor="w")
        self.status_label = ttk.Label(container, text="")
        self.status_label.pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(container)
        actions.pack(side="bottom", fill="x")
        self.install_button = ttk.Button(actions, text="Установить", command=self._install)
        self.install_button.pack(side="right")
        ttk.Button(actions, text="Отмена", command=self.destroy).pack(side="right", padx=(0, 6))

    def _browse(self) -> None:
        current = Path(self.path_var.get().strip() or default_install_dir())
        initial_dir = current if current.is_dir() else current.parent
        selected = filedialog.askdirectory(
            title=f"Выберите папку для {APP_NAME}",
            initialdir=str(initial_dir),
            parent=self,
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.name.casefold() != APP_NAME.casefold():
            destination /= APP_NAME
        self.path_var.set(str(destination))

    def _set_installing(self, installing: bool) -> None:
        state = "disabled" if installing else "normal"
        self.path_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.launch_checkbox.configure(state=state)
        self.install_button.configure(state=state, text="Установка..." if installing else "Установить")

    def _install(self) -> None:
        self._set_installing(True)
        self.status_label.configure(text="Копирование файлов...")
        self.update_idletasks()
        try:
            destination = validate_install_dir(self.path_var.get())
            executable = install_payload(bundled_payload_dir(), destination)
        except InstallerError as exc:
            self._set_installing(False)
            self.status_label.configure(text=str(exc))
            messagebox.showerror("Не удалось установить", str(exc), parent=self)
            return

        self.status_label.configure(text="Установка завершена")
        self.update_idletasks()
        if self.launch_var.get():
            try:
                subprocess.Popen([str(executable)], cwd=executable.parent)
            except OSError:
                messagebox.showwarning(
                    "Установка завершена",
                    f"Приложение установлено, но не запустилось автоматически.\n\n{executable}",
                    parent=self,
                )
                self.destroy()
                return
        messagebox.showinfo("Готово", f"{APP_NAME} установлен в:\n{destination}", parent=self)
        self.destroy()


def main() -> None:
    InstallerUi().mainloop()


if __name__ == "__main__":
    main()
