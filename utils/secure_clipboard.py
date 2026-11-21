"""Win32-адаптер паролей без обхода защиты через Tk или другой буфер.

Контракт форматов и владения памятью: Microsoft Learn (Win32):
https://learn.microsoft.com/windows/win32/dataxchg/clipboard-formats
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setclipboarddata
https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-globalunlock
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getclipboardsequencenumber
Адаптер вызывается из потока GUI; таймером и сообщениями управляет UI.
"""

import ctypes
import sys

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_EXCLUSION_NAMES = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
)


def _load_libraries():
    if sys.platform != "win32":
        raise OSError("Защищённый буфер обмена доступен только в Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error = True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error = True)
    # HWND/HGLOBAL/HANDLE и SIZE_T имеют размер указателя, не DWORD.
    signatures = (
        (user32.RegisterClipboardFormatW, [ctypes.c_wchar_p], ctypes.c_uint),
        (user32.OpenClipboard, [ctypes.c_void_p], ctypes.c_int),
        (user32.CloseClipboard, [], ctypes.c_int),
        (user32.EmptyClipboard, [], ctypes.c_int),
        (user32.SetClipboardData, [ctypes.c_uint, ctypes.c_void_p], ctypes.c_void_p),
        (user32.GetClipboardSequenceNumber, [], ctypes.c_uint32),
        (kernel32.GlobalAlloc, [ctypes.c_uint, ctypes.c_size_t], ctypes.c_void_p),
        (kernel32.GlobalLock, [ctypes.c_void_p], ctypes.c_void_p),
        (kernel32.GlobalUnlock, [ctypes.c_void_p], ctypes.c_int),
        (kernel32.GlobalFree, [ctypes.c_void_p], ctypes.c_void_p),
    )
    for function, arguments, result in signatures:
        function.argtypes = arguments
        function.restype = result
    return user32, kernel32


class WindowsClipboard:
    """Копирует пароль с запретом истории/синхронизации; ошибки — OSError."""

    def __init__(self, hwnd: int):
        if type(hwnd) is not int or not 0 < hwnd < 1 << (ctypes.sizeof(ctypes.c_void_p) * 8):
            raise OSError("Требуется ненулевой HWND окна приложения.")
        self._hwnd = hwnd
        try:
            self._user32, self._kernel32 = _load_libraries()
        except AttributeError:
            raise OSError("Необходимые функции защищённого буфера обмена недоступны.") from None
        self._formats = []
        for name in _EXCLUSION_NAMES:
            format_id = self._user32.RegisterClipboardFormatW(name)
            if not format_id:
                raise self._error("RegisterClipboardFormatW")
            self._formats.append(format_id)
        self._sequence = None

    def copy_password(self, value: str) -> None:
        """Публикует запреты раньше CF_UNICODETEXT и не хранит пароль в объекте."""
        if not isinstance(value, str) or "\0" in value:
            raise OSError("Значение нельзя безопасно передать в буфер обмена.")
        try:
            encoded = value.encode("utf-16-le") + b"\0\0"
        except UnicodeError:
            raise OSError("Значение нельзя безопасно передать в буфер обмена.") from None
        if not self._user32.OpenClipboard(self._hwnd):
            raise self._error("OpenClipboard")
        try:
            if not self._user32.EmptyClipboard():
                raise self._error("EmptyClipboard")
            self._sequence = None
            for format_id in self._formats:
                self._publish(format_id, b"\0" * 4)
            self._publish(_CF_UNICODETEXT, encoded)
            sequence = self._user32.GetClipboardSequenceNumber()
            if not sequence:
                # Не оставляем пароль без возможности условной очистки.
                error = self._error("GetClipboardSequenceNumber")
                if not self._user32.EmptyClipboard():
                    raise self._error("EmptyClipboard")
                raise error
            self._sequence = sequence
        finally:
            if not self._user32.CloseClipboard():
                raise self._error("CloseClipboard")

    def _publish(self, format_id: int, payload: bytes) -> None:
        handle = self._kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(payload))
        if not handle:
            raise self._error("GlobalAlloc")
        try:
            pointer = self._kernel32.GlobalLock(handle)
            if not pointer:
                raise self._error("GlobalLock")
            try:
                ctypes.memmove(pointer, payload, len(payload))
            finally:
                # GlobalUnlock возвращает 0 также при успешном снятии последней блокировки.
                ctypes.set_last_error(0)
                if not self._kernel32.GlobalUnlock(handle) and ctypes.get_last_error():
                    raise self._error("GlobalUnlock")
            if not self._user32.SetClipboardData(format_id, handle):
                raise self._error("SetClipboardData")
            handle = None  # После успеха память принадлежит Windows.
        finally:
            if handle and self._kernel32.GlobalFree(handle):
                raise self._error("GlobalFree")

    def clear_password(self) -> None:
        """Очищает только нашу публикацию; чужие данные не читает и не удаляет."""
        if self._sequence is None:
            return
        if not self._user32.OpenClipboard(self._hwnd):
            raise self._error("OpenClipboard")
        try:
            sequence = self._user32.GetClipboardSequenceNumber()
            if not sequence:
                raise self._error("GetClipboardSequenceNumber")
            if sequence == self._sequence and not self._user32.EmptyClipboard():
                raise self._error("EmptyClipboard")
            self._sequence = None
        finally:
            if not self._user32.CloseClipboard():
                raise self._error("CloseClipboard")

    @staticmethod
    def _error(operation: str) -> OSError:
        return OSError(ctypes.get_last_error(), f"Ошибка защищённого буфера обмена: {operation}.")
