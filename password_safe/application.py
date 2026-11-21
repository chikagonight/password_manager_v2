"""Use cases: own session state and coordinate the outbound ports."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from models import PasswordRecord, utc_now
from password_safe.domain import (
    MAX_GENERATED_PASSWORD_LENGTH,
    MIN_GENERATED_PASSWORD_LENGTH,
    ValidationError,
    normalize_settings,
    normalize_web_url,
    record_fields,
    validate_master_password,
)
from password_safe.ports import (
    CsvImportData,
    ImportRecordsError,
    LegacyRecordsPort,
    LegacySnapshot,
    MigrationIncomplete,
    PasswordChangeResult,
    ProgressCallback,
    SettingsPort,
    VaultError,
    VaultLockedError,
    VaultPort,
)


class PasswordSafe:
    def __init__(
        self, *, vault: VaultPort, settings: SettingsPort, legacy: LegacyRecordsPort, migration_backup: Path,
        csv_reader: Callable[[Path, ProgressCallback | None], CsvImportData],
        browser: Callable[[str], None], generator: Callable[[int | str], str | None],
    ):
        self._vault = vault
        self._settings = settings
        self._legacy = legacy
        self._migration_backup = migration_backup
        self._read_csv = csv_reader
        self._browser = browser
        self._generate = generator
        self.settings = settings.load()
        self._records: list[PasswordRecord] = []

    @property
    def is_locked(self) -> bool:
        return not self._vault.is_unlocked

    @property
    def vault_exists(self) -> bool:
        return self._vault.exists

    @property
    def has_automatic_backup(self) -> bool:
        return self._vault.has_automatic_backup

    @property
    def suggested_legacy_source(self) -> Path | None:
        return self._legacy.suggested_source()

    @property
    def has_legacy_records(self) -> bool:
        return self.suggested_legacy_source is not None

    def create_vault(
        self, master_password: str, repeat_password: str, *, migrate_legacy: bool = False,
        legacy_source: Path | None = None,
    ) -> int:
        validate_master_password(master_password, repeat_password)
        if migrate_legacy and legacy_source is None:
            legacy_source = self.suggested_legacy_source
            if legacy_source is None:
                raise ValidationError("Файл старых записей не найден")
        snapshot = self._read_legacy(legacy_source) if legacy_source is not None else None
        self._records = self._vault.create(master_password, snapshot.records if snapshot else ())
        if snapshot is not None:
            try:
                self._finish_migration(snapshot, master_password)
            except (VaultError, OSError, ValidationError) as exc:
                raise MigrationIncomplete(
                    "Хранилище создано, но миграция не завершена. Исходный файл сохранён. "
                    "До редактирования записей выберите «Завершить миграцию» в настройках."
                ) from exc
        return len(self._records)

    def finish_legacy_migration(self, source: Path, master_password: str) -> None:
        self._require_unlocked()
        self._finish_migration(self._read_legacy(source), master_password)

    def _read_legacy(self, source: Path) -> LegacySnapshot:
        snapshot = self._legacy.load(source)
        normalized = []
        for number, record in enumerate(snapshot.records, start=1):
            try:
                name, service, login, url = record_fields(
                    record.record_name, record.service_name, record.login, record.password, record.password,
                    record.url_link_service,
                )
            except ValidationError as exc:
                raise ValidationError(f"Запись №{number}: {exc}; миграция отменена") from None
            normalized.append(replace(record, record_name=name, service_name=service, login=login, url_link_service=url))
        return replace(snapshot, records=tuple(normalized))

    def _finish_migration(self, snapshot: LegacySnapshot, master_password: str) -> None:
        # Missing timestamps in the old format are generated when it is read.
        def without_timestamps(records):
            return [replace(record, created_at="", updated_at="") for record in records]

        if without_timestamps(snapshot.records) != without_timestamps(self._records):
            raise ValidationError("Старые записи не совпадают с хранилищем. Исходный файл не удалён.")
        copy = self._vault.create_backup(self._migration_backup)
        if self._vault.verify_backup(copy, master_password) != self._records:
            raise VaultError("Данные резервной копии не совпадают с хранилищем. Исходный файл не удалён.")
        self._legacy.remove(snapshot)

    def unlock(self, master_password: str) -> int:
        if not master_password:
            raise ValidationError("Введите мастер-пароль")
        self._records = self._vault.unlock(master_password)
        return len(self._records)

    def lock(self) -> None:
        self._vault.lock()
        self._clear_records()

    def _clear_records(self) -> None:
        for record in self._records:
            record.password = record.note = ""
        self._records.clear()

    def get_records(self, query: str = "") -> list[PasswordRecord]:
        self._require_unlocked()
        normalized = query.strip().casefold()
        return [
            replace(record) for record in self._records
            if not normalized or normalized in " ".join((record.record_name, record.service_name, record.login,
                                                          record.url_link_service, record.note)).casefold()
        ]

    def _find_record(self, record_id: str) -> PasswordRecord:
        self._require_unlocked()
        for record in self._records:
            if record.id == str(record_id):
                return record
        raise ValidationError("Запись не найдена")

    def get_record(self, record_id: str) -> PasswordRecord:
        return replace(self._find_record(record_id))

    def save_record(
        self, record_name: str, service_name: str, login: str, password: str, repeat_password: str,
        url_link_service: str = "", note: str = "",
    ) -> PasswordRecord:
        self._require_unlocked()
        name, service, user, url = record_fields(
            record_name, service_name, login, password, repeat_password, url_link_service
        )
        record = PasswordRecord.create(
            record_name=name, service_name=service, login=user, password=password, url_link_service=url, note=note,
        )
        self._commit([record, *self._records])
        return replace(record)

    def update_record(
        self, record_id: str, *, record_name: str, service_name: str, login: str, password: str, repeat_password: str,
        url_link_service: str = "", note: str = "",
    ) -> PasswordRecord:
        previous = self._find_record(record_id)
        name, service, user, url = record_fields(
            record_name, service_name, login, password, repeat_password, url_link_service
        )
        record = replace(
            previous, record_name=name, service_name=service, login=user, password=password, url_link_service=url,
            note=note.strip(), updated_at=utc_now(),
        )
        self._commit([record if item is previous else item for item in self._records])
        return replace(record)

    def delete_record(self, record_id: str) -> bool:
        removed = self._find_record(record_id)
        self._commit([record for record in self._records if record is not removed])
        return True

    def _commit(self, candidate: list[PasswordRecord]) -> None:
        self._vault.save(candidate)
        self._records = candidate

    def password_generate(self, length_password: int | str) -> str:
        generated = self._generate(length_password)
        if not generated:
            raise ValidationError(
                f"Длина генерируемого пароля должна быть от {MIN_GENERATED_PASSWORD_LENGTH} "
                f"до {MAX_GENERATED_PASSWORD_LENGTH} символов"
            )
        return generated

    def import_records_from_csv(
        self, path_to_file: Path | str, progress_callback: ProgressCallback | None = None,
    ) -> int:
        self._require_unlocked()
        csv_data = self._read_csv(Path(path_to_file), progress_callback)
        total = len(csv_data.rows)
        phase = f"Проверка: {csv_data.source_format}"
        if progress_callback:
            progress_callback(0, total, phase)
        imported: list[PasswordRecord] = []
        progress_step = max(1, total // 100)
        for number, row in enumerate(csv_data.rows, start=1):
            password = row["password"]
            try:
                name, service, login, url = record_fields(
                    row["record_name"], row["service_name"], row["login"], password, password, row["url_link_service"],
                )
            except ValidationError as exc:
                raise ImportRecordsError(f"Импорт отменён: запись №{number}: {exc}") from None
            imported.append(PasswordRecord.create(
                record_name=name, service_name=service, login=login, password=password, url_link_service=url,
                note=row["note"],
            ))
            if progress_callback and (number == total or number % progress_step == 0):
                progress_callback(number, total, phase)
        if progress_callback:
            progress_callback(total, total, "Шифрование и сохранение")
        self._commit([*imported, *self._records])
        return len(imported)

    def export_encrypted_backup(self, destination: Path | str) -> Path:
        self._require_unlocked()
        return self._vault.create_backup(Path(destination))

    def restore_encrypted_backup(
        self, source: Path | str | None, master_password: str, *, replace_existing: bool = True,
    ) -> None:
        if not master_password:
            raise ValidationError("Введите мастер-пароль резервной копии")
        self._vault.restore_backup(
            master_password, Path(source) if source is not None else None, replace_existing=replace_existing,
        )
        self._clear_records()

    def change_master_password(
        self, current_password: str, new_password: str, repeat_password: str,
    ) -> PasswordChangeResult:
        self._require_unlocked()
        validate_master_password(new_password, repeat_password)
        return self._vault.change_master_password(current_password, new_password, self._records)

    def save_setting(self, key: str, value: object) -> None:
        if key not in self.settings:
            raise ValidationError("Неизвестная настройка")
        settings = normalize_settings(self.settings | {key: value})
        if type(value) is not type(settings[key]) or value != settings[key]:
            raise ValidationError("Недопустимое значение настройки")
        self._settings.save_all(settings)
        self.settings = settings

    def open_url(self, value: str) -> None:
        url = normalize_web_url(value)
        if url:
            self._browser(url)

    def _require_unlocked(self) -> None:
        if self.is_locked:
            raise VaultLockedError("Хранилище заблокировано")
