"""Base class for every stage frame.

Lives in its own module so stage modules can import it without a circular
dependency on app.py (which itself imports the stage modules).
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..app import App


class StageFrame(tk.Frame):
    """Base for every stage in the flow.

    Subclasses set ``NAME`` and override ``build``, ``on_enter``, ``on_leave``.
    Use ``self.app.show_stage(name, **kwargs)`` to advance.
    """

    NAME: str = "__abstract__"

    def __init__(self, app: App) -> None:
        super().__init__(
            app.root,
            bg=app.config.display.background_color,
        )
        self.app = app
        self._wrappables: list[tuple[tk.Misc, float, int]] = []
        self.build()
        self.bind("<Configure>", self._on_stage_resize)

    def build(self) -> None:
        """Create the static widgets. Called once at construction."""

    def on_enter(self, **payload: Any) -> None:
        """Called every time this frame is shown."""

    def on_leave(self) -> None:
        """Called every time this frame is hidden."""

    # ---- responsive text wrapping ---------------------------------------

    def register_wrappable(
        self,
        widget: tk.Misc,
        ratio: float = 0.85,
        min_px: int = 300,
    ) -> None:
        """Register a Label (or any widget supporting ``wraplength``) so its
        wrap width tracks the stage's actual width.

        ``ratio`` is the fraction of the stage frame's width to wrap at.
        For full-width content use ~0.85; for one column of a two-column
        layout use ~0.42.
        """
        self._wrappables.append((widget, ratio, min_px))

    def _on_stage_resize(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        width = event.width
        for widget, ratio, min_px in self._wrappables:
            try:
                widget.configure(wraplength=max(min_px, int(width * ratio)))
            except tk.TclError:
                pass
