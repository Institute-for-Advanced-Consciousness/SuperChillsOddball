"""Post-rest-block alertness rating panel."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class RatingsRestFrame(PlaceholderStage, StageFrame):
    NAME = "ratings_rest"
    LABEL = (
        "Rest ratings (placeholder).\n\n"
        "Real version: single 0–10 alertness slider\n"
        "(0 = fell asleep, 5 = neutral, 10 = highly alert / wired)."
    )
    NEXT = "active_oddball"
