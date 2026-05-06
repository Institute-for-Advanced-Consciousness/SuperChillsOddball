"""Final active oddball block: practice gate + main 250-trial run."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class ActiveOddballFrame(PlaceholderStage, StageFrame):
    NAME = "active_oddball"
    LABEL = (
        "Active oddball (placeholder).\n\n"
        "Real version: instructions -> practice (10 trials, 8 std + 2 dev,\n"
        "≥75% hits & ≤50% FA to pass; repeat until passed) ->\n"
        "main 250-trial block with spacebar response on deviants."
    )
    NEXT = "completion"
