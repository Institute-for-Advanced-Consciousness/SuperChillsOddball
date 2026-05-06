"""Completion screen: summary stats + Save & Exit.

On entry, summarizes the session from the writer's records (chills
success rate, mean intensity from chills ratings, P300 hit rate /
false-alarm rate / mean RT from the active oddball summary).

Save & Exit:
  1. Emits ``session_end`` marker.
  2. Calls ``writer.finalize(status="completed")`` (writes session.json
     and deletes PARTIAL_session.json).
  3. Closes the LSL outlet.
  4. Destroys the Tk root.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

from .. import theme
from ._base import StageFrame

logger = logging.getLogger(__name__)


class CompletionFrame(StageFrame):
    NAME = "completion"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        tk.Label(
            self,
            text="Session complete",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=(30, 10))

        self.body_var = tk.StringVar(
            value=self.app.config.instructions.get(
                "completion", "Thank you for participating!"
            )
        )
        tk.Label(
            self,
            textvariable=self.body_var,
            font=(cfg.font_family, cfg.font_size_instruction),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=10)

        # Pin Save & Exit to the bottom so the RA can always reach it.
        tk.Button(
            self,
            text="Save & Exit",
            font=(cfg.font_family, cfg.font_size_instruction, "bold"),
            width=24,
            command=self._on_save_and_exit,
            padx=12,
            pady=8,
            **theme.PRIMARY_BUTTON,
        ).pack(side="bottom", pady=18)

        self.summary_var = tk.StringVar(value="")
        summary_label = tk.Label(
            self,
            textvariable=self.summary_var,
            font=(cfg.font_family, cfg.font_size_normal),
            fg=theme.TEXT,
            bg=theme.CHROME_BG,
            justify="left",
            wraplength=800,
        )
        summary_label.pack(side="top", fill="both", expand=True, pady=10)
        self.register_wrappable(summary_label, ratio=0.85)

    def on_enter(self, **_: Any) -> None:
        self.summary_var.set(self._build_summary())

    def _build_summary(self) -> str:
        writer = self.app.writer
        if writer is None:
            return "(no SessionWriter attached — running without persistence)"

        # Chills stats: count successes across chills-flavored blocks with ratings.
        chills_blocks = [
            b for b in writer.blocks
            if b.condition in ("chills_only", "chills_oddball_passive", "calibration")
        ]
        n_chills = len(chills_blocks)
        n_success = sum(
            1 for b in chills_blocks if (b.ratings or {}).get("success") is True
        )
        intensities = [
            (b.ratings or {}).get("intensity")
            for b in chills_blocks
            if (b.ratings or {}).get("intensity") is not None
        ]
        mean_intensity = (sum(intensities) / len(intensities)) if intensities else None

        rest_blocks = [
            b for b in writer.blocks if b.condition in ("rest_only", "rest_oddball_passive")
        ]
        alertness = [
            (b.ratings or {}).get("alertness")
            for b in rest_blocks
            if (b.ratings or {}).get("alertness") is not None
        ]
        mean_alertness = (sum(alertness) / len(alertness)) if alertness else None

        ao = writer.active_oddball_summary or {}

        lines: list[str] = []
        lines.append(f"Participant: {writer.participant_id}")
        lines.append(f"Blocks completed: {len(writer.blocks)}")
        lines.append("")
        lines.append("CHILLS")
        lines.append(
            f"  Successful inductions: {n_success} / {n_chills}"
            if n_chills
            else "  (no chills blocks)"
        )
        if mean_intensity is not None:
            lines.append(f"  Mean intensity: {mean_intensity:.1f} / 10")
        lines.append("")
        lines.append("REST")
        if mean_alertness is not None:
            lines.append(f"  Mean alertness: {mean_alertness:.1f} / 10")
        else:
            lines.append("  (no rest blocks)")
        lines.append("")
        lines.append("ACTIVE ODDBALL")
        if ao:
            n_dev = ao.get("main_hits", 0) + ao.get("main_misses", 0)
            n_std = ao.get("main_total_trials", 0) - n_dev
            hit_rate = (ao.get("main_hits", 0) / n_dev * 100) if n_dev else 0.0
            fa_rate = (ao.get("main_false_alarms", 0) / n_std * 100) if n_std else 0.0
            mean_rt = ao.get("mean_rt_ms")
            lines.append(f"  Practice attempts: {ao.get('practice_attempts', '?')}")
            lines.append(
                f"  Hits: {ao.get('main_hits', 0)} / {n_dev}  ({hit_rate:.0f}%)"
            )
            lines.append(
                f"  False alarms: {ao.get('main_false_alarms', 0)} / {n_std}  ({fa_rate:.0f}%)"
            )
            if mean_rt is not None:
                lines.append(f"  Mean RT: {mean_rt:.0f} ms")
            if "engagement_rating" in ao:
                lines.append(f"  Engagement self-rating: {ao['engagement_rating']} / 10")
        else:
            lines.append("  (no active oddball summary recorded)")
        return "\n".join(lines)

    def _on_save_and_exit(self) -> None:
        if self.app.outlet is not None:
            try:
                self.app.outlet.session_end()
            except Exception:  # noqa: BLE001
                logger.exception("session_end marker failed")

        if self.app.writer is not None:
            try:
                final_path = self.app.writer.finalize(status="completed")
                logger.info("session record finalized: %s", final_path)
            except Exception:  # noqa: BLE001
                logger.exception("writer.finalize failed")

        if self.app.outlet is not None:
            try:
                self.app.outlet.close()
            except Exception:  # noqa: BLE001
                logger.exception("outlet.close failed")

        self.app.shutdown()
