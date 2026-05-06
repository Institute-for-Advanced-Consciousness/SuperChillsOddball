"""30 s baseline chills calibration block (always before the main schedule).

Inherits the full block lifecycle (pre-block instructions -> SPACE ->
block_start marker + writer.start_block -> start gong -> silent timer ->
end gong -> block_end + writer.end_block -> route to ratings_chills)
from :class:`BlockRunnerFrame` and adds the calibration-specific
``calibration_start`` / ``calibration_end`` markers. The pre-block text
is sourced from ``config.instructions.calibration_chills`` instead of
the generic ``pre_block_*`` keys.

Routing: app.show_block(0) sends the calibration entry here (idx 0 is
always condition="calibration"); after the chills ratings panel
submits, the controller advances into block 1 (the first short-
condition block).
"""

from __future__ import annotations

import logging
from typing import Any

from ..schedule import ScheduledBlock
from .block_runner import BlockRunnerFrame

logger = logging.getLogger(__name__)


class CalibrationChillsFrame(BlockRunnerFrame):
    NAME = "calibration_chills"

    def on_enter(self, *, block: ScheduledBlock | None = None, **kw: Any) -> None:
        if block is None:
            raise ValueError("calibration_chills requires `block=` payload")
        super().on_enter(block=block, **kw)
        # Override the generic pre-block text with the calibration-specific copy.
        body = self.app.config.instructions.get(
            "calibration_chills",
            "Calibration block: 30 s self-induced chills. Press SPACE when ready.",
        )
        self.body_var.set(body)
        self.title_var.set("Calibration — chills baseline")

    def _begin_block(self) -> None:
        # We need calibration_start to land between block_start and the
        # start gong, so emit it after super's block_start but before super
        # kicks off the worker thread (which plays the gong). Easiest path:
        # split super's work — emit our marker before the worker spawns.
        block = self._block
        assert block is not None
        self._show_eyes_closed_view()

        self._block_start_lsl = self._lsl_now()
        if self.app.outlet is not None:
            try:
                _, ts = self.app.outlet.block_start(
                    idx=block.idx, condition=block.condition, duration_s=block.duration_s
                )
                self._block_start_lsl = ts
            except Exception:  # noqa: BLE001
                logger.exception("block_start marker push failed")
            try:
                self.app.outlet.calibration_start()
            except Exception:  # noqa: BLE001
                logger.exception("calibration_start marker failed")
        if self.app.writer is not None:
            self._record = self.app.writer.start_block(
                idx=block.idx,
                condition=block.condition,
                duration_s=block.duration_s,
                start_lsl=self._block_start_lsl,
            )

        import threading as _threading

        self._block_done_event = _threading.Event()
        self._worker = _threading.Thread(target=self._run_block_in_worker, daemon=True)
        self._worker.start()
        self._poll_block_done()

    def _finish_block(self) -> None:
        # Emit calibration_end before the generic block_end marker.
        if self.app.outlet is not None:
            try:
                self.app.outlet.calibration_end()
            except Exception:  # noqa: BLE001
                logger.exception("calibration_end marker failed")
        super()._finish_block()
