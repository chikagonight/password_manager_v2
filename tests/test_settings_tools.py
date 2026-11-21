import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from constants import DEFAULT_SETTINGS
from utils.settings_tools import SettingsTools


class SettingsToolsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "settings.json"
        self.adapter = SettingsTools(self.path, self.path.with_name("legacy.json"))

    def test_invalid_values_use_defaults_without_discarding_valid_theme(self):
        self.path.write_text(json.dumps({"theme": "Light", "auto_lock_minutes": False, "clipboard_clear_seconds": -1}))
        self.assertEqual(DEFAULT_SETTINGS | {"theme": "Light"}, self.adapter.load())

    def test_invalid_utf8_uses_defaults_without_rewriting_source(self):
        snapshot = b"\xff"
        self.path.write_bytes(snapshot)
        self.assertEqual(DEFAULT_SETTINGS, self.adapter.load())
        self.assertEqual(snapshot, self.path.read_bytes())

    def test_access_error_is_not_reported_as_successful_read(self):
        self.path.touch()
        with patch.object(Path, "open", side_effect=PermissionError), self.assertRaises(PermissionError):
            self.adapter.load()
