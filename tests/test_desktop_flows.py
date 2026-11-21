import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from password_manager_app import PasswordManagerApp
from password_manager_ui import Ui
from password_safe.ports import PasswordChangeResult
from tests.test_vault_store import MASTER_PASSWORD, make_record
from utils.vault_store import VaultStore


@unittest.skipUnless(os.environ.get("PASSWORD_SAFE_GUI_SMOKE") == "1", "requires a desktop display")
class DesktopRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.app = PasswordManagerApp(data_dir=directory, legacy_records_path=directory / "records.json")
        backup = VaultStore(self.app.store.backup_path)
        backup.create(MASTER_PASSWORD, [make_record()])
        backup.lock()
        self.backup = backup.path
        self.original = self.backup.read_bytes()
        self.directory_entries = set(directory.iterdir())
        self.ui = Ui(self.app)
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
