"""Post-rest-block alertness rating panel."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

from .. import theme
from ..config import SliderItem
from ._base import StageFrame

logger = logging.getLogger(__name__)


class RatingsRestFrame(StageFrame):
    NAME = "ratings_rest"

    def build(self) -> None:
        cfg = self.app.config.display
        self.configure(bg=theme.CHROME_BG)

        tk.Label(
            self,
            text="Alertness",
            font=(cfg.font_family, cfg.font_size_heading, "bold"),
            fg=theme.ACCENT_LIGHT,
            bg=theme.CHROME_BG,
        ).pack(side="top", pady=(30, 12))

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
        self._submit_btn.pack(side="bottom", pady=14)

        self._items_frame = tk.Frame(self, bg=theme.CHROME_BG)
        self._items_frame.pack(side="top", fill="both", expand=True, padx=60, pady=10)

        self._block_idx: int | None = None
        self._vars: dict[str, Any] = {}
        self._item_widgets: list[tk.Widget] = []

    def on_enter(self, *, block_idx: int | None = None, **_: Any) -> None:
        if block_idx is None:
            raise ValueError("ratings_rest requires `block_idx=` payload")
        self._block_idx = block_idx
        if self.app.outlet is not None:
            try:
                self.app.outlet.ratings_start(block_idx=block_idx)
            except Exception:  # noqa: BLE001
                logger.exception("ratings_start marker failed")
        self._build_items()

    def on_leave(self) -> None:
        for w in self._item_widgets:
            w.destroy()
        self._item_widgets.clear()
        self._vars.clear()
        if self._block_idx is not None and self.app.outlet is not None:
            try:
                self.app.outlet.ratings_end(block_idx=self._block_idx)
            except Exception:  # noqa: BLE001
                logger.exception("ratings_end marker failed")

    def _build_items(self) -> None:
        cfg = self.app.config.display
        for item in self.app.config.ratings.rest.items:
            row = tk.Frame(self._items_frame, bg=theme.CHROME_BG)
            row.pack(fill="x", pady=10)
            self._item_widgets.append(row)

            label = tk.Label(
                row,
                text=item.label,
                font=(cfg.font_family, cfg.font_size_instruction),
                fg=theme.TEXT,
                bg=theme.CHROME_BG,
            )
            label.pack(anchor="w")
            self.register_wrappable(label, ratio=0.85)

            if isinstance(item, SliderItem):
                var = tk.IntVar(value=item.default)
                self._vars[item.id] = var
                value_lbl = tk.Label(
                    row,
                    text=f"Selected: {var.get()}",
                    font=(cfg.font_family, cfg.font_size_instruction, "bold"),
                    fg=theme.ACCENT_LIGHT,
                    bg=theme.CHROME_BG,
                )
                value_lbl.pack(anchor="w", pady=(4, 2))
                tk.Scale(
                    row,
                    from_=item.min,
                    to=item.max,
                    orient="horizontal",
                    variable=var,
                    length=600,
                    bg=theme.CHROME_BG,
                    fg=theme.TEXT,
                    highlightthickness=0,
                    troughcolor=theme.SURFACE_RAISED,
                    activebackground=theme.ACCENT_LIGHT,
                    tickinterval=max(1, (item.max - item.min) // 10),
                    font=(cfg.font_family, cfg.font_size_normal),
                    sliderlength=26,
                    width=24,
                ).pack(anchor="w", pady=8, fill="x")
                var.trace_add(
                    "write",
                    lambda *_a, v=var, l=value_lbl: l.configure(text=f"Selected: {v.get()}"),
                )
                if item.anchors:
                    parts = [f"{k} = {v}" for k, v in sorted(item.anchors.items())]
                    tk.Label(
                        row,
                        text="  |  ".join(parts),
                        font=(cfg.font_family, cfg.font_size_normal - 2, "italic"),
                        fg=theme.TEXT_MUTED,
                        bg=theme.CHROME_BG,
                    ).pack(anchor="w")

    def _collect_values(self) -> dict[str, Any]:
        return {item.id: self._vars[item.id].get() for item in self.app.config.ratings.rest.items}

    def _on_submit(self) -> None:
        values = self._collect_values()
        alertness = int(values["alertness"])

        if self.app.outlet is not None:
            try:
                self.app.outlet.ratings_submit_rest(
                    block_idx=self._block_idx, alertness=alertness
                )
            except Exception:  # noqa: BLE001
                logger.exception("ratings_submit rest marker failed")

        if self.app.writer is not None and self._block_idx is not None:
            try:
                self.app.writer.set_block_ratings(self._block_idx, {"alertness": alertness})
            except KeyError:
                logger.exception("could not attach ratings to block %s", self._block_idx)

        self.app.advance_after_block(self._block_idx)
