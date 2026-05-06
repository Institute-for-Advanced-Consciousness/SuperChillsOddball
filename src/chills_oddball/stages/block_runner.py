"""Generic block loop for the 4 short-condition variants.

Drives one block of any of: ``chills_only``, ``rest_only``,
``chills_oddball_passive``, ``rest_oddball_passive``.

Per-block lifecycle:

  1. Show pre-block instructions for the upcoming condition
     (``config.instructions.pre_block_<condition>``); wait for SPACE.
  2. Open writer record + emit ``block_start`` marker.
  3. Play start gong (emits ``block_gong_start``).
  4. Run the block:
       silent  -> ``after(duration_s, end)`` Tk timer
       oddball -> ``ToneScheduler.play_block`` in a worker thread
                  (sample-anchored ``tone_*`` markers from the audio callback)
  5. Play end gong (emits ``block_gong_end``).
  6. Emit ``block_end`` marker, write per-block CSV via writer.
  7. Route to the appropriate ratings panel
     (chills*/calibration -> ratings_chills, rest* -> ratings_rest).

Runtime services (``app.outlet``, ``app.audio_scheduler``, ``app.writer``)
are all optional — when absent (e.g. during a test or developer
walkthrough) the corresponding side-effect is silently no-oped, so the
flow can be exercised without an LSL stack or audio hardware.
"""

from __future__ import annotations

import logging
import random
import threading
import tkinter as tk
from typing import Any

from ..audio import play_gong
from ..persistence import TrialRow
from ..schedule import ScheduledBlock, generate_oddball_sequence
from ._base import StageFrame

logger = logging.getLogger(__name__)


CHILLS_CONDITIONS = {"chills_only", "chills_oddball_passive", "calibration"}
ODDBALL_CONDITIONS = {"chills_oddball_passive", "rest_oddball_passive"}


_BLOCK_TYPE_LABELS = {
    "chills_only": "CHILLS",
    "chills_oddball_passive": "CHILLS",
    "rest_only": "REST",
    "rest_oddball_passive": "REST",
    "calibration": "CALIBRATION CHILLS",
    "active_oddball": "ACTIVE LISTENING",
}


def block_type_label(condition: str) -> str:
    """Human-friendly block-type label for the in-block 'eyes closed' screen."""
    return _BLOCK_TYPE_LABELS.get(condition, condition.upper())


class BlockRunnerFrame(StageFrame):
    NAME = "block_runner"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=cfg.background_color)

        self.title_var = tk.StringVar(value="Block")
        self.body_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.footer_var = tk.StringVar(value="")

        tk.Label(
            self,
            textvariable=self.title_var,
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=cfg.text_color,
            bg=cfg.background_color,
        ).pack(pady=(60, 20))

        tk.Label(
            self,
            textvariable=self.body_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=cfg.text_color,
            bg=cfg.background_color,
            wraplength=900,
            justify="center",
        ).pack(pady=20)

        tk.Label(
            self,
            textvariable=self.status_var,
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=cfg.text_color,
            bg=cfg.background_color,
        ).pack(pady=20)

        if cfg.ra_footer_visible:
            tk.Label(
                self,
                textvariable=self.footer_var,
                font=(cfg.font_family, cfg.font_size_normal),
                fg="#888888",
                bg=cfg.background_color,
            ).pack(side="bottom", pady=10)

        # Per-entry state.
        self._block: ScheduledBlock | None = None
        self._record = None  # BlockRecord
        self._space_binding: str | None = None
        self._timer_id: str | None = None
        self._block_start_lsl: float = 0.0
        self._block_end_lsl: float = 0.0
        self._trials: list[TrialRow] | None = None
        self._worker: threading.Thread | None = None
        self._block_done_event: threading.Event | None = None

    # ---------------------------------------------------------------- lifecycle

    def on_enter(self, *, block: ScheduledBlock | None = None, **_: Any) -> None:
        if block is None:
            raise ValueError("block_runner requires `block=` payload")
        self._block = block
        self._trials = None
        self._record = None

        condition = block.condition
        instructions_key = f"pre_block_{condition}"
        body = self.app.config.instructions.get(
            instructions_key, f"Up next: {condition}.\nPress SPACE when ready."
        )

        self.title_var.set(f"Block {block.idx} — {condition}")
        self.body_var.set(body)
        self.status_var.set("Press SPACE when ready.")
        self.footer_var.set(
            f"[RA] block.idx={block.idx} cond={condition} dur={block.duration_s}s"
        )

        # Wait for SPACE to begin.
        self._space_binding = self.app.root.bind("<space>", self._on_space, add="+")

    def on_leave(self) -> None:
        # Tear down event bindings + any pending after().
        if self._space_binding is not None:
            self.app.root.unbind("<space>", self._space_binding)
            self._space_binding = None
        if self._timer_id is not None:
            try:
                self.app.root.after_cancel(self._timer_id)
            except tk.TclError:
                pass
            self._timer_id = None

    # ---------------------------------------------------------------- handlers

    def _on_space(self, _event: object = None) -> None:
        if self._space_binding is None:
            return
        self.app.root.unbind("<space>", self._space_binding)
        self._space_binding = None
        self._begin_block()

    def _show_eyes_closed_view(self) -> None:
        """Black-screen view shown for the duration of the block.

        Hides the pre-block instructions; shows just "Your eyes should be
        closed.\\n\\nThis is the {TYPE} block." centered in the body.
        """
        block = self._block
        assert block is not None
        label = block_type_label(block.condition)
        self.title_var.set("")
        self.body_var.set(f"Your eyes should be closed.\n\nThis is the {label} block.")
        self.status_var.set("")

    def _begin_block(self) -> None:
        block = self._block
        assert block is not None
        # Swap the screen to the eyes-closed view immediately. The start gong
        # plays while this is shown; the screen stays put for the entire
        # block body, then we advance to the rating panel.
        self._show_eyes_closed_view()

        # Open writer record + emit block_start marker.
        self._block_start_lsl = self._lsl_now()
        if self.app.outlet is not None:
            try:
                _, ts = self.app.outlet.block_start(
                    idx=block.idx, condition=block.condition, duration_s=block.duration_s
                )
                self._block_start_lsl = ts
            except Exception:  # noqa: BLE001
                logger.exception("block_start marker push failed")
        if self.app.writer is not None:
            self._record = self.app.writer.start_block(
                idx=block.idx,
                condition=block.condition,
                duration_s=block.duration_s,
                start_lsl=self._block_start_lsl,
            )

        # Run the block in a worker thread (audio.play_block blocks).
        # The worker signals completion via _block_done_event; the Tk thread
        # polls the event from after(50, self._poll_block_done). Avoids
        # calling Tk methods from the non-Tk thread (not reliably thread-safe).
        self._block_done_event = threading.Event()
        self._worker = threading.Thread(target=self._run_block_in_worker, daemon=True)
        self._worker.start()
        self._poll_block_done()

    # ------------------------------------------------ worker-thread execution

    def _run_block_in_worker(self) -> None:
        block = self._block
        assert block is not None
        try:
            self._play_gong("start")

            if block.condition in ODDBALL_CONDITIONS:
                self._trials = self._run_oddball_block()
            else:
                # Silent block: just wait the configured duration.
                threading.Event().wait(block.duration_s)
                self._trials = None  # writer emits its silent-block default.

            self._play_gong("end")
        except Exception:
            logger.exception("block %s worker crashed", block.idx)
        finally:
            self._block_done_event.set()

    def _poll_block_done(self) -> None:
        """Tk-thread poller: every 50 ms, check whether the worker finished."""
        if self._block_done_event is not None and self._block_done_event.is_set():
            self._finish_block()
            return
        self._timer_id = self.app.root.after(50, self._poll_block_done)

    def _run_oddball_block(self) -> list[TrialRow]:
        block = self._block
        assert block is not None
        if self.app.audio_scheduler is None:
            logger.info("no audio_scheduler attached; sleeping %ds in lieu", block.duration_s)
            threading.Event().wait(block.duration_s)
            return []
        oddcfg = self.app.config.oddball
        # n trials chosen to fit duration; sequence freshly generated per block.
        from ..schedule import estimate_oddball_trial_count

        n = estimate_oddball_trial_count(
            duration_s=block.duration_s,
            isi_min_ms=oddcfg.isi_min_ms,
            isi_max_ms=oddcfg.isi_max_ms,
        )
        rng = random.Random()  # session-RNG already seeded the schedule itself
        sequence = generate_oddball_sequence(
            n_trials=n,
            deviant_probability=oddcfg.deviant_probability,
            min_standards_before_first_deviant=oddcfg.min_standards_before_first_deviant,
            min_standards_between_deviants=oddcfg.min_standards_between_deviants,
            max_consecutive_standards=oddcfg.max_consecutive_standards,
            rng=rng,
        )
        records = self.app.audio_scheduler.play_block(
            sequence=sequence,
            block_idx=block.idx,
            condition=block.condition,
            rng=rng,
        )
        return [
            TrialRow(
                trial_idx=r.trial_idx,
                t_lsl=r.onset_lsl,
                event="tone_onset",
                tone_type="deviant" if r.is_deviant else "standard",
            )
            for r in records
        ]

    def _play_gong(self, which: str) -> None:
        if self.app.audio_scheduler is None or self.app.outlet is None:
            # No hardware path — just emit the marker so analysis still has it.
            if self.app.outlet is not None:
                try:
                    if which == "start":
                        self.app.outlet.block_gong_start()
                    else:
                        self.app.outlet.block_gong_end()
                except Exception:  # noqa: BLE001
                    logger.exception("gong marker failed")
            return
        try:
            from ..config import REPO_ROOT

            play_gong(
                audio_config=self.app.config.audio,
                repo_root=REPO_ROOT,
                which=which,
                outlet=self.app.outlet,
                blocking=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("gong playback (%s) failed", which)

    # ------------------------------------------------------- end-of-block UI

    def _finish_block(self) -> None:
        block = self._block
        assert block is not None
        self._block_end_lsl = self._lsl_now()
        if self.app.outlet is not None:
            try:
                _, ts = self.app.outlet.block_end(idx=block.idx, condition=block.condition)
                self._block_end_lsl = ts
            except Exception:  # noqa: BLE001
                logger.exception("block_end marker push failed")

        if self.app.writer is not None and self._record is not None:
            self.app.writer.end_block(
                record=self._record,
                end_lsl=self._block_end_lsl,
                trials=self._trials,
                ratings=None,  # ratings are added by the next stage
                status="completed",
            )

        # Route to the right ratings panel.
        next_stage = (
            "ratings_chills" if block.condition in CHILLS_CONDITIONS else "ratings_rest"
        )
        self.app.show_stage(
            next_stage, block_idx=block.idx, condition=block.condition
        )

    # --------------------------------------------------------------- helpers

    def _lsl_now(self) -> float:
        try:
            from pylsl import local_clock

            return float(local_clock())
        except Exception:  # noqa: BLE001
            return 0.0
