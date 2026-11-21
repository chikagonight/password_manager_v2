"""Изолированные проверки Win32: системный буфер и история не затрагиваются."""

import ctypes
import importlib
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class FakeWindows:
    """Модель владения HGLOBAL с настоящими локальными буферами памяти."""

    def __init__(self):
        self.events = []
        self.blocks = {}
        self.published = {}
        self.freed = []
        self.sequence = 100
        self.opened = False
        self.formats = {}
        self.last_error = 0
        self.user32 = SimpleNamespace(**{
            name: Mock(side_effect = callback)
            for name, callback in {
                "RegisterClipboardFormatW": self.register,
                "OpenClipboard": self.open,
                "CloseClipboard": self.close,
                "EmptyClipboard": self.empty,
                "SetClipboardData": self.publish,
                "GetClipboardSequenceNumber": self.get_sequence,
            }.items()
        })
        self.kernel32 = SimpleNamespace(**{
            name: Mock(side_effect = callback)
            for name, callback in {
                "GlobalAlloc": self.allocate,
                "GlobalLock": self.lock,
                "GlobalUnlock": self.unlock,
                "GlobalFree": self.free,
            }.items()
        })

    def register(self, name):
        self.formats[name] = 0xC000 + len(self.formats)
        return self.formats[name]

    def open(self, hwnd):
        self.events.append(("open", hwnd))
        self.opened = True
        return 1

    def close(self):
        self.events.append(("close",))
        self.opened = False
        return 1

    def empty(self):
        assert self.opened
        self.events.append(("empty",))
        self.published.clear()
        self.sequence += 1
        return 1

    def publish(self, format_id, handle):
        assert self.opened
        self.events.append(("publish", format_id))
        self.published[format_id] = handle
        self.sequence += 1
        return handle

    def get_sequence(self):
        assert self.opened, "Проверка последовательности должна быть под OpenClipboard"
        self.events.append(("sequence",))
        return self.sequence

    def allocate(self, flags, size):
        assert flags & 0x0002, "Требуется GMEM_MOVEABLE"
        handle = 0x100000001 + len(self.blocks)
        self.blocks[handle] = ctypes.create_string_buffer(size)
        return handle

    def lock(self, handle):
        return ctypes.addressof(self.blocks[handle])

    def unlock(self, handle):
        return 0  # Нулевой результат без LastError означает успех.

    def free(self, handle):
        assert handle not in self.published.values(), "Нельзя освобождать память Windows"
        self.freed.append(handle)
        return 0

    def data(self, format_id):
        return bytes(self.blocks[self.published[format_id]])


class SecureClipboardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("utils.secure_clipboard"),
            "Защищённый Windows-адаптер отсутствует",
        )
        self.module = importlib.import_module("utils.secure_clipboard")
        self.native = FakeWindows()
        self.patches = [
            patch.object(self.module, "_load_libraries", return_value = (self.native.user32, self.native.kernel32)),
            patch.object(ctypes, "get_last_error", side_effect = lambda: self.native.last_error, create = True),
            patch.object(ctypes, "set_last_error", side_effect = self.set_last_error, create = True),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def set_last_error(self, value):
        self.native.last_error = value

    def test_copy_sets_all_exclusions_before_unicode(self):
        adapter = self.module.WindowsClipboard(0x100000010)
        value = "  синтетический\U0001f511\nпароль  "
        self.assertIsNone(adapter.copy_password(value))
        names = (
            "ExcludeClipboardContentFromMonitorProcessing",
            "CanIncludeInClipboardHistory",
            "CanUploadToCloudClipboard",
        )
        self.assertEqual(set(self.native.formats), set(names))
        formats = [self.native.formats[name] for name in names]
        for format_id in formats:
            self.assertEqual(self.native.data(format_id), b"\0" * 4)
        self.assertEqual(self.native.data(13), value.encode("utf-16-le") + b"\0\0")
        published = [event[1] for event in self.native.events if event[0] == "publish"]
        self.assertEqual(published, [*formats, 13])
        self.assertEqual(self.native.events[0], ("open", 0x100000010))
        self.assertEqual(self.native.events[-1], ("close",))
        self.assertFalse(self.native.freed)

    def test_busy_clipboard_raises_without_emptying_or_closing(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.user32.OpenClipboard.side_effect = None
        self.native.user32.OpenClipboard.return_value = 0
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.native.user32.EmptyClipboard.assert_not_called()
        self.native.user32.CloseClipboard.assert_not_called()

    def test_exclusion_failure_never_publishes_password(self):
        adapter = self.module.WindowsClipboard(42)
        original = self.native.publish

        def fail_second(format_id, handle):
            if format_id == self.native.formats["CanIncludeInClipboardHistory"]:
                return 0
            return original(format_id, handle)

        self.native.user32.SetClipboardData.side_effect = fail_second
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.assertNotIn(13, self.native.published)
        self.assertFalse(self.native.opened)
        self.assertEqual(len(self.native.freed), 1)

    def test_clear_removes_own_copy_once(self):
        adapter = self.module.WindowsClipboard(42)
        self.assertIsNone(adapter.clear_password())
        self.assertFalse(self.native.events)
        adapter.copy_password("synthetic")
        self.native.events.clear()
        self.assertIsNone(adapter.clear_password())
        self.assertEqual(self.native.events, [("open", 42), ("sequence",), ("empty",), ("close",)])
        self.assertFalse(self.native.published)
        self.native.events.clear()
        adapter.clear_password()
        self.assertFalse(self.native.events)

    def test_clear_preserves_new_content_even_with_identical_text(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic")
        self.native.sequence += 1
        previous = dict(self.native.published)
        self.native.events.clear()
        adapter.clear_password()
        self.assertEqual(self.native.published, previous)
        self.assertEqual(self.native.events, [("open", 42), ("sequence",), ("close",)])

    def test_clear_checks_sequence_after_open_not_before(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic")
        original = self.native.open

        def intervening_copy(hwnd):
            self.native.sequence += 1
            return original(hwnd)

        self.native.user32.OpenClipboard.side_effect = intervening_copy
        previous = dict(self.native.published)
        adapter.clear_password()
        self.assertEqual(self.native.published, previous)

    def test_clear_busy_preserves_retry_token(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic")
        self.native.user32.OpenClipboard.side_effect = lambda hwnd: 0
        with self.assertRaises(OSError):
            adapter.clear_password()
        self.native.user32.OpenClipboard.side_effect = self.native.open
        adapter.clear_password()
        self.assertFalse(self.native.published)

    def test_invalid_window_handle_is_rejected(self):
        for hwnd in (0, -1, True, None, "42", 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)):
            with self.subTest(hwnd = hwnd), self.assertRaises(OSError):
                self.module.WindowsClipboard(hwnd)
        self.assertFalse(self.native.events)

    def test_registration_failure_never_opens_clipboard(self):
        self.native.user32.RegisterClipboardFormatW.side_effect = lambda name: 0
        with self.assertRaises(OSError):
            self.module.WindowsClipboard(42)
        self.assertFalse(self.native.events)

    def test_invalid_text_is_rejected_without_clipboard_changes(self):
        adapter = self.module.WindowsClipboard(42)
        for value in ("before\0after", "\ud800", None, 123):
            with self.subTest(value_type = type(value).__name__):
                with self.assertRaises(OSError) as error:
                    adapter.copy_password(value)
                self.assertNotIn("before", str(error.exception))
        self.assertFalse(self.native.events)

    def test_empty_failure_never_publishes(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.user32.EmptyClipboard.side_effect = lambda: 0
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.native.user32.SetClipboardData.assert_not_called()
        self.assertFalse(self.native.opened)

    def test_allocation_failure_is_oserror_and_closes(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.kernel32.GlobalAlloc.side_effect = lambda flags, size: 0
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.native.kernel32.GlobalLock.assert_not_called()
        self.assertFalse(self.native.opened)

    def test_lock_failure_frees_untransferred_memory(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.kernel32.GlobalLock.side_effect = lambda handle: 0
        # Не позволяем дефектной реализации вызвать memmove(NULL, ...).
        with patch.object(ctypes, "memmove") as move, self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        move.assert_not_called()
        self.assertEqual(len(self.native.freed), 1)
        self.assertFalse(self.native.opened)

    def test_unlock_error_frees_memory_without_publishing(self):
        adapter = self.module.WindowsClipboard(42)

        def fail_unlock(handle):
            self.native.last_error = 6
            return 0

        self.native.kernel32.GlobalUnlock.side_effect = fail_unlock
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.native.user32.SetClipboardData.assert_not_called()
        self.assertEqual(len(self.native.freed), 1)
        self.assertFalse(self.native.opened)

    def test_unicode_publication_failure_frees_only_untransferred_memory(self):
        adapter = self.module.WindowsClipboard(42)
        original = self.native.publish
        self.native.user32.SetClipboardData.side_effect = (
            lambda format_id, handle: 0 if format_id == 13 else original(format_id, handle)
        )
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.assertEqual(len(self.native.freed), 1)
        self.assertNotIn(13, self.native.published)
        self.assertFalse(self.native.opened)

    def test_zero_sequence_on_copy_rolls_back_publication(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.user32.GetClipboardSequenceNumber.side_effect = lambda: 0
        with self.assertRaises(OSError):
            adapter.copy_password("synthetic")
        self.assertFalse(self.native.published)
        self.assertFalse(self.native.opened)

    def test_zero_sequence_on_clear_preserves_data_and_retry(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic")
        previous = dict(self.native.published)
        self.native.user32.GetClipboardSequenceNumber.side_effect = lambda: 0
        with self.assertRaises(OSError):
            adapter.clear_password()
        self.assertEqual(self.native.published, previous)
        self.native.user32.GetClipboardSequenceNumber.side_effect = self.native.get_sequence
        adapter.clear_password()
        self.assertFalse(self.native.published)

    def test_close_failure_is_reported_without_secret(self):
        adapter = self.module.WindowsClipboard(42)
        self.native.user32.CloseClipboard.side_effect = lambda: 0
        with self.assertRaises(OSError) as error:
            adapter.copy_password("synthetic-secret-not-for-errors")
        self.assertNotIn("synthetic-secret-not-for-errors", str(error.exception))

    def test_clear_empty_failure_can_be_retried(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic")
        self.native.user32.EmptyClipboard.side_effect = lambda: 0
        with self.assertRaises(OSError):
            adapter.clear_password()
        self.assertFalse(self.native.opened)
        self.native.user32.EmptyClipboard.side_effect = self.native.empty
        adapter.clear_password()
        self.assertFalse(self.native.published)

    def test_empty_password_is_an_explicit_unicode_string(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("")
        self.assertEqual(self.native.data(13), b"\0\0")
        self.assertNotIn("", vars(adapter).values())

    def test_latest_copy_can_be_cleared(self):
        adapter = self.module.WindowsClipboard(42)
        adapter.copy_password("synthetic-first")
        adapter.copy_password("synthetic-second")
        self.assertNotIn("synthetic-second", vars(adapter).values())
        adapter.clear_password()
        self.assertFalse(self.native.published)


class LibraryLoadingTests(unittest.TestCase):
    def test_non_windows_has_no_fallback(self):
        module = importlib.import_module("utils.secure_clipboard")
        with patch.object(module.sys, "platform", "linux"), self.assertRaises(OSError):
            module.WindowsClipboard(42)

    def test_missing_windows_export_is_oserror(self):
        module = importlib.import_module("utils.secure_clipboard")
        with (
            patch.object(module.sys, "platform", "win32"),
            patch.object(ctypes, "WinDLL", return_value = SimpleNamespace(), create = True),
            self.assertRaises(OSError),
        ):
            module.WindowsClipboard(42)

    def test_native_signatures_are_pointer_sized(self):
        module = importlib.import_module("utils.secure_clipboard")
        native = FakeWindows()
        with (
            patch.object(module.sys, "platform", "win32"),
            patch.object(ctypes, "WinDLL", side_effect = [native.user32, native.kernel32], create = True) as loader,
        ):
            module._load_libraries()
        self.assertEqual(loader.call_args_list[0].kwargs, {"use_last_error": True})
        self.assertEqual(loader.call_args_list[1].kwargs, {"use_last_error": True})
        self.assertEqual(native.user32.OpenClipboard.argtypes, [ctypes.c_void_p])
        self.assertEqual(native.user32.SetClipboardData.argtypes, [ctypes.c_uint, ctypes.c_void_p])
        self.assertIs(native.user32.SetClipboardData.restype, ctypes.c_void_p)
        self.assertEqual(native.kernel32.GlobalAlloc.argtypes, [ctypes.c_uint, ctypes.c_size_t])
        self.assertIs(native.kernel32.GlobalAlloc.restype, ctypes.c_void_p)
        self.assertIs(native.kernel32.GlobalLock.restype, ctypes.c_void_p)
        self.assertEqual(native.kernel32.GlobalFree.argtypes, [ctypes.c_void_p])
        self.assertIs(native.kernel32.GlobalFree.restype, ctypes.c_void_p)


if __name__ == "__main__":
    unittest.main()
