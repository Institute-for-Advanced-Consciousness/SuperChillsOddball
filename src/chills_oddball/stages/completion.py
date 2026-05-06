"""Completion screen: summary stats + Save & Exit."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class CompletionFrame(PlaceholderStage, StageFrame):
    NAME = "completion"
    LABEL = (
        "Completion (placeholder).\n\n"
        "Real version: summary stats (chills success rate, mean intensity,\n"
        "P300 hit rate / FA / mean RT), plus Save & Exit button."
    )
    NEXT = None  # End of flow.
