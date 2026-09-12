import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import PasswordRecord
from utils.vault_store import (
    VaultAuthenticationError,
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
        self.directory = Path(self.temp_dir.name)
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

    def test_save_keeps_previous_encrypted_backup(self):
        first = make_record("First-Password-44")
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [first])
        store.save([first, make_record("Second-Password-55")])

        old_store = VaultStore(self.backup)
        restored = old_store.unlock(MASTER_PASSWORD)
        self.assertEqual(1, len(restored))
        self.assertEqual(first.id, restored[0].id)

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

    def test_restore_verifies_password_before_replacing_vault(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD, [make_record()])
        exported = store.create_backup(self.directory / "export.pm2")
        original = self.path.read_bytes()

        with self.assertRaises(VaultAuthenticationError):
            store.restore_backup("wrong password", exported)
        self.assertEqual(original, self.path.read_bytes())

    def test_backup_cannot_overwrite_working_vault(self):
        store = VaultStore(self.path, self.backup)
        store.create(MASTER_PASSWORD)

        with self.assertRaises(VaultError):
            store.create_backup(self.path)


if __name__ == "__main__":
    unittest.main()
