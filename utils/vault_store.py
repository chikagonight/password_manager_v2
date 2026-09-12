from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from constants import RECORDS_SCHEMA_VERSION, VAULT_FORMAT, VAULT_VERSION
from models import PasswordRecord

AAD = b"PasswordManagerV2:vault:1"
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32


class VaultError(Exception):
    """Base class for safe, user-displayable vault failures."""


class VaultLockedError(VaultError):
    pass


class VaultAuthenticationError(VaultError):
    pass


class VaultCorruptedError(VaultError):
    pass


class VaultStore:
    def __init__(self, path: Path, backup_path: Path | None = None):
        self.path = Path(path)
        self.backup_path = Path(backup_path) if backup_path else self.path.with_suffix(self.path.suffix + ".bak")
        self._key: bytearray | None = None
        self._kdf: dict[str, Any] | None = None

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def is_unlocked(self) -> bool:
        return self._key is not None

    def create(self, master_password: str, records: Iterable[PasswordRecord] = ()) -> list[PasswordRecord]:
        if self.exists:
            raise VaultError("Хранилище уже существует")
        salt = os.urandom(16)
        self._kdf = {
            "name": "scrypt",
            "salt": self._encode(salt),
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
        }
        self._key = bytearray(self._derive_key(master_password, self._kdf))
        records_list = list(records)
        self.save(records_list, create_backup=False)
        return records_list

    def unlock(self, master_password: str) -> list[PasswordRecord]:
        envelope = self._read_envelope(self.path)
        kdf_config = self._validate_envelope(envelope)
        candidate_key = self._derive_key(master_password, kdf_config)
        try:
            records = self._decrypt_records(envelope, candidate_key)
        except InvalidTag as exc:
            raise VaultAuthenticationError("Неверный мастер-пароль или хранилище повреждено") from exc
        self.lock()
        self._key = bytearray(candidate_key)
        self._kdf = kdf_config
        return records

    def lock(self) -> None:
        if self._key is not None:
            for index in range(len(self._key)):
                self._key[index] = 0
        self._key = None
        self._kdf = None

    def save(self, records: Iterable[PasswordRecord], *, create_backup: bool = True) -> None:
        if self._key is None or self._kdf is None:
            raise VaultLockedError("Хранилище заблокировано")
        payload = {
            "schema_version": RECORDS_SCHEMA_VERSION,
            "records": [record.to_dict() for record in records],
        }
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(bytes(self._key)).encrypt(nonce, plaintext, AAD)
        envelope = {
            "format": VAULT_FORMAT,
            "version": VAULT_VERSION,
            "kdf": self._kdf,
            "cipher": {
                "name": "AES-256-GCM",
                "nonce": self._encode(nonce),
                "ciphertext": self._encode(ciphertext),
            },
        }
        self._decrypt_records(envelope, bytes(self._key))
        self._atomic_write(envelope, create_backup=create_backup)

    def change_master_password(self, current_password: str, new_password: str, records: Iterable[PasswordRecord]) -> None:
        self.unlock(current_password)
        new_kdf = {
            "name": "scrypt",
            "salt": self._encode(os.urandom(16)),
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
        }
        self.lock()
        self._kdf = new_kdf
        self._key = bytearray(self._derive_key(new_password, new_kdf))
        self.save(records)
        # Recovery must not require remembering the previous master password.
        self.create_backup()

    def create_backup(self, destination: Path | None = None) -> Path:
        if not self.exists:
            raise VaultError("Хранилище ещё не создано")
        target = Path(destination) if destination else self.backup_path
        if target.resolve() == self.path.resolve():
            raise VaultError("Нельзя сохранить резервную копию поверх рабочего хранилища")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, target)
        return target

    def restore_backup(self, master_password: str, source: Path | None = None) -> None:
        backup = Path(source) if source else self.backup_path
        if not backup.is_file():
            raise VaultError("Резервная копия не найдена")
        envelope = self._read_envelope(backup)
        kdf_config = self._validate_envelope(envelope)
        candidate_key = self._derive_key(master_password, kdf_config)
        try:
            self._decrypt_records(envelope, candidate_key)
        except InvalidTag as exc:
            raise VaultAuthenticationError("Неверный мастер-пароль или резервная копия повреждена") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_file() and backup.resolve() != self.path.resolve():
            pre_restore = self.path.with_suffix(self.path.suffix + ".pre-restore.bak")
            shutil.copy2(self.path, pre_restore)
        shutil.copy2(backup, self.path)
        self.lock()

    def _atomic_write(self, envelope: dict[str, Any], *, create_backup: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(envelope, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            if create_backup and self.path.exists():
                self.create_backup()
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @classmethod
    def _read_envelope(cls, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as source:
                value = json.load(source)
        except FileNotFoundError as exc:
            raise VaultError("Хранилище не найдено") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise VaultCorruptedError("Не удалось прочитать хранилище") from exc
        if not isinstance(value, dict):
            raise VaultCorruptedError("Неверный формат хранилища")
        return value

    @staticmethod
    def _validate_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            if envelope["format"] != VAULT_FORMAT or envelope["version"] != VAULT_VERSION:
                raise VaultCorruptedError("Версия хранилища не поддерживается")
            kdf_config = envelope["kdf"]
            cipher = envelope["cipher"]
            if kdf_config["name"] != "scrypt" or cipher["name"] != "AES-256-GCM":
                raise VaultCorruptedError("Алгоритм хранилища не поддерживается")
            if (
                int(kdf_config["n"]) != SCRYPT_N
                or int(kdf_config["r"]) != SCRYPT_R
                or int(kdf_config["p"]) != SCRYPT_P
            ):
                raise VaultCorruptedError("Параметры шифрования не поддерживаются")
            return kdf_config
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultCorruptedError("В хранилище отсутствуют обязательные поля") from exc

    @classmethod
    def _derive_key(cls, password: str, config: dict[str, Any]) -> bytes:
        try:
            salt = cls._decode(config["salt"])
            kdf = Scrypt(
                salt=salt,
                length=KEY_LENGTH,
                n=int(config["n"]),
                r=int(config["r"]),
                p=int(config["p"]),
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
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, AAD)
            payload = json.loads(plaintext.decode("utf-8"))
            if payload["schema_version"] != RECORDS_SCHEMA_VERSION or not isinstance(payload["records"], list):
                raise VaultCorruptedError("Схема записей не поддерживается")
            if not all(isinstance(item, dict) for item in payload["records"]):
                raise VaultCorruptedError("Некорректная запись в хранилище")
            return [PasswordRecord.from_dict(item) for item in payload["records"]]
        except InvalidTag:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultCorruptedError("Зашифрованные данные повреждены") from exc

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.b64decode(value.encode("ascii"), validate=True)
