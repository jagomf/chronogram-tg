"""Window placement helpers."""

from __future__ import annotations


def centre_on_screen(window, width: int | None = None, height: int | None = None) -> None:
    """Place a window in the centre of the screen.

    Windows without an explicit size are measured first (their natural
    requested size), so this must run after their widgets are built.
    """
    window.update_idletasks()
    explicit = width is not None and height is not None
    width = width or window.winfo_reqwidth()
    height = height or window.winfo_reqheight()
    x = max((window.winfo_screenwidth() - width) // 2, 0)
    y = max((window.winfo_screenheight() - height) // 2, 0)
    window.geometry(f"{width}x{height}+{x}+{y}" if explicit else f"+{x}+{y}")
