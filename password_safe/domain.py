"""Password and web-address policies, independent of GUI and persistence."""

import re
from urllib.parse import urlsplit

MIN_MASTER_PASSWORD_LENGTH = 8
MIN_GENERATED_PASSWORD_LENGTH = 8
MAX_GENERATED_PASSWORD_LENGTH = 128

DEFAULT_SETTINGS = {
    "theme": "Dark",
    "auto_lock_minutes": 5,
    "clipboard_clear_seconds": 30,
}


class ValidationError(ValueError):
    pass


def normalize_web_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    if "\\" in url or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValidationError("Укажите корректный адрес сайта без пробелов")
    if url.startswith("//"):
        url = f"https:{url}"
    elif not url.casefold().startswith(("http://", "https://")):
        scheme = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url)
        host_and_port = re.match(r"^(?:localhost|[^:/\s]+\.[^:/\s]+):[0-9]+(?:[/?#]|$)", url, re.I)
        if scheme and not host_and_port:
            raise ValidationError("Допустимы только ссылки HTTP или HTTPS")
        url = f"https://{url}"

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
        if not hostname or parsed.scheme not in {"http", "https"} or parsed.username is not None:
            raise ValueError
        if port is not None and port == 0 or parsed.netloc.endswith(":"):
            raise ValueError
        if parsed.netloc.startswith("["):
            if not re.fullmatch(r"\[[0-9A-Fa-f:.]+\](?::[0-9]+)?", parsed.netloc):
                raise ValueError
        else:
            labels = hostname.encode("idna").decode("ascii").removesuffix(".").split(".")
            if not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in labels):
                raise ValueError
    except ValueError:
        raise ValidationError("Укажите корректный HTTP(S)-адрес сайта") from None
    return url


def record_fields(
    record_name: str, service_name: str, login: str, password: str, repeat_password: str, url: str,
) -> tuple[str, str, str, str]:
    if password != repeat_password:
        raise ValidationError("Пароли не совпадают")
    login = login.strip()
    url = normalize_web_url(url)
    name = record_name.strip() or urlsplit(url).hostname or login or "Без названия"
    return name, service_name.strip() or name, login, url


def validate_master_password(password: str, repeat_password: str) -> None:
    if password != repeat_password:
        raise ValidationError("Мастер-пароли не совпадают")
    if len(password) < MIN_MASTER_PASSWORD_LENGTH:
        raise ValidationError(f"Мастер-пароль должен содержать не менее {MIN_MASTER_PASSWORD_LENGTH} символов")


def normalize_settings(values: object) -> dict[str, str | int]:
    defaults = DEFAULT_SETTINGS.copy()
    if not isinstance(values, dict):
        return defaults
    theme = values.get("theme")
    if theme in ("Dark", "Light", "System"):
        defaults["theme"] = theme
    for key, maximum in (("auto_lock_minutes", 30), ("clipboard_clear_seconds", 300)):
        value = values.get(key)
        if type(value) is int and 1 <= value <= maximum:
            defaults[key] = value
    return defaults
