from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ProgressCallback = Callable[[int, int, str], None]


class BrowserCsvError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserCsvData:
    source_format: str
    rows: list[dict[str, str]]


NAME_KEYS = ("name", "title", "record_name", "service", "service_name", "имя", "название")
URL_KEYS = (
    "url",
    "website",
    "origin_url",
    "login_uri",
    "uri",
    "form_action_origin",
    "formactionorigin",
    "сайт",
    "адрес",
)
LOGIN_KEYS = ("username", "user", "login", "login_username", "пользователь", "логин")
PASSWORD_KEYS = ("password", "pass", "login_password", "пароль")
NOTE_KEYS = ("note", "notes", "comment", "extra", "заметка", "комментарий")
REALM_KEYS = ("http_realm", "httprealm")
OTP_KEYS = ("otp_auth", "otpauth", "totp")


def read_browser_csv(path: Path, progress_callback: ProgressCallback | None = None) -> BrowserCsvData:
    if progress_callback:
        progress_callback(0, 1, "Чтение CSV")
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise BrowserCsvError(f"Не удалось открыть CSV: {exc}") from exc
    if not raw:
        raise BrowserCsvError("CSV-файл пуст")

    text = _decode_browser_export(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:16_384], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise BrowserCsvError("В CSV отсутствует строка заголовков")
    normalized_headers = {_normalize_header(header) for header in reader.fieldnames if header}
    if not normalized_headers.intersection(PASSWORD_KEYS):
        raise BrowserCsvError(
            "Не найдена колонка password. Экспортируйте пароли из Chrome/Edge/Brave/Opera, Firefox или Safari."
        )

    source_format = _detect_source(normalized_headers)
    output: list[dict[str, str]] = []
    for raw_row in reader:
        row = {
            _normalize_header(str(key)): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        url = _first_value(row, URL_KEYS)
        realm = _first_value(row, REALM_KEYS)
        login = _first_value(row, LOGIN_KEYS)
        parsed_url = urlparse(url if "://" in url else f"https://{url}")
        fallback_name = realm or parsed_url.hostname or login or "Без названия"
        name = _first_value(row, NAME_KEYS) or fallback_name
        note = _first_value(row, NOTE_KEYS)
        otp = _first_value(row, OTP_KEYS)
        if otp:
            note = f"{note}\nOTPAuth: {otp}".strip()

        # Chromium may export Android application identifiers. Preserve them in
        # the encrypted note, but do not expose them to webbrowser.open().
        if url and parsed_url.scheme and parsed_url.scheme not in {"http", "https"}:
            note = f"{note}\nИсходный адрес: {url}".strip()
            url = ""

        output.append(
            {
                "record_name": name,
                "service_name": name,
                "login": login,
                "password": _first_value(row, PASSWORD_KEYS),
                "url_link_service": url,
                "note": note,
            }
        )

    if not output:
        raise BrowserCsvError("CSV не содержит записей")
    return BrowserCsvData(source_format=source_format, rows=output)


def _decode_browser_export(raw: bytes) -> str:
    encodings = ["utf-8-sig"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("cp1251")
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BrowserCsvError("Не удалось определить кодировку CSV")


def _normalize_header(value: str) -> str:
    return re.sub(r"[^\w]+", "_", value.strip().casefold()).strip("_")


def _first_value(row: dict[str, str], keys: tuple[str, ...]) -> str:
    return next((row[key] for key in keys if row.get(key)), "")


def _detect_source(headers: set[str]) -> str:
    if "httprealm" in headers or "timepasswordchanged" in headers:
        return "Firefox"
    if "otpauth" in headers or ("title" in headers and "notes" in headers):
        return "Safari / Apple Passwords"
    if "name" in headers and {"url", "username", "password"}.issubset(headers):
        return "Chrome / Edge / Brave / Opera"
    if "login_uri" in headers or "login_password" in headers:
        return "Bitwarden"
    return "универсальный CSV"
