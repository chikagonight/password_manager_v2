"""Read and retire explicit plaintext exports from the original app."""

import json
import stat
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from models import PasswordRecord, utc_now
from password_safe.ports import LegacySnapshot, ValidationError

TEXT_FIELDS = ("record_name", "service_name", "login", "password", "url_link_service", "note", "created_at", "updated_at")


class LegacyJsonRecords:
    def __init__(self, candidates: Iterable[Path]):
        self._candidates = tuple(candidates)

    def suggested_source(self) -> Path | None:
        for path in self._candidates:
            try:
                metadata = path.stat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(metadata.st_mode) and metadata.st_size:
                return path
        return None

    def load(self, source: Path) -> LegacySnapshot:
        if source.is_symlink():
            raise ValidationError("Выберите сам файл старых записей, а не ссылку на него")
        source = source.absolute()
        try:
            raw = source.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=self._unique_keys)
        except (OSError, ValueError, RecursionError):
            raise ValidationError("Не удалось прочитать старые записи; миграция отменена") from None
        if not isinstance(payload, list):
            raise ValidationError("Файл старых записей должен содержать массив")
        revision = sha256(raw).digest()
        records = []
        ids = set()
        timestamp = utc_now()
        for number, item in enumerate(payload, start=1):
            try:
                if not isinstance(item, dict) or set(item) - {*TEXT_FIELDS, "id", "ID"} or "password" not in item:
                    raise ValueError
                text_fields = {key: item.get(key, "") for key in TEXT_FIELDS}
                for value in text_fields.values():
                    if not isinstance(value, str):
                        raise ValueError
                    value.encode("utf-8")
                if "id" in item and "ID" in item:
                    raise ValueError
                if "id" in item or "ID" in item:
                    raw_id = item.get("id", item.get("ID"))
                    if not ((type(raw_id) is int and raw_id >= 0) or (isinstance(raw_id, str) and raw_id.strip())):
                        raise ValueError
                    record_id = str(raw_id)
                    record_id.encode("utf-8")
                else:
                    record_id = str(uuid5(NAMESPACE_URL, f"passwordSafe:legacy:{revision.hex()}:{number}"))
                if record_id in ids:
                    raise ValueError
                text_fields["created_at"] = text_fields["created_at"] or timestamp
                text_fields["updated_at"] = text_fields["updated_at"] or text_fields["created_at"]
                records.append(PasswordRecord(id=record_id, **text_fields))
                ids.add(record_id)
            except ValueError:
                raise ValidationError(f"Некорректная запись старого файла №{number}; миграция отменена") from None
        return LegacySnapshot(source, revision, tuple(records))

    def remove(self, snapshot: LegacySnapshot) -> None:
        source = snapshot.source
        if source.is_symlink() or sha256(source.read_bytes()).digest() != snapshot.revision:
            raise ValidationError("После чтения файл старых записей изменился; он не удалён")
        source.unlink()

    @staticmethod
    def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        values = dict(pairs)
        if len(values) != len(pairs):
            raise ValueError
        return values
