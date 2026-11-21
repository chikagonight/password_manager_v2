"""Contracts shared by the use cases and their adapters."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from models import PasswordRecord
from password_safe.domain import ValidationError as ValidationError

type ProgressCallback = Callable[[int, int, str], None]


class ImportRecordsError(ValidationError):
    pass


class VaultError(Exception):
    """Safe, user-displayable vault failure."""


class VaultLockedError(VaultError):
    pass


class VaultConflictError(VaultError):
    pass


class VaultAuthenticationError(VaultError):
    pass


class VaultCorruptedError(VaultError):
    pass


class MigrationIncomplete(VaultError):
    pass


@dataclass(frozen=True, slots=True)
class PasswordChangeResult:
    backup_updated: bool


@dataclass(frozen=True, slots=True)
class CsvImportData:
    source_format: str
    rows: list[dict[str, str]] = field(repr=False)


@dataclass(frozen=True, slots=True)
class LegacySnapshot:
    source: Path
    revision: bytes = field(repr=False)
    records: tuple[PasswordRecord, ...] = field(repr=False)


class LegacyRecordsPort(Protocol):
    def suggested_source(self) -> Path | None: ...
    def load(self, source: Path) -> LegacySnapshot: ...
    def remove(self, snapshot: LegacySnapshot) -> None: ...


class VaultPort(Protocol):
    @property
    def exists(self) -> bool: ...
    @property
    def is_unlocked(self) -> bool: ...
    @property
    def has_automatic_backup(self) -> bool: ...
    def create(self, master_password: str, records: Iterable[PasswordRecord] = ()) -> list[PasswordRecord]: ...
    def unlock(self, master_password: str) -> list[PasswordRecord]: ...
    def lock(self) -> None: ...
    def save(self, records: Iterable[PasswordRecord]) -> None: ...
    def create_backup(self, destination: Path | None = None) -> Path: ...
    def verify_backup(self, source: Path, master_password: str) -> list[PasswordRecord]: ...
    def restore_backup(
        self, master_password: str, source: Path | None = None, *, replace_existing: bool = True,
    ) -> None: ...
    def change_master_password(
        self, current_password: str, new_password: str, records: Iterable[PasswordRecord]
    ) -> PasswordChangeResult: ...


class SettingsPort(Protocol):
    def load(self) -> dict[str, str | int]: ...
    def save_all(self, settings: dict[str, str | int]) -> None: ...


class PasswordClipboard(Protocol):
    def copy_password(self, value: str) -> None: ...
    def clear_password(self) -> None: ...
