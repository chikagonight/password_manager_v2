import tempfile
import unittest
from pathlib import Path

from constants import APP_NAME, LEGACY_APP_NAME, select_windows_data_dir


class DataDirectoryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_new_name_is_used_for_a_fresh_install(self):
        self.assertEqual(self.base / APP_NAME, select_windows_data_dir(self.base))

    def test_existing_legacy_vault_remains_available(self):
        legacy = self.base / LEGACY_APP_NAME
        legacy.mkdir()
        (legacy / "vault.pm2").write_text("encrypted", encoding="utf-8")

        self.assertEqual(legacy, select_windows_data_dir(self.base))

    def test_new_vault_takes_precedence_when_both_exist(self):
        for name in (APP_NAME, LEGACY_APP_NAME):
            directory = self.base / name
            directory.mkdir()
            (directory / "vault.pm2").write_text("encrypted", encoding="utf-8")

        self.assertEqual(self.base / APP_NAME, select_windows_data_dir(self.base))


if __name__ == "__main__":
    unittest.main()
