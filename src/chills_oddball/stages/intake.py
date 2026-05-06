"""RA-facing intake screen: participant ID + pre-flight check + parameter review.

Shows:
  - Participant ID entry (auto-suggested = highest existing P{NNN} + 1)
  - A read-only summary of paradigm-fixed and operator-tunable params
  - "Begin Session" button that:
      1. resolves the RNG seed and generates the schedule,
      2. opens the LSL outlet + ToneScheduler + SessionWriter,
      3. emits session_start / participant_id / session_config_seed markers,
      4. advances to the volume_check stage.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT
from ..persistence import SessionWriter, next_participant_id
from ..schedule import generate_session_schedule, resolve_seed
from ._base import StageFrame

logger = logging.getLogger(__name__)


class IntakeFrame(StageFrame):
    NAME = "intake"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=cfg.background_color)

        tk.Label(
            self,
            text=f"{self.app.config.session.protocol_label}",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=cfg.text_color,
            bg=cfg.background_color,
        ).pack(pady=(40, 6))
        tk.Label(
            self,
            text=f"protocol: {self.app.config.session.protocol_id}",
            font=(cfg.font_family, cfg.font_size_normal, "italic"),
            fg=cfg.text_color,
            bg=cfg.background_color,
        ).pack(pady=(0, 20))

        # Participant ID row.
        pid_row = tk.Frame(self, bg=cfg.background_color)
        pid_row.pack(pady=10)
        tk.Label(
            pid_row,
            text="Participant ID:",
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=cfg.text_color,
            bg=cfg.background_color,
        ).pack(side="left", padx=10)
        self._pid_var = tk.StringVar(value="")
        tk.Entry(
            pid_row,
            textvariable=self._pid_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            width=12,
        ).pack(side="left")

        # Two-column body: parameter summary | pre-flight.
        body = tk.Frame(self, bg=cfg.background_color)
        body.pack(fill="both", expand=True, padx=40, pady=20)

        self._summary_text = tk.Text(
            body, width=60, height=18,
            font=(cfg.font_family, cfg.font_size_normal),
            bg="#1a1a1a", fg=cfg.text_color, relief="flat",
        )
        self._summary_text.pack(side="left", padx=10, fill="both", expand=True)

        self._preflight_text = tk.Text(
            body, width=40, height=18,
            font=(cfg.font_family, cfg.font_size_normal),
            bg="#1a1a1a", fg=cfg.text_color, relief="flat",
        )
        self._preflight_text.pack(side="left", padx=10, fill="both", expand=True)

        self._begin_btn = tk.Button(
            self,
            text="Begin Session",
            font=(cfg.font_family, cfg.font_size_instruction, "bold"),
            width=24,
            command=self._on_begin,
        )
        self._begin_btn.pack(pady=20)

        self._error_var = tk.StringVar(value="")
        tk.Label(
            self,
            textvariable=self._error_var,
            font=(cfg.font_family, cfg.font_size_normal),
            fg="#ff6666",
            bg=cfg.background_color,
        ).pack(pady=(0, 10))

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

        self._preflight_text.configure(state="normal")
        self._preflight_text.delete("1.0", "end")
        self._preflight_text.insert("1.0", self._format_preflight())
        self._preflight_text.configure(state="disabled")
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

    def _format_preflight(self) -> str:
        # Static checks (the dynamic checks happen on _on_begin).
        return (
            "PRE-FLIGHT CHECKLIST\n\n"
            "  [ ] LabRecorder is running and recording the\n"
            f"      `{self.app.config.lsl.stream_name}` stream\n"
            "      (plus EEG + CGX AIM-2 streams)\n\n"
            "  [ ] Headphones plugged in and on the participant\n\n"
            "  [ ] Audio device verified (volume check is next)\n\n"
            "  [ ] Participant briefed and consent on file\n\n"
            "Click Begin Session to:\n"
            "  • create LSL marker outlet\n"
            "  • generate the block schedule (random per session)\n"
            "  • open the participant data folder\n"
        )

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
        from ..markers import ChillsMarkerOutlet

        cfg = self.app.config

        # Resolve schedule + seed.
        seed = resolve_seed(cfg, participant_id=pid)
        self.app.schedule = generate_session_schedule(cfg, seed=seed, participant_id=pid)
        self.app.rng_seed = seed

        # Open marker outlet.
        outlet = ChillsMarkerOutlet(cfg.lsl)
        outlet.open()
        self.app.outlet = outlet

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
