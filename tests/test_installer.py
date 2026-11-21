import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_update_does_not_replace_an_install_containing_portable_data(self):
        destination = self.directory / APP_NAME
        install_payload(self.payload, destination)
        located_vault = destination / "vault.pm2"
        located_vault.write_bytes(b"synthetic vault")
        with self.assertRaisesRegex(InstallerError, "данн"):
            install_payload(self.payload, destination)
        self.assertEqual(b"synthetic vault", located_vault.read_bytes())

    def test_update_cannot_replace_parent_of_configured_data_directory(self):
        destination = self.directory / APP_NAME
        install_payload(self.payload, destination)
        data = destination / "custom-data"
        data.mkdir()
        with (
            patch.dict("install_password_safe.os.environ", {"PASSWORD_SAFE_DATA_DIR": str(data)}),
            self.assertRaisesRegex(InstallerError, "данн"),
        ):
            install_payload(self.payload, destination)
        self.assertTrue(data.is_dir())

    def test_update_removes_files_absent_from_new_payload(self):
        destination = self.directory / "Мои программы" / APP_NAME
        install_payload(self.payload, destination)
        (destination / "obsolete.dll").write_bytes(b"old library")
        (destination / "_internal" / "obsolete.dat").write_bytes(b"old data")

        install_payload(self.payload, destination)

        self.assertFalse((destination / "obsolete.dll").exists())
        self.assertFalse((destination / "_internal" / "obsolete.dat").exists())

    def test_failed_publication_restores_previous_install(self):
        destination = self.directory / "Мои программы" / APP_NAME
        install_payload(self.payload, destination)
        (destination / EXECUTABLE_NAME).write_bytes(b"old")
        (destination / "obsolete.dll").write_bytes(b"keep on failure")
        rename = Path.rename

        def fail_publication(source, target):
            if source.name == "new":
                raise PermissionError("publication denied")
            return rename(source, target)

        with patch.object(Path, "rename", fail_publication), self.assertRaises(InstallerError):
            install_payload(self.payload, destination)

        self.assertEqual(b"old", (destination / EXECUTABLE_NAME).read_bytes())
        self.assertEqual(b"keep on failure", (destination / "obsolete.dll").read_bytes())
        self.assertEqual([destination], list(destination.parent.iterdir()))

    def test_failed_rollback_keeps_recoverable_previous_install(self):
        destination = self.directory / "Мои программы" / APP_NAME
        install_payload(self.payload, destination)
        (destination / EXECUTABLE_NAME).write_bytes(b"old")
        rename = Path.rename

        def fail_publication_and_rollback(source, target):
            if source.name in {"new", "previous"}:
                raise PermissionError("rename denied")
            return rename(source, target)

        with patch.object(Path, "rename", fail_publication_and_rollback), self.assertRaises(InstallerError) as error:
            install_payload(self.payload, destination)

        backups = list(destination.parent.glob(f".{APP_NAME}-install-*/previous"))
        self.assertEqual(1, len(backups))
        self.assertEqual(b"old", (backups[0] / EXECUTABLE_NAME).read_bytes())
        self.assertIn(str(backups[0]), str(error.exception))

    def test_partial_staging_is_rejected_before_replacing_previous_install(self):
        destination = self.directory / APP_NAME
        install_payload(self.payload, destination)
        (destination / EXECUTABLE_NAME).write_bytes(b"old")

        def incomplete_copy(source, target):
            target.mkdir()
            (target / "partial.dat").write_bytes(b"partial")

        with patch("install_password_safe.shutil.copytree", incomplete_copy), self.assertRaises(InstallerError):
            install_payload(self.payload, destination)

        self.assertEqual(b"old", (destination / EXECUTABLE_NAME).read_bytes())
        self.assertFalse((destination / "partial.dat").exists())

    def test_prepublication_failures_keep_previous_files_and_clean_staging(self):
        destination = self.directory / "Мои программы" / APP_NAME
        install_payload(self.payload, destination)
        (destination / EXECUTABLE_NAME).write_bytes(b"old")
        expected = {
            path.relative_to(destination): path.read_bytes()
            for path in destination.rglob("*") if path.is_file()
        }
        original_rename = Path.rename
        original_write = Path.write_text

        def interrupted_copy(source, target):
            target.mkdir()
            (target / EXECUTABLE_NAME).write_bytes(b"partial")
            raise OSError("copy interrupted")

        def denied_marker(path, *args, **kwargs):
            if path.name == ".passwordSafe-install":
                raise PermissionError("marker denied")
            return original_write(path, *args, **kwargs)

        def denied_move(source, target):
            if source == destination:
                raise PermissionError("previous install is busy")
            return original_rename(source, target)

        faults = (
            patch("install_password_safe.shutil.copytree", interrupted_copy),
            patch.object(Path, "write_text", denied_marker),
            patch.object(Path, "rename", denied_move),
        )
        for fault in faults:
            with self.subTest(fault=fault.attribute), fault, self.assertRaises(InstallerError):
                install_payload(self.payload, destination)
            actual = {
                path.relative_to(destination): path.read_bytes()
                for path in destination.rglob("*") if path.is_file()
            }
            self.assertEqual(expected, actual)
            self.assertEqual([destination], list(destination.parent.iterdir()))

    def test_failed_first_install_leaves_no_partial_target(self):
        destination = self.directory / "Мои программы" / APP_NAME

        with (
            patch.object(Path, "rename", side_effect=PermissionError("publication denied")),
            self.assertRaises(InstallerError),
        ):
            install_payload(self.payload, destination)

        self.assertFalse(destination.exists())
        self.assertEqual([], list(destination.parent.iterdir()))

    def test_cleanup_error_distinguishes_already_published_update(self):
        destination = self.directory / "Мои программы" / APP_NAME
        install_payload(self.payload, destination)
        (self.payload / EXECUTABLE_NAME).write_bytes(b"exe-v2")

        with (
            patch("install_password_safe.shutil.rmtree", side_effect=PermissionError("cleanup denied")),
            self.assertRaisesRegex(InstallerError, "Новая версия установлена"),
        ):
            install_payload(self.payload, destination)

        self.assertEqual(b"exe-v2", (destination / EXECUTABLE_NAME).read_bytes())
        backups = list(destination.parent.glob(f".{APP_NAME}-install-*/previous"))
        self.assertEqual(1, len(backups))
        self.assertEqual(b"exe-v1", (backups[0] / EXECUTABLE_NAME).read_bytes())

    def test_install_and_update_do_not_modify_separate_data_directory(self):
        data = self.directory / "Данные" / "vault.pm2"
        data.parent.mkdir()
        data.write_bytes(b"synthetic vault sentinel")
        destination = self.directory / "Мои программы" / APP_NAME

        install_payload(self.payload, destination)
        (self.payload / EXECUTABLE_NAME).write_bytes(b"exe-v2")
        install_payload(self.payload, destination)

        self.assertEqual(b"synthetic vault sentinel", data.read_bytes())

    def test_payload_parent_is_rejected_without_modifying_source(self):
        destination = self.directory
        (destination / EXECUTABLE_NAME).write_bytes(b"old")

        with self.assertRaises(InstallerError):
            install_payload(self.payload, destination)

        self.assertEqual(b"exe-v1", (self.payload / EXECUTABLE_NAME).read_bytes())
        self.assertEqual(b"old", (destination / EXECUTABLE_NAME).read_bytes())

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


class ReleaseDependencyTests(unittest.TestCase):
    def test_build_and_ci_use_one_complete_pinned_dependency_set(self):
        root = Path(__file__).resolve().parents[1]
        lock_path = root / "requirements-build.lock"
        self.assertTrue(lock_path.is_file(), "Release dependency lock is missing")
        pins = {}
        for line in lock_path.read_text(encoding="utf-8").splitlines():
            requirement = line.split("#", 1)[0].strip()
            if not requirement:
                continue
            self.assertRegex(requirement, r"^[a-zA-Z0-9_.-]+==[^\s;]+(?:\s*;.*)?$")
            name, version = requirement.split(";", 1)[0].strip().split("==")
            self.assertNotIn(name, pins)
            pins[name] = version
        self.assertEqual("5.2.2", pins["customtkinter"])
        self.assertEqual("50.0.1", pins["cryptography"])
        for name in ("pip", "setuptools", "wheel", "ruff", "pyinstaller", "pyinstaller-hooks-contrib",
                     "altgraph", "pefile", "pywin32-ctypes", "cffi", "pycparser", "darkdetect", "packaging"):
            self.assertIn(name, pins)
        build = (root / "build.ps1").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("requirements-build.lock", build)
        self.assertIn("--no-deps", build)
        self.assertIn("--no-build-isolation", build)
        self.assertIn("-DependenciesOnly", workflow)
        self.assertIn("-SkipDependencies", workflow)
        self.assertIn("cache-dependency-path: requirements-build.lock", workflow)
        self.assertNotIn('pip install -e ".[dev]"', workflow)


if __name__ == "__main__":
    unittest.main()
