from __future__ import annotations

import os
import sys
from pathlib import Path

from password_safe.domain import DEFAULT_SETTINGS as DEFAULT_SETTINGS
from password_safe.domain import MIN_MASTER_PASSWORD_LENGTH as MIN_MASTER_PASSWORD_LENGTH

APP_NAME = "passwordSafe"
APP_TITLE = "passwordSafe"
LEGACY_APP_NAME = "PasswordManagerV2"
VAULT_FORMAT = "password-manager-vault"
VAULT_VERSION = 1
RECORDS_SCHEMA_VERSION = 1


def default_data_dir() -> Path:
    """Return a stable per-user data directory."""

    override = os.environ.get("PASSWORD_SAFE_DATA_DIR") or os.environ.get("PASSWORD_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return select_windows_data_dir(Path(base))

    return Path.home() / ".local" / "share" / APP_NAME


def select_windows_data_dir(base: Path) -> Path:
    """Prefer the renamed location, while keeping an existing legacy vault accessible."""

    current = Path(base) / APP_NAME
    legacy = Path(base) / LEGACY_APP_NAME
    if (current / "vault.pm2").is_file():
        return current
    if (legacy / "vault.pm2").is_file():
        return legacy
    if not (current / "vault.pm2.bak").is_file() and (legacy / "vault.pm2.bak").is_file():
        return legacy
    return current


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DATA_DIR = default_data_dir()
VAULT_FILE = APP_DATA_DIR / "vault.pm2"
VAULT_BACKUP_FILE = APP_DATA_DIR / "vault.pm2.bak"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
LEGACY_RECORDS_FILE = application_dir() / "records.json"
LEGACY_SETTINGS_FILE = application_dir() / "settings.json"
