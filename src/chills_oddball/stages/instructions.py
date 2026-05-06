"""Pre-session instructions screen. SPACE -> first block (calibration)."""

from __future__ import annotations

import tkinter as tk
from typing import Any

from .. import theme
from ._base import StageFrame


class InstructionsFrame(StageFrame):
    NAME = "instructions"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        tk.Label(
            self,
            text="Instructions",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(pady=(60, 20))

        self.body_var = tk.StringVar(
            value=self.app.config.instructions.get(
                "pre_session", "Eyes closed. Listen for the gongs. SPACE when ready."
            )
        )
        tk.Label(
            self,
            textvariable=self.body_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
            wraplength=900,
            justify="left",
        ).pack(pady=20, padx=80)

        tk.Label(
            self,
            text="Press SPACE when ready to begin.",
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.CHROME_BG,
        ).pack(pady=20)

        self._space_binding: str | None = None

    def on_enter(self, **_: Any) -> None:
        self._space_binding = self.app.root.bind("<space>", self._on_space, add="+")

    def on_leave(self) -> None:
        if self._space_binding is not None:
            self.app.root.unbind("<space>", self._space_binding)
            self._space_binding = None

    def _on_space(self, _e: object = None) -> None:
        # Hand off to the schedule (block 0 = calibration).
        if self._space_binding is not None:
            self.app.root.unbind("<space>", self._space_binding)
            self._space_binding = None
        self.app.show_block(0)
