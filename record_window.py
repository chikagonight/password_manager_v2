from __future__ import annotations

from contextlib import suppress
from tkinter import messagebox

import customtkinter as ctk

from models import PasswordRecord
from password_manager_app import PasswordManagerApp, ValidationError
from utils.vault_store import VaultError


class RecordWindow(ctk.CTkToplevel):
    def __init__(self, parent, record: PasswordRecord, password_manager_app: PasswordManagerApp):
        super().__init__(parent)
        self.parent_ui = parent
        self.record = record
        self.password_manager_app = password_manager_app
        self.is_editing = False

        self.title(record.record_name)
        self.geometry("720x520")
        self.minsize(620, 470)
        self.transient(parent)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._create_widgets()
        self.after(50, lambda: self._center_window(parent))

    def _create_widgets(self) -> None:
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(5, weight=1)

        self.record_name = self._entry_row(frame, 0, "Имя записи", self.record.record_name)
        self.service_name = self._entry_row(frame, 1, "Сервис", self.record.service_name)
        self.link_service = self._entry_row(frame, 2, "URL", self.record.url_link_service)
        self.login_service = self._entry_row(frame, 3, "Логин", self.record.login)

        ctk.CTkLabel(frame, text="Пароль").grid(row=4, column=0, padx=10, pady=6, sticky="w")
        password_panel = ctk.CTkFrame(frame, fg_color="transparent")
        password_panel.grid(row=4, column=1, padx=8, pady=6, sticky="ew")
        password_panel.grid_columnconfigure(0, weight=1)
        self.password_service = ctk.CTkEntry(password_panel, show="*")
        self.password_service.insert(0, self.record.password)
        self.password_service.configure(state="readonly")
        self.password_service.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.show_password_button = ctk.CTkButton(
            password_panel, text="Показать", width=90, command=self.toggle_password
        )
        self.show_password_button.grid(row=0, column=1, padx=5)
        ctk.CTkButton(password_panel, text="Копировать", width=90, command=self.copy_password).grid(
            row=0, column=2, padx=(5, 0)
        )

        ctk.CTkLabel(frame, text="Заметка").grid(row=5, column=0, padx=10, pady=6, sticky="nw")
        self.note_service = ctk.CTkTextbox(frame, border_width=1)
        self.note_service.insert("1.0", self.record.note)
        self.note_service.configure(state="disabled")
        self.note_service.grid(row=5, column=1, padx=8, pady=6, sticky="nsew")

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=2, padx=8, pady=(10, 8), sticky="ew")
        buttons.grid_columnconfigure((0, 1, 2), weight=1)
        self.edit_button = ctk.CTkButton(buttons, text="Изменить", command=self.toggle_edit)
        self.edit_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.browser_button = ctk.CTkButton(buttons, text="Открыть сайт", command=self.open_browser)
        self.browser_button.grid(row=0, column=1, padx=5, sticky="ew")
        if not self.record.url_link_service:
            self.browser_button.configure(state="disabled")
        ctk.CTkButton(buttons, text="Копировать логин", command=self.copy_login).grid(
            row=0, column=2, padx=5, sticky="ew"
        )
        ctk.CTkButton(
            buttons, text="Удалить", command=self.delete_record, fg_color="#b33a3a", hover_color="#8f2d2d"
        ).grid(row=0, column=3, padx=(5, 0), sticky="ew")

    def _entry_row(self, parent, row: int, label: str, value: str):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=10, pady=6, sticky="w")
        entry = ctk.CTkEntry(parent)
        entry.insert(0, value)
        entry.configure(state="readonly")
        entry.grid(row=row, column=1, padx=8, pady=6, sticky="ew")
        return entry

    def toggle_edit(self) -> None:
        if self.is_editing:
            self.save_changes()
            return
        self.is_editing = True
        for entry in (
            self.record_name,
            self.service_name,
            self.link_service,
            self.login_service,
            self.password_service,
        ):
            entry.configure(state="normal")
        self.note_service.configure(state="normal")
        self.edit_button.configure(text="Сохранить изменения")
        self.browser_button.configure(state="disabled")

    def save_changes(self) -> None:
        try:
            self.record = self.password_manager_app.update_record(
                self.record.id,
                record_name=self.record_name.get(),
                service_name=self.service_name.get(),
                login=self.login_service.get(),
                password=self.password_service.get(),
                repeat_password=self.password_service.get(),
                url_link_service=self.link_service.get(),
                note=self.note_service.get("1.0", "end-1c"),
            )
        except (ValidationError, VaultError, OSError) as exc:
            messagebox.showerror("Не удалось изменить запись", str(exc), parent=self)
            return
        self.is_editing = False
        for entry in (
            self.record_name,
            self.service_name,
            self.link_service,
            self.login_service,
            self.password_service,
        ):
            entry.configure(state="readonly")
        self.note_service.configure(state="disabled")
        self.password_service.configure(show="*")
        self.show_password_button.configure(text="Показать")
        self.browser_button.configure(state="normal" if self.record.url_link_service else "disabled")
        self.edit_button.configure(text="Изменить")
        self.title(self.record.record_name)
        self.parent_ui.refresh_records()
        messagebox.showinfo("Готово", "Изменения сохранены", parent=self)

    def toggle_password(self) -> None:
        show = "" if self.password_service.cget("show") == "*" else "*"
        self.password_service.configure(show=show)
        self.show_password_button.configure(text="Скрыть" if show == "" else "Показать")
        if show == "":
            self.after(15_000, self.hide_password)

    def hide_password(self) -> None:
        if self.winfo_exists():
            self.password_service.configure(show="*")
            self.show_password_button.configure(text="Показать")

    def copy_login(self) -> None:
        self.parent_ui.copy_to_clipboard(self.login_service.get(), "Логин")

    def copy_password(self) -> None:
        self.parent_ui.copy_to_clipboard(self.password_service.get(), "Пароль")

    def open_browser(self) -> None:
        self.parent_ui.open_url(self.record.url_link_service)

    def delete_record(self) -> None:
        if not messagebox.askyesno(
            "Удаление записи",
            f"Удалить «{self.record.record_name}»? Отменить это действие нельзя.",
            parent=self,
        ):
            return
        try:
            self.password_manager_app.delete_record(self.record.id)
        except (ValidationError, VaultError, OSError) as exc:
            messagebox.showerror("Не удалось удалить запись", str(exc), parent=self)
            return
        self.parent_ui.refresh_records()
        self.close()

    def close(self) -> None:
        with suppress(Exception):
            self.grab_release()
        self.destroy()
        self.parent_ui.record_window = None

    def _center_window(self, parent) -> None:
        self.update_idletasks()
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
