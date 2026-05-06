"""Smoke tests for the Tk app controller (Step 8 stage shells)."""

from __future__ import annotations

import pytest


@pytest.fixture
def app(shared_app):
    return shared_app


def test_app_constructs_and_registers_all_stages(app):
    names = sorted(app.stages.keys())
    assert names == sorted(
        [
            "intake",
            "volume_check",
            "instructions",
            "calibration_chills",
            "block_runner",
            "ratings_chills",
            "ratings_rest",
            "active_oddball",
            "completion",
        ]
    )


def test_show_stage_unknown_raises(app):
    with pytest.raises(KeyError, match="unknown stage"):
        app.show_stage("nope")


def test_main_self_check_returns_zero():
    """The --self-check stub should at least confirm config loads."""
    from chills_oddball.app import main

    assert main(["--self-check"]) == 0
