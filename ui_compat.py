from __future__ import annotations

import sys

import customtkinter as ctk


def configure_stable_windows_dpi() -> None:
    """Let Windows scale the whole Tk window instead of rebuilding every CTk widget."""

    if sys.platform.startswith("win"):
        # CustomTkinter 5.2.2 temporarily corrupts logical window dimensions
        # while moving between monitors with different DPI. Windows bitmap
        # scaling is stable and avoids the expensive per-widget redraw.
        ctk.deactivate_automatic_dpi_awareness()
