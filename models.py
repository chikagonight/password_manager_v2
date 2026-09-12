from __future__ import annotations

from dataclasses import asdict, dataclass
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
    password: str
    url_link_service: str = ""
    note: str = ""
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
        record_id = str(value.get("id") or value.get("ID") or uuid4())
        created_at = str(value.get("created_at") or utc_now())
        return cls(
            id=record_id,
            record_name=str(value.get("record_name", "")).strip(),
            service_name=str(value.get("service_name", "")).strip(),
            login=str(value.get("login", "")).strip(),
            password=str(value.get("password", "")),
            url_link_service=str(value.get("url_link_service", "")).strip(),
            note=str(value.get("note", "")).strip(),
            created_at=created_at,
            updated_at=str(value.get("updated_at") or created_at),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

