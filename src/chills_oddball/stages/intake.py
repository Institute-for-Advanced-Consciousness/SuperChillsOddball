"""RA-facing intake screen: participant ID + pre-flight check + parameter review.

Shows:
  - Participant ID entry (auto-suggested = highest existing P{NNN} + 1)
  - A read-only summary of paradigm-fixed and operator-tunable params
  - "Begin Session" button that:
      1. resolves the RNG seed and generates the schedule,
      2. constructs the ToneScheduler + SessionWriter (PID-dependent),
      3. emits session_start / participant_id / session_config_seed markers
         on the outlet that was already opened at app boot
         (so LabRecorder sees the stream while the RA fills the checklist),
      4. advances to the volume_check stage.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Any

from .. import theme
from ..config import REPO_ROOT
from ..persistence import SessionWriter, next_participant_id
from ..schedule import generate_session_schedule, resolve_seed
from ._base import StageFrame

logger = logging.getLogger(__name__)


class IntakeFrame(StageFrame):
    NAME = "intake"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        # ---- Bottom strip: pin error + Begin button so they're always
        # ---- visible even if the body content is taller than the window.
        self._error_var = tk.StringVar(value="")
        tk.Label(
            self,
            textvariable=self._error_var,
            font=(cfg.font_family, cfg.font_size_normal),
            fg="#ff8888",
            bg=theme.CHROME_BG,
        ).pack(side="bottom", pady=(0, 6))

        self._begin_btn = tk.Button(
            self,
            text="Begin Session",
            font=(cfg.font_family, cfg.font_size_instruction, "bold"),
            width=24,
            state="disabled",
            command=self._on_begin,
            padx=12,
            pady=8,
            **theme.PRIMARY_BUTTON,
        )
        self._begin_btn.pack(side="bottom", pady=(4, 8))

        # ---- Top strip: heading + sub + PID row.
        tk.Label(
            self,
            text=f"{self.app.config.session.protocol_label}",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=(12, 2))
        tk.Label(
            self,
            text=f"protocol: {self.app.config.session.protocol_id}",
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=(0, 6))

        pid_row = tk.Frame(self, bg=theme.CHROME_BG)
        pid_row.pack(side="top", pady=4)
        tk.Label(
            pid_row,
            text="Participant ID:",
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
        ).pack(side="left", padx=10)
        self._pid_var = tk.StringVar(value="")
        tk.Entry(
            pid_row,
            textvariable=self._pid_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            width=12,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            insertbackground=theme.ACCENT_LIGHT,
            relief="flat",
            highlightthickness=2,
            highlightbackground=theme.ACCENT_DARK,
            highlightcolor=theme.ACCENT_LIGHT,
        ).pack(side="left")

        # ---- Middle: two-column body fills whatever vertical space is
        # ---- left between the top strip and the pinned bottom strip.
        body = tk.Frame(self, bg=theme.CHROME_BG)
        body.pack(side="top", fill="both", expand=True, padx=24, pady=8)
        body.grid_columnconfigure(0, weight=1, uniform="cols")
        body.grid_columnconfigure(1, weight=1, uniform="cols")
        body.grid_rowconfigure(0, weight=1)

        # Smaller `height` request so on short screens the Text widget
        # shrinks rather than pushing the button off the bottom.
        self._summary_text = tk.Text(
            body, width=40, height=8,
            font=(cfg.font_family, cfg.font_size_normal),
            bg=theme.SURFACE, fg=theme.TEXT, relief="flat",
            insertbackground=theme.ACCENT_LIGHT,
            highlightthickness=1,
            highlightbackground=theme.DIVIDER,
            wrap="word",
        )
        self._summary_text.grid(row=0, column=0, padx=8, sticky="nsew")

        self._preflight_frame = tk.Frame(
            body, bg=theme.SURFACE, padx=14, pady=10,
            highlightthickness=1,
            highlightbackground=theme.DIVIDER,
        )
        self._preflight_frame.grid(row=0, column=1, padx=8, sticky="nsew")

        tk.Label(
            self._preflight_frame,
            text="PRE-FLIGHT CHECKLIST",
            font=(cfg.font_family, cfg.font_size_normal, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.SURFACE,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 4))
        tk.Label(
            self._preflight_frame,
            text="Tick every item before launching:",
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=theme.TEXT,
            bg=theme.SURFACE,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 6))

        preflight_items = [
            f"LabRecorder is running and recording the "
            f"`{self.app.config.lsl.stream_name}` stream "
            f"(plus EEG + CGX AIM-2 streams)",
            "Headphones plugged in and on the participant",
            "Audio device verified (volume check is next)",
            "Participant briefed and consent on file",
        ]
        self._preflight_vars: list[tk.BooleanVar] = []
        for item in preflight_items:
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *_: self._update_begin_button_state())
            self._preflight_vars.append(var)
            cb = tk.Checkbutton(
                self._preflight_frame,
                text=item,
                variable=var,
                font=(cfg.font_family, cfg.font_size_normal),
                fg=theme.TEXT,
                bg=theme.SURFACE,
                activebackground=theme.SURFACE,
                activeforeground=theme.ACCENT_LIGHT,
                selectcolor=theme.ACCENT_DARK,
                anchor="w",
                justify="left",
                wraplength=420,
                padx=4,
                pady=2,
                cursor="hand2",
            )
            cb.pack(fill="x", anchor="w")
            self.register_wrappable(cb, ratio=0.42, min_px=300)

        tk.Label(
            self._preflight_frame,
            text=(
                "The LSL marker stream is already broadcasting — "
                "confirm LabRecorder sees it before continuing. "
                "Begin Session will generate the block schedule "
                "and open the participant data folder."
            ),
            font=(cfg.font_family, cfg.font_size_normal - 2, "italic"),
            fg=theme.TEXT_MUTED,
            bg=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------ on_enter

    def on_enter(self, **_: Any) -> None:
        # Auto-suggest the next participant ID.
        data_root = Path(self.app.config.session.data_root_dir)
        if not data_root.is_absolute():
            data_root = REPO_ROOT / data_root
        self._pid_var.set(
            next_participant_id(
                data_root=data_root,
                prefix=self.app.config.session.participant_id_prefix,
                zfill=self.app.config.session.participant_id_zfill,
            )
        )
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        self._summary_text.insert("1.0", self._format_summary())
        self._summary_text.configure(state="disabled")

        for var in self._preflight_vars:
            var.set(False)
        self._update_begin_button_state()
        self._error_var.set("")

    def _format_summary(self) -> str:
        cfg = self.app.config
        lines = [
            "PARADIGM (fixed)",
            "  Tones: 1000 Hz / 2000 Hz, 100 ms, 10 ms cosine ramps",
            f"  Ratio: 80% std / 20% dev   ISI: {cfg.oddball.isi_min_ms}–{cfg.oddball.isi_max_ms} ms",
            f"  Constraints: ≥{cfg.oddball.min_standards_before_first_deviant} std before first dev,",
            f"               ≥{cfg.oddball.min_standards_between_deviants} std between dev,",
            f"               max {cfg.oddball.max_consecutive_standards} consecutive std",
            "",
            "SCHEDULE",
            f"  Conditions: {', '.join(cfg.schedule.conditions)}",
            f"  Per condition: {cfg.schedule.n_blocks_per_condition} blocks at {cfg.schedule.block_duration_set_s} s",
            f"  Calibration first ({cfg.calibration.duration_s} s) | active oddball last",
            f"  Seed strategy: {cfg.schedule.seed_strategy}",
            "",
            "ACTIVE ODDBALL",
            f"  Total trials: {cfg.active_oddball.total_trials}  (~{cfg.active_oddball.duration_target_s} s)",
            f"  Practice gate: ≥{cfg.active_oddball.practice.hit_threshold:.0%} hits, "
            f"≤{cfg.active_oddball.practice.fa_ceiling:.0%} false alarms",
            f"  Response window: {cfg.oddball.response_window_ms} ms",
            "",
            "AUDIO",
            f"  Sample rate: {cfg.audio.sample_rate_hz} Hz   Channels: {cfg.audio.channels}",
            f"  Tone level: {cfg.audio.tone_volume_dbfs:+.1f} dBFS RMS",
            f"  Device: {cfg.audio.device_name or 'system default'}",
        ]
        return "\n".join(lines)

    def _update_begin_button_state(self) -> None:
        all_checked = all(v.get() for v in self._preflight_vars)
        self._begin_btn.configure(state="normal" if all_checked else "disabled")

    # ------------------------------------------------------------ begin

    def _on_begin(self) -> None:
        pid = self._pid_var.get().strip()
        if not pid:
            self._error_var.set("Participant ID required.")
            return
        try:
            self._initialize_services(pid)
        except Exception as e:  # noqa: BLE001 — display + log
            logger.exception("session start failed")
            self._error_var.set(f"Failed to start: {e}")
            return
        self.app.show_stage("volume_check")

    def _initialize_services(self, pid: str) -> None:
        from ..audio import ToneScheduler

        cfg = self.app.config

        # Resolve schedule + seed.
        seed = resolve_seed(cfg, participant_id=pid)
        self.app.schedule = generate_session_schedule(cfg, seed=seed, participant_id=pid)
        self.app.rng_seed = seed

        # The marker outlet was opened at app boot (so LabRecorder
        # discovers the stream while the RA fills the checklist).
        outlet = self.app.outlet
        if outlet is None or not outlet.is_open:
            raise RuntimeError(
                "LSL outlet is not open — app boot may have failed to create it."
            )

        # Open SessionWriter.
        data_root = Path(cfg.session.data_root_dir)
        if not data_root.is_absolute():
            data_root = REPO_ROOT / data_root
        writer = SessionWriter(
            data_root=data_root,
            participant_id=pid,
            config_snapshot=cfg.model_dump(mode="json"),
            schedule=self.app.schedule,
            rng_seed=seed,
        )
        self.app.writer = writer
        self.app.participant_id = pid

        # Construct ToneScheduler (loads tone .wav files; will raise if missing).
        scheduler = ToneScheduler(
            audio_config=cfg.audio,
            oddball_config=cfg.oddball,
            outlet=outlet,
            repo_root=REPO_ROOT,
        )
        self.app.audio_scheduler = scheduler

        # Emit session-level markers.
        outlet.session_start()
        outlet.participant_id(pid)
        outlet.session_config_seed(seed)
        logger.info("session started: pid=%s seed=%d", pid, seed)
