"""Internal helper: a placeholder stage frame with a label and a Continue button.

Used in Step 8 so we can manually walk the entire stage flow before any
stage has its real experimental logic. Subclasses set NAME, LABEL, NEXT;
later steps replace each subclass with the real implementation.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

# Imported lazily inside _build to avoid circular imports during app import.


class PlaceholderStage:
    """Mixin that gives a StageFrame a centered label + Continue button.

    Real subclasses won't use this once they have their own widgets.
    """

    LABEL: str = "Stage placeholder"
    NEXT: str | None = None

    def build(self) -> None:
        cfg = self.app.config.display  # type: ignore[attr-defined]
        self.configure(bg=cfg.background_color)  # type: ignore[attr-defined]

        title = tk.Label(
            self,  # type: ignore[arg-type]
            text=self.NAME.upper(),  # type: ignore[attr-defined]
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=cfg.text_color,
            bg=cfg.background_color,
        )
        title.pack(pady=(60, 20))

        body = tk.Label(
            self,  # type: ignore[arg-type]
            text=self.LABEL,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=cfg.text_color,
            bg=cfg.background_color,
            wraplength=800,
            justify="center",
        )
        body.pack(pady=20)

        if self.NEXT:
            btn = tk.Button(
                self,  # type: ignore[arg-type]
                text="Continue",
                font=(cfg.font_family, cfg.font_size_normal),
                command=self._continue,
                width=20,
            )
            btn.pack(pady=40)
        else:
            done = tk.Label(
                self,  # type: ignore[arg-type]
                text="(end of flow — close window to exit)",
                font=(cfg.font_family, cfg.font_size_normal, "italic"),
                fg=cfg.text_color,
                bg=cfg.background_color,
            )
            done.pack(pady=40)

    def on_enter(self, **payload: Any) -> None:
        # Stash payload for inspection during dev walkthroughs.
        self._last_payload = payload  # type: ignore[attr-defined]

    def _continue(self) -> None:
        if self.NEXT:
            self.app.show_stage(self.NEXT)  # type: ignore[attr-defined]
