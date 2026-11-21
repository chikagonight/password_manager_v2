"""Tk clipboard for non-Windows desktops and password-entry bindings."""

from collections.abc import Callable
from tkinter import Misc, TclError
from uuid import uuid4

_CLIPBOARD_MARKER = "PASSWORDSAFE_MARKER"


class TkClipboard:
    def __init__(self, window: Misc):
        self._window = window
        self._marker: str | None = None

    def copy_password(self, value: str) -> None:
        marker = uuid4().hex
        try:
            self._window.clipboard_clear()
            self._window.clipboard_append(marker, type=_CLIPBOARD_MARKER)
            self._window.clipboard_append(value, type="UTF8_STRING")
        except TclError:
            raise OSError("Не удалось записать буфер обмена") from None
        self._marker = marker

    def clear_password(self) -> None:
        if self._marker is None:
            return
        try:
            if self._window.clipboard_get(type=_CLIPBOARD_MARKER) == self._marker:
                self._window.clipboard_clear()
        except TclError:
            # The current owner has no marker (or there is no owner).
            pass
        self._marker = None


def protect_password_entry(entry, copy: Callable[[str, str], bool]) -> None:
    entry.configure(exportselection=False)

    def copy_or_cut(event, *, cut: bool = False):
        widget = event.widget
        if not widget.cget("show") and widget.selection_present():
            first, last = widget.index("sel.first"), widget.index("sel.last")
            value = widget.get()[first:last]
            if copy(value, "Пароль") and cut and widget.cget("state") == "normal":
                widget.delete(first, last)
        return "break"

    entry.bind("<<Copy>>", copy_or_cut)
    entry.bind("<<Cut>>", lambda event: copy_or_cut(event, cut=True))
