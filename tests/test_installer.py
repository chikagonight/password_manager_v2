import tempfile
import unittest
from pathlib import Path

from constants import APP_NAME
from install_password_safe import EXECUTABLE_NAME, InstallerError, install_payload, validate_install_dir


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.payload = self.directory / "payload"
        (self.payload / "_internal").mkdir(parents=True)
        (self.payload / EXECUTABLE_NAME).write_bytes(b"exe-v1")
        (self.payload / "_internal" / "library.dat").write_bytes(b"library")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_installs_payload_to_unicode_path(self):
        destination = self.directory / "Мои программы" / APP_NAME

        executable = install_payload(self.payload, destination)

        self.assertTrue(executable.samefile(destination / EXECUTABLE_NAME))
        self.assertEqual(b"exe-v1", executable.read_bytes())
        self.assertEqual(b"library", (destination / "_internal" / "library.dat").read_bytes())

    def test_existing_install_can_be_updated(self):
        destination = self.directory / APP_NAME
        destination.mkdir()
        (destination / EXECUTABLE_NAME).write_bytes(b"old")

        executable = install_payload(self.payload, destination)

        self.assertEqual(b"exe-v1", executable.read_bytes())

    def test_nonempty_unrelated_directory_is_rejected(self):
        destination = self.directory / "documents"
        destination.mkdir()
        (destination / "personal.txt").write_text("keep", encoding="utf-8")

        with self.assertRaises(InstallerError):
            install_payload(self.payload, destination)

        self.assertEqual("keep", (destination / "personal.txt").read_text(encoding="utf-8"))

    def test_root_and_relative_paths_are_rejected(self):
        with self.assertRaises(InstallerError):
            validate_install_dir(str(Path.cwd().anchor))
        with self.assertRaises(InstallerError):
            validate_install_dir("relative-folder")


if __name__ == "__main__":
    unittest.main()
