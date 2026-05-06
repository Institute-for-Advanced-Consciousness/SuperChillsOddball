"""30 s baseline chills calibration block (always before the main schedule)."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class CalibrationChillsFrame(PlaceholderStage, StageFrame):
    NAME = "calibration_chills"
    LABEL = (
        "Calibration chills (placeholder).\n\n"
        "Real version: SPACE -> start gong -> 30 s timer (silent) ->\n"
        "end gong -> ratings panel."
    )
    NEXT = "ratings_chills"
