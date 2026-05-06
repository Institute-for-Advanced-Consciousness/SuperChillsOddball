"""Generic block loop for the 4 short-condition variants."""

from __future__ import annotations

from ._base import StageFrame
from ._placeholder import PlaceholderStage


class BlockRunnerFrame(PlaceholderStage, StageFrame):
    NAME = "block_runner"
    LABEL = (
        "Block runner (placeholder).\n\n"
        "Real version: pre-block instructions for the upcoming condition,\n"
        "SPACE -> start gong -> block timer (silent or oddball stream) ->\n"
        "end gong -> ratings panel routing."
    )
    NEXT = "ratings_rest"
