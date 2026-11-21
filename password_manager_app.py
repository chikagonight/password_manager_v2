"""Desktop entry point and composition root."""

from __future__ import annotations

import logging
import os
import webbrowser
from collections.abc import Callable
from pathlib import Path

from constants import APP_DATA_DIR, LEGACY_RECORDS_FILE, SETTINGS_FILE, VAULT_BACKUP_FILE, VAULT_FILE
from password_safe.application import PasswordSafe
from password_safe.ports import CsvImportData, PasswordClipboard, ProgressCallback
from password_safe.ports import ImportRecordsError as ImportRecordsError
from password_safe.ports import ValidationError as ValidationError
from utils.browser_csv import BrowserCsvError, read_browser_csv
from utils.legacy_records import LegacyJsonRecords
from utils.password_tools import PasswordGenerator
from utils.settings_tools import SettingsTools
from utils.vault_store import VaultStore


def _read_csv(path: Path, progress: ProgressCallback | None) -> CsvImportData:
    try:
        data = read_browser_csv(path, progress)
    except BrowserCsvError as exc:
        raise ImportRecordsError(str(exc)) from None
    return CsvImportData(data.source_format, data.rows)


def _open_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        raise ValidationError("Не удалось открыть браузер")


class PasswordManagerApp(PasswordSafe):
    """Build the desktop configuration; keep the original entry point importable."""

    def __init__(
        self, *, data_dir: Path = APP_DATA_DIR, legacy_records_path: Path | None = None,
        browser: Callable[[str], None] = _open_browser,
    ):
        self.data_dir = Path(data_dir)
        legacy_path = LEGACY_RECORDS_FILE if legacy_records_path is None else Path(legacy_records_path)
        candidates = (Path.cwd() / "records.json", legacy_path) if legacy_records_path is None else (legacy_path,)
        self.store = VaultStore(self.data_dir / VAULT_FILE.name, self.data_dir / VAULT_BACKUP_FILE.name)
        super().__init__(
            vault=self.store,
            settings=SettingsTools(self.data_dir / SETTINGS_FILE.name, legacy_path.with_name("settings.json")),
            legacy=LegacyJsonRecords(candidates),
            migration_backup=self.data_dir / "backups" / "legacy-migration.pm2",
            csv_reader=_read_csv,
            browser=browser,
            generator=PasswordGenerator().generate,
        )


def main() -> None:
    from tkinter import TclError, messagebox

    from password_manager_ui import Ui

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        app = PasswordManagerApp()
    except OSError:
        messagebox.showerror("passwordSafe", "Не удалось прочитать настройки. Проверьте доступ к каталогу данных.")
        return
    def clipboard_factory(window: Ui) -> PasswordClipboard:
        if os.name == "nt":
            from utils.secure_clipboard import WindowsClipboard

            try:
                return WindowsClipboard(window.winfo_id())
            except TclError:
                raise OSError("Не удалось получить дескриптор окна") from None
        from utils.tk_clipboard import TkClipboard

        return TkClipboard(window)

    Ui(app, data_dir=app.data_dir, clipboard_factory=clipboard_factory).mainloop()


if __name__ == "__main__":
    main()
