"""Tk root + stage controller. Entry point for the GUI runner.

The controller is a single Tk root with one fullscreen-capable frame
visible at a time. Each stage subclasses :class:`StageFrame`, declares
its NAME, and is registered into ``App._frames``. A stage advances by
calling ``self.app.show_stage(other_name, **payload)``.

The shell is intentionally thin: experimental logic — block scheduling,
audio playback, marker emission, ratings collection — lives in the
individual stage modules. This file only owns frame construction,
swapping, and the abort/window-close hooks (Step 14).
"""

from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk
from collections.abc import Iterable
from typing import Any

from .config import Config, load_config
from .stages._base import StageFrame
from .stages.active_oddball import ActiveOddballFrame
from .stages.block_runner import BlockRunnerFrame
from .stages.calibration_chills import CalibrationChillsFrame
from .stages.completion import CompletionFrame
from .stages.instructions import InstructionsFrame
from .stages.intake import IntakeFrame
from .stages.ratings_chills import RatingsChillsFrame
from .stages.ratings_rest import RatingsRestFrame
from .stages.volume_check import VolumeCheckFrame

logger = logging.getLogger(__name__)


__all__ = ["App", "StageFrame", "main"]


# ---------------------------------------------------------------------------
# App / controller
# ---------------------------------------------------------------------------


_STAGE_CLASSES: tuple[type[StageFrame], ...] = (
    IntakeFrame,
    VolumeCheckFrame,
    InstructionsFrame,
    CalibrationChillsFrame,
    BlockRunnerFrame,
    RatingsChillsFrame,
    RatingsRestFrame,
    ActiveOddballFrame,
    CompletionFrame,
)


class App:
    """Owns the Tk root, the stage registry, and runtime context (config etc.).

    Runtime services that are constructed once per session — the LSL outlet,
    the audio scheduler, the SessionWriter — will be attached here in later
    build steps. The stage shells in Step 8 only need ``config`` and the
    ``show_stage`` method.
    """

    INITIAL_STAGE = "intake"

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.root = tk.Tk()
        self.root.title("IACS Chills × Oddball Study")
        self.root.configure(bg=self.config.display.background_color)
        # Reasonable starting geometry; fullscreen is wired in Step 13.
        self.root.geometry("1024x720")

        # Runtime services attached by the intake stage on Begin Session.
        self.outlet = None  # ChillsMarkerOutlet
        self.audio_scheduler = None  # ToneScheduler
        self.writer = None  # SessionWriter

        # Session metadata populated by intake.
        self.schedule: list = []
        self.rng_seed: int | None = None
        self.participant_id: str | None = None
        self._frames: dict[str, StageFrame] = {}
        self._current: str | None = None
        self._register_frames(_STAGE_CLASSES)

    def _register_frames(self, classes: Iterable[type[StageFrame]]) -> None:
        for cls in classes:
            if cls.NAME == StageFrame.NAME:
                raise ValueError(f"{cls.__name__} did not override NAME")
            if cls.NAME in self._frames:
                raise ValueError(f"duplicate stage NAME: {cls.NAME!r}")
            self._frames[cls.NAME] = cls(self)

    # ----- public API used by stages --------------------------------------

    def show_stage(self, name: str, **payload: Any) -> None:
        if name not in self._frames:
            raise KeyError(f"unknown stage: {name!r}. Known: {sorted(self._frames)}")
        if self._current is not None:
            old = self._frames[self._current]
            old.on_leave()
            old.pack_forget()
        frame = self._frames[name]
        frame.pack(fill="both", expand=True)
        try:
            frame.on_enter(**payload)
        except Exception:
            logger.exception("stage %s.on_enter raised", name)
            raise
        self._current = name
        logger.info("stage -> %s (payload: %s)", name, payload)

    @property
    def current_stage(self) -> str | None:
        return self._current

    @property
    def stages(self) -> dict[str, StageFrame]:
        return dict(self._frames)

    # ----- block-flow routing --------------------------------------------

    def show_block(self, block_idx: int) -> None:
        """Route to the right stage for the schedule entry at ``block_idx``.

        - ``calibration`` -> calibration_chills
        - ``active_oddball`` -> active_oddball
        - everything else -> block_runner with the ScheduledBlock as payload
        """
        if not self.schedule:
            raise RuntimeError("no schedule loaded; intake stage must populate it")
        if not (0 <= block_idx < len(self.schedule)):
            raise IndexError(f"block_idx {block_idx} out of range (0..{len(self.schedule) - 1})")
        block = self.schedule[block_idx]
        if block.condition == "calibration":
            self.show_stage("calibration_chills", block=block)
        elif block.condition == "active_oddball":
            self.show_stage("active_oddball", block=block)
        else:
            self.show_stage("block_runner", block=block)

    def advance_after_block(self, finished_block_idx: int) -> None:
        """Called by ratings panels (and active oddball) to move forward.

        If another block follows, route there. Otherwise show the
        completion stage.
        """
        next_idx = finished_block_idx + 1
        if next_idx >= len(self.schedule):
            self.show_stage("completion")
        else:
            self.show_block(next_idx)

    # ----- lifecycle ------------------------------------------------------

    def run(self) -> None:
        self.show_stage(self.INITIAL_STAGE)
        self.root.mainloop()

    def shutdown(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chills-oddball")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run install-time sanity checks (LSL outlet + audio device) and exit.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to an alternate session_defaults.yaml.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.self_check:
        return _run_self_check(args.config)

    cfg = load_config(args.config)
    app = App(cfg)
    try:
        app.run()
    finally:
        app.shutdown()
    return 0


def _run_self_check(config_path: str | None) -> int:
    """Stub for Step 16. Returns 0 if config loads + critical modules import."""
    try:
        cfg = load_config(config_path)
    except Exception as e:  # noqa: BLE001 — surface to install script
        print(f"FAIL: config load: {e}", file=sys.stderr)
        return 1
    print(f"OK: config loaded ({cfg.session.protocol_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
