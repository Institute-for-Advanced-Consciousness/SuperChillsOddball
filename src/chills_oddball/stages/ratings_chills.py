"""Post-chills-block rating panel (success / waves / intensity / quality / keep / notes).

Built dynamically from ``config.ratings.chills.items``. Emits
``ratings_start`` on entry, ``ratings_submit`` (chills variant) on submit,
``ratings_end`` on leave; updates the writer's block record with the
collected ratings; then calls ``app.advance_after_block(block_idx)``.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

from .. import theme
from ..config import RadioItem, SliderItem, SpinnerIntItem, TextboxItem
from ._base import StageFrame

logger = logging.getLogger(__name__)


class RatingsChillsFrame(StageFrame):
    NAME = "ratings_chills"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        tk.Label(
            self,
            text="Ratings",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=(20, 6))

        # Pin Submit button to the bottom so it stays reachable even when
        # the items frame is taller than the visible window area.
        self._submit_btn = tk.Button(
            self,
            text="Submit",
            font=(cfg.font_family, cfg.font_size_instruction, "bold"),
            width=20,
            command=self._on_submit,
            padx=10,
            pady=6,
            **theme.PRIMARY_BUTTON,
        )
        self._submit_btn.pack(side="bottom", pady=12)

        self._items_frame = tk.Frame(self, bg=theme.CHROME_BG)
        self._items_frame.pack(side="top", fill="both", expand=True, padx=60, pady=6)

        # Per-entry state.
        self._block_idx: int | None = None
        self._condition: str | None = None
        self._vars: dict[str, Any] = {}
        self._text_widgets: dict[str, tk.Text] = {}
        self._item_widgets: list[tk.Widget] = []

    # --------------------------------------------------------------- lifecycle

    def on_enter(self, *, block_idx: int | None = None, condition: str | None = None,
                 **_: Any) -> None:
        if block_idx is None:
            raise ValueError("ratings_chills requires `block_idx=` payload")
        self._block_idx = block_idx
        self._condition = condition

        if self.app.outlet is not None:
            try:
                self.app.outlet.ratings_start(block_idx=block_idx)
            except Exception:  # noqa: BLE001
                logger.exception("ratings_start marker failed")

        self._build_items()

    def on_leave(self) -> None:
        # Tear down items so a re-entry rebuilds cleanly.
        for w in self._item_widgets:
            w.destroy()
        self._item_widgets.clear()
        self._vars.clear()
        self._text_widgets.clear()
        if self._block_idx is not None and self.app.outlet is not None:
            try:
                self.app.outlet.ratings_end(block_idx=self._block_idx)
            except Exception:  # noqa: BLE001
                logger.exception("ratings_end marker failed")

    # --------------------------------------------------------------- widgets

    def _build_items(self) -> None:
        cfg = self.app.config.display
        for item in self.app.config.ratings.chills.items:
            row = tk.Frame(self._items_frame, bg=theme.CHROME_BG)
            row.pack(fill="x", pady=8)
            self._item_widgets.append(row)

            label = tk.Label(
                row,
                text=item.label,
                font=(cfg.font_family, cfg.font_size_normal),
                fg=theme.TEXT,
                bg=theme.CHROME_BG,
                anchor="w",
                wraplength=600,
            )
            label.pack(side="top", anchor="w")
            self.register_wrappable(label, ratio=0.85)

            if isinstance(item, RadioItem):
                var = tk.StringVar(value="")
                self._vars[item.id] = var
                btn_frame = tk.Frame(row, bg=theme.CHROME_BG)
                btn_frame.pack(anchor="w")
                # `indicatoron=False` renders each option as a button so the
                # selected/unselected state is unambiguous on dark backgrounds.
                # Selected fills with the IACS purple accent.
                for option in item.options:
                    tk.Radiobutton(
                        btn_frame,
                        text=f"  {option}  ",
                        value=option,
                        variable=var,
                        indicatoron=False,
                        font=(cfg.font_family, cfg.font_size_instruction, "bold"),
                        fg=theme.TEXT,
                        bg=theme.SURFACE_RAISED,
                        selectcolor=theme.ACCENT,
                        activebackground=theme.ACCENT_DARK,
                        activeforeground="#FFFFFF",
                        relief="flat",
                        borderwidth=0,
                        padx=18,
                        pady=8,
                        cursor="hand2",
                    ).pack(side="left", padx=10)
                value_lbl = tk.Label(
                    row,
                    text="Selected: (none yet)",
                    font=(cfg.font_family, cfg.font_size_normal, "bold"),
                    fg=theme.ACCENT_LIGHT,
                    bg=theme.CHROME_BG,
                )
                value_lbl.pack(anchor="w", pady=(4, 0))
                var.trace_add(
                    "write",
                    lambda *_a, v=var, l=value_lbl: l.configure(
                        text=f"Selected: {v.get() or '(none yet)'}"
                    ),
                )

            elif isinstance(item, SpinnerIntItem):
                var = tk.IntVar(value=item.default)
                self._vars[item.id] = var
                spinner_row = tk.Frame(row, bg=theme.CHROME_BG)
                spinner_row.pack(anchor="w")
                tk.Spinbox(
                    spinner_row,
                    from_=item.min,
                    to=item.max,
                    textvariable=var,
                    width=5,
                    font=(cfg.font_family, cfg.font_size_instruction, "bold"),
                    justify="center",
                    bg=theme.SURFACE,
                    fg=theme.TEXT,
                    insertbackground=theme.ACCENT_LIGHT,
                    buttonbackground=theme.ACCENT_DARK,
                    relief="flat",
                ).pack(side="left")
                value_lbl = tk.Label(
                    spinner_row,
                    text=f"  Selected: {var.get()}",
                    font=(cfg.font_family, cfg.font_size_normal, "bold"),
                    fg=theme.ACCENT_LIGHT,
                    bg=theme.CHROME_BG,
                )
                value_lbl.pack(side="left", padx=12)
                var.trace_add(
                    "write",
                    lambda *_a, v=var, l=value_lbl: l.configure(text=f"  Selected: {v.get()}"),
                )

            elif isinstance(item, SliderItem):
                var = tk.IntVar(value=item.default)
                self._vars[item.id] = var
                value_lbl = tk.Label(
                    row,
                    text=f"Selected: {var.get()}",
                    font=(cfg.font_family, cfg.font_size_instruction, "bold"),
                    fg=theme.ACCENT_LIGHT,
                    bg=theme.CHROME_BG,
                )
                value_lbl.pack(anchor="w", pady=(2, 0))
                tk.Scale(
                    row,
                    from_=item.min,
                    to=item.max,
                    orient="horizontal",
                    variable=var,
                    length=500,
                    bg=theme.CHROME_BG,
                    fg=theme.TEXT,
                    highlightthickness=0,
                    troughcolor=theme.SURFACE_RAISED,
                    activebackground=theme.ACCENT_LIGHT,
                    tickinterval=max(1, (item.max - item.min) // 10),
                    font=(cfg.font_family, cfg.font_size_normal),
                    sliderlength=24,
                    width=22,
                ).pack(anchor="w", fill="x")
                var.trace_add(
                    "write",
                    lambda *_a, v=var, l=value_lbl: l.configure(text=f"Selected: {v.get()}"),
                )
                if item.anchors:
                    parts = [f"{k}={v}" for k, v in sorted(item.anchors.items())]
                    anchors_text = "  (" + ", ".join(parts) + ")"
                    tk.Label(
                        row,
                        text=anchors_text.strip(),
                        font=(cfg.font_family, cfg.font_size_normal - 2, "italic"),
                        fg=theme.TEXT_MUTED,
                        bg=theme.CHROME_BG,
                    ).pack(anchor="w")

            elif isinstance(item, TextboxItem):
                text = tk.Text(
                    row,
                    height=item.rows,
                    width=80,
                    font=(cfg.font_family, cfg.font_size_normal),
                    bg=theme.SURFACE,
                    fg=theme.TEXT,
                    insertbackground=theme.ACCENT_LIGHT,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=theme.DIVIDER,
                )
                text.pack(anchor="w")
                self._text_widgets[item.id] = text

    # --------------------------------------------------------------- submit

    def _collect_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for item in self.app.config.ratings.chills.items:
            if isinstance(item, TextboxItem):
                txt = self._text_widgets[item.id].get("1.0", "end").strip()
                values[item.id] = txt
            else:
                var = self._vars[item.id]
                values[item.id] = var.get()
        return values

    def _validate(self, values: dict[str, Any]) -> str | None:
        """Return an error message if any required field is missing/blank."""
        for item in self.app.config.ratings.chills.items:
            if not item.required:
                continue
            if isinstance(item, RadioItem):
                if not values.get(item.id):
                    return f"Please answer: {item.label}"
            # Numeric items always have a value via the IntVar default.
        return None

    def _on_submit(self) -> None:
        values = self._collect_values()
        err = self._validate(values)
        if err:
            self.status_msg(err)
            return

        # Normalize for marker / writer.
        success = values["success"] == "Yes"
        keep = values["keep"] == "Yes, keep"
        ratings_for_writer = {
            "success": success,
            "waves": int(values["waves"]),
            "intensity": int(values["intensity"]),
            "quality": int(values["quality"]),
            "keep": keep,
            "notes": values.get("notes", ""),
        }

        if self.app.outlet is not None:
            try:
                self.app.outlet.ratings_submit_chills(
                    block_idx=self._block_idx,
                    success=success,
                    waves=ratings_for_writer["waves"],
                    intensity=ratings_for_writer["intensity"],
                    quality=ratings_for_writer["quality"],
                    keep=keep,
                )
            except Exception:  # noqa: BLE001
                logger.exception("ratings_submit chills marker failed")

        if self.app.writer is not None and self._block_idx is not None:
            try:
                self.app.writer.set_block_ratings(self._block_idx, ratings_for_writer)
            except KeyError:
                logger.exception("could not attach ratings to block %s", self._block_idx)

        idx = self._block_idx
        self.app.advance_after_block(idx)

    def status_msg(self, msg: str) -> None:
        # Inline validation message — replace with a real toast widget later.
        self._submit_btn.configure(text=f"⚠ {msg} — click Submit again")
