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
        self.build()

    def build(self) -> None:
        """Create the static widgets. Called once at construction."""

    def on_enter(self, **payload: Any) -> None:
        """Called every time this frame is shown."""

    def on_leave(self) -> None:
        """Called every time this frame is hidden."""
