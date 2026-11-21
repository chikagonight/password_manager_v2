from __future__ import annotations

import json
from pathlib import Path

from constants import LEGACY_SETTINGS_FILE, SETTINGS_FILE
from password_safe.domain import normalize_settings
from utils.atomic_file import atomic_write


class SettingsTools:
    def __init__(self, path: Path = SETTINGS_FILE, legacy_path: Path = LEGACY_SETTINGS_FILE):
        self.path = Path(path)
        self.legacy_path = Path(legacy_path)

    def load(self) -> dict[str, str | int]:
        for source in (self.path, self.legacy_path):
            try:
                return normalize_settings(json.loads(source.read_text(encoding="utf-8")))
            except FileNotFoundError:
                continue
            except (ValueError, RecursionError):
                break
        return normalize_settings(None)

    def save_all(self, settings: dict[str, str | int]) -> None:
        atomic_write(self.path, json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8"))
