from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PasswordManagerV2"
APP_TITLE = "Password Manager"
VAULT_FORMAT = "password-manager-vault"
VAULT_VERSION = 1
RECORDS_SCHEMA_VERSION = 1
MIN_MASTER_PASSWORD_LENGTH = 8


def default_data_dir() -> Path:
    """Return a stable per-user data directory."""

    override = os.environ.get("PASSWORD_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


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

DEFAULT_SETTINGS = {
    "theme": "Dark",
    "auto_lock_minutes": 5,
    "clipboard_clear_seconds": 30,
}
