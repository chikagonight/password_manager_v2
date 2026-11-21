from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from password_safe.domain import ValidationError, normalize_web_url

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
    except OSError:
        raise BrowserCsvError("Не удалось открыть CSV. Проверьте доступ к файлу.") from None
    if not raw:
        raise BrowserCsvError("CSV-файл пуст")

    text = _decode_browser_export(raw)
    try:
        return _parse_browser_export(text)
    except csv.Error:
        raise BrowserCsvError("Нарушена структура CSV: проверьте кавычки и разделители") from None


def _parse_browser_export(text: str) -> BrowserCsvData:
    try:
        dialect = csv.Sniffer().sniff(text[:16_384], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(
        io.StringIO(text, newline=""), dialect=dialect, doublequote=True, skipinitialspace=False, strict=True
    )
    if not reader.fieldnames:
        raise BrowserCsvError("В CSV отсутствует строка заголовков")
    headers = [_normalize_header(header) for header in reader.fieldnames]
    normalized_headers = set(headers)
    if "" in normalized_headers or len(normalized_headers) != len(headers):
        raise BrowserCsvError("Заголовки CSV пусты или повторяются")
    password_headers = normalized_headers.intersection(PASSWORD_KEYS)
    if not password_headers:
        raise BrowserCsvError(
            "Не найдена колонка password. Экспортируйте пароли из Chrome/Edge/Brave/Opera, Firefox или Safari."
        )
    if len(password_headers) != 1:
        raise BrowserCsvError("В CSV больше одной колонки пароля")
    (password_header,) = password_headers

    source_format = _detect_source(normalized_headers)
    reader.fieldnames = headers
    output: list[dict[str, str]] = []
    for raw_row in reader:
        if None in raw_row or any(value is None for value in raw_row.values()):
            raise BrowserCsvError(f"Неверное количество полей CSV: строка {reader.line_num}")
        # Пароли сохраняются буквально; нормализация применяется только к метаданным.
        row = {key: value if key in PASSWORD_KEYS else value.strip() for key, value in raw_row.items()}
        url = _first_value(row, URL_KEYS)
        realm = _first_value(row, REALM_KEYS)
        login = _first_value(row, LOGIN_KEYS)
        note = _first_value(row, NOTE_KEYS)
        otp = _first_value(row, OTP_KEYS)
        if otp:
            note = f"{note}\nOTPAuth: {otp}".strip()

        # Chromium may export Android application identifiers. Preserve them in
        # the encrypted note, but do not expose them to webbrowser.open().
        scheme = re.match(r"^([a-z][a-z0-9+.-]*)://", url, re.IGNORECASE)
        if scheme and scheme.group(1).casefold() not in {"http", "https"}:
            note = f"{note}\nИсходный адрес: {url}".strip()
            url = ""
        try:
            hostname = urlsplit(normalize_web_url(url)).hostname
        except ValidationError as exc:
            raise BrowserCsvError(f"Строка {reader.line_num}: {exc}") from None
        name = _first_value(row, NAME_KEYS) or realm or hostname or login or "Без названия"

        output.append(
            {
                "record_name": name,
                "service_name": name,
                "login": login,
                "password": row[password_header],
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
