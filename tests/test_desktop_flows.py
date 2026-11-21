import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from password_manager_app import PasswordManagerApp
from password_manager_ui import Ui
from password_safe.ports import PasswordChangeResult
from password_safe.updates import Release, UpdateChecker, UpdateError
from password_safe.version import APP_VERSION
from tests.test_vault_store import MASTER_PASSWORD, make_record
from utils.vault_store import VaultStore


@unittest.skipUnless(os.environ.get("PASSWORD_SAFE_GUI_SMOKE") == "1", "requires a desktop display")
class DesktopRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.open_browser = Mock()
        self.app = PasswordManagerApp(
            data_dir=directory, legacy_records_path=directory / "records.json", browser=self.open_browser,
        )
        backup = VaultStore(self.app.store.backup_path)
        backup.create(MASTER_PASSWORD, [make_record()])
        backup.lock()
        self.backup = backup.path
        self.original = self.backup.read_bytes()
        self.directory_entries = set(directory.iterdir())
        self.release_source = Mock()
        self.releases_url = "https://example.test/releases"
        self.ui = Ui(
            self.app,
            check_updates=UpdateChecker(APP_VERSION, self.release_source).check,
            releases_url=self.releases_url,
        )
        self.ui.withdraw()
        self.addCleanup(self.ui.on_close)

    @staticmethod
    def _buttons(widget):
        for child in widget.winfo_children():
            if "Button" in type(child).__name__:
                yield child
            yield from DesktopRecoveryTests._buttons(child)

    def _button(self, text):
        matches = [widget for widget in self._buttons(self.ui) if widget.cget("text") == text]
        self.assertEqual(1, len(matches), f"Ожидалась одна кнопка «{text}»")
        return matches[0]

    def test_restore_automatic_backup_without_existing_vault(self):
        with (
            patch("password_manager_ui.messagebox.showinfo"),
            patch("password_manager_ui.simpledialog.askstring", return_value=MASTER_PASSWORD),
        ):
            self._button("Восстановить автоматическую копию").invoke()
        self.assertTrue(self.app.vault_exists)
        self.assertTrue(self.app.is_locked)
        self._button("Разблокировать")
        self.assertTrue(self.original == self.backup.read_bytes())

    def test_wrong_password_does_not_create_working_file(self):
        with (
            patch("password_manager_ui.messagebox.showerror") as error,
            patch("password_manager_ui.filedialog.askopenfilename", return_value=str(self.backup)),
            patch("password_manager_ui.simpledialog.askstring", return_value="incorrect credential"),
        ):
            self._button("Выбрать резервную копию…").invoke()
        error.assert_called_once()
        self.assertFalse(self.app.vault_exists)
        self.assertTrue(self.original == self.backup.read_bytes())
        self.assertEqual(self.directory_entries, set(self.backup.parent.iterdir()))

    def test_cancel_selection_does_not_create_working_file(self):
        with patch("password_manager_ui.filedialog.askopenfilename", return_value=""):
            self._button("Выбрать резервную копию…").invoke()
        self.assertFalse(self.app.vault_exists)
        self.assertTrue(self.original == self.backup.read_bytes())
        self.assertEqual(self.directory_entries, set(self.backup.parent.iterdir()))

    def test_exported_backup_reopens_to_main_screen_with_correct_password(self):
        exported = self.backup.with_name("exported.pm2")
        exported.write_bytes(self.original)
        self.backup.unlink()
        self.ui.show_lock_screen()
        with (
            patch("password_manager_ui.messagebox.showinfo"),
            patch("password_manager_ui.filedialog.askopenfilename", return_value=str(exported)),
            patch("password_manager_ui.simpledialog.askstring", return_value=MASTER_PASSWORD),
        ):
            self._button("Выбрать резервную копию…").invoke()
        unlock = self._button("Разблокировать")
        self.ui.master_password_entry.insert(0, MASTER_PASSWORD)
        unlock.invoke()
        self.assertFalse(self.app.is_locked)
        self.assertEqual(1, len(self.app.get_records()))
        self.ui.lock_now()
        self._button("Разблокировать")

    def test_password_change_reports_partial_success_as_warning(self):
        with (
            patch("password_manager_ui.simpledialog.askstring", return_value="synthetic credential"),
            patch.object(self.app, "change_master_password", return_value=PasswordChangeResult(False)),
            patch("password_manager_ui.messagebox.showwarning") as warning,
            patch("password_manager_ui.messagebox.showerror") as error,
        ):
            self.ui.change_master_password()
        warning.assert_called_once()
        self.assertIn("Пароль изменён", warning.call_args.args[1])
        self.assertIn("не удалось обновить", warning.call_args.args[1])
        error.assert_not_called()

    def _open_settings(self):
        self.app.restore_encrypted_backup(None, MASTER_PASSWORD)
        self.app.unlock(MASTER_PASSWORD)
        self.ui.create_main_ui()
        self.ui.tabviews.set("Настройки")
        self.assertTrue(self.ui.title().endswith(APP_VERSION))
        return self._button("Проверить обновления")

    def _wait_for_ui(self, condition):
        deadline = time.monotonic() + 3
        while not condition():
            self.ui.update()
            self.assertLess(time.monotonic(), deadline, "Окно не показало результат проверки")
            time.sleep(0.01)

    def test_update_check_offers_a_new_release_before_opening_the_browser(self):
        button = self._open_settings()
        release_url = f"{self.releases_url}/tag/v999.0.0"
        self.release_source.return_value = Release("v999.0.0", release_url, True)
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed), patch("password_manager_ui.messagebox.askyesno", return_value=confirmed) as ask:
                button.invoke()
                self.assertEqual("disabled", button.cget("state"))
                button.invoke()
                self._wait_for_ui(lambda: ask.called)
                self.assertIn("v999.0.0", ask.call_args.args[1])
                self.assertEqual("normal", button.cget("state"))
            if confirmed:
                self.open_browser.assert_called_once_with(release_url)
            else:
                self.open_browser.assert_not_called()
        self.assertEqual(2, self.release_source.call_count)

    def test_unavailable_release_offers_to_open_releases_in_the_browser(self):
        button = self._open_settings()
        self.release_source.side_effect = UpdateError("Релиз недоступен.")
        with patch("password_manager_ui.messagebox.askyesno", return_value=True) as ask:
            button.invoke()
            self._wait_for_ui(lambda: ask.called)
            self.assertIn("Релиз недоступен", ask.call_args.args[1])
        self.open_browser.assert_called_once_with(self.releases_url)

    def test_update_check_reports_current_version(self):
        button = self._open_settings()
        self.release_source.return_value = Release(f"v{APP_VERSION}", self.releases_url, True)
        with patch("password_manager_ui.messagebox.showinfo") as info:
            button.invoke()
            self._wait_for_ui(lambda: info.called)
            self.assertIn(APP_VERSION, info.call_args.args[1])
        self.open_browser.assert_not_called()

    def test_lock_during_check_does_not_open_a_dialog_or_lose_vault_data(self):
        button = self._open_settings()
        original = self.app.store.path.read_bytes()
        finish = threading.Event()
        self.addCleanup(finish.set)

        def fetch_release():
            finish.wait(3)
            return Release("v999.0.0", self.releases_url, True)

        self.release_source.side_effect = fetch_release
        with patch("password_manager_ui.messagebox.askyesno") as ask:
            button.invoke()
            self.ui.lock_now()
            finish.set()
            self._wait_for_ui(lambda: self.ui._update_poll_job is None)
            ask.assert_not_called()
        self.assertTrue(self.app.is_locked)
        self.assertEqual(original, self.app.store.path.read_bytes())
        self.open_browser.assert_not_called()
