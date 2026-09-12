from __future__ import annotations

import queue
import threading
import webbrowser
from contextlib import suppress
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from constants import APP_TITLE, MIN_MASTER_PASSWORD_LENGTH
from models import PasswordRecord
from password_manager_app import ImportRecordsError, PasswordManagerApp, ValidationError
from record_window import RecordWindow
from utils.vault_store import VaultError

RECORDS_BATCH_SIZE = 20
SEARCH_DEBOUNCE_MS = 180


class Ui(ctk.CTk):
    def __init__(self, password_manager_app: PasswordManagerApp):
        self.password_manager_app = password_manager_app
        ctk.set_default_color_theme("dark-blue")
        ctk.set_appearance_mode(str(self.password_manager_app.settings["theme"]))
        super().__init__()

        self.title(f"{APP_TITLE} 1.0")
        self.geometry("620x820")
        self.minsize(540, 700)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._lock_job: str | None = None
        self._focus_job: str | None = None
        self._clipboard_job: str | None = None
        self._status_job: str | None = None
        self._search_job: str | None = None
        self._clipboard_value: str | None = None
        self._record_results: list[PasswordRecord] = []
        self._rendered_record_count = 0
        self._load_more_button: ctk.CTkButton | None = None
        self._import_running = False
        self._import_poll_job: str | None = None
        self._import_queue: queue.Queue[tuple] = queue.Queue()
        self.import_dialog: ctk.CTkToplevel | None = None
        self.record_window: RecordWindow | None = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_lock_screen()

    def show_lock_screen(self) -> None:
        self._cancel_lock_timer()
        self._cancel_search_refresh()
        self._record_results.clear()
        self._rendered_record_count = 0
        self._load_more_button = None
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
            "Введите мастер-пароль."
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
        self.search_records_input.bind("<KeyRelease>", self._schedule_records_refresh)
        ctk.CTkButton(search_frame, text="Очистить", width=90, command=self.clear_search).grid(
            row=0, column=1, sticky="e"
        )
        self.records_count_label = ctk.CTkLabel(search_frame, text="", text_color="gray60", height=18)
        self.records_count_label.grid(row=1, column=0, columnspan=2, pady=(3, 0), sticky="e")

        self.records_field = ctk.CTkScrollableFrame(self.records_tab, border_width=1)
        self.records_field.grid(row=1, column=0, padx=8, pady=(5, 8), sticky="nsew")
        self.records_field.grid_columnconfigure(0, weight=1)
        self._record_name_font = ctk.CTkFont(size=16, weight="bold")
        self._record_action_font = ctk.CTkFont(size=12)

    def _create_record_form(self) -> None:
        self.create_tab.grid_columnconfigure(0, weight=1)
        self.create_tab.grid_rowconfigure(2, weight=1)

        basic_frame = ctk.CTkFrame(self.create_tab)
        basic_frame.grid(row=0, column=0, padx=8, pady=(10, 5), sticky="ew")
        basic_frame.grid_columnconfigure(0, weight=1)
        self.name_record_field = self._labeled_entry(basic_frame, 0, "Имя записи")
        self.name_service_field = self._labeled_entry(basic_frame, 2, "Сервис")
        self.url_input_field = self._labeled_entry(
            basic_frame, 4, "Сайт", "example.com — https:// добавится автоматически"
        )

        password_frame = ctk.CTkFrame(self.create_tab)
        password_frame.grid(row=1, column=0, padx=8, pady=5, sticky="ew")
        password_frame.grid_columnconfigure(0, weight=1)
        self.login_input = self._labeled_entry(password_frame, 0, "Логин")
        ctk.CTkLabel(password_frame, text="Пароль").grid(row=2, column=0, padx=10, pady=(5, 2), sticky="w")
        self.password_input = ctk.CTkEntry(password_frame, placeholder_text="Пароль", show="*")
        self.password_input.grid(row=3, column=0, padx=10, pady=(0, 5), sticky="ew")
        ctk.CTkLabel(password_frame, text="Повтор пароля").grid(
            row=4, column=0, padx=10, pady=(5, 2), sticky="w"
        )
        self.repeat_password_input = ctk.CTkEntry(password_frame, placeholder_text="Повторите пароль", show="*")
        self.repeat_password_input.grid(row=5, column=0, padx=10, pady=(0, 5), sticky="ew")
        generator_frame = ctk.CTkFrame(password_frame, fg_color="transparent")
        generator_frame.grid(row=6, column=0, padx=10, pady=(5, 10), sticky="ew")
        generator_frame.grid_columnconfigure(2, weight=1)
        self.show_password_button = ctk.CTkButton(
            generator_frame, text="Показать", width=90, command=self.toggle_create_password
        )
        self.show_password_button.grid(row=0, column=0, padx=(0, 5))
        self.length_password = ctk.CTkComboBox(
            generator_frame, values=[str(i) for i in range(12, 65)], width=75
        )
        self.length_password.set("20")
        self.length_password.grid(row=0, column=1, padx=5)
        ctk.CTkButton(generator_frame, text="Сгенерировать", command=self.on_generate_password).grid(
            row=0, column=2, padx=(5, 0), sticky="ew"
        )

        note_frame = ctk.CTkFrame(self.create_tab)
        note_frame.grid(row=2, column=0, padx=8, pady=5, sticky="nsew")
        note_frame.grid_columnconfigure(0, weight=1)
        note_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(note_frame, text="Комментарий или заметка").grid(
            row=0, column=0, padx=10, pady=(8, 2), sticky="w"
        )
        self.note_input_field = ctk.CTkTextbox(note_frame, border_width=1, height=90)
        self.note_input_field.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        ctk.CTkButton(self.create_tab, text="Сохранить запись", command=self.save_record, height=38).grid(
            row=3, column=0, padx=8, pady=(5, 10), sticky="ew"
        )

    @staticmethod
    def _labeled_entry(parent, row: int, label: str, placeholder: str = ""):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=10, pady=(7, 2), sticky="w")
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder)
        entry.grid(row=row + 1, column=0, padx=10, pady=(0, 5), sticky="ew")
        return entry

    def _create_settings_tab(self) -> None:
        self.settings_tab.grid_columnconfigure(0, weight=1)
        panel = ctk.CTkFrame(self.settings_tab)
        panel.grid(row=0, column=0, padx=12, pady=12, sticky="new")
        panel.grid_columnconfigure(0, weight=1)
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
            row=2, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сохранить зашифрованную копию", command=self.export_backup).grid(
            row=3, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(panel, text="Восстановить зашифрованную копию", command=self.restore_backup).grid(
            row=4, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сменить мастер-пароль", command=self.change_master_password).grid(
            row=5, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(panel, text="Поддерживаемые CSV", command=self.show_csv_help).grid(
            row=6, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(panel, text="Заблокировать сейчас", command=self.lock_now).grid(
            row=7, column=0, columnspan=2, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkLabel(
            panel,
            text=f"Данные: {self.password_manager_app.data_dir}",
            wraplength=480,
            text_color="gray60",
        ).grid(row=8, column=0, columnspan=2, padx=12, pady=(12, 10), sticky="w")

    def refresh_records(self) -> None:
        if self.password_manager_app.is_locked or not hasattr(self, "records_field"):
            return
        self._cancel_search_refresh()
        for child in self.records_field.winfo_children():
            child.destroy()
        query = self.search_records_input.get() if hasattr(self, "search_records_input") else ""
        has_query = bool(query.strip())
        all_records = self.password_manager_app.get_records()
        self._record_results = self.password_manager_app.get_records(query) if has_query else all_records
        total_count = len(all_records)
        result_count = len(self._record_results)
        count_text = f"Найдено: {result_count} из {total_count}" if has_query else f"Всего записей: {total_count}"
        self.records_count_label.configure(text=count_text)
        self._rendered_record_count = 0
        self._load_more_button = None
        if not self._record_results:
            text = "Ничего не найдено" if has_query else "Пока нет сохранённых записей"
            ctk.CTkLabel(self.records_field, text=text, text_color="gray60").grid(
                row=0, column=0, padx=15, pady=30
            )
            return
        self._append_record_batch()

    def _schedule_records_refresh(self, _event=None) -> None:
        self._cancel_search_refresh()
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self._run_scheduled_records_refresh)

    def _run_scheduled_records_refresh(self) -> None:
        self._search_job = None
        self.refresh_records()

    def _cancel_search_refresh(self) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None

    def _append_record_batch(self) -> None:
        if self.password_manager_app.is_locked or not hasattr(self, "records_field"):
            return
        if self._load_more_button is not None and self._load_more_button.winfo_exists():
            self._load_more_button.destroy()
        self._load_more_button = None

        start = self._rendered_record_count
        end = min(start + RECORDS_BATCH_SIZE, len(self._record_results))
        for row, record in enumerate(self._record_results[start:end], start=start):
            self._create_record_card(row, record)
        self._rendered_record_count = end

        if end < len(self._record_results):
            self._load_more_button = ctk.CTkButton(
                self.records_field,
                text=f"Показать ещё  ·  {end} из {len(self._record_results)}",
                command=self._append_record_batch,
                height=34,
                fg_color="transparent",
                border_width=1,
            )
            self._load_more_button.grid(row=end, column=0, padx=3, pady=8, sticky="ew")

    def _create_record_card(self, row: int, record: PasswordRecord) -> None:
        card = ctk.CTkFrame(self.records_field, border_width=1)
        card.grid(row=row, column=0, padx=3, pady=3, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=record.record_name, font=self._record_name_font).grid(
            row=0, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        details = "  •  ".join(value for value in (record.service_name, record.login) if value)
        ctk.CTkLabel(card, text=details or "Поля не заполнены", text_color="gray60").grid(
            row=1, column=0, padx=12, pady=(1, 5), sticky="w"
        )

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")
        for column in range(3):
            actions.grid_columnconfigure(column, weight=1, uniform="record-actions")
        ctk.CTkButton(
            actions,
            text="Копировать логин",
            command=lambda item=record: self.copy_to_clipboard(item.login, "Логин"),
            state="normal" if record.login else "disabled",
            height=28,
            font=self._record_action_font,
            fg_color="transparent",
            border_width=1,
        ).grid(row=0, column=0, padx=(0, 3), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Копировать пароль",
            command=lambda item=record: self.copy_to_clipboard(item.password, "Пароль"),
            state="normal" if record.password else "disabled",
            height=28,
            font=self._record_action_font,
            fg_color="transparent",
            border_width=1,
        ).grid(row=0, column=1, padx=3, sticky="ew")
        ctk.CTkButton(
            actions,
            text="Открыть",
            command=lambda item=record: self.open_record(item),
            height=28,
            font=self._record_action_font,
        ).grid(row=0, column=2, padx=(3, 0), sticky="ew")

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
            "Импорт CSV",
            "Файл будет полностью прочитан и проверен до изменения хранилища.\n\n"
            "Если хотя бы одна строка некорректна, ни одна запись не импортируется. Продолжить?",
            parent=self,
        ):
            return
        self._start_csv_import(path)

    def show_csv_help(self) -> None:
        messagebox.showinfo(
            "Форматы CSV",
            "Поддерживаются стандартные файлы экспорта паролей:\n\n"
            "Chrome / Edge / Brave / Opera:\n"
            "name, url, username, password, note\n\n"
            "Firefox:\n"
            "url, username, password, httpRealm, formActionOrigin, ...\n\n"
            "Safari / Apple Passwords:\n"
            "Title, URL, Username, Password, Notes, OTPAuth\n\n"
            "Формат определяется автоматически.",
            parent=self,
        )

    def _start_csv_import(self, path: str) -> None:
        self._cancel_lock_timer()
        self._import_running = True
        self._import_queue = queue.Queue()

        self.import_dialog = ctk.CTkToplevel(self)
        self.import_dialog.title("Импорт паролей")
        self.import_dialog.geometry("460x210")
        self.import_dialog.resizable(False, False)
        self.import_dialog.transient(self)
        self.import_dialog.grab_set()
        self.import_dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        self.import_dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.import_dialog,
            text="Импорт паролей из браузера",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(24, 8), sticky="ew")
        self.import_progress_label = ctk.CTkLabel(self.import_dialog, text="Чтение CSV…")
        self.import_progress_label.grid(row=1, column=0, padx=24, pady=5, sticky="ew")
        self.import_progress_bar = ctk.CTkProgressBar(self.import_dialog, mode="determinate")
        self.import_progress_bar.set(0)
        self.import_progress_bar.grid(row=2, column=0, padx=28, pady=(8, 24), sticky="ew")

        def report_progress(current: int, total: int, phase: str) -> None:
            self._import_queue.put(("progress", current, total, phase))

        def worker() -> None:
            try:
                count = self.password_manager_app.import_records_from_csv(path, report_progress)
            except (ImportRecordsError, VaultError, OSError, ValueError) as exc:
                self._import_queue.put(("error", str(exc)))
            except Exception as exc:
                self._import_queue.put(("error", f"Непредвиденная ошибка импорта: {exc}"))
            else:
                self._import_queue.put(("done", count))

        threading.Thread(target=worker, name="browser-csv-import", daemon=True).start()
        self._import_poll_job = self.after(50, self._poll_csv_import)

    def _poll_csv_import(self) -> None:
        self._import_poll_job = None
        finished = False
        while True:
            try:
                event = self._import_queue.get_nowait()
            except queue.Empty:
                break
            if event[0] == "progress":
                _, current, total, phase = event
                fraction = current / total if total else 0
                self.import_progress_bar.set(max(0, min(1, fraction)))
                percentage = round(fraction * 100)
                self.import_progress_label.configure(text=f"{phase}: {current} из {total} ({percentage}%)")
            elif event[0] == "error":
                self._finish_csv_import()
                messagebox.showerror("Импорт отменён", event[1], parent=self)
                finished = True
                break
            elif event[0] == "done":
                count = event[1]
                self.import_progress_bar.set(1)
                self._finish_csv_import()
                self.refresh_records()
                messagebox.showinfo("Импорт завершён", f"Добавлено записей: {count}", parent=self)
                finished = True
                break
        if not finished and self._import_running:
            self._import_poll_job = self.after(75, self._poll_csv_import)

    def _finish_csv_import(self) -> None:
        self._import_running = False
        if self.import_dialog is not None and self.import_dialog.winfo_exists():
            with suppress(Exception):
                self.import_dialog.grab_release()
            self.import_dialog.destroy()
        self.import_dialog = None
        self._register_activity()

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
        if self._import_running:
            return
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
        if self._import_running:
            messagebox.showinfo("Импорт выполняется", "Дождитесь завершения импорта.", parent=self)
            return
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
