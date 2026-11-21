import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.app.create_vault("1234567", "1234567")
        self.assertFalse(self.app.vault_exists)

        with self.assertRaises(ValidationError):
            self.app.create_vault(MASTER_PASSWORD, "different passphrase")
        self.assertFalse(self.app.vault_exists)

        self.app.create_vault("12345678", "12345678")
        self.assertTrue(self.app.vault_exists)

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

    def test_all_record_fields_may_be_empty(self):
        self.create_vault()

        record = self.app.save_record("", "", "", "", "", "", "")

        self.assertEqual("Без названия", record.record_name)
        self.assertEqual("Без названия", record.service_name)
        self.assertEqual("", record.login)
        self.assertEqual("", record.password)

    def test_empty_name_falls_back_to_site_then_login(self):
        self.create_vault()

        site_record = self.app.save_record(
            "", "", "fallback-login", "", "", "sub.example.test/path", ""
        )
        login_record = self.app.save_record("", "Explicit service", "only-login", "", "", "", "")

        self.assertEqual("sub.example.test", site_record.record_name)
        self.assertEqual("sub.example.test", site_record.service_name)
        self.assertEqual("only-login", login_record.record_name)
        self.assertEqual("Explicit service", login_record.service_name)

    def test_url_rejects_unsafe_schemes(self):
        self.create_vault()
        for url in ("javascript:alert(1)", "data:text/plain,bad", "file:///tmp/secret", "ftp://example.test"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.app.save_record("Name", "Service", "login", "secret", "secret", url)

    def test_browser_port_receives_only_valid_http_urls(self):
        opened = []
        app = PasswordManagerApp(
            data_dir=self.directory / "data", legacy_records_path=self.legacy_path, browser=opened.append
        )
        for url in ("javascript:123", "https://[not-an-ip", "https://ok.test\\@bad.test", "https://user@ok.test"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                app.open_url(url)
        self.assertEqual([], opened)
        app.open_url("example.test:8443/path")
        self.assertEqual(["https://example.test:8443/path"], opened)

    def test_generator_uses_same_limits_for_validation_and_message(self):
        for length in (8, 128):
            self.assertEqual(length, len(self.app.password_generate(length)))
        for length in (7, 129, "not a number"):
            with self.subTest(length=length), self.assertRaisesRegex(ValidationError, "от 8 до 128"):
                self.app.password_generate(length)

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

    def test_csv_row_with_empty_cells_is_imported(self):
        self.create_vault()
        path = self.directory / "empty-values.csv"
        self._write_csv(
            path,
            [{"name": "", "username": "", "password": "", "url": "", "note": ""}],
        )

        self.assertEqual(1, self.app.import_records_from_csv(path))
        record = self.app.get_records()[0]
        self.assertEqual("Без названия", record.record_name)
        self.assertEqual("", record.login)
        self.assertEqual("", record.password)

    def test_csv_password_is_preserved_after_reopening_vault(self):
        self.create_vault()
        path = self.directory / "literal.csv"
        value = '  prefix,"line"\r\nend  '
        self._write_csv(path, [{"name": "Test", "password": value}])
        self.assertEqual(1, self.app.import_records_from_csv(path))
        self.app.lock()
        self.app.unlock(MASTER_PASSWORD)
        self.assertTrue(self.app.get_records()[0].password == value)

    def test_structurally_invalid_csv_keeps_main_and_backup_bytes(self):
        self.create_vault()
        first = self.save_record()
        files = (self.app.store.path, self.app.store.backup_path)
        initial = [path.read_bytes() for path in files]
        path = self.directory / "bad-shape.csv"
        path.write_text("url,username,password\nexample.test,user,value\nexample.test,user\n", encoding="utf-8")
        with self.assertRaises(ImportRecordsError):
            self.app.import_records_from_csv(path)
        self.assertTrue(initial == [path.read_bytes() for path in files])
        self.assertEqual([first.id], [record.id for record in self.app.get_records()])

    def test_malformed_csv_url_is_an_import_error_without_row_content(self):
        self.create_vault()
        path = self.directory / "bad-url.csv"
        row = {"url": "https://[private-marker", "password": "other-private-marker"}
        self._write_csv(path, [row])
        with self.assertRaises(ImportRecordsError) as error:
            self.app.import_records_from_csv(path)
        self.assertNotIn("private-marker", str(error.exception))
        self.assertEqual([], self.app.get_records())

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

    def test_legacy_migration_rejects_mixed_array_without_creating_a_vault(self):
        self.legacy_path.parent.mkdir(parents=True)
        self.legacy_path.write_text('[{"ID": 0, "password": ""}, 42]', encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.app.create_vault(MASTER_PASSWORD, MASTER_PASSWORD, migrate_legacy=True)
        self.assertTrue(self.legacy_path.exists())
        self.assertFalse(self.app.vault_exists)

    def test_migration_with_selected_source_can_resume_without_duplicate_records(self):
        source = self.directory / "выбранные записи.json"
        source.write_text('[{"ID": 0, "password": "", "url_link_service": "example.test"}]', encoding="utf-8")
        with (
            patch.object(self.app.store, "create_backup", side_effect=OSError),
            self.assertRaisesRegex(VaultError, "миграци"),
        ):
            self.app.create_vault(MASTER_PASSWORD, MASTER_PASSWORD, legacy_source=source)
        self.assertTrue(source.exists())
        self.assertTrue(self.app.vault_exists)
        self.app.lock()
        self.app.unlock(MASTER_PASSWORD)
        self.app.finish_legacy_migration(source, MASTER_PASSWORD)
        self.assertFalse(source.exists())
        (record,) = self.app.get_records()
        self.assertEqual("0", record.id)
        self.assertEqual("https://example.test", record.url_link_service)
        copy = VaultStore(self.app.data_dir / "backups" / "legacy-migration.pm2").unlock(MASTER_PASSWORD)
        self.assertTrue(copy == [record])

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
