import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from models import PasswordRecord
from utils.vault_store import (
    VaultAuthenticationError,
    VaultCorruptedError,
    VaultError,
    VaultLockedError,
    VaultStore,
)

MASTER_PASSWORD = "correct horse battery staple"


def make_record(password: str = "Secret-Marker-8391") -> PasswordRecord:
    return PasswordRecord.create(
        record_name="Primary mail",
        service_name="Example Mail",
        login="person@example.test",
        password=password,
        url_link_service="https://example.test",
        note="private note",
    )


class VaultStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        # Match the store's canonical paths when injecting destination-specific failures.
        self.directory = Path(self.temp_dir.name).resolve()
        self.path = self.directory / "vault.pm2"
        self.backup = self.directory / "vault.pm2.bak"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip_and_plaintext_is_not_stored(self):
        record = make_record()
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [record])

        serialized = self.path.read_text(encoding="utf-8")
        self.assertNotIn(record.password, serialized)
        self.assertNotIn(record.login, serialized)
        store.lock()
        restored = store.unlock(MASTER_PASSWORD)

        self.assertEqual([record.to_dict()], [item.to_dict() for item in restored])

    def test_locked_store_cannot_save(self):
        store = VaultStore(self.path, self.backup)

        with self.assertRaises(VaultLockedError):
            store.save([])

    def test_wrong_password_does_not_unlock(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD)
        store.lock()

        with self.assertRaises(VaultAuthenticationError):
            store.unlock("definitely the wrong password")
        self.assertFalse(store.is_unlocked)

    def test_tampered_ciphertext_is_rejected(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [make_record()])
        store.lock()
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        ciphertext = envelope["cipher"]["ciphertext"]
        envelope["cipher"]["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
        self.path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertRaises(VaultAuthenticationError):
            store.unlock(MASTER_PASSWORD)

    def test_unsupported_kdf_parameters_are_rejected_before_derivation(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD)
        store.lock()
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        envelope["kdf"]["n"] = 2**30
        self.path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertRaises(VaultError):
            store.unlock(MASTER_PASSWORD)

    def test_invalid_envelope_types_do_not_escape_vault_error_contract(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD)
        store.lock()
        envelope = json.loads(self.path.read_bytes())
        envelope["cipher"]["nonce"] = 4
        self.path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(VaultCorruptedError):
            store.unlock(MASTER_PASSWORD)
        self.assertFalse(store.is_unlocked)

    def test_new_kdf_profile_is_stronger_but_legacy_backups_still_open(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD)
        envelope = json.loads(self.path.read_bytes())
        self.assertEqual((2**15, 8, 3), tuple(envelope["kdf"][key] for key in ("n", "r", "p")))
        legacy = VaultStore(self.directory / "old.pm2")
        with patch.object(VaultStore, "_new_kdf", return_value=envelope["kdf"] | {"p": 1}):
            legacy.create(MASTER_PASSWORD, [make_record()])
        exported = legacy.create_backup(self.directory / "old-backup.pm2")
        store.restore_backup(MASTER_PASSWORD, exported)
        self.assertEqual(1, len(VaultStore(self.path).unlock(MASTER_PASSWORD)))

    def test_save_keeps_previous_encrypted_backup(self):
        first = make_record("First-Password-44")
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [first])
        store.save([first, make_record("Second-Password-55")])

        old_store = VaultStore(self.backup)
        restored = old_store.unlock(MASTER_PASSWORD)
        self.assertEqual(1, len(restored))
        self.assertEqual(first.id, restored[0].id)

    def test_stale_session_cannot_replace_vault_or_backup_after_another_process_saves(self):
        first = make_record()
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD, [first])
        result = subprocess.run(
            [sys.executable, "-c", """
import sys
from pathlib import Path
from tests.test_vault_store import MASTER_PASSWORD, make_record
from utils.vault_store import VaultStore
store = VaultStore(Path(sys.argv[1]))
records = store.unlock(MASTER_PASSWORD)
store.save(records + [make_record()])
""", str(self.path)],
            capture_output=True, check=True, timeout=30,
        )
        self.assertEqual(0, result.returncode)
        before = (self.path.read_bytes(), self.backup.read_bytes())
        with self.assertRaisesRegex(VaultError, "другим сеансом"):
            store.save([first])
        self.assertTrue(before == (self.path.read_bytes(), self.backup.read_bytes()))
        reopened = VaultStore(self.path)
        self.assertEqual(2, len(reopened.unlock(MASTER_PASSWORD)))
        reopened.save([first])

    def test_failed_replace_preserves_working_vault(self):
        first = make_record()
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [first])

        with (
            patch("utils.vault_store.os.replace", side_effect=OSError("simulated failure")),
            self.assertRaises(OSError),
        ):
            store.save([first, make_record("Another-Secret-778")])

        restored = VaultStore(self.path).unlock(MASTER_PASSWORD)
        self.assertEqual([first.id], [item.id for item in restored])
        self.assertEqual([], list(self.directory.glob("*.tmp")))

    def test_file_lock_releases_after_abrupt_process_exit_and_is_per_vault(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD)
        ready = self.directory / "ready"
        child = subprocess.Popen(
            [sys.executable, "-c", """
import sys
import time
from pathlib import Path
from utils.vault_file_lock import vault_file_lock
with vault_file_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).touch()
    time.sleep(90)
""", str(self.path), str(ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while child.poll() is None and not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "Дочерний процесс не получил блокировку")
            with self.assertRaisesRegex(VaultError, "другим сеансом"):
                store.save([make_record()])
            self.assertFalse(self.backup.exists())
            independent = VaultStore(self.directory / "independent" / self.path.name)
            independent.create(MASTER_PASSWORD)
            independent.save([make_record()])
        finally:
            child.kill()
            child.wait(timeout=10)
        store.save([make_record()])
        self.assertEqual(1, len(VaultStore(self.path).unlock(MASTER_PASSWORD)))

    def test_change_master_password_invalidates_old_password(self):
        record = make_record()
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [record])
        store.change_master_password(MASTER_PASSWORD, "a newer and stronger passphrase", [record])
        store.lock()

        with self.assertRaises(VaultAuthenticationError):
            store.unlock(MASTER_PASSWORD)
        restored = store.unlock("a newer and stronger passphrase")
        self.assertEqual(record.id, restored[0].id)

    def test_failed_password_change_does_not_change_key_for_subsequent_crud(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD)
        original = self.path.read_bytes()
        new_password = "a newer and stronger passphrase"
        replace = os.replace

        def fail_main(source, destination):
            if destination == self.path:
                raise OSError("simulated replace failure")
            replace(source, destination)

        with patch("utils.vault_store.os.replace", side_effect=fail_main), self.assertRaises(OSError):
            store.change_master_password(MASTER_PASSWORD, new_password, [])
        self.assertTrue(original == self.path.read_bytes())
        store.save([make_record()])
        self.assertEqual(1, len(VaultStore(self.path).unlock(MASTER_PASSWORD)))
        with self.assertRaises(VaultAuthenticationError):
            VaultStore(self.path).unlock(new_password)

    def test_password_change_reports_backup_failure_after_main_commit(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD)
        records = [make_record()]
        store.save(records)
        previous_backup = self.backup.read_bytes()
        new_password = "a newer and stronger passphrase"
        replace = os.replace

        def fail_backup(source, destination):
            if destination == self.backup:
                raise OSError("simulated backup failure")
            replace(source, destination)

        with patch("utils.vault_store.os.replace", side_effect=fail_backup):
            result = store.change_master_password(MASTER_PASSWORD, new_password, records)
        self.assertFalse(result.backup_updated)
        self.assertTrue(previous_backup == self.backup.read_bytes())
        self.assertEqual(1, len(VaultStore(self.path).unlock(new_password)))
        with self.assertRaises(VaultAuthenticationError):
            VaultStore(self.path).unlock(MASTER_PASSWORD)
        self.assertEqual([], VaultStore(self.backup).unlock(MASTER_PASSWORD))
        store.save(records + [make_record()])
        self.assertEqual(2, len(VaultStore(self.path).unlock(new_password)))

    def test_restore_verifies_password_before_replacing_vault(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [make_record()])
        exported = store.create_backup(self.directory / "export.pm2")
        original = self.path.read_bytes()

        with self.assertRaises(VaultAuthenticationError):
            store.restore_backup("wrong password", exported)
        self.assertEqual(original, self.path.read_bytes())

    def test_restore_publishes_the_bytes_that_were_verified(self):
        store = VaultStore(self.path)
        first = make_record()
        store.create(MASTER_PASSWORD, [first])
        exported = store.create_backup(self.directory / "export.pm2")
        verified = exported.read_bytes()
        store.save([first, make_record()])
        previous = self.path.read_bytes()
        decrypt = store._decrypt_records

        def replace_source(envelope, key):
            records = decrypt(envelope, key)
            exported.write_bytes(b"source changed after validation")
            return records

        with patch.object(store, "_decrypt_records", side_effect=replace_source):
            store.restore_backup(MASTER_PASSWORD, exported)
        self.assertFalse(store.is_unlocked)
        self.assertTrue(verified == self.path.read_bytes())
        pre_restore = self.path.with_suffix(".pm2.pre-restore.bak")
        self.assertTrue(previous == pre_restore.read_bytes())
        self.assertEqual(2, len(VaultStore(pre_restore).unlock(MASTER_PASSWORD)))

    def test_interrupted_restore_keeps_original_and_open_session(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD, [make_record()])
        exported = store.create_backup(self.directory / "export.pm2")
        store.save([make_record(), make_record()])
        previous = self.path.read_bytes()

        with (
            patch("utils.vault_store.os.fsync", side_effect=OSError("simulated write failure")),
            self.assertRaises(OSError),
        ):
            store.restore_backup(MASTER_PASSWORD, exported)
        self.assertTrue(store.is_unlocked)
        self.assertTrue(previous == self.path.read_bytes())
        self.assertEqual(2, len(VaultStore(self.path).unlock(MASTER_PASSWORD)))
        self.assertEqual([], list(self.directory.glob("*.tmp")))

    def test_failed_backup_replacement_keeps_previous_copy(self):
        store = VaultStore(self.path)
        store.create(MASTER_PASSWORD, [make_record()])
        store.save([make_record(), make_record()])
        before = (self.path.read_bytes(), self.backup.read_bytes())
        with (
            patch("utils.vault_store.os.replace", side_effect=OSError("simulated replace failure")),
            self.assertRaises(OSError),
        ):
            store.create_backup()
        self.assertTrue(before == (self.path.read_bytes(), self.backup.read_bytes()))
        self.assertEqual(1, len(VaultStore(self.backup).unlock(MASTER_PASSWORD)))
        self.assertEqual([], list(self.directory.glob("*.tmp")))

    def test_backup_cannot_overwrite_working_vault(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD)

        with self.assertRaises(VaultError):
            store.create_backup(self.path)


if __name__ == "__main__":
    unittest.main()
