import csv
import io
import tempfile
import unittest
from pathlib import Path

from password_manager_app import ImportRecordsError, PasswordManagerApp
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

    def test_passwords_survive_import_and_reunlock_exactly(self):
        passwords = [' \tпароль,"quoted"\r\nsecond\nthird\rline\t ', " \t  ", "", " leading", "trailing "]
        path = self.directory / "exact.csv"
        export = io.StringIO(newline="")
        writer = csv.writer(export)
        writer.writerow(["name", "url", "username", "password", "note"])
        for number, password in enumerate(passwords):
            writer.writerow([f"Example {number}", "https://example.test", "user", password, "note"])
        path.write_bytes(export.getvalue().encode("utf-8-sig"))
        app = PasswordManagerApp(
            data_dir=self.directory / "data",
            legacy_records_path=self.directory / "missing-records.json",
        )
        self.addCleanup(app.lock)
        app.create_vault("synthetic-master", "synthetic-master")

        self.assertEqual(len(passwords), app.import_records_from_csv(path))
        app.lock()
        self.assertEqual(len(passwords), app.unlock("synthetic-master"))

        self.assertEqual(passwords, [record.password for record in app.get_records()])

    def test_malformed_rows_cancel_entire_import(self):
        malformed_rows = {
            "missing_password": "Broken,https://example.test,user\n",
            "missing_note": "Broken,https://example.test,user,synthetic-secret\n",
            "extra_field": "Broken,https://example.test,user,synthetic-secret,note,extra\n",
            "unclosed_note": 'Broken,https://example.test,user,synthetic-secret,"note\n',
            "text_after_quote": 'Broken,https://example.test,user,"synthetic-secret"junk,note\n',
        }
        for case, malformed in malformed_rows.items():
            with self.subTest(case=case):
                directory = self.directory / case
                app = PasswordManagerApp(data_dir=directory, legacy_records_path=directory / "missing.json")
                self.addCleanup(app.lock)
                app.create_vault("synthetic-master", "synthetic-master")
                app.save_record("Existing", "Existing", "user", "existing-secret", "existing-secret")
                records_before = [record.to_dict() for record in app.get_records()]
                vault_before = app.store.path.read_bytes()
                backup_before = app.store.backup_path.read_bytes()
                path = self.directory / f"{case}.csv"
                path.write_text(
                    "name,url,username,password,note\n"
                    "Valid,https://example.test,user,synthetic-secret,note\n" + malformed,
                    encoding="utf-8",
                )

                with self.assertRaises(ImportRecordsError) as caught:
                    app.import_records_from_csv(path)

                self.assertRegex(str(caught.exception), "строка 3|Нарушена структура CSV")
                self.assertNotIn("synthetic-secret", str(caught.exception))
                self.assertNotIn("Broken", str(caught.exception))
                self.assertEqual(records_before, [record.to_dict() for record in app.get_records()])
                self.assertEqual(vault_before, app.store.path.read_bytes())
                self.assertEqual(backup_before, app.store.backup_path.read_bytes())
                app.lock()
                app.unlock("synthetic-master")
                self.assertEqual(records_before, [record.to_dict() for record in app.get_records()])

    def test_malformed_quoting_cancels_entire_import(self):
        malformed_rows = {
            "unclosed_note": 'Broken,https://example.test,user,synthetic-secret,"note\n',
            "text_after_quote": 'Broken,https://example.test,user,"synthetic-secret"junk,note\n',
        }
        for case, malformed in malformed_rows.items():
            with self.subTest(case=case):
                path = self.directory / f"{case}.csv"
                path.write_text(
                    "name,url,username,password,note\n"
                    "Valid,https://example.test,user,synthetic-secret,note\n" + malformed,
                    encoding="utf-8",
                )
                with self.assertRaises(BrowserCsvError) as caught:
                    read_browser_csv(path)

                self.assertNotIn("synthetic-secret", str(caught.exception))
                self.assertNotIn("Broken", str(caught.exception))

    def test_ambiguous_headers_are_rejected(self):
        exports = {
            "duplicate": "name,password,password\nExample,synthetic-secret,replacement\n",
            "normalized_duplicate": "name, Password ,PASSWORD\nExample,synthetic-secret,replacement\n",
            "empty": "name,password,\nExample,synthetic-secret,ignored\n",
            "blank": "name,password, !!! \nExample,synthetic-secret,ignored\n",
        }
        for case, export in exports.items():
            with self.subTest(case=case):
                path = self.directory / f"{case}.csv"
                path.write_text(export, encoding="utf-8")
                with self.assertRaises(BrowserCsvError) as caught:
                    read_browser_csv(path)

                self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_sniffing_does_not_consume_password_spaces(self):
        path = self.directory / "spaces.csv"
        path.write_text(
            "name, url, username, password, note\n"
            " Example, https://example.test, user,   synthetic-secret  , note\n",
            encoding="utf-8",
        )

        data = read_browser_csv(path)

        self.assertEqual("   synthetic-secret  ", data.rows[0]["password"])
        self.assertEqual("user", data.rows[0]["login"])

    def test_supported_formats_encodings_and_delimiters_preserve_passwords(self):
        formats = [
            (["name", "url", "username", "password", "note"], "Chrome / Edge / Brave / Opera"),
            (["httpRealm", "url", "username", "password", "note"], "Firefox"),
            (["Title", "URL", "Username", "Password", "Notes"], "Safari / Apple Passwords"),
            (["name", "login_uri", "login_username", "login_password", "notes"], "Bitwarden"),
            (["Название", "Адрес", "Логин", "Пароль", "Заметка"], "универсальный CSV"),
            (["name", "url", "username", "pass", "note"], "универсальный CSV"),
        ]
        password = ' \tпароль,"quoted"\r\nsecond\nthird\rline\t '
        for headers, source_format in formats:
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1251"):
                for delimiter in (",", ";", "\t"):
                    with self.subTest(headers=headers, encoding=encoding, delimiter=delimiter):
                        export = io.StringIO(newline="")
                        writer = csv.writer(export, delimiter=delimiter)
                        writer.writerow(headers)
                        writer.writerow([" Example ", "https://example.test", " user ", password, "first\r\nsecond"])
                        path = self.directory / "matrix.csv"
                        path.write_bytes(export.getvalue().encode(encoding))

                        data = read_browser_csv(path)

                        self.assertEqual(source_format, data.source_format)
                        self.assertEqual(password, data.rows[0]["password"])
                        self.assertEqual("user", data.rows[0]["login"])
                        self.assertEqual("first\r\nsecond", data.rows[0]["note"])

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
