from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from constants import RECORDS_SCHEMA_VERSION, VAULT_FORMAT, VAULT_VERSION
from models import PasswordRecord
from password_safe.ports import PasswordChangeResult
from password_safe.ports import VaultAuthenticationError as VaultAuthenticationError
from password_safe.ports import VaultConflictError as VaultConflictError
from password_safe.ports import VaultCorruptedError as VaultCorruptedError
from password_safe.ports import VaultError as VaultError
from password_safe.ports import VaultLockedError as VaultLockedError
from utils.atomic_file import atomic_write, staged_write
from utils.vault_file_lock import FileLockBusy, vault_file_lock

AAD = b"PasswordManagerV2:vault:1"
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 3
SUPPORTED_SCRYPT = {(SCRYPT_N, SCRYPT_R, 1), (SCRYPT_N, SCRYPT_R, SCRYPT_P)}
KEY_LENGTH = 32


class VaultStore:
    def __init__(self, path: Path, backup_path: Path | None = None):
        self.path = Path(path).resolve()
        self.backup_path = Path(backup_path) if backup_path else self.path.with_suffix(self.path.suffix + ".bak")
        self._key: bytearray | None = None
        self._kdf: dict[str, Any] | None = None
        self._revision: bytes | None = None

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def has_automatic_backup(self) -> bool:
        return self.backup_path.is_file()

    @property
    def is_unlocked(self) -> bool:
        return self._key is not None

    def create(self, master_password: str, records: Iterable[PasswordRecord] = ()) -> list[PasswordRecord]:
        if self.exists:
            raise VaultError("Хранилище уже существует")
        kdf = self._new_kdf()
        key = self._derive_key(master_password, kdf)
        records_list = list(records)
        self._atomic_write(self._encrypt_records(records_list, key, kdf), create_backup=False)
        self._key = bytearray(key)
        self._kdf = kdf
        return records_list

    @classmethod
    def _new_kdf(cls) -> dict[str, Any]:
        return {
            "name": "scrypt",
            "salt": cls._encode(os.urandom(16)),
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
        }

    def unlock(self, master_password: str) -> list[PasswordRecord]:
        snapshot = self._current_snapshot()
        if snapshot is None:
            raise VaultError("Хранилище не найдено")
        envelope = self._read_envelope(snapshot)
        kdf_config = self._validate_envelope(envelope)
        candidate_key = self._derive_key(master_password, kdf_config)
        try:
            records = self._decrypt_records(envelope, candidate_key)
        except InvalidTag as exc:
            raise VaultAuthenticationError("Неверный мастер-пароль или хранилище повреждено") from exc
        self.lock()
        self._key = bytearray(candidate_key)
        self._kdf = kdf_config
        self._revision = sha256(snapshot).digest()
        return records

    def lock(self) -> None:
        if self._key is not None:
            for index in range(len(self._key)):
                self._key[index] = 0
        self._key = None
        self._kdf = None
        self._revision = None

    def save(self, records: Iterable[PasswordRecord], *, create_backup: bool = True) -> None:
        if self._key is None or self._kdf is None:
            raise VaultLockedError("Хранилище заблокировано")
        envelope = self._encrypt_records(records, bytes(self._key), self._kdf)
        self._atomic_write(envelope, create_backup=create_backup)

    @classmethod
    def _encrypt_records(
        cls, records: Iterable[PasswordRecord], key: bytes, kdf: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "schema_version": RECORDS_SCHEMA_VERSION,
            "records": [record.to_dict() for record in records],
        }
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, AAD)
        envelope = {
            "format": VAULT_FORMAT,
            "version": VAULT_VERSION,
            "kdf": kdf,
            "cipher": {
                "name": "AES-256-GCM",
                "nonce": cls._encode(nonce),
                "ciphertext": cls._encode(ciphertext),
            },
        }
        cls._decrypt_records(envelope, key)
        return envelope

    def change_master_password(
        self, current_password: str, new_password: str, records: Iterable[PasswordRecord]
    ) -> PasswordChangeResult:
        if not self.is_unlocked:
            raise VaultLockedError("Хранилище заблокировано")
        snapshot = self.path.read_bytes()
        self._check_revision(snapshot)
        envelope = self._read_envelope(snapshot)
        try:
            self._decrypt_records(envelope, self._derive_key(current_password, self._validate_envelope(envelope)))
        except InvalidTag as exc:
            raise VaultAuthenticationError("Неверный текущий мастер-пароль") from exc
        kdf = self._new_kdf()
        key = self._derive_key(new_password, kdf)
        candidate = self._encrypt_records(records, key, kdf)
        with self._write_lock():
            self._check_revision(self._current_snapshot())
            committed = self._publish_envelope(candidate, None)
            revision = self._revision
            self.lock()
            self._key = bytearray(key)
            self._kdf = kdf
            self._revision = revision
            # Do not replace the previous backup until the new main file is committed.
            try:
                self._write_backup(self.backup_path, committed)
            except (OSError, VaultError):
                return PasswordChangeResult(backup_updated=False)
            return PasswordChangeResult(backup_updated=True)

    def create_backup(self, destination: Path | None = None) -> Path:
        with self._write_lock():
            return self._copy_backup(destination)

    def verify_backup(self, source: Path, master_password: str) -> list[PasswordRecord]:
        reader = VaultStore(source)
        try:
            return reader.unlock(master_password)
        finally:
            reader.lock()

    def _copy_backup(self, destination: Path | None = None) -> Path:
        snapshot = self._current_snapshot()
        if snapshot is None:
            raise VaultError("Хранилище ещё не создано")
        if self.is_unlocked:
            self._check_revision(snapshot)
        target = Path(destination) if destination else self.backup_path
        self._write_backup(target, snapshot)
        return target

    def _write_backup(self, target: Path, snapshot: bytes) -> None:
        if target.resolve() in {self.path, self.path.with_name(self.path.name + ".lock")}:
            raise VaultError("Нельзя сохранить резервную копию поверх рабочего хранилища или его блокировки")
        atomic_write(target, snapshot)

    def restore_backup(
        self, master_password: str, source: Path | None = None, *, replace_existing: bool = True,
    ) -> None:
        previous = self._current_snapshot()
        if previous is not None and not replace_existing:
            raise VaultConflictError("Рабочее хранилище уже появилось. Подтвердите замену заново.")
        if self.is_unlocked:
            self._check_revision(previous)
        snapshot = self._verified_snapshot(master_password, source)
        with self._write_lock():
            if previous != self._current_snapshot():
                raise VaultConflictError("Хранилище изменено другим сеансом; повторите восстановление")
            with staged_write(self.path, snapshot) as temporary:
                if previous is not None:
                    pre_restore = self.path.with_suffix(self.path.suffix + ".pre-restore.bak")
                    self._write_backup(pre_restore, previous)
                os.replace(temporary, self.path)
            self.lock()

    def _verified_snapshot(self, master_password: str, source: Path | None) -> bytes:
        backup = Path(source) if source else self.backup_path
        if backup.resolve() == self.path:
            raise VaultError("Выберите резервную копию, а не рабочее хранилище")
        try:
            snapshot = backup.read_bytes()
        except FileNotFoundError as exc:
            raise VaultError("Резервная копия не найдена") from exc
        envelope = self._read_envelope(snapshot)
        kdf_config = self._validate_envelope(envelope)
        candidate_key = self._derive_key(master_password, kdf_config)
        try:
            self._decrypt_records(envelope, candidate_key)
        except InvalidTag as exc:
            raise VaultAuthenticationError("Неверный мастер-пароль или резервная копия повреждена") from exc
        return snapshot

    def _atomic_write(self, envelope: dict[str, Any], *, create_backup: bool) -> None:
        with self._write_lock():
            previous = self._current_snapshot()
            self._check_revision(previous)
            self._publish_envelope(envelope, previous if create_backup else None)

    def _publish_envelope(self, envelope: dict[str, Any], previous: bytes | None) -> bytes:
        snapshot = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
        with staged_write(self.path, snapshot) as temporary:
            if previous is not None:
                self._write_backup(self.backup_path, previous)
            os.replace(temporary, self.path)
        self._revision = sha256(snapshot).digest()
        return snapshot

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        try:
            with vault_file_lock(self.path):
                yield
        except FileLockBusy as exc:
            raise VaultConflictError("Хранилище занято другим сеансом; повторите операцию") from exc

    def _current_snapshot(self) -> bytes | None:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    def _check_revision(self, snapshot: bytes | None) -> None:
        revision = sha256(snapshot).digest() if snapshot is not None else None
        if revision != self._revision:
            raise VaultConflictError("Хранилище изменено другим сеансом; заблокируйте и откройте его снова")

    @staticmethod
    def _read_envelope(snapshot: bytes) -> dict[str, Any]:
        try:
            value = json.loads(snapshot.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise VaultCorruptedError("Не удалось прочитать хранилище") from exc
        if not isinstance(value, dict):
            raise VaultCorruptedError("Неверный формат хранилища")
        return value

    @staticmethod
    def _validate_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            version = envelope["version"]
            if envelope["format"] != VAULT_FORMAT or type(version) is not int or version != VAULT_VERSION:
                raise VaultCorruptedError("Версия хранилища не поддерживается")
            kdf_config = envelope["kdf"]
            cipher = envelope["cipher"]
            if kdf_config["name"] != "scrypt" or cipher["name"] != "AES-256-GCM":
                raise VaultCorruptedError("Алгоритм хранилища не поддерживается")
            profile = tuple(kdf_config[key] for key in ("n", "r", "p"))
            if any(type(value) is not int for value in profile) or profile not in SUPPORTED_SCRYPT:
                raise VaultCorruptedError("Параметры шифрования не поддерживаются")
            return kdf_config
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultCorruptedError("В хранилище отсутствуют обязательные поля") from exc

    @classmethod
    def _derive_key(cls, password: str, config: dict[str, Any]) -> bytes:
        try:
            salt = cls._decode(config["salt"])
            if len(salt) != 16:
                raise ValueError
            kdf = Scrypt(
                salt=salt,
                length=KEY_LENGTH,
                n=config["n"],
                r=config["r"],
                p=config["p"],
            )
            return kdf.derive(password.encode("utf-8"))
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultCorruptedError("Некорректные параметры шифрования") from exc

    @classmethod
    def _decrypt_records(cls, envelope: dict[str, Any], key: bytes) -> list[PasswordRecord]:
        try:
            cipher = envelope["cipher"]
            nonce = cls._decode(cipher["nonce"])
            ciphertext = cls._decode(cipher["ciphertext"])
            if len(nonce) != 12 or len(ciphertext) < 16:
                raise ValueError
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, AAD)
            payload = json.loads(plaintext.decode("utf-8"))
            version = payload["schema_version"]
            if type(version) is not int or version != RECORDS_SCHEMA_VERSION or not isinstance(payload["records"], list):
                raise VaultCorruptedError("Схема записей не поддерживается")
            if not all(isinstance(item, dict) for item in payload["records"]):
                raise VaultCorruptedError("Некорректная запись в хранилище")
            records = [PasswordRecord.from_dict(item) for item in payload["records"]]
            if len({record.id for record in records}) != len(records):
                raise VaultCorruptedError("Идентификаторы записей повторяются")
            return records
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise VaultCorruptedError("Зашифрованные данные повреждены") from exc

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @staticmethod
    def _decode(value: object) -> bytes:
        if not isinstance(value, str):
            raise ValueError
        return base64.b64decode(value.encode("ascii"), validate=True)
