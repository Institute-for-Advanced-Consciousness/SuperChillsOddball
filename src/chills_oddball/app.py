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
from tkinter import messagebox
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
        # Reasonable starting geometry as a fallback.
        self.root.geometry("1024x720")
        if self.config.display.fullscreen:
            try:
                self.root.attributes("-fullscreen", True)
            except tk.TclError:
                self._maximize_window()
        else:
            self._maximize_window()

        # Scale fonts to the actual screen so dense screens (intake) fit.
        self._scale_display_fonts()

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

    def _maximize_window(self) -> None:
        try:
            self.root.state("zoomed")
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)
            except tk.TclError:
                pass

    def _scale_display_fonts(self) -> None:
        """Scale the configured font sizes to the current screen height.

        The YAML defaults are tuned for ~1080 px; on shorter laptop panels
        (768 / 900 px) the heading + dense intake content overflow before
        the Begin button. Compute a scale factor against a 1080 reference
        so the same content fits on any single-laptop deployment.
        """
        try:
            self.root.update_idletasks()
            screen_h = self.root.winfo_screenheight()
        except tk.TclError:
            return
        if screen_h <= 0:
            return
        scale = max(0.65, min(1.4, screen_h / 1080.0))
        d = self.config.display
        d.font_size_heading = max(20, round(d.font_size_heading * scale))
        d.font_size_instruction = max(14, round(d.font_size_instruction * scale))
        d.font_size_normal = max(11, round(d.font_size_normal * scale))

    def _register_frames(self, classes: Iterable[type[StageFrame]]) -> None:
        for cls in classes:
            if cls.NAME == StageFrame.NAME:
                raise ValueError(f"{cls.__name__} did not override NAME")
            if cls.NAME in self._frames:
                raise ValueError(f"duplicate stage NAME: {cls.NAME!r}")
            self._frames[cls.NAME] = cls(self)
        # Abort hooks: Escape key + window-close button.
        self.root.bind("<Escape>", self._on_escape)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

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

    # ----- abort handling -------------------------------------------------

    # Test seam: tests monkeypatch this to skip the Tk modal dialog.
    confirm_abort = staticmethod(
        lambda: messagebox.askyesno(
            "Abort session?",
            "Abort session?\n\nData so far will be saved as a PARTIAL_session.json.",
            icon="warning",
        )
    )

    def _on_escape(self, _event: object = None) -> None:
        if self.config.abort.require_confirmation:
            if not self.confirm_abort():
                return
        self.abort()

    def _on_window_close(self) -> None:
        if self.config.abort.require_confirmation:
            if not self.confirm_abort():
                return
        self.abort()

    def abort(self) -> None:
        """Mark the session as aborted, refresh PARTIAL, close outlet, exit.

        Idempotent — safe to call multiple times. Does not raise even if
        services are partially attached or already shut down.
        """
        logger.warning("abort requested at stage %s", self._current)
        if self.outlet is not None and self.config.abort.emit_session_abort_marker:
            try:
                self.outlet.session_abort()
            except Exception:  # noqa: BLE001
                logger.exception("session_abort marker push failed")
        if self.writer is not None:
            try:
                self.writer.mark_pending_blocks_aborted()
                self.writer.finalize(status="aborted")
            except Exception:  # noqa: BLE001
                logger.exception("writer.finalize(aborted) failed")
        if self.outlet is not None:
            try:
                self.outlet.close()
            except Exception:  # noqa: BLE001
                logger.exception("outlet.close failed")
        self.shutdown()

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
    """Confirm the install is good: config loads, LSL outlet opens, audio device
    opens, tone assets exist. Returns 0 on success, 1 on any failure.

    Used by INSTALL.bat after first-run setup. Designed to print a clean
    OK/FAIL line per check so a non-tech user can see what's wrong.
    """
    failures: list[str] = []

    # 1) Config
    try:
        cfg = load_config(config_path)
        print(f"OK   config loaded                  {cfg.session.protocol_id}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL config load                    {e}", file=sys.stderr)
        return 1

    # 2) Tone .wav assets
    from .config import REPO_ROOT
    missing: list[str] = []
    for label, rel in [
        ("standard tone", cfg.audio.files.tone_standard),
        ("deviant tone",  cfg.audio.files.tone_deviant),
        ("ref tone",      cfg.audio.files.volume_reference),
        ("gong start",    cfg.audio.files.gong_start),
        ("gong end",      cfg.audio.files.gong_end),
    ]:
        p = REPO_ROOT / rel
        if not p.exists():
            missing.append(f"{label}: {p}")
    if missing:
        for m in missing:
            print(f"FAIL audio asset missing            {m}", file=sys.stderr)
        print("     fix: run `uv run python scripts/generate_tones.py`")
        failures.append("audio assets missing")
    else:
        print(f"OK   {len([1])*5} audio assets present       at assets/sounds/")

    # 3) LSL outlet
    try:
        from .markers import ChillsMarkerOutlet
        outlet = ChillsMarkerOutlet(cfg.lsl)
        outlet.open()
        outlet.close()
        print(f"OK   LSL outlet opens               {cfg.lsl.stream_name}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL LSL outlet                     {e}", file=sys.stderr)
        failures.append("LSL outlet")

    # 4) Audio device
    try:
        import sounddevice as sd
        # query_devices() raises if PortAudio can't open. We don't actually
        # play anything — that's the volume-check step.
        info = sd.query_devices(cfg.audio.device_name, "output")
        name = info["name"] if isinstance(info, dict) else str(info)
        print(f"OK   audio device available         {name}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL audio device                   {e}", file=sys.stderr)
        failures.append("audio device")

    # 5) Tk
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        print("OK   Tk display available")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL Tk display                     {e}", file=sys.stderr)
        failures.append("Tk")

    if failures:
        print(f"\nSELF-CHECK FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nSELF-CHECK OK — ready to launch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
