"""Pre-session instructions screen."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class InstructionsFrame(PlaceholderStage, StageFrame):
    NAME = "instructions"
    LABEL = (
        "Instructions (placeholder).\n\n"
        "Real version: full pre-session instructions text from\n"
        "config.instructions.pre_session, SPACE to continue."
    )
    NEXT = "calibration_chills"
