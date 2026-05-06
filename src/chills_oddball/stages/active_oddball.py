"""Final active oddball block: practice gate + main 250-trial run.

Phases:
  intro          Show instructions; SPACE -> practice
  practice       10-trial block (8 std + 2 dev). Score; if pass -> post_practice,
                 else replay practice.
  post_practice  "Great" screen; SPACE -> main
  main           250-trial block; SPACE responses captured live.
  engagement     Single 0–10 slider + auto summary; Submit -> completion.

Two pure helpers are extracted so the response classifier and the
practice gate can be unit-tested without Tk:

    classify_responses(tone_records, press_times, window_s) -> list[ResponseRecord]
    evaluate_practice(records, n_deviants, n_standards, hit_threshold, fa_ceiling)

Audio playback uses ToneScheduler.play_block(..., practice=True/False) so
the same callback-based scheduler emits the right marker variant for
each phase.
"""

from __future__ import annotations

import logging
import random
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Any

from .. import theme
from ..audio import TrialRecord
from ..persistence import TrialRow
from ..schedule import ScheduledBlock, generate_oddball_sequence
from ._base import StageFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no Tk; fully testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponseRecord:
    """Per-tone outcome computed from press/tone timestamps."""

    trial_idx: int
    is_deviant: bool
    onset_lsl: float
    kind: str  # "hit" | "miss" | "false_alarm" | "correct_rejection"
    rt_ms: int | None  # press latency for hit/FA; None for miss/CR


def classify_responses(
    tone_records: list[TrialRecord],
    press_times: list[float],
    window_s: float,
) -> list[ResponseRecord]:
    """Attribute presses to tones; classify each tone.

    A press is attributed to the first un-claimed tone whose onset falls
    in ``[press - window_s, press]`` (i.e. the most recent tone within the
    response window). Once a press is consumed by a tone, no later tone
    can receive it.

    Each tone is classified as:
      deviant + has press        -> hit (with rt)
      deviant + no press         -> miss
      standard + has press       -> false_alarm (with rt)
      standard + no press        -> correct_rejection
    """
    consumed_press_indices: set[int] = set()
    out: list[ResponseRecord] = []
    sorted_tones = sorted(tone_records, key=lambda t: t.onset_lsl)

    for tone in sorted_tones:
        match_idx = None
        for i, pt in enumerate(press_times):
            if i in consumed_press_indices:
                continue
            if tone.onset_lsl <= pt <= tone.onset_lsl + window_s:
                match_idx = i
                break
        if match_idx is not None:
            consumed_press_indices.add(match_idx)
            rt_ms = int(round((press_times[match_idx] - tone.onset_lsl) * 1000.0))
            kind = "hit" if tone.is_deviant else "false_alarm"
        else:
            kind = "miss" if tone.is_deviant else "correct_rejection"
            rt_ms = None
        out.append(
            ResponseRecord(
                trial_idx=tone.trial_idx,
                is_deviant=tone.is_deviant,
                onset_lsl=tone.onset_lsl,
                kind=kind,
                rt_ms=rt_ms,
            )
        )
    out.sort(key=lambda r: r.trial_idx)
    return out


@dataclass(frozen=True)
class PracticeOutcome:
    n_hits: int
    n_misses: int
    n_false_alarms: int
    n_correct_rejections: int
    hit_rate: float
    fa_rate: float
    passed: bool


def evaluate_practice(
    records: list[ResponseRecord],
    *,
    hit_threshold: float,
    fa_ceiling: float,
) -> PracticeOutcome:
    """Apply the practice gate to a classified set of responses."""
    n_dev = sum(1 for r in records if r.is_deviant)
    n_std = sum(1 for r in records if not r.is_deviant)
    hits = sum(1 for r in records if r.kind == "hit")
    misses = sum(1 for r in records if r.kind == "miss")
    fas = sum(1 for r in records if r.kind == "false_alarm")
    crs = sum(1 for r in records if r.kind == "correct_rejection")
    hit_rate = hits / n_dev if n_dev else 0.0
    fa_rate = fas / n_std if n_std else 0.0
    passed = (hit_rate >= hit_threshold) and (fa_rate <= fa_ceiling)
    return PracticeOutcome(
        n_hits=hits,
        n_misses=misses,
        n_false_alarms=fas,
        n_correct_rejections=crs,
        hit_rate=hit_rate,
        fa_rate=fa_rate,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------


PHASE_INTRO = "intro"
PHASE_PRACTICE = "practice"
PHASE_POST_PRACTICE = "post_practice"
PHASE_MAIN = "main"
PHASE_ENGAGEMENT = "engagement"


class ActiveOddballFrame(StageFrame):
    NAME = "active_oddball"

    def build(self) -> None:
        cfg = self.app.config.display
        # Default to chrome; _start_main flips to task mode for the responding block.
        self.configure(bg=theme.CHROME_BG)

        self.title_var = tk.StringVar(value="Active oddball")
        self.body_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.footer_var = tk.StringVar(value="")

        self._title_label = tk.Label(
            self,
            textvariable=self.title_var,
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        )
        self._title_label.pack(pady=(40, 10))

        self._body_label = tk.Label(
            self,
            textvariable=self.body_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
            wraplength=900,
            justify="center",
        )
        self._body_label.pack(pady=10)

        self._status_label = tk.Label(
            self,
            textvariable=self.status_var,
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.CHROME_BG,
        )
        self._status_label.pack(pady=10)

        # Engagement slider container (built lazily in _show_engagement).
        self._engagement_frame = tk.Frame(self, bg=theme.CHROME_BG)
        self._engagement_frame.pack(pady=10)

        self._summary_label = tk.Label(
            self,
            textvariable=self.summary_var,
            font=(cfg.font_family, cfg.font_size_normal),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
            justify="left",
        )
        self._summary_label.pack(pady=20)

        self._footer_label: tk.Label | None = None
        if cfg.ra_footer_visible:
            self._footer_label = tk.Label(
                self,
                textvariable=self.footer_var,
                font=(cfg.font_family, cfg.font_size_normal),
                fg=theme.TEXT_MUTED,
                bg=theme.CHROME_BG,
            )
            self._footer_label.pack(side="bottom", pady=10)

        # Per-entry state.
        self._block: ScheduledBlock | None = None
        self._record = None
        self._phase: str = PHASE_INTRO
        self._practice_attempt: int = 0
        self._press_log: list[float] = []
        self._press_binding: str | None = None
        self._space_binding: str | None = None
        self._main_records: list[ResponseRecord] | None = None
        self._main_outcome: dict[str, Any] | None = None
        self._worker: threading.Thread | None = None
        self._worker_done: threading.Event | None = None
        self._worker_records: list[TrialRecord] | None = None
        self._timer_id: str | None = None
        self._engagement_var: tk.IntVar | None = None
        self._engagement_widgets: list[tk.Widget] = []

    # ---------------------------------------------------------------- lifecycle

    def on_enter(self, *, block: ScheduledBlock | None = None, **_: Any) -> None:
        if block is None:
            raise ValueError("active_oddball requires `block=` payload")
        self._block = block
        self._practice_attempt = 0
        self._main_records = None
        self._main_outcome = None
        self._apply_chrome_theme()
        self._show_intro()

    def _apply_task_theme(self) -> None:
        """Switch frame + child widgets to pure black/white task mode."""
        self.configure(bg=theme.TASK_BG)
        for w in (self._title_label, self._body_label, self._status_label,
                  self._summary_label, self._engagement_frame):
            w.configure(bg=theme.TASK_BG)
        for w in (self._title_label, self._body_label, self._status_label,
                  self._summary_label):
            w.configure(fg=theme.TASK_TEXT)
        if self._footer_label is not None:
            self._footer_label.configure(bg=theme.TASK_BG, fg="#444444")

    def _apply_chrome_theme(self) -> None:
        """Restore the IACS chrome theme (used outside the main responding block)."""
        self.configure(bg=theme.CHROME_BG)
        self._engagement_frame.configure(bg=theme.CHROME_BG)
        self._title_label.configure(bg=theme.CHROME_BG, fg=theme.ACCENT_LIGHT)
        self._body_label.configure(bg=theme.CHROME_BG, fg=theme.TEXT)
        self._status_label.configure(bg=theme.CHROME_BG, fg=theme.TEXT_MUTED)
        self._summary_label.configure(bg=theme.CHROME_BG, fg=theme.TEXT)
        if self._footer_label is not None:
            self._footer_label.configure(bg=theme.CHROME_BG, fg=theme.TEXT_MUTED)

    def on_leave(self) -> None:
        self._unbind_all()
        if self._timer_id is not None:
            try:
                self.app.root.after_cancel(self._timer_id)
            except tk.TclError:
                pass
            self._timer_id = None

    def _unbind_all(self) -> None:
        if self._space_binding is not None:
            self.app.root.unbind("<space>", self._space_binding)
            self._space_binding = None
        if self._press_binding is not None:
            self.app.root.unbind("<space>", self._press_binding)
            self._press_binding = None

    # ---------------------------------------------------------------- intro

    def _show_intro(self) -> None:
        self._phase = PHASE_INTRO
        self._unbind_all()
        self.title_var.set("Active oddball — instructions")
        self.body_var.set(
            self.app.config.instructions.get(
                "active_oddball_intro",
                "Press SPACE on the HIGH tones. SPACE to begin practice.",
            )
        )
        self.status_var.set("Press SPACE when ready.")
        self.summary_var.set("")
        self.footer_var.set("[RA] phase=intro")
        self._space_binding = self.app.root.bind("<space>", self._on_intro_space, add="+")

    def _on_intro_space(self, _e: object = None) -> None:
        if self._space_binding is None:
            return
        self.app.root.unbind("<space>", self._space_binding)
        self._space_binding = None
        self._start_practice()

    # ------------------------------------------------------------ practice

    def _start_practice(self) -> None:
        self._phase = PHASE_PRACTICE
        self._practice_attempt += 1
        self._press_log = []
        self.title_var.set(f"Practice (attempt {self._practice_attempt})")
        self.body_var.set("Listen — press SPACE on the HIGH tones only.")
        self.status_var.set("Practice in progress…")
        self.footer_var.set(f"[RA] phase=practice attempt={self._practice_attempt}")

        if self.app.outlet is not None:
            try:
                self.app.outlet.active_practice_start(attempt=self._practice_attempt)
            except Exception:  # noqa: BLE001
                logger.exception("active_practice_start marker failed")

        # 10 trials, 8 std + 2 dev, with relaxed spacing for the short block.
        practice_cfg = self.app.config.active_oddball.practice
        rng = random.Random()
        sequence = generate_oddball_sequence(
            n_trials=practice_cfg.n_trials,
            deviant_probability=practice_cfg.n_deviants / practice_cfg.n_trials,
            min_standards_before_first_deviant=2,
            min_standards_between_deviants=2,
            max_consecutive_standards=practice_cfg.n_trials,  # don't constrain
            rng=rng,
        )
        self._press_binding = self.app.root.bind("<space>", self._on_response_press, add="+")
        self._launch_audio_worker(sequence=sequence, practice=True)

    def _on_practice_audio_done(self) -> None:
        if self.app.outlet is not None:
            try:
                self.app.outlet.active_practice_end(attempt=self._practice_attempt)
            except Exception:  # noqa: BLE001
                logger.exception("active_practice_end marker failed")
        if self._press_binding is not None:
            self.app.root.unbind("<space>", self._press_binding)
            self._press_binding = None

        records = self._worker_records or []
        results = classify_responses(
            tone_records=records,
            press_times=list(self._press_log),
            window_s=self.app.config.oddball.response_window_ms / 1000.0,
        )
        practice_cfg = self.app.config.active_oddball.practice
        outcome = evaluate_practice(
            records=results,
            hit_threshold=practice_cfg.hit_threshold,
            fa_ceiling=practice_cfg.fa_ceiling,
        )

        if outcome.passed:
            if self.app.outlet is not None:
                try:
                    self.app.outlet.active_practice_passed()
                except Exception:  # noqa: BLE001
                    logger.exception("active_practice_passed marker failed")
            self._show_post_practice(outcome)
            return

        # Failed — gate the retry on max_attempts (None = unlimited).
        max_attempts = practice_cfg.max_attempts
        if max_attempts is not None and self._practice_attempt >= max_attempts:
            logger.warning(
                "practice gate failed after %d attempts; proceeding to main anyway",
                self._practice_attempt,
            )
            self._show_post_practice(outcome)
            return

        self._show_practice_failed(outcome)

    def _show_practice_failed(self, outcome: PracticeOutcome) -> None:
        self._phase = PHASE_INTRO  # acts like a re-intro for the next attempt
        self._unbind_all()
        self.title_var.set("Practice — let's try again")
        self.body_var.set(
            self.app.config.instructions.get(
                "active_practice_fail",
                "Let's try the practice again. Press SPACE only on the HIGH tones.",
            )
        )
        self.status_var.set(
            f"Last attempt: hits {outcome.hit_rate:.0%}, false alarms {outcome.fa_rate:.0%}.\n"
            f"Press SPACE to retry."
        )
        self._space_binding = self.app.root.bind("<space>", self._on_intro_space, add="+")

    def _show_post_practice(self, outcome: PracticeOutcome) -> None:
        self._phase = PHASE_POST_PRACTICE
        self._unbind_all()
        self.title_var.set("Practice complete")
        self.body_var.set(
            self.app.config.instructions.get(
                "active_practice_pass",
                "Great — press SPACE to start the main block.",
            )
        )
        self.status_var.set(
            f"Practice: hits {outcome.hit_rate:.0%}, false alarms {outcome.fa_rate:.0%}."
        )
        self._space_binding = self.app.root.bind("<space>", self._on_post_practice_space, add="+")

    def _on_post_practice_space(self, _e: object = None) -> None:
        if self._space_binding is None:
            return
        self.app.root.unbind("<space>", self._space_binding)
        self._space_binding = None
        self._start_main()

    # ------------------------------------------------------------ main

    def _start_main(self) -> None:
        block = self._block
        assert block is not None
        self._phase = PHASE_MAIN
        self._press_log = []
        # Active-main is the responding phase — flip to pure black/white
        # task mode so the chrome doesn't distract from listening.
        self._apply_task_theme()
        # Eyes-closed view tailored for the active block (still need the
        # spacebar reminder since this is the responding phase).
        self.title_var.set("")
        self.body_var.set(
            "Your eyes should be closed.\n\n"
            "This is the ACTIVE LISTENING block.\n\n"
            "Press SPACE on every HIGH tone."
        )
        self.status_var.set("")
        self.footer_var.set(f"[RA] phase=main block.idx={block.idx}")

        # Open writer record + emit block_start.
        block_start_lsl = self._lsl_now()
        if self.app.outlet is not None:
            try:
                _, ts = self.app.outlet.block_start(
                    idx=block.idx, condition=block.condition, duration_s=block.duration_s
                )
                block_start_lsl = ts
            except Exception:  # noqa: BLE001
                logger.exception("block_start marker failed")
        if self.app.writer is not None:
            self._record = self.app.writer.start_block(
                idx=block.idx,
                condition=block.condition,
                duration_s=block.duration_s,
                start_lsl=block_start_lsl,
            )

        # Generate the 250-trial sequence subject to all paradigm constraints.
        oddcfg = self.app.config.oddball
        rng = random.Random()
        sequence = generate_oddball_sequence(
            n_trials=self.app.config.active_oddball.total_trials,
            deviant_probability=oddcfg.deviant_probability,
            min_standards_before_first_deviant=oddcfg.min_standards_before_first_deviant,
            min_standards_between_deviants=oddcfg.min_standards_between_deviants,
            max_consecutive_standards=oddcfg.max_consecutive_standards,
            rng=rng,
        )

        self._press_binding = self.app.root.bind("<space>", self._on_response_press, add="+")
        self._launch_audio_worker(sequence=sequence, practice=False)

    def _on_main_audio_done(self) -> None:
        block = self._block
        assert block is not None
        if self._press_binding is not None:
            self.app.root.unbind("<space>", self._press_binding)
            self._press_binding = None

        records = self._worker_records or []
        results = classify_responses(
            tone_records=records,
            press_times=list(self._press_log),
            window_s=self.app.config.oddball.response_window_ms / 1000.0,
        )
        self._main_records = results

        # Emit per-trial response markers (post-hoc, with real press timestamps).
        if self.app.outlet is not None:
            for r in results:
                try:
                    if r.kind == "hit":
                        self.app.outlet.active_response_hit(rt_ms=r.rt_ms)
                    elif r.kind == "miss":
                        self.app.outlet.active_response_miss()
                    elif r.kind == "false_alarm":
                        self.app.outlet.active_response_false_alarm(rt_ms=r.rt_ms)
                except Exception:  # noqa: BLE001
                    logger.exception("response marker push failed")

        # Build CSV rows: tone_onset rows + response rows for trials with presses.
        rows: list[TrialRow] = []
        for r in results:
            rows.append(
                TrialRow(
                    trial_idx=r.trial_idx,
                    t_lsl=r.onset_lsl,
                    event="tone_onset",
                    tone_type="deviant" if r.is_deviant else "standard",
                )
            )
            if r.kind in ("hit", "false_alarm"):
                rows.append(
                    TrialRow(
                        trial_idx=r.trial_idx,
                        t_lsl=r.onset_lsl + (r.rt_ms or 0) / 1000.0,
                        event="response",
                        tone_type="deviant" if r.is_deviant else "standard",
                        response=r.kind,
                        rt_ms=r.rt_ms,
                    )
                )

        block_end_lsl = self._lsl_now()
        if self.app.outlet is not None:
            try:
                _, ts = self.app.outlet.block_end(idx=block.idx, condition=block.condition)
                block_end_lsl = ts
            except Exception:  # noqa: BLE001
                logger.exception("block_end marker failed")

        if self.app.writer is not None and self._record is not None:
            self.app.writer.end_block(
                record=self._record,
                end_lsl=block_end_lsl,
                trials=rows,
                ratings=None,
                status="completed",
            )

        # Compute summary numbers for the engagement screen + writer.
        n_hits = sum(1 for r in results if r.kind == "hit")
        n_misses = sum(1 for r in results if r.kind == "miss")
        n_fas = sum(1 for r in results if r.kind == "false_alarm")
        rts = [r.rt_ms for r in results if r.kind == "hit" and r.rt_ms is not None]
        mean_rt_ms = (sum(rts) / len(rts)) if rts else None
        self._main_outcome = {
            "practice_attempts": self._practice_attempt,
            "practice_passed": True,
            "main_total_trials": len(results),
            "main_hits": n_hits,
            "main_misses": n_misses,
            "main_false_alarms": n_fas,
            "mean_rt_ms": mean_rt_ms,
        }

        self._show_engagement()

    # ------------------------------------------------------------ engagement

    def _show_engagement(self) -> None:
        self._phase = PHASE_ENGAGEMENT
        self._unbind_all()
        cfg = self.app.config.display
        # Returning from task-mode main block; restore the chrome.
        self._apply_chrome_theme()
        self.title_var.set("Active oddball complete")
        self.body_var.set("How engaged did you feel during that block?")
        self.status_var.set("Move the slider, then click Submit.")

        # Build the slider lazily.
        for w in self._engagement_widgets:
            w.destroy()
        self._engagement_widgets.clear()

        self._engagement_var = tk.IntVar(value=5)
        scale = tk.Scale(
            self._engagement_frame,
            from_=0,
            to=10,
            orient="horizontal",
            variable=self._engagement_var,
            length=500,
            bg=theme.CHROME_BG,
            fg=theme.TEXT,
            highlightthickness=0,
            troughcolor=theme.SURFACE_RAISED,
            activebackground=theme.ACCENT_LIGHT,
        )
        scale.pack(pady=8)
        self._engagement_widgets.append(scale)

        anchor = tk.Label(
            self._engagement_frame,
            text="0 = not engaged    10 = fully engaged",
            font=(cfg.font_family, cfg.font_size_normal - 2, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.CHROME_BG,
        )
        anchor.pack()
        self._engagement_widgets.append(anchor)

        submit = tk.Button(
            self._engagement_frame,
            text="Submit",
            font=(cfg.font_family, cfg.font_size_normal, "bold"),
            width=20,
            command=self._on_engagement_submit,
            padx=10,
            pady=6,
            **theme.PRIMARY_BUTTON,
        )
        submit.pack(pady=15)
        self._engagement_widgets.append(submit)

        # Auto-summary.
        if self._main_outcome:
            mo = self._main_outcome
            n_dev = mo["main_hits"] + mo["main_misses"]
            hit_pct = (mo["main_hits"] / n_dev * 100) if n_dev else 0.0
            n_std = (
                mo["main_total_trials"] - n_dev
            ) if mo["main_total_trials"] else 0
            fa_pct = (mo["main_false_alarms"] / n_std * 100) if n_std else 0.0
            mean_rt = mo["mean_rt_ms"]
            mean_rt_text = f"{mean_rt:.0f} ms" if mean_rt is not None else "n/a"
            self.summary_var.set(
                f"Hits: {mo['main_hits']} / {n_dev}  ({hit_pct:.0f}%)\n"
                f"False alarms: {mo['main_false_alarms']} / {n_std}  ({fa_pct:.0f}%)\n"
                f"Mean RT: {mean_rt_text}"
            )

    def _on_engagement_submit(self) -> None:
        engagement = int(self._engagement_var.get()) if self._engagement_var else None
        if self._main_outcome is not None and engagement is not None:
            self._main_outcome["engagement_rating"] = engagement
            if self.app.writer is not None:
                self.app.writer.set_active_oddball_summary(self._main_outcome)
        # Active oddball is the last block; advance routes to completion.
        block = self._block
        assert block is not None
        self.app.advance_after_block(block.idx)

    # ------------------------------------------------------------ shared

    def _on_response_press(self, _e: object = None) -> None:
        self._press_log.append(self._lsl_now())

    def _launch_audio_worker(self, *, sequence: list[bool], practice: bool) -> None:
        """Run ToneScheduler.play_block in a worker; poll for completion."""
        self._worker_records = None
        self._worker_done = threading.Event()

        block = self._block
        assert block is not None
        # Capture in closure
        scheduler = self.app.audio_scheduler

        def _runner() -> None:
            try:
                if scheduler is not None:
                    rng = random.Random()
                    self._worker_records = scheduler.play_block(
                        sequence=sequence,
                        block_idx=block.idx,
                        condition=block.condition,
                        rng=rng,
                        practice=practice,
                    )
                else:
                    # No hardware path: fabricate records with synthetic timestamps
                    # so classification still has something to work with.
                    now = self._lsl_now()
                    self._worker_records = [
                        TrialRecord(
                            trial_idx=i,
                            is_deviant=bool(s),
                            onset_sample=i * 1000,
                            onset_lsl=now + i * 1.3,
                        )
                        for i, s in enumerate(sequence)
                    ]
            except Exception:
                logger.exception("active oddball worker crashed")
            finally:
                self._worker_done.set()

        self._worker = threading.Thread(target=_runner, daemon=True)
        self._worker.start()
        self._poll_audio_done(practice=practice)

    def _poll_audio_done(self, *, practice: bool) -> None:
        if self._worker_done is not None and self._worker_done.is_set():
            if practice:
                self._on_practice_audio_done()
            else:
                self._on_main_audio_done()
            return
        self._timer_id = self.app.root.after(50, lambda: self._poll_audio_done(practice=practice))

    def _lsl_now(self) -> float:
        try:
            from pylsl import local_clock

            return float(local_clock())
        except Exception:  # noqa: BLE001
            return 0.0
