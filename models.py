from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class PasswordRecord:
    id: str
    record_name: str
    service_name: str
    login: str
    password: str = field(repr=False)
    url_link_service: str = ""
    note: str = field(default="", repr=False)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        record_name: str,
        service_name: str,
        login: str,
        password: str,
        url_link_service: str = "",
        note: str = "",
    ) -> PasswordRecord:
        timestamp = utc_now()
        return cls(
            id=str(uuid4()),
            record_name=record_name.strip(),
            service_name=service_name.strip(),
            login=login.strip(),
            password=password,
            url_link_service=url_link_service.strip(),
            note=note.strip(),
            created_at=timestamp,
            updated_at=timestamp,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PasswordRecord:
        keys = ("id", "record_name", "service_name", "login", "password", "url_link_service", "note", "created_at", "updated_at")
        fields = {key: value[key] for key in keys}
        if not all(isinstance(item, str) for item in fields.values()) or not fields["id"]:
            raise ValueError("Некорректные поля записи")
        for item in fields.values():
            item.encode("utf-8")
        return cls(**fields)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

