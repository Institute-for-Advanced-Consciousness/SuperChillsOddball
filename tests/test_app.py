"""Smoke tests for the Tk app controller (Step 8 stage shells).

Each test handles Tk init failure individually (via _make_app) so a
headless CI environment skips per test, and there is no module-level
Tk init that can poison state for later tests.
"""

from __future__ import annotations

import tkinter as tk

import pytest


def _make_app():
    """Return an App instance, or skip the test if Tk can't init."""
    try:
        from chills_oddball.app import App

        return App()
    except tk.TclError as e:
        pytest.skip(f"Tk display not available: {e}")


def test_app_constructs_and_registers_all_stages():
    app = _make_app()
    try:
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
    finally:
        app.shutdown()


def test_show_stage_advances_through_full_chain():
    """Walk the placeholder chain: intake -> ... -> completion."""
    app = _make_app()
    try:
        order = []
        app.show_stage("intake")
        order.append(app.current_stage)
        for _ in range(len(app.stages)):
            current_frame = app.stages[app.current_stage]
            nxt = getattr(current_frame, "NEXT", None)
            if nxt is None:
                break
            app.show_stage(nxt)
            order.append(app.current_stage)
        assert order[-1] == "completion"
        assert set(order) >= {"intake", "calibration_chills", "active_oddball", "completion"}
    finally:
        app.shutdown()


def test_show_stage_unknown_raises():
    app = _make_app()
    try:
        with pytest.raises(KeyError, match="unknown stage"):
            app.show_stage("nope")
    finally:
        app.shutdown()


def test_show_stage_passes_payload_to_on_enter():
    app = _make_app()
    try:
        app.show_stage("ratings_chills", block_idx=4, condition="chills_only")
        frame = app.stages["ratings_chills"]
        assert getattr(frame, "_last_payload", {}) == {
            "block_idx": 4,
            "condition": "chills_only",
        }
    finally:
        app.shutdown()


def test_main_self_check_returns_zero():
    """The --self-check stub should at least confirm config loads."""
    from chills_oddball.app import main

    assert main(["--self-check"]) == 0
