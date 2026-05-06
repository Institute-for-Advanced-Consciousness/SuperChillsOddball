"""Tests for the calibration chills stage."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from chills_oddball.config import load_config
from chills_oddball.schedule import ScheduledBlock, generate_session_schedule


@pytest.fixture
def app(shared_app):
    return shared_app


@dataclass
class MockOutlet:
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def block_start(self, *, idx, condition, duration_s):
        self.calls.append(("block_start", {"idx": idx, "condition": condition}))
        return ("block_start", 100.0)

    def block_gong_start(self):
        self.calls.append(("block_gong_start", {}))
        return ("block_gong_start", 100.1)

    def block_gong_end(self):
        self.calls.append(("block_gong_end", {}))
        return ("block_gong_end", 100.2)

    def block_end(self, *, idx, condition):
        self.calls.append(("block_end", {"idx": idx, "condition": condition}))
        return ("block_end", 100.3)

    def calibration_start(self):
        self.calls.append(("calibration_start", {}))
        return ("calibration_start", 100.05)

    def calibration_end(self):
        self.calls.append(("calibration_end", {}))
        return ("calibration_end", 100.25)

    # The ratings_chills frame fires this on entry; tolerate the call.
    def ratings_start(self, *, block_idx):
        self.calls.append(("ratings_start", {"block_idx": block_idx}))
        return ("ratings_start", 100.4)


@dataclass
class MockWriter:
    blocks: list = field(default_factory=list)
    ended: list = field(default_factory=list)

    def start_block(self, *, idx, condition, duration_s, start_lsl):
        rec = {"idx": idx, "condition": condition, "duration_s": duration_s,
               "start_lsl": start_lsl, "ratings": None}
        self.blocks.append(rec)
        return rec

    def end_block(self, *, record, end_lsl, trials, ratings, status):
        self.ended.append({"record": record, "end_lsl": end_lsl,
                           "trials": trials, "status": status})


@pytest.fixture(autouse=True)
def reset(app):
    app.outlet = None
    app.writer = None
    app.audio_scheduler = None
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_stage("intake")
    yield
    app.outlet = None
    app.writer = None
    app.audio_scheduler = None
    app.schedule = []


def _wait_for_stage(app, target, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.root.update()
        if app.current_stage == target:
            return
        time.sleep(0.01)
    raise AssertionError(f"timeout: current={app.current_stage}, expected={target}")


# ---------------------------------------------------------------------------


def test_calibration_uses_calibration_chills_instruction_text(app):
    block = ScheduledBlock(idx=0, condition="calibration", duration_s=30)
    app.show_stage("calibration_chills", block=block)
    frame = app.stages["calibration_chills"]
    body = frame.body_var.get()
    # The shipped instruction text mentions 30-second / chills.
    assert "30" in body or "chills" in body.lower()


def test_calibration_eyes_closed_view_shown_after_space(app):
    block = ScheduledBlock(idx=0, condition="calibration", duration_s=0)
    app.show_stage("calibration_chills", block=block)
    frame = app.stages["calibration_chills"]
    frame._on_space()
    body = frame.body_var.get()
    assert "Your eyes should be closed" in body
    assert "CALIBRATION CHILLS" in body
    _wait_for_stage(app, "ratings_chills")


def test_calibration_emits_full_marker_chain_in_order(app):
    """block_start -> calibration_start -> gong_start -> gong_end -> calibration_end -> block_end"""
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=0, condition="calibration", duration_s=0)
    app.show_stage("calibration_chills", block=block)
    app.stages["calibration_chills"]._on_space()
    _wait_for_stage(app, "ratings_chills")

    # Filter out the ratings_start emission (fired by the next stage on entry).
    events = [c[0] for c in app.outlet.calls if c[0] != "ratings_start"]
    assert events == [
        "block_start",
        "calibration_start",
        "block_gong_start",
        "block_gong_end",
        "calibration_end",
        "block_end",
    ]


def test_calibration_routes_to_ratings_chills(app):
    """Calibration is in CHILLS_CONDITIONS so it routes to ratings_chills."""
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=0, condition="calibration", duration_s=0)
    app.show_stage("calibration_chills", block=block)
    app.stages["calibration_chills"]._on_space()
    _wait_for_stage(app, "ratings_chills")
    assert app.current_stage == "ratings_chills"


def test_calibration_silent_block_records_no_trials(app):
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=0, condition="calibration", duration_s=0)
    app.show_stage("calibration_chills", block=block)
    app.stages["calibration_chills"]._on_space()
    _wait_for_stage(app, "ratings_chills")

    assert len(app.writer.ended) == 1
    assert app.writer.ended[0]["trials"] is None  # silent default


def test_calibration_requires_block_payload(app):
    with pytest.raises(ValueError, match="block="):
        app.show_stage("calibration_chills")


def test_show_block_routes_idx0_to_calibration_chills(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_block(0)
    assert app.current_stage == "calibration_chills"
