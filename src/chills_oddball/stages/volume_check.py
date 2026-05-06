"""Volume-check stage: 1 kHz reference tone + adjust-headphones prompt.

Loops the volume-reference .wav (3 s body, played in a worker thread)
until the operator presses SPACE; on SPACE we set the stop event and
advance to instructions.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Any

from .. import theme
from ..audio import play_reference_tone
from ..config import REPO_ROOT
from ._base import StageFrame

logger = logging.getLogger(__name__)


class VolumeCheckFrame(StageFrame):
    NAME = "volume_check"
    NEXT = "instructions"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        tk.Label(
            self,
            text="Volume check",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(pady=(80, 20))

        self.body_var = tk.StringVar(
            value=self.app.config.instructions.get(
                "volume_check",
                "A 1 kHz tone will play. Adjust headphone volume until comfortable.\n"
                "Press SPACE when ready.",
            )
        )
        body_label = tk.Label(
            self,
            textvariable=self.body_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
            wraplength=900,
            justify="center",
        )
        body_label.pack(pady=20)
        self.register_wrappable(body_label, ratio=0.85)

        self.status_var = tk.StringVar(value="(starting tone…)")
        tk.Label(
            self,
            textvariable=self.status_var,
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.CHROME_BG,
        ).pack(pady=10)

        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._space_binding: str | None = None

    def on_enter(self, **_: Any) -> None:
        self._space_binding = self.app.root.bind("<space>", self._on_space, add="+")
        self._start_tone()

    def on_leave(self) -> None:
        self._stop_tone()
        if self._space_binding is not None:
            self.app.root.unbind("<space>", self._space_binding)
            self._space_binding = None

    def _start_tone(self) -> None:
        if self.app.audio_scheduler is None:
            # No services attached — quietly skip.
            self.status_var.set("(no audio device — press SPACE to continue)")
            return
        self._stop_event = threading.Event()
        self.status_var.set("Tone playing — press SPACE when comfortable.")

        def _runner() -> None:
            try:
                play_reference_tone(
                    audio_config=self.app.config.audio,
                    repo_root=REPO_ROOT,
                    stop_event=self._stop_event,
                )
            except Exception:
                logger.exception("reference tone playback failed")

        self._worker = threading.Thread(target=_runner, daemon=True)
        self._worker.start()

    def _stop_tone(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self._stop_event = None
        self._worker = None

    def _on_space(self, _e: object = None) -> None:
        self.app.show_stage("instructions")
