import csv
import json
import tempfile
import unittest
from pathlib import Path

from password_manager_app import ImportRecordsError, PasswordManagerApp, ValidationError
from utils.vault_store import VaultAuthenticationError, VaultError, VaultStore

MASTER_PASSWORD = "correct horse battery staple"


class PasswordManagerAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.legacy_path = self.directory / "legacy" / "records.json"
        self.app = PasswordManagerApp(data_dir=self.directory / "data", legacy_records_path=self.legacy_path)

    def tearDown(self):
        self.app.lock()
        self.temp_dir.cleanup()

    def create_vault(self):
        self.app.create_vault(MASTER_PASSWORD, MASTER_PASSWORD)

    def save_record(self, *, password: str = "entry-secret-123"):
        return self.app.save_record(
            "Mail account",
            "Example Mail",
            "person@example.test",
            password,
            password,
            "https://example.test",
            "work",
        )

    def test_master_password_validation_happens_before_vault_creation(self):
        with self.assertRaises(ValidationError):
            self.app.create_vault("too short", "too short")
        self.assertFalse(self.app.vault_exists)

        with self.assertRaises(ValidationError):
            self.app.create_vault(MASTER_PASSWORD, "different passphrase")
        self.assertFalse(self.app.vault_exists)

    def test_crud_round_trip(self):
        self.create_vault()
        record = self.save_record()
        self.assertEqual(record.id, self.app.get_record(record.id).id)

        updated = self.app.update_record(
            record.id,
            record_name="Updated mail",
            service_name="Example Mail",
            login="new@example.test",
            password="new-entry-secret-321",
            repeat_password="new-entry-secret-321",
            url_link_service="https://mail.example.test",
            note="updated",
        )
        self.assertEqual("Updated mail", updated.record_name)
        self.assertTrue(self.app.delete_record(record.id))
        self.assertEqual([], self.app.get_records())

    def test_invalid_record_does_not_clear_existing_records(self):
        self.create_vault()
        original = self.save_record()

        with self.assertRaises(ValidationError):
            self.app.save_record("", "Service", "login", "one", "two")
        self.assertEqual([original.id], [item.id for item in self.app.get_records()])

    def test_url_rejects_unsafe_schemes(self):
        self.create_vault()
        for url in ("javascript:alert(1)", "data:text/plain,bad", "file:///tmp/secret", "ftp://example.test"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.app.save_record("Name", "Service", "login", "secret", "secret", url)

    def test_url_without_scheme_is_normalized_to_https(self):
        self.create_vault()

        record = self.app.save_record(
            "Name",
            "Service",
            "login",
            "secret",
            "secret",
            "example.test/account",
        )

        self.assertEqual("https://example.test/account", record.url_link_service)

    def test_search_does_not_match_password_contents(self):
        self.create_vault()
        self.save_record(password="uniquely-secret-search-marker")

        self.assertEqual(1, len(self.app.get_records("example mail")))
        self.assertEqual([], self.app.get_records("uniquely-secret-search-marker"))

    def test_crud_is_rejected_while_locked(self):
        self.create_vault()
        self.app.lock()

        with self.assertRaises(VaultError):
            self.app.get_records()

    def test_csv_import_is_transactional(self):
        self.create_vault()
        progress_events: list[tuple[int, int, str]] = []
        valid_csv = self.directory / "valid.csv"
        self._write_csv(
            valid_csv,
            [
                {"name": "One", "username": "one", "password": "secret-1", "url": "https://one.test", "note": ""},
                {"name": "Two", "username": "two", "password": "secret-2", "url": "https://two.test", "note": ""},
            ],
        )
        self.assertEqual(
            2,
            self.app.import_records_from_csv(
                valid_csv,
                lambda current, total, phase: progress_events.append((current, total, phase)),
            ),
        )
        self.assertTrue(any("Chrome / Edge / Brave / Opera" in event[2] for event in progress_events))
        self.assertEqual("Шифрование и сохранение", progress_events[-1][2])
        before = [record.id for record in self.app.get_records()]

        invalid_csv = self.directory / "invalid.csv"
        self._write_csv(
            invalid_csv,
            [
                {"name": "Three", "username": "three", "password": "secret-3", "url": "https://three.test", "note": ""},
                {"name": "Broken", "username": "", "password": "", "url": "javascript:bad", "note": ""},
            ],
        )
        with self.assertRaises(ImportRecordsError):
            self.app.import_records_from_csv(invalid_csv)
        self.assertEqual(before, [record.id for record in self.app.get_records()])

    def test_legacy_migration_creates_encrypted_backup_then_removes_plaintext(self):
        self.legacy_path.parent.mkdir(parents=True)
        legacy_password = "Legacy-Plaintext-Marker-831"
        self.legacy_path.write_text(
            json.dumps(
                [
                    {
                        "ID": 7,
                        "record_name": "Legacy",
                        "service_name": "Old Service",
                        "login": "old-user",
                        "password": legacy_password,
                        "url_link_service": "https://old.example.test",
                        "note": "old note",
                    }
                ]
            ),
            encoding="utf-8",
        )

        migrated = self.app.create_vault(MASTER_PASSWORD, MASTER_PASSWORD, migrate_legacy=True)

        self.assertEqual(1, migrated)
        self.assertFalse(self.legacy_path.exists())
        backup = self.app.data_dir / "backups" / "legacy-migration.pm2"
        self.assertTrue(backup.is_file())
        self.assertNotIn(legacy_password, backup.read_text(encoding="utf-8"))

    def test_export_restore_and_unlock(self):
        self.create_vault()
        first = self.save_record()
        export = self.directory / "export.pm2"
        self.app.export_encrypted_backup(export)
        self.save_record(password="second-record-secret")

        self.app.restore_encrypted_backup(export, MASTER_PASSWORD)
        self.assertTrue(self.app.is_locked)
        pre_restore = self.app.store.path.with_suffix(self.app.store.path.suffix + ".pre-restore.bak")
        self.assertEqual(2, len(VaultStore(pre_restore).unlock(MASTER_PASSWORD)))
        self.app.unlock(MASTER_PASSWORD)
        self.assertEqual([first.id], [record.id for record in self.app.get_records()])

    def test_change_master_password(self):
        self.create_vault()
        self.save_record()
        new_password = "a brand new master passphrase"
        self.app.change_master_password(MASTER_PASSWORD, new_password, new_password)
        self.app.lock()

        with self.assertRaises(VaultAuthenticationError):
            self.app.unlock(MASTER_PASSWORD)
        self.app.unlock(new_password)
        self.assertEqual(1, len(self.app.get_records()))
        self.assertEqual(1, len(VaultStore(self.app.store.backup_path).unlock(new_password)))

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["name", "username", "password", "url", "note"])
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
