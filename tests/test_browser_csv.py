import tempfile
import unittest
from pathlib import Path

from utils.browser_csv import BrowserCsvError, read_browser_csv


class BrowserCsvTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_chromium_format_and_utf8_bom(self):
        path = self.directory / "chrome.csv"
        path.write_text(
            "\ufeffname,url,username,password,note\n"
            'Google,https://accounts.google.com,user@example.test,"secret,with,commas",Personal\n',
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("Chrome / Edge / Brave / Opera", data.source_format)
        self.assertEqual("Google", data.rows[0]["record_name"])
        self.assertEqual("secret,with,commas", data.rows[0]["password"])

    def test_firefox_format_derives_name_from_domain(self):
        path = self.directory / "firefox.csv"
        path.write_text(
            "url,username,password,httpRealm,formActionOrigin,guid,timeCreated,timeLastUsed,timePasswordChanged\n"
            "https://mail.example.test/login,firefox-user,firefox-secret,,,,0,0,0\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("Firefox", data.source_format)
        self.assertEqual("mail.example.test", data.rows[0]["record_name"])
        self.assertEqual("firefox-user", data.rows[0]["login"])

    def test_safari_format_preserves_otpauth_in_encrypted_note(self):
        path = self.directory / "safari.csv"
        path.write_text(
            "Title,URL,Username,Password,Notes,OTPAuth\n"
            "Apple ID,https://appleid.apple.com,apple-user,apple-secret,Main account,otpauth://totp/example\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("Safari / Apple Passwords", data.source_format)
        self.assertEqual("Apple ID", data.rows[0]["service_name"])
        self.assertIn("OTPAuth: otpauth://totp/example", data.rows[0]["note"])

    def test_semicolon_delimiter_and_russian_headers(self):
        path = self.directory / "localized.csv"
        path.write_text(
            "Название;Адрес;Логин;Пароль;Заметка\n"
            "Почта;https://mail.example.test;user;secret;Личная\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("Почта", data.rows[0]["record_name"])
        self.assertEqual("secret", data.rows[0]["password"])

    def test_android_identifier_is_not_opened_as_web_url(self):
        path = self.directory / "android.csv"
        path.write_text(
            "name,url,username,password,note\n"
            "Mobile app,android://hash@com.example.app,user,mobile-secret,\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("", data.rows[0]["url_link_service"])
        self.assertIn("android://hash@com.example.app", data.rows[0]["note"])

    def test_missing_password_column_is_rejected(self):
        path = self.directory / "not-passwords.csv"
        path.write_text("name,url,username\nExample,https://example.test,user\n", encoding="utf-8")

        with self.assertRaises(BrowserCsvError):
            read_browser_csv(path)

    def test_empty_cells_are_preserved_with_display_name_fallback(self):
        path = self.directory / "empty.csv"
        path.write_text("name,url,username,password,note\n,,,,\n", encoding="utf-8")

        data = read_browser_csv(path)

        self.assertEqual("Без названия", data.rows[0]["record_name"])
        self.assertEqual("", data.rows[0]["login"])
        self.assertEqual("", data.rows[0]["password"])

    def test_name_falls_back_to_site_before_login(self):
        path = self.directory / "fallback.csv"
        path.write_text(
            "name,url,username,password,note\n"
            ",portal.example.test/path,site-login,,\n"
            ",,login-only,,\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("portal.example.test", data.rows[0]["record_name"])
        self.assertEqual("login-only", data.rows[1]["record_name"])


if __name__ == "__main__":
    unittest.main()
