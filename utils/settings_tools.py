from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from constants import DEFAULT_SETTINGS, LEGACY_SETTINGS_FILE, SETTINGS_FILE


class SettingsTools:
    def __init__(self, path: Path = SETTINGS_FILE, legacy_path: Path = LEGACY_SETTINGS_FILE):
        self.path = Path(path)
        self.legacy_path = Path(legacy_path)

    def load(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        source = self.path if self.path.is_file() else self.legacy_path
        if source.is_file() and source.stat().st_size:
            try:
                with source.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    settings.update({key: loaded[key] for key in DEFAULT_SETTINGS if key in loaded})
            except (OSError, json.JSONDecodeError):
                pass
        self.save_all(settings)
        return settings

    def save(self, key: str, file_config: dict[str, Any], new_value: Any, file: Path | str | None = None) -> None:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(f"Неизвестная настройка: {key}")
        file_config[key] = new_value
        self.save_all(file_config, Path(file) if file else self.path)

    def save_all(self, settings: dict[str, Any], path: Path | None = None) -> None:
        target = Path(path) if path else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(settings, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path.exists():
                temp_path.unlink()
