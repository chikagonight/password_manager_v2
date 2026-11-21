from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from constants import APP_TITLE
from models import PasswordRecord
from password_safe.application import PasswordSafe
from password_safe.domain import (
    MAX_GENERATED_PASSWORD_LENGTH,
    MIN_GENERATED_PASSWORD_LENGTH,
    MIN_MASTER_PASSWORD_LENGTH,
)
from password_safe.ports import ImportRecordsError, MigrationIncomplete, PasswordClipboard, ValidationError, VaultError
from password_safe.updates import SETUP_FILENAME, Release, UpdateError
from password_safe.version import APP_VERSION
from record_window import RecordWindow
from ui_compat import configure_stable_windows_dpi
from utils.tk_clipboard import protect_password_entry

configure_stable_windows_dpi()

RECORDS_BATCH_SIZE = 20
SEARCH_DEBOUNCE_MS = 180
OUTLINE_BUTTON_STYLE = {
    "fg_color": "transparent",
    "hover_color": ("gray82", "gray28"),
    "border_color": ("gray48", "gray55"),
    "text_color": ("gray20", "gray90"),
    "text_color_disabled": ("gray45", "gray55"),
}


class Ui(ctk.CTk):
    def __init__(
        self, password_manager_app: PasswordSafe, *, data_dir: Path | None = None,
        clipboard_factory: Callable[[Ui], PasswordClipboard] | None = None,
        check_updates: Callable[[], Release | None] | None = None,
        releases_url: str = "",
    ):
        self.password_manager_app = password_manager_app
        self._data_dir = data_dir
        self._clipboard_factory = clipboard_factory
        self._check_updates = check_updates
        self._releases_url = releases_url
        ctk.set_default_color_theme("dark-blue")
        ctk.set_appearance_mode(str(self.password_manager_app.settings["theme"]))
        super().__init__()

        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("600x760")
        self.minsize(520, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._lock_job: str | None = None
        self._focus_job: str | None = None
        self._clipboard_job: str | None = None
        self._status_job: str | None = None
        self._search_job: str | None = None
        self._clipboard: PasswordClipboard | None = None
        self._record_results: list[PasswordRecord] = []
        self._rendered_record_count = 0
        self._load_more_button: ctk.CTkButton | None = None
        self._import_running = False
        self._import_poll_job: str | None = None
        self._import_queue: queue.Queue[tuple] = queue.Queue()
        self._update_poll_job: str | None = None
        self._update_button: ctk.CTkButton | None = None
        self.import_dialog: ctk.CTkToplevel | None = None
        self.record_window: RecordWindow | None = None
        self._legacy_source: Path | None = None
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

        container = ctk.CTkFrame(self, width=460, height=370)
        container.grid(row=0, column=0, padx=20, pady=20)

        container.grid_columnconfigure(0, weight=1)

        is_existing = self.password_manager_app.vault_exists
        heading = "Разблокировать хранилище" if is_existing else "Создать безопасное хранилище"
        description = (
            "Введите мастер-пароль."
            if is_existing
            else f"Минимум {MIN_MASTER_PASSWORD_LENGTH} символов. Лучше выбрать длинную фразу из нескольких "
            "случайных слов. Забытый мастер-пароль восстановить нельзя."
        )
        ctk.CTkLabel(container, text=heading, font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, padx=24, pady=(28, 8), sticky="ew"
        )
        ctk.CTkLabel(container, text=description, wraplength=400).grid(
            row=1, column=0, padx=24, pady=(0, 14), sticky="ew"
        )

        self.master_password_entry = ctk.CTkEntry(container, placeholder_text="Мастер-пароль", show="*")
        self.master_password_entry.grid(row=2, column=0, padx=35, pady=4, sticky="ew")
        self.master_password_entry.bind("<Return>", lambda _event: self._submit_unlock())

        row = 3
        if not is_existing:
            self.repeat_master_password_entry = ctk.CTkEntry(
                container, placeholder_text="Повторите мастер-пароль", show="*"
            )
            self.repeat_master_password_entry.grid(row=row, column=0, padx=35, pady=4, sticky="ew")
            self.repeat_master_password_entry.bind("<Return>", lambda _event: self._submit_unlock())
            row += 1

            self.legacy_button = ctk.CTkButton(
                container, text="Выбрать файл старых записей…", command=self._choose_legacy_source,
                border_width=1, **OUTLINE_BUTTON_STYLE,
            )
            self.legacy_button.grid(row=row, column=0, padx=35, pady=4, sticky="ew")
            row += 1

        self.unlock_error_label = ctk.CTkLabel(container, text="", text_color="#e57373", wraplength=390)
        self.unlock_error_label.grid(row=row, column=0, padx=30, pady=3, sticky="ew")
        row += 1

        ctk.CTkButton(
            container,
            text="Разблокировать" if is_existing else "Создать хранилище",
            command=self._submit_unlock,
            height=38,
        ).grid(row=row, column=0, padx=35, pady=(5, 4), sticky="ew")
        row += 1

        if self.password_manager_app.has_automatic_backup:
            ctk.CTkButton(
                container,
                text="Восстановить автоматическую копию",
                command=self._restore_default_backup,
                border_width=1,
                **OUTLINE_BUTTON_STYLE,
            ).grid(row=row, column=0, padx=35, pady=4, sticky="ew")
            row += 1

        ctk.CTkButton(
            container, text="Выбрать резервную копию…", command=self.restore_backup,
            border_width=1, **OUTLINE_BUTTON_STYLE,
        ).grid(row=row, column=0, padx=35, pady=(4, 18), sticky="ew")

        self._focus_job = self.after(150, self._focus_master_password)

    def _focus_master_password(self) -> None:
        self._focus_job = None
        with suppress(Exception):
            self.master_password_entry.focus_set()

    def _select_legacy_path(self) -> Path | None:
        try:
            suggested = self.password_manager_app.suggested_legacy_source
        except OSError:
            suggested = None
        path = filedialog.askopenfilename(
            parent=self, title="Выберите старый records.json",
            initialdir=str(suggested.parent) if suggested else str(Path.cwd()),
            initialfile=suggested.name if suggested else "records.json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        return Path(path) if path else None

    def _choose_legacy_source(self) -> None:
        self._legacy_source = self._select_legacy_path()
        self.legacy_button.configure(text="Файл старых записей выбран" if self._legacy_source else "Выбрать файл старых записей…")

    def _confirm_legacy_removal(self) -> bool:
        return messagebox.askyesno(
            "Миграция", "Удалить выбранный открытый JSON-файл после проверки зашифрованной копии?",
            parent=self,
        )

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
                if self._legacy_source is not None and not self._confirm_legacy_removal():
                    return
                if self._legacy_source is None and self.password_manager_app.has_legacy_records:
                    proceed = messagebox.askyesno(
                        "Старые записи",
                        "Старый records.json не будет импортирован. Создать пустое хранилище?",
                        parent=self,
                    )
                    if not proceed:
                        return
                self.password_manager_app.create_vault(password, repeat, legacy_source=self._legacy_source)
            self.create_main_ui()
        except MigrationIncomplete as exc:
            self.create_main_ui()
            messagebox.showwarning("Миграция не завершена", str(exc), parent=self)
        except (ValidationError, VaultError) as exc:
            self.unlock_error_label.configure(text=str(exc))
            self.master_password_entry.delete(0, "end")
            self.master_password_entry.focus_set()
        except OSError:
            self.unlock_error_label.configure(text="Ошибка доступа к файлам хранилища")

    def create_main_ui(self) -> None:
        self._clear_root()
        self.unbind_all("<Any-KeyPress>")
        self.unbind_all("<Any-Button>")
        self.bind_all("<Any-KeyPress>", self._register_activity, add="+")
        self.bind_all("<Any-Button>", self._register_activity, add="+")

        self.tabviews = ctk.CTkTabview(self, anchor="w")
        self.tabviews.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.records_tab = self.tabviews.add("Пароли")
        self.create_tab = self.tabviews.add("Создать запись")
        self.settings_tab = self.tabviews.add("Настройки")
        self._create_records_tab()
        self._create_record_form()
        self._create_settings_tab()
        self.status_label = ctk.CTkLabel(self, text="", height=20, text_color="gray60")
        self.status_label.grid(row=1, column=0, padx=8, pady=(0, 3), sticky="w")
        self.refresh_records()
        self._register_activity()

    def _create_records_tab(self) -> None:
        self.records_tab.grid_columnconfigure(0, weight=1)
        self.records_tab.grid_rowconfigure(1, weight=1)
        search_frame = ctk.CTkFrame(self.records_tab, fg_color="transparent")
        search_frame.grid(row=0, column=0, padx=5, pady=(5, 3), sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)

        self.search_records_input = ctk.CTkEntry(
            search_frame, placeholder_text="Поиск по имени, сервису, логину, URL или заметке"
        )
        self.search_records_input.configure(height=30)
        self.search_records_input.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.search_records_input.bind("<KeyRelease>", self._schedule_records_refresh)
        ctk.CTkButton(search_frame, text="Очистить", width=82, height=30, command=self.clear_search).grid(
            row=0, column=1, sticky="e"
        )
        self.records_count_label = ctk.CTkLabel(search_frame, text="", text_color="gray60", height=16)
        self.records_count_label.grid(row=1, column=0, columnspan=2, pady=(1, 0), sticky="e")

        self.records_field = ctk.CTkScrollableFrame(self.records_tab, border_width=1)
        self.records_field.grid(row=1, column=0, padx=5, pady=(3, 5), sticky="nsew")
        self.records_field.grid_columnconfigure(0, weight=1)
        self._record_name_font = ctk.CTkFont(size=15, weight="bold")
        self._record_action_font = ctk.CTkFont(size=12)

    def _create_record_form(self) -> None:
        self.create_tab.grid_columnconfigure(0, weight=1)
        self.create_tab.grid_rowconfigure(2, weight=1)

        basic_frame = ctk.CTkFrame(self.create_tab)
        basic_frame.grid(row=0, column=0, padx=5, pady=(5, 3), sticky="ew")
        basic_frame.grid_columnconfigure(0, weight=1)
        self.name_record_field = self._labeled_entry(basic_frame, 0, "Имя записи")
        self.name_service_field = self._labeled_entry(basic_frame, 2, "Сервис")
        self.url_input_field = self._labeled_entry(
            basic_frame, 4, "Сайт", "example.com — https:// добавится автоматически"
        )

        password_frame = ctk.CTkFrame(self.create_tab)
        password_frame.grid(row=1, column=0, padx=5, pady=3, sticky="ew")
        password_frame.grid_columnconfigure(0, weight=1)
        self.login_input = self._labeled_entry(password_frame, 0, "Логин")
        ctk.CTkLabel(password_frame, text="Пароль", height=22).grid(
            row=2, column=0, padx=8, pady=(3, 1), sticky="w"
        )
        self.password_input = ctk.CTkEntry(password_frame, placeholder_text="Пароль", show="*")
        protect_password_entry(self.password_input, self.copy_to_clipboard)
        self.password_input.grid(row=3, column=0, padx=8, pady=(0, 2), sticky="ew")
        ctk.CTkLabel(password_frame, text="Повтор пароля", height=22).grid(
            row=4, column=0, padx=8, pady=(3, 1), sticky="w"
        )
        self.repeat_password_input = ctk.CTkEntry(password_frame, placeholder_text="Повторите пароль", show="*")
        protect_password_entry(self.repeat_password_input, self.copy_to_clipboard)
        self.repeat_password_input.grid(row=5, column=0, padx=8, pady=(0, 2), sticky="ew")
        generator_frame = ctk.CTkFrame(password_frame, fg_color="transparent")
        generator_frame.grid(row=6, column=0, padx=8, pady=(2, 5), sticky="ew")
        generator_frame.grid_columnconfigure(2, weight=1)
        self.show_password_button = ctk.CTkButton(
            generator_frame, text="Показать", width=82, height=30, command=self.toggle_create_password
        )
        self.show_password_button.grid(row=0, column=0, padx=(0, 3))
        self.length_password = ctk.CTkComboBox(
            generator_frame,
            values=[str(i) for i in range(MIN_GENERATED_PASSWORD_LENGTH, MAX_GENERATED_PASSWORD_LENGTH + 1)],
            width=70,
            height=30,
        )
        self.length_password.set("20")
        self.length_password.grid(row=0, column=1, padx=3)
        ctk.CTkButton(generator_frame, text="Сгенерировать", height=30, command=self.on_generate_password).grid(
            row=0, column=2, padx=(3, 0), sticky="ew"
        )

        note_frame = ctk.CTkFrame(self.create_tab)
        note_frame.grid(row=2, column=0, padx=5, pady=3, sticky="nsew")
        note_frame.grid_columnconfigure(0, weight=1)
        note_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(note_frame, text="Комментарий или заметка").grid(
            row=0, column=0, padx=8, pady=(4, 1), sticky="w"
        )
        self.note_input_field = ctk.CTkTextbox(note_frame, border_width=1, height=70)
        self.note_input_field.grid(row=1, column=0, padx=8, pady=(0, 5), sticky="nsew")
        ctk.CTkButton(self.create_tab, text="Сохранить запись", command=self.save_record, height=34).grid(
            row=3, column=0, padx=5, pady=(3, 5), sticky="ew"
        )

    @staticmethod
    def _labeled_entry(parent, row: int, label: str, placeholder: str = ""):
        ctk.CTkLabel(parent, text=label, height=22).grid(row=row, column=0, padx=8, pady=(3, 1), sticky="w")
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder, height=30)
        entry.grid(row=row + 1, column=0, padx=8, pady=(0, 2), sticky="ew")
        return entry

    def _create_settings_tab(self) -> None:
        self.settings_tab.grid_columnconfigure(0, weight=1)
        panel = ctk.CTkFrame(self.settings_tab)
        panel.grid(row=0, column=0, padx=8, pady=8, sticky="new")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Оформление").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.change_theme_switch = ctk.CTkSwitch(
            panel, text="Тёмная тема", command=self.change_theme, onvalue="Dark", offvalue="Light"
        )
        self.change_theme_switch.grid(row=0, column=1, padx=10, pady=6, sticky="w")
        if self.password_manager_app.settings["theme"] == "Dark":
            self.change_theme_switch.select()

        ctk.CTkLabel(panel, text="Автоблокировка").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.auto_lock_combo = ctk.CTkComboBox(
            panel, values=["1", "5", "10", "15", "30"], command=self.change_auto_lock, width=120, state="readonly"
        )
        self.auto_lock_combo.set(str(self.password_manager_app.settings["auto_lock_minutes"]))
        self.auto_lock_combo.grid(row=1, column=1, padx=10, pady=6, sticky="w")
        ctk.CTkLabel(panel, text="минут бездействия", text_color="gray60").grid(
            row=1, column=1, padx=(143, 10), pady=6, sticky="w"
        )

        ctk.CTkButton(panel, text="Импортировать CSV", command=self.import_csv).grid(
            row=2, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сохранить зашифрованную копию", command=self.export_backup).grid(
            row=3, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Восстановить зашифрованную копию", command=self.restore_backup).grid(
            row=4, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Сменить мастер-пароль", command=self.change_master_password).grid(
            row=5, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Поддерживаемые CSV", command=self.show_csv_help).grid(
            row=6, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Заблокировать сейчас", command=self.lock_now).grid(
            row=7, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        ctk.CTkButton(panel, text="Завершить миграцию", command=self.finish_legacy_migration).grid(
            row=8, column=0, columnspan=2, padx=10, pady=3, sticky="ew"
        )
        if self._check_updates is not None:
            button = ctk.CTkButton(
                panel, text="Проверить обновления", command=self._start_update_check,
            )
            button.grid(row=9, column=0, columnspan=2, padx=10, pady=3, sticky="ew")
            if self._update_poll_job is not None:
                button.configure(state="disabled", text="Проверка…")
            self._update_button = button
        if self._data_dir is not None:
            ctk.CTkLabel(
                panel, text=f"Данные: {self._data_dir}", wraplength=480, text_color="gray60",
            ).grid(row=10, column=0, columnspan=2, padx=10, pady=(8, 6), sticky="w")

    def _start_update_check(self) -> None:
        check_updates = self._check_updates
        if check_updates is None or self._update_button is None or self._update_poll_job is not None:
            return
        self._update_button.configure(state="disabled", text="Проверка…")
        results: queue.Queue[Release | UpdateError | None] = queue.Queue()

        def worker() -> None:
            try:
                results.put(check_updates())
            except UpdateError as exc:
                results.put(exc)
            except Exception:
                results.put(UpdateError("Не удалось проверить обновления."))

        threading.Thread(target=worker, name="release-check", daemon=True).start()
        self._update_poll_job = self.after(75, self._poll_update_check, results)

    def _poll_update_check(self, results: queue.Queue[Release | UpdateError | None]) -> None:
        try:
            result = results.get_nowait()
        except queue.Empty:
            self._update_poll_job = self.after(75, self._poll_update_check, results)
            return
        self._update_poll_job = None
        if self._update_button is not None:
            self._update_button.configure(state="normal", text="Проверить обновления")
        if self.password_manager_app.is_locked or self._import_running:
            return

        title = "Обновления"
        if result is None:
            messagebox.showinfo(title, f"Установлена актуальная версия: {APP_VERSION}.", parent=self)
            return
        if isinstance(result, UpdateError):
            url = self._releases_url
            text = f"{result}\n\nОткрыть список релизов в браузере?"
        else:
            url = result.page_url
            text = (
                f"Доступна версия {result.tag}. У вас установлена {APP_VERSION}.\n\n"
                f"Скачайте {SETUP_FILENAME} со страницы релиза, закройте passwordSafe "
                "и запустите установщик. При установке выберите текущую папку приложения.\n\n"
                "Открыть страницу релиза в браузере?"
            )
        if url and messagebox.askyesno(title, text, parent=self):
            try:
                self.password_manager_app.open_url(url)
            except ValidationError as exc:
                messagebox.showerror(title, str(exc), parent=self)

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
                height=30,
                border_width=1,
                **OUTLINE_BUTTON_STYLE,
            )
            self._load_more_button.grid(row=end, column=0, padx=2, pady=5, sticky="ew")

    def _create_record_card(self, row: int, record: PasswordRecord) -> None:
        card = ctk.CTkFrame(self.records_field, border_width=1)
        card.grid(row=row, column=0, padx=2, pady=2, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=record.record_name, font=self._record_name_font, height=22).grid(
            row=0, column=0, padx=10, pady=(5, 0), sticky="w"
        )
        details = "  •  ".join(value for value in (record.service_name, record.login) if value)
        ctk.CTkLabel(card, text=details or "Поля не заполнены", text_color="gray60", height=22).grid(
            row=1, column=0, padx=10, pady=(0, 3), sticky="w"
        )

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=2, column=0, padx=8, pady=(0, 5), sticky="ew")
        for column in range(3):
            actions.grid_columnconfigure(column, weight=1, uniform="record-actions")
        ctk.CTkButton(
            actions,
            text="Копировать логин",
            command=lambda item=record: self.copy_to_clipboard(item.login, "Логин"),
            state="normal" if record.login else "disabled",
            height=28,
            font=self._record_action_font,
            border_width=1,
            **OUTLINE_BUTTON_STYLE,
        ).grid(row=0, column=0, padx=(0, 3), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Копировать пароль",
            command=lambda item=record: self.copy_to_clipboard(item.password, "Пароль"),
            state="normal" if record.password else "disabled",
            height=28,
            font=self._record_action_font,
            border_width=1,
            **OUTLINE_BUTTON_STYLE,
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

    def copy_to_clipboard(self, value: str, label: str) -> bool:
        try:
            if self._clipboard is None:
                if self._clipboard_factory is None:
                    raise OSError
                self._clipboard = self._clipboard_factory(self)
            self._clipboard.copy_password(value)
        except (OSError, ValueError):
            messagebox.showerror("Буфер обмена", "Не удалось безопасно скопировать значение", parent=self)
            return False
        if self._clipboard_job:
            self.after_cancel(self._clipboard_job)
        seconds = int(self.password_manager_app.settings["clipboard_clear_seconds"])
        self._clipboard_job = self.after(seconds * 1000, self._clear_clipboard_if_unchanged)
        self.status_label.configure(text=f"{label} скопирован. Буфер очистится через {seconds} секунд.")
        if self._status_job:
            self.after_cancel(self._status_job)
        self._status_job = self.after(4_000, self._clear_status)
        return True

    def _clear_status(self) -> None:
        self._status_job = None
        with suppress(Exception):
            self.status_label.configure(text="")

    def _clear_clipboard_if_unchanged(self) -> None:
        if self._clipboard_job:
            self.after_cancel(self._clipboard_job)
            self._clipboard_job = None
        if self._clipboard is not None:
            with suppress(OSError):
                self._clipboard.clear_password()

    def open_url(self, url: str) -> None:
        try:
            self.password_manager_app.open_url(url)
        except ValidationError as exc:
            messagebox.showerror("Не удалось открыть сайт", str(exc), parent=self)

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
            except Exception:
                self._import_queue.put(("error", "Непредвиденная ошибка импорта"))
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
            filetypes=[("passwordSafe vault", "*.pm2"), ("Все файлы", "*.*")],
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
            filetypes=[("passwordSafe vault", "*.pm2"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        self._restore_selected_backup(Path(path))

    def _restore_default_backup(self) -> None:
        self._restore_selected_backup(None)

    def _restore_selected_backup(self, path: Path | None) -> None:
        replace_existing = self.password_manager_app.vault_exists
        if replace_existing and not messagebox.askyesno(
            "Восстановление",
            "Текущее хранилище будет заменено резервной копией. Продолжить?",
            parent=self,
        ):
            return
        try:
            backup_password = simpledialog.askstring(
                "Восстановление", "Мастер-пароль резервной копии", show="*", parent=self
            )
            if backup_password is None:
                return
            self.password_manager_app.restore_encrypted_backup(path, backup_password, replace_existing=replace_existing)
        except (ValidationError, VaultError) as exc:
            messagebox.showerror("Восстановление", str(exc), parent=self)
            return
        except OSError:
            messagebox.showerror("Восстановление", "Ошибка доступа к файлам хранилища", parent=self)
            return
        self.lock_now()
        messagebox.showinfo("Восстановление", "Копия восстановлена. Разблокируйте хранилище.", parent=self)

    def finish_legacy_migration(self) -> None:
        source = self._select_legacy_path()
        if source is None or not self._confirm_legacy_removal():
            return
        master = simpledialog.askstring("Миграция", "Мастер-пароль хранилища", show="*", parent=self)
        if master is None:
            return
        try:
            self.password_manager_app.finish_legacy_migration(source, master)
        except (ValidationError, VaultError) as exc:
            messagebox.showerror("Миграция", str(exc), parent=self)
            return
        except OSError:
            messagebox.showerror("Миграция", "Ошибка записи копии или удаления. Исходный файл не удалён.", parent=self)
            return
        messagebox.showinfo("Миграция", "Зашифрованная копия проверена, исходный файл удалён.", parent=self)

    def change_master_password(self) -> None:
        current = simpledialog.askstring(
            "Смена мастер-пароля", "Текущий мастер-пароль", show="*", parent=self
        )
        if current is None:
            return
        new = simpledialog.askstring(
            "Смена мастер-пароля",
            f"Новый мастер-пароль (минимум {MIN_MASTER_PASSWORD_LENGTH} символов). Лучше выбрать длинную фразу.",
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
            result = self.password_manager_app.change_master_password(current, new, repeat)
        except (ValidationError, VaultError) as exc:
            messagebox.showerror("Смена мастер-пароля", str(exc), parent=self)
            return
        except OSError:
            messagebox.showerror("Смена мастер-пароля", "Не удалось записать хранилище. Пароль не изменён.", parent=self)
            return
        if result.backup_updated:
            messagebox.showinfo(
                "Смена мастер-пароля", "Пароль и автоматическая копия обновлены. Экспортированные копии не менялись.",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "Смена мастер-пароля",
                "Пароль изменён, но автоматическую копию не удалось обновить. Если она есть, она не изменилась. "
                "Сохраните новую зашифрованную копию. Экспортированные ранее копии не менялись.",
                parent=self,
            )

    def change_theme(self) -> None:
        theme = self.change_theme_switch.get()
        try:
            self.password_manager_app.save_setting("theme", theme)
        except (OSError, ValidationError):
            messagebox.showerror("Настройки", "Не удалось сохранить оформление", parent=self)
            return
        ctk.set_appearance_mode(theme)

    def change_auto_lock(self, value: str) -> None:
        try:
            self.password_manager_app.save_setting("auto_lock_minutes", int(value))
        except (OSError, ValueError):
            self.auto_lock_combo.set(str(self.password_manager_app.settings["auto_lock_minutes"]))
            messagebox.showerror("Настройки", "Не удалось сохранить время автоблокировки", parent=self)
            return
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
        self._update_button = None
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
        # CustomTkinter schedules callbacks on both the root and its child widgets.
        # Cancel their Tcl timers; each widget's destroy still owns command cleanup.
        for job in self.tk.splitlist(self.tk.call("after", "info")):
            self.tk.call("after", "cancel", job)
        self.destroy()
