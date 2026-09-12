from __future__ import annotations

import webbrowser
from contextlib import suppress
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from constants import APP_TITLE, MIN_MASTER_PASSWORD_LENGTH
from password_manager_app import ImportRecordsError, PasswordManagerApp, ValidationError
from record_window import RecordWindow
from utils.vault_store import VaultError


class Ui(ctk.CTk):
    def __init__(self, password_manager_app: PasswordManagerApp):
        self.password_manager_app = password_manager_app
        ctk.set_default_color_theme("dark-blue")
        ctk.set_appearance_mode(str(self.password_manager_app.settings["theme"]))
        super().__init__()

        self.title(f"{APP_TITLE} 1.0")
        self.geometry("1050x650")
        self.minsize(900, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._lock_job: str | None = None
        self._focus_job: str | None = None
        self._clipboard_job: str | None = None
        self._status_job: str | None = None
        self._clipboard_value: str | None = None
        self.record_window: RecordWindow | None = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_lock_screen()

    def show_lock_screen(self) -> None:
        self._cancel_lock_timer()
        if self._focus_job:
            self.after_cancel(self._focus_job)
            self._focus_job = None
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None
        self._close_record_window()
        self._clear_root()

        container = ctk.CTkFrame(self, width=480, height=430)
        container.grid(row=0, column=0, padx=30, pady=30)
        container.grid_propagate(False)
        container.grid_columnconfigure(0, weight=1)

        is_existing = self.password_manager_app.vault_exists
        heading = "Разблокировать хранилище" if is_existing else "Создать безопасное хранилище"
        description = (
            "Введите мастер-пароль. Он нигде не сохраняется."
            if is_existing
            else f"Придумайте мастер-пароль не короче {MIN_MASTER_PASSWORD_LENGTH} символов.\n"
            "Восстановить забытый мастер-пароль невозможно."
        )
        ctk.CTkLabel(container, text=heading, font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, padx=30, pady=(38, 10), sticky="ew"
        )
        ctk.CTkLabel(container, text=description, wraplength=400).grid(
            row=1, column=0, padx=30, pady=(0, 22), sticky="ew"
        )

        self.master_password_entry = ctk.CTkEntry(container, placeholder_text="Мастер-пароль", show="*")
        self.master_password_entry.grid(row=2, column=0, padx=45, pady=6, sticky="ew")
        self.master_password_entry.bind("<Return>", lambda _event: self._submit_unlock())

        row = 3
        if not is_existing:
            self.repeat_master_password_entry = ctk.CTkEntry(
                container, placeholder_text="Повторите мастер-пароль", show="*"
            )
            self.repeat_master_password_entry.grid(row=row, column=0, padx=45, pady=6, sticky="ew")
            self.repeat_master_password_entry.bind("<Return>", lambda _event: self._submit_unlock())
            row += 1

            self.migrate_legacy_var = ctk.BooleanVar(value=self.password_manager_app.has_legacy_records)
            if self.password_manager_app.has_legacy_records:
                ctk.CTkCheckBox(
                    container,
                    text="Зашифровать записи из старого records.json\nи удалить его после проверенной миграции",
                    variable=self.migrate_legacy_var,
                ).grid(row=row, column=0, padx=45, pady=10, sticky="w")
                row += 1

        self.unlock_error_label = ctk.CTkLabel(container, text="", text_color="#e57373", wraplength=390)
        self.unlock_error_label.grid(row=row, column=0, padx=35, pady=5, sticky="ew")
        row += 1

        ctk.CTkButton(
            container,
            text="Разблокировать" if is_existing else "Создать хранилище",
            command=self._submit_unlock,
            height=38,
        ).grid(row=row, column=0, padx=45, pady=(8, 6), sticky="ew")
        row += 1

        if is_existing and self.password_manager_app.store.backup_path.is_file():
            ctk.CTkButton(
                container,
                text="Восстановить последнюю резервную копию",
                command=self._restore_default_backup,
                fg_color="transparent",
                border_width=1,
            ).grid(row=row, column=0, padx=45, pady=6, sticky="ew")

        self._focus_job = self.after(150, self._focus_master_password)

    def _focus_master_password(self) -> None:
        self._focus_job = None
        with suppress(Exception):
            self.master_password_entry.focus_set()

    def _submit_unlock(self) -> None:
        if self._focus_job:
            self.after_cancel(self._focus_job)
            self._focus_job = None
        password = self.master_password_entry.get()
        try:
            if self.password_manager_app.vault_exists:
                self.password_manager_app.unlock(password)
            else:
                repeat = self.repeat_master_password_entry.get()
                migrate = bool(
                    self.password_manager_app.has_legacy_records
                    and hasattr(self, "migrate_legacy_var")
                    and self.migrate_legacy_var.get()
                )
                if self.password_manager_app.has_legacy_records and not migrate:
                    proceed = messagebox.askyesno(
                        "Старые записи",
                        "Старый records.json не будет импортирован. Создать пустое хранилище?",
                        parent=self,
                    )
                    if not proceed:
                        return
                self.password_manager_app.create_vault(password, repeat, migrate_legacy=migrate)
            self.create_main_ui()
        except (ValidationError, VaultError) as exc:
            self.unlock_error_label.configure(text=str(exc))
            self.master_password_entry.delete(0, "end")
            self.master_password_entry.focus_set()

    def create_main_ui(self) -> None:
        self._clear_root()
        self.unbind_all("<Any-KeyPress>")
        self.unbind_all("<Any-Button>")
        self.bind_all("<Any-KeyPress>", self._register_activity, add="+")
        self.bind_all("<Any-Button>", self._register_activity, add="+")

        self.tabviews = ctk.CTkTabview(self, anchor="w")
        self.tabviews.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self.records_tab = self.tabviews.add("Пароли")
        self.create_tab = self.tabviews.add("Создать запись")
        self.settings_tab = self.tabviews.add("Настройки")
        self._create_records_tab()
        self._create_record_form()
        self._create_settings_tab()
        self.status_label = ctk.CTkLabel(self, text="", height=20, text_color="gray60")
        self.status_label.grid(row=1, column=0, padx=12, pady=(0, 5), sticky="w")
        self.refresh_records()
        self._register_activity()

    def _create_records_tab(self) -> None:
        self.records_tab.grid_columnconfigure(0, weight=1)
        self.records_tab.grid_rowconfigure(1, weight=1)
        search_frame = ctk.CTkFrame(self.records_tab, fg_color="transparent")
        search_frame.grid(row=0, column=0, padx=8, pady=(8, 5), sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)

        self.search_records_input = ctk.CTkEntry(
            search_frame, placeholder_text="Поиск по имени, сервису, логину, URL или заметке"
        )
        self.search_records_input.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.search_records_input.bind("<KeyRelease>", lambda _event: self.refresh_records())
        ctk.CTkButton(search_frame, text="Очистить", width=90, command=self.clear_search).grid(
            row=0, column=1, sticky="e"
        )

        self.records_field = ctk.CTkScrollableFrame(self.records_tab, border_width=1)
        self.records_field.grid(row=1, column=0, padx=8, pady=(5, 8), sticky="nsew")
        self.records_field.grid_columnconfigure(0, weight=1)

    def _create_record_form(self) -> None:
        self.create_tab.grid_columnconfigure((0, 1), weight=1)
        self.create_tab.grid_rowconfigure(5, weight=1)

        self.name_record_field = ctk.CTkEntry(self.create_tab, placeholder_text="Имя записи *")
        self.name_record_field.grid(row=0, column=0, columnspan=2, padx=8, pady=(12, 6), sticky="ew")
        self.name_service_field = ctk.CTkEntry(self.create_tab, placeholder_text="Сервис *")
        self.name_service_field.grid(row=1, column=0, padx=(8, 4), pady=6, sticky="ew")
        self.url_input_field = ctk.CTkEntry(self.create_tab, placeholder_text="https://example.com")
        self.url_input_field.grid(row=1, column=1, padx=(4, 8), pady=6, sticky="ew")
        self.login_input = ctk.CTkEntry(self.create_tab, placeholder_text="Логин *")
        self.login_input.grid(row=2, column=0, columnspan=2, padx=8, pady=6, sticky="ew")

        password_frame = ctk.CTkFrame(self.create_tab, fg_color="transparent")
        password_frame.grid(row=3, column=0, columnspan=2, padx=8, pady=6, sticky="ew")
        password_frame.grid_columnconfigure((0, 1), weight=1)
        self.password_input = ctk.CTkEntry(password_frame, placeholder_text="Пароль *", show="*")
        self.password_input.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.repeat_password_input = ctk.CTkEntry(password_frame, placeholder_text="Повторите пароль *", show="*")
        self.repeat_password_input.grid(row=0, column=1, padx=(4, 4), sticky="ew")
        self.show_password_button = ctk.CTkButton(
            password_frame, text="Показать", width=90, command=self.toggle_create_password
        )
        self.show_password_button.grid(row=0, column=2, padx=(4, 4))
        self.length_password = ctk.CTkComboBox(
            password_frame, values=[str(i) for i in range(12, 65)], width=75
        )
        self.length_password.set("20")
        self.length_password.grid(row=0, column=3, padx=4)
        ctk.CTkButton(password_frame, text="Сгенерировать", width=110, command=self.on_generate_password).grid(
            row=0, column=4, padx=(4, 0)
        )

        ctk.CTkLabel(self.create_tab, text="Комментарий или заметка").grid(
            row=4, column=0, columnspan=2, padx=10, pady=(8, 2), sticky="w"
        )
        self.note_input_field = ctk.CTkTextbox(self.create_tab, border_width=1)
        self.note_input_field.grid(row=5, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="nsew")
        ctk.CTkButton(self.create_tab, text="Сохранить запись", command=self.save_record, height=38).grid(
            row=6, column=0, columnspan=2, padx=8, pady=(0, 10), sticky="ew"
        )

    def _create_settings_tab(self) -> None:
        self.settings_tab.grid_columnconfigure(0, weight=1)
        panel = ctk.CTkFrame(self.settings_tab)
        panel.grid(row=0, column=0, padx=12, pady=12, sticky="new")
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Оформление").grid(row=0, column=0, padx=12, pady=10, sticky="w")
        self.change_theme_switch = ctk.CTkSwitch(
            panel, text="Тёмная тема", command=self.change_theme, onvalue="Dark", offvalue="Light"
        )
        self.change_theme_switch.grid(row=0, column=1, padx=12, pady=10, sticky="w")
        if self.password_manager_app.settings["theme"] == "Dark":
            self.change_theme_switch.select()

        ctk.CTkLabel(panel, text="Автоблокировка").grid(row=1, column=0, padx=12, pady=10, sticky="w")
        self.auto_lock_combo = ctk.CTkComboBox(
            panel, values=["1", "5", "10", "15", "30"], command=self.change_auto_lock, width=120
        )
        self.auto_lock_combo.set(str(self.password_manager_app.settings["auto_lock_minutes"]))
        self.auto_lock_combo.grid(row=1, column=1, padx=12, pady=10, sticky="w")
        ctk.CTkLabel(panel, text="минут бездействия", text_color="gray60").grid(
            row=1, column=1, padx=(145, 12), pady=10, sticky="w"
        )

        ctk.CTkButton(panel, text="Импортировать CSV", command=self.import_csv).grid(
            row=2, column=0, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сохранить зашифрованную копию", command=self.export_backup).grid(
            row=2, column=1, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkButton(panel, text="Восстановить зашифрованную копию", command=self.restore_backup).grid(
            row=3, column=0, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сменить мастер-пароль", command=self.change_master_password).grid(
            row=3, column=1, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkButton(panel, text="Заблокировать сейчас", command=self.lock_now).grid(
            row=4, column=0, columnspan=2, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkLabel(
            panel,
            text=f"Данные: {self.password_manager_app.data_dir}",
            wraplength=760,
            text_color="gray60",
        ).grid(row=5, column=0, columnspan=2, padx=12, pady=(12, 10), sticky="w")

    def refresh_records(self) -> None:
        if self.password_manager_app.is_locked or not hasattr(self, "records_field"):
            return
        for child in self.records_field.winfo_children():
            child.destroy()
        query = self.search_records_input.get() if hasattr(self, "search_records_input") else ""
        records = self.password_manager_app.get_records(query)
        if not records:
            text = "Ничего не найдено" if query else "Пока нет сохранённых записей"
            ctk.CTkLabel(self.records_field, text=text, text_color="gray60").grid(
                row=0, column=0, padx=15, pady=30
            )
            return
        for row, record in enumerate(records):
            card = ctk.CTkFrame(self.records_field, border_width=1)
            card.grid(row=row, column=0, padx=3, pady=3, sticky="ew")
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=record.record_name, font=ctk.CTkFont(size=16, weight="bold")).grid(
                row=0, column=0, padx=12, pady=(8, 0), sticky="w"
            )
            ctk.CTkLabel(card, text=f"{record.service_name}  •  {record.login}", text_color="gray60").grid(
                row=1, column=0, padx=12, pady=(1, 8), sticky="w"
            )
            ctk.CTkButton(card, text="Открыть", width=100, command=lambda item=record: self.open_record(item)).grid(
                row=0, column=1, rowspan=2, padx=10, pady=8
            )

    def open_record(self, record) -> None:
        self._close_record_window()
        self.record_window = RecordWindow(self, record, self.password_manager_app)

    def save_record(self) -> None:
        try:
            self.password_manager_app.save_record(
                self.name_record_field.get(),
                self.name_service_field.get(),
                self.login_input.get(),
                self.password_input.get(),
                self.repeat_password_input.get(),
                self.url_input_field.get(),
                self.note_input_field.get("1.0", "end-1c"),
            )
        except (ValidationError, VaultError, OSError) as exc:
            messagebox.showerror("Не удалось сохранить", str(exc), parent=self)
            return
        self.clear_input_fields()
        self.refresh_records()
        self.tabviews.set("Пароли")
        messagebox.showinfo("Готово", "Запись сохранена", parent=self)

    def on_generate_password(self) -> None:
        try:
            password = self.password_manager_app.password_generate(self.length_password.get())
        except (ValueError, ValidationError) as exc:
            messagebox.showerror("Генератор паролей", str(exc), parent=self)
            return
        for field in (self.password_input, self.repeat_password_input):
            field.delete(0, "end")
            field.insert(0, password)
            field.configure(show="*")
        self.show_password_button.configure(text="Показать")

    def toggle_create_password(self) -> None:
        show = "" if self.password_input.cget("show") == "*" else "*"
        for field in (self.password_input, self.repeat_password_input):
            field.configure(show=show)
        self.show_password_button.configure(text="Скрыть" if show == "" else "Показать")
        if show == "":
            self.after(15_000, self._hide_create_password)

    def _hide_create_password(self) -> None:
        if hasattr(self, "password_input") and self.password_input.winfo_exists():
            for field in (self.password_input, self.repeat_password_input):
                field.configure(show="*")
            self.show_password_button.configure(text="Показать")

    def clear_input_fields(self) -> None:
        for field in (
            self.name_record_field,
            self.name_service_field,
            self.login_input,
            self.password_input,
            self.repeat_password_input,
            self.url_input_field,
        ):
            field.delete(0, "end")
        self.note_input_field.delete("1.0", "end")

    def clear_search(self) -> None:
        self.search_records_input.delete(0, "end")
        self.refresh_records()

    def copy_to_clipboard(self, value: str, label: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()
        self._clipboard_value = value
        if self._clipboard_job:
            self.after_cancel(self._clipboard_job)
        seconds = int(self.password_manager_app.settings["clipboard_clear_seconds"])
        self._clipboard_job = self.after(seconds * 1000, self._clear_clipboard_if_unchanged)
        self.status_label.configure(text=f"{label} скопирован. Буфер очистится через {seconds} секунд.")
        if self._status_job:
            self.after_cancel(self._status_job)
        self._status_job = self.after(4_000, self._clear_status)

    def _clear_status(self) -> None:
        self._status_job = None
        with suppress(Exception):
            self.status_label.configure(text="")

    def _clear_clipboard_if_unchanged(self) -> None:
        try:
            if self.clipboard_get() == self._clipboard_value:
                self.clipboard_clear()
                self.update_idletasks()
        except Exception:
            pass
        self._clipboard_value = None
        self._clipboard_job = None

    def open_url(self, url: str) -> None:
        if url:
            webbrowser.open(url, new=2)

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Импорт CSV", filetypes=[("CSV", "*.csv"), ("Все файлы", "*.*")]
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Импорт CSV", "Все строки будут проверены до записи. Продолжить?", parent=self
        ):
            return
        try:
            count = self.password_manager_app.import_records_from_csv(path)
        except (ImportRecordsError, VaultError, OSError) as exc:
            messagebox.showerror("Импорт отменён", str(exc), parent=self)
            return
        self.refresh_records()
        messagebox.showinfo("Импорт завершён", f"Добавлено записей: {count}", parent=self)

    def export_backup(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Зашифрованная резервная копия",
            defaultextension=".pm2",
            filetypes=[("Password Manager vault", "*.pm2"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            self.password_manager_app.export_encrypted_backup(path)
        except (VaultError, OSError) as exc:
            messagebox.showerror("Резервная копия", str(exc), parent=self)
            return
        messagebox.showinfo("Резервная копия", "Зашифрованная копия сохранена", parent=self)

    def restore_backup(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Восстановить резервную копию",
            filetypes=[("Password Manager vault", "*.pm2"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Восстановление",
            "Текущее хранилище будет заменено выбранной копией. Продолжить?",
            parent=self,
        ):
            return
        try:
            backup_password = simpledialog.askstring(
                "Восстановление", "Мастер-пароль резервной копии", show="*", parent=self
            )
            if backup_password is None:
                return
            self.password_manager_app.restore_encrypted_backup(path, backup_password)
        except (VaultError, OSError) as exc:
            messagebox.showerror("Восстановление", str(exc), parent=self)
            return
        messagebox.showinfo("Восстановление", "Копия восстановлена. Разблокируйте хранилище.", parent=self)
        self.show_lock_screen()

    def _restore_default_backup(self) -> None:
        if not messagebox.askyesno(
            "Восстановление",
            "Основной файл будет заменён последней автоматической копией. Продолжить?",
            parent=self,
        ):
            return
        try:
            password = self.master_password_entry.get()
            self.password_manager_app.restore_encrypted_backup(
                self.password_manager_app.store.backup_path, password
            )
        except (VaultError, OSError) as exc:
            self.unlock_error_label.configure(text=str(exc))
            return
        self.unlock_error_label.configure(text="Резервная копия восстановлена. Введите мастер-пароль.")

    def change_master_password(self) -> None:
        current = simpledialog.askstring(
            "Смена мастер-пароля", "Текущий мастер-пароль", show="*", parent=self
        )
        if current is None:
            return
        new = simpledialog.askstring(
            "Смена мастер-пароля",
            f"Новый мастер-пароль (минимум {MIN_MASTER_PASSWORD_LENGTH} символов)",
            show="*",
            parent=self,
        )
        if new is None:
            return
        repeat = simpledialog.askstring(
            "Смена мастер-пароля", "Повторите новый мастер-пароль", show="*", parent=self
        )
        if repeat is None:
            return
        try:
            self.password_manager_app.change_master_password(current, new, repeat)
        except (ValidationError, VaultError) as exc:
            messagebox.showerror("Смена мастер-пароля", str(exc), parent=self)
            return
        messagebox.showinfo("Смена мастер-пароля", "Мастер-пароль изменён", parent=self)

    def change_theme(self) -> None:
        theme = self.change_theme_switch.get()
        ctk.set_appearance_mode(theme)
        self.password_manager_app.save_setting("theme", theme)

    def change_auto_lock(self, value: str) -> None:
        self.password_manager_app.save_setting("auto_lock_minutes", int(value))
        self._register_activity()

    def lock_now(self) -> None:
        self._clear_clipboard_if_unchanged()
        self.password_manager_app.lock()
        self.unbind_all("<Any-KeyPress>")
        self.unbind_all("<Any-Button>")
        self.show_lock_screen()

    def _register_activity(self, _event=None) -> None:
        if self.password_manager_app.is_locked:
            return
        self._cancel_lock_timer()
        minutes = int(self.password_manager_app.settings["auto_lock_minutes"])
        self._lock_job = self.after(minutes * 60_000, self.lock_now)

    def _cancel_lock_timer(self) -> None:
        if self._lock_job:
            self.after_cancel(self._lock_job)
            self._lock_job = None

    def _close_record_window(self) -> None:
        if self.record_window is not None and self.record_window.winfo_exists():
            self.record_window.destroy()
        self.record_window = None

    def _clear_root(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def on_close(self) -> None:
        self._cancel_lock_timer()
        if self._focus_job:
            self.after_cancel(self._focus_job)
            self._focus_job = None
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None
        self._clear_clipboard_if_unchanged()
        self.password_manager_app.lock()
        self.destroy()
