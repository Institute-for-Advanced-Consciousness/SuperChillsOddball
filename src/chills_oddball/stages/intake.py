"""RA-facing intake screen: participant ID + parameter review + pre-flight checklist."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class IntakeFrame(PlaceholderStage, StageFrame):
    NAME = "intake"
    LABEL = (
        "Intake (placeholder).\n\n"
        "Real version: participant ID field, parameter review table,\n"
        "pre-flight checklist (LSL outlet OK / audio device OK / headphones)."
    )
    NEXT = "volume_check"
