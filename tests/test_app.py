"""Smoke tests for the Tk app controller (Step 8 stage shells).

Uses a module-scoped App fixture so we only init Tk once per test module
(the uv-managed Tk install runs out of init handles after a few inits in
the same process).
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="module")
def app():
    try:
        from chills_oddball.app import App

        a = App()
    except tk.TclError as e:
        pytest.skip(f"Tk display not available: {e}")
    yield a
    a.shutdown()


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


def test_show_stage_passes_payload_to_on_enter(app):
    app.show_stage("ratings_chills", block_idx=4, condition="chills_only")
    frame = app.stages["ratings_chills"]
    assert getattr(frame, "_last_payload", {}) == {
        "block_idx": 4,
        "condition": "chills_only",
    }


def test_main_self_check_returns_zero():
    """The --self-check stub should at least confirm config loads."""
    from chills_oddball.app import main

    assert main(["--self-check"]) == 0
