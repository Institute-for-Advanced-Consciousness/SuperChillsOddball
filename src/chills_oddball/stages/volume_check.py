"""Volume-check stage: 1 kHz reference tone + adjust-headphones prompt."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class VolumeCheckFrame(PlaceholderStage, StageFrame):
    NAME = "volume_check"
    LABEL = (
        "Volume check (placeholder).\n\n"
        "Real version: loops the 1 kHz reference tone, asks the participant\n"
        "to adjust headphone volume, then SPACE to continue."
    )
    NEXT = "instructions"
