import unittest
from unittest.mock import patch

from password_manager_ui import OUTLINE_BUTTON_STYLE
from ui_compat import configure_stable_windows_dpi


class DpiCompatibilityTests(unittest.TestCase):
    @patch("ui_compat.ctk.deactivate_automatic_dpi_awareness")
    @patch("ui_compat.sys.platform", "win32")
    def test_windows_uses_stable_system_dpi_scaling(self, deactivate_dpi):
        configure_stable_windows_dpi()

        deactivate_dpi.assert_called_once_with()

    def test_outline_buttons_define_colors_for_both_themes(self):
        self.assertEqual(2, len(OUTLINE_BUTTON_STYLE["text_color"]))
        self.assertEqual(2, len(OUTLINE_BUTTON_STYLE["text_color_disabled"]))
        self.assertEqual(2, len(OUTLINE_BUTTON_STYLE["hover_color"]))


if __name__ == "__main__":
    unittest.main()
