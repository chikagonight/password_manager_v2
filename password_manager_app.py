from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from constants import (
    APP_DATA_DIR,
    LEGACY_RECORDS_FILE,
    MIN_MASTER_PASSWORD_LENGTH,
    SETTINGS_FILE,
    VAULT_BACKUP_FILE,
    VAULT_FILE,
)
from models import PasswordRecord, utc_now
from utils.browser_csv import BrowserCsvError, read_browser_csv
from utils.password_tools import PasswordGenerator
from utils.settings_tools import SettingsTools
from utils.vault_store import VaultError, VaultStore

LOGGER = logging.getLogger(__name__)


class ValidationError(ValueError):
    pass


class ImportRecordsError(ValidationError):
    pass


class PasswordManagerApp:
    def __init__(
        self,
        *,
        data_dir: Path = APP_DATA_DIR,
        legacy_records_path: Path = LEGACY_RECORDS_FILE,
    ):
        self.data_dir = Path(data_dir)
        self.legacy_records_path = Path(legacy_records_path)
        self.store = VaultStore(self.data_dir / VAULT_FILE.name, self.data_dir / VAULT_BACKUP_FILE.name)
        self.settings_tools = SettingsTools(
            self.data_dir / SETTINGS_FILE.name,
            self.legacy_records_path.with_name("settings.json"),
        )
        self.password_generator = PasswordGenerator()
        self.settings = self.settings_tools.load()
        self._records: list[PasswordRecord] = []

    @property
    def is_locked(self) -> bool:
        return not self.store.is_unlocked

    @property
    def vault_exists(self) -> bool:
        return self.store.exists

    @property
    def has_legacy_records(self) -> bool:
        return self.legacy_records_path.is_file() and self.legacy_records_path.stat().st_size > 0

    def create_vault(
        self,
        master_password: str,
        repeat_password: str,
        *,
        migrate_legacy: bool = False,
    ) -> int:
        self._validate_master_password(master_password, repeat_password)
        records: list[PasswordRecord] = []
        if migrate_legacy:
            records = self._load_legacy_records()
        self._records = self.store.create(master_password, records)

        if migrate_legacy:
            # Preserve a recoverable encrypted copy before removing plaintext.
            migration_backup = self.data_dir / "backups" / "legacy-migration.pm2"
            self.store.create_backup(migration_backup)
            self.legacy_records_path.unlink()
        return len(self._records)

    def unlock(self, master_password: str) -> int:
        if not master_password:
            raise ValidationError("Введите мастер-пароль")
        self._records = self.store.unlock(master_password)
        return len(self._records)

    def lock(self) -> None:
        self.store.lock()
        for record in self._records:
            record.password = ""
        self._records.clear()

    def get_records(self, query: str = "") -> list[PasswordRecord]:
        self._require_unlocked()
        normalized = query.strip().casefold()
        if not normalized:
            return list(self._records)
        return [
            record
            for record in self._records
            if normalized
            in " ".join(
                (
                    record.record_name,
                    record.service_name,
                    record.login,
                    record.url_link_service,
                    record.note,
                )
            ).casefold()
        ]

    def get_record(self, record_id: str) -> PasswordRecord:
        self._require_unlocked()
        for record in self._records:
            if record.id == str(record_id):
                return record
        raise ValidationError("Запись не найдена")

    def save_record(
        self,
        record_name: str,
        service_name: str,
        login: str,
        password: str,
        repeat_password: str,
        url_link_service: str = "",
        note: str = "",
    ) -> PasswordRecord:
        self._require_unlocked()
        values = self._validate_record_fields(
            record_name,
            service_name,
            login,
            password,
            repeat_password,
            url_link_service,
        )
        record = PasswordRecord.create(
            record_name=values[0],
            service_name=values[1],
            login=values[2],
            password=password,
            url_link_service=values[3],
            note=note,
        )
        self._records.insert(0, record)
        try:
            self.store.save(self._records)
        except Exception:
            self._records.remove(record)
            raise
        return record

    def update_record(
        self,
        record_id: str,
        *,
        record_name: str,
        service_name: str,
        login: str,
        password: str,
        repeat_password: str,
        url_link_service: str = "",
        note: str = "",
    ) -> PasswordRecord:
        record = self.get_record(record_id)
        values = self._validate_record_fields(
            record_name,
            service_name,
            login,
            password,
            repeat_password,
            url_link_service,
        )
        previous = record.to_dict()
        record.record_name, record.service_name, record.login, record.url_link_service = values
        record.password = password
        record.note = note.strip()
        record.updated_at = utc_now()
        try:
            self.store.save(self._records)
        except Exception:
            restored = PasswordRecord.from_dict(previous)
            index = self._records.index(record)
            self._records[index] = restored
            raise
        return record

    def delete_record(self, record_id: str) -> bool:
        record = self.get_record(record_id)
        index = self._records.index(record)
        removed = self._records.pop(index)
        try:
            self.store.save(self._records)
        except Exception:
            self._records.insert(index, removed)
            raise
        removed.password = ""
        return True

    def password_generate(self, length_password: int | str) -> str:
        generated = self.password_generator.generate(length_password)
        if not generated:
            raise ValidationError("Длина генерируемого пароля должна быть от 12 до 128 символов")
        LOGGER.info("Сгенерирован пароль длиной %s символов", len(generated))
        return generated

    def import_records_from_csv(
        self,
        path_to_file: Path | str,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> int:
        self._require_unlocked()
        path = Path(path_to_file)
        try:
            csv_data = read_browser_csv(path, progress_callback)
        except BrowserCsvError as exc:
            raise ImportRecordsError(str(exc)) from exc

        rows = csv_data.rows
        total = len(rows)
        if progress_callback:
            progress_callback(0, total, f"Проверка: {csv_data.source_format}")

        imported: list[PasswordRecord] = []
        errors: list[str] = []
        progress_step = max(1, total // 100)
        for number, row in enumerate(rows, start=1):
            name = row["record_name"]
            service = row["service_name"]
            login = row["login"]
            password = row["password"]
            url = row["url_link_service"]
            note = row["note"]
            try:
                values = self._validate_record_fields(name, service, login, password, password, url)
            except ValidationError as exc:
                errors.append(f"строка {number + 1}: {exc}")
                continue
            imported.append(
                PasswordRecord.create(
                    record_name=values[0],
                    service_name=values[1],
                    login=values[2],
                    password=password,
                    url_link_service=values[3],
                    note=note,
                )
            )
            if progress_callback and (number == total or number % progress_step == 0):
                progress_callback(number, total, f"Проверка: {csv_data.source_format}")
        if errors:
            preview = "; ".join(errors[:5])
            suffix = f"; ещё ошибок: {len(errors) - 5}" if len(errors) > 5 else ""
            raise ImportRecordsError(f"Импорт отменён: {preview}{suffix}")

        if progress_callback:
            progress_callback(total, total, "Шифрование и сохранение")
        self._records = imported + self._records
        try:
            self.store.save(self._records)
        except Exception:
            del self._records[: len(imported)]
            raise
        return len(imported)

    def export_encrypted_backup(self, destination: Path | str) -> Path:
        self._require_unlocked()
        return self.store.create_backup(Path(destination))

    def restore_encrypted_backup(self, source: Path | str, master_password: str) -> None:
        if not master_password:
            raise ValidationError("Введите мастер-пароль резервной копии")
        self.store.restore_backup(master_password, Path(source))
        self._records.clear()

    def change_master_password(self, current_password: str, new_password: str, repeat_password: str) -> None:
        self._require_unlocked()
        self._validate_master_password(new_password, repeat_password)
        self.store.change_master_password(current_password, new_password, self._records)

    def save_setting(self, key: str, value: object) -> None:
        self.settings_tools.save(key, self.settings, value)

    def _load_legacy_records(self) -> list[PasswordRecord]:
        try:
            with self.legacy_records_path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("Старый records.json повреждён; миграция отменена") from exc
        if not isinstance(payload, list):
            raise ValidationError("Старый records.json имеет неверный формат")
        records = [PasswordRecord.from_dict(item) for item in payload if isinstance(item, dict)]
        for record in records:
            self._validate_record_fields(
                record.record_name,
                record.service_name,
                record.login,
                record.password,
                record.password,
                record.url_link_service,
            )
        return records

    @staticmethod
    def _validate_master_password(password: str, repeat_password: str) -> None:
        if password != repeat_password:
            raise ValidationError("Мастер-пароли не совпадают")
        if len(password) < MIN_MASTER_PASSWORD_LENGTH:
            raise ValidationError(f"Мастер-пароль должен содержать не менее {MIN_MASTER_PASSWORD_LENGTH} символов")

    @staticmethod
    def _validate_record_fields(
        record_name: str,
        service_name: str,
        login: str,
        password: str,
        repeat_password: str,
        url_link_service: str,
    ) -> tuple[str, str, str, str]:
        record_name = record_name.strip()
        service_name = service_name.strip()
        login = login.strip()
        url_link_service = PasswordManagerApp._normalize_web_url(url_link_service)
        if password != repeat_password:
            raise ValidationError("Пароли не совпадают")
        site_name = urlparse(url_link_service).hostname if url_link_service else ""
        record_name = record_name or site_name or login or "Без названия"
        service_name = service_name or record_name
        return record_name, service_name, login, url_link_service

    @staticmethod
    def _normalize_web_url(value: str) -> str:
        url = value.strip()
        if not url:
            return ""

        lower_url = url.casefold()
        has_supported_scheme = lower_url.startswith(("http://", "https://"))
        host_with_port = re.match(r"^[^/\s:]+(?::\d+)(?:/|$)", url) is not None
        scheme = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url)
        if scheme and not has_supported_scheme and not host_with_port:
            raise ValidationError("Допустимы только ссылки HTTP или HTTPS")

        if url.startswith("//"):
            url = f"https:{url}"
        elif not has_supported_scheme:
            url = f"https://{url}"

        parsed = urlparse(url)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ValidationError("В URL указан некорректный порт") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValidationError("Укажите корректный адрес сайта")
        if any(character.isspace() for character in parsed.hostname):
            raise ValidationError("Адрес сайта не должен содержать пробелы")
        if parsed_port is not None and not 1 <= parsed_port <= 65_535:
            raise ValidationError("В URL указан некорректный порт")
        return url

    def _require_unlocked(self) -> None:
        if self.is_locked:
            raise VaultError("Хранилище заблокировано")


def main() -> None:
    from password_manager_ui import Ui

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = Ui(PasswordManagerApp())
    app.mainloop()


if __name__ == "__main__":
    main()
