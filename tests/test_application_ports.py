import unittest
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import Mock

from models import PasswordRecord
from password_safe.application import PasswordSafe
from password_safe.domain import DEFAULT_SETTINGS
from password_safe.ports import LegacyRecordsPort, SettingsPort, VaultPort


class ApplicationPortsTests(unittest.TestCase):
    def setUp(self):
        self.vault = Mock(spec=VaultPort, is_unlocked=True)
        settings = Mock(spec=SettingsPort)
        settings.load.return_value = DEFAULT_SETTINGS.copy()
        self.app = PasswordSafe(
            vault=self.vault,
            settings=settings,
            legacy=Mock(spec=LegacyRecordsPort),
            migration_backup=Path("unused.pm2"),
            csv_reader=Mock(),
            browser=Mock(),
            generator=Mock(),
        )

    def test_update_exposes_old_state_until_vault_port_commits(self):
        record = self.app.save_record("Before", "Example", "Example", "", "")

        def fail_save(candidate: Iterable[PasswordRecord]) -> None:
            self.assertEqual(["After"], [item.record_name for item in candidate])
            self.assertEqual("Before", self.app.get_record(record.id).record_name)
            raise OSError("simulated disk error")

        self.vault.save.side_effect = fail_save
        with self.assertRaises(OSError):
            self.app.update_record(
                record.id, record_name="After", service_name="Example", login="Example", password="", repeat_password="",
            )
        self.assertEqual("Before", self.app.get_record(record.id).record_name)

    def test_returned_record_cannot_modify_active_session(self):
        record = self.app.save_record("Before", "Example", "Example", "", "")
        record.record_name = "Mutated"
        self.app.get_record(record.id).record_name = "Also mutated"
        self.assertEqual("Before", self.app.get_record(record.id).record_name)
