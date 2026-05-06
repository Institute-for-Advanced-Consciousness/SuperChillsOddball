"""Post-chills-block rating panel (success / waves / intensity / quality / keep / notes)."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class RatingsChillsFrame(PlaceholderStage, StageFrame):
    NAME = "ratings_chills"
    LABEL = (
        "Chills ratings (placeholder).\n\n"
        "Real version: 6 items — success (Y/N), waves (spinner 0–20),\n"
        "intensity (0–10 slider), quality (0–10 slider),\n"
        "keep (Y/N), notes (textbox)."
    )
    NEXT = "block_runner"
