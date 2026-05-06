"""Block runner integration tests.

Mocks outlet / audio_scheduler / writer so we exercise the full lifecycle
(start markers -> gong -> block body -> end markers -> CSV write -> route
to ratings) without real audio hardware.

Tk on the uv-managed python-build-standalone distribution exhausts some
internal handle pool after a handful of full Tk() inits in the same
process. We therefore use a *module-scoped* App fixture (one Tk init for
the whole file) and reset services + show a neutral stage between tests.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass, field

import pytest

from chills_oddball.config import load_config
from chills_oddball.persistence import TrialRow
from chills_oddball.schedule import (
    ScheduledBlock,
    generate_session_schedule,
)


@pytest.fixture(scope="module")
def app():
    """Single App per module — survives the Tk-init handle limit on uv Python."""
    try:
        from chills_oddball.app import App

        a = App()
    except tk.TclError as e:
        pytest.skip(f"Tk display not available: {e}")
    yield a
    a.shutdown()


@pytest.fixture(autouse=True)
def reset_services(app):
    """Reset runtime state between tests so each starts from a clean slate."""
    app.outlet = None
    app.audio_scheduler = None
    app.writer = None
    app.schedule = []
    # Park on intake so leftover bindings from a prior block_runner are gone.
    app.show_stage("intake")
    yield
    app.outlet = None
    app.audio_scheduler = None
    app.writer = None
    app.schedule = []


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


@dataclass
class MockOutlet:
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def block_start(self, *, idx: int, condition: str, duration_s: int):
        self.calls.append(("block_start", {"idx": idx, "condition": condition}))
        return ("block_start", 100.0)

    def block_gong_start(self):
        self.calls.append(("block_gong_start", {}))
        return ("block_gong_start", 100.1)

    def block_gong_end(self):
        self.calls.append(("block_gong_end", {}))
        return ("block_gong_end", 100.2)

    def block_end(self, *, idx: int, condition: str):
        self.calls.append(("block_end", {"idx": idx, "condition": condition}))
        return ("block_end", 100.3)


@dataclass
class MockAudioScheduler:
    play_block_called: bool = False
    last_args: dict = field(default_factory=dict)

    def play_block(self, *, sequence, block_idx, condition, rng):
        self.play_block_called = True
        self.last_args = {
            "sequence": list(sequence),
            "block_idx": block_idx,
            "condition": condition,
        }
        from chills_oddball.audio import TrialRecord

        return [
            TrialRecord(
                trial_idx=i,
                is_deviant=bool(seq),
                onset_sample=i * 1000,
                onset_lsl=200.0 + i * 0.1,
            )
            for i, seq in enumerate(sequence)
        ]


@dataclass
class MockWriter:
    blocks: list[dict] = field(default_factory=list)
    ended: list[dict] = field(default_factory=list)

    def start_block(self, *, idx, condition, duration_s, start_lsl):
        rec = {"idx": idx, "condition": condition, "duration_s": duration_s, "start_lsl": start_lsl}
        self.blocks.append(rec)
        return rec

    def end_block(self, *, record, end_lsl, trials, ratings, status):
        self.ended.append(
            {
                "record": record,
                "end_lsl": end_lsl,
                "trials": trials,
                "ratings": ratings,
                "status": status,
            }
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for_stage(app, target: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.root.update()
        if app.current_stage == target:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"timeout waiting for stage {target!r}; current = {app.current_stage!r}"
    )


def _short_silent_block(condition: str, duration_s: int = 0) -> ScheduledBlock:
    return ScheduledBlock(idx=1, condition=condition, duration_s=duration_s)


# ---------------------------------------------------------------------------
# on_enter wiring
# ---------------------------------------------------------------------------


def test_on_enter_displays_pre_block_instructions(app):
    block = _short_silent_block("rest_only")
    app.show_stage("block_runner", block=block)
    frame = app.stages["block_runner"]
    assert "REST" in frame.body_var.get().upper()


def test_on_enter_requires_block_payload(app):
    with pytest.raises(ValueError, match="block="):
        app.show_stage("block_runner")


# ---------------------------------------------------------------------------
# End-to-end: silent block (chills_only) with all services mocked
# ---------------------------------------------------------------------------


def test_silent_chills_block_completes_and_routes_to_ratings_chills(app):
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = _short_silent_block("chills_only", duration_s=0)
    app.show_stage("block_runner", block=block)
    app.stages["block_runner"]._on_space()
    _wait_for_stage(app, target="ratings_chills")

    events = [c[0] for c in app.outlet.calls]
    assert events == ["block_start", "block_gong_start", "block_gong_end", "block_end"]
    assert len(app.writer.blocks) == 1
    assert len(app.writer.ended) == 1
    assert app.writer.ended[0]["status"] == "completed"
    assert app.writer.ended[0]["trials"] is None  # silent default


def test_silent_rest_block_routes_to_ratings_rest(app):
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = _short_silent_block("rest_only", duration_s=0)
    app.show_stage("block_runner", block=block)
    app.stages["block_runner"]._on_space()
    _wait_for_stage(app, target="ratings_rest")


# ---------------------------------------------------------------------------
# Oddball block: audio scheduler is invoked with a generated sequence
# ---------------------------------------------------------------------------


def test_oddball_block_runs_audio_scheduler_and_emits_tone_records(app):
    app.outlet = MockOutlet()
    app.audio_scheduler = MockAudioScheduler()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=2, condition="chills_oddball_passive", duration_s=30)
    app.show_stage("block_runner", block=block)
    app.stages["block_runner"]._on_space()
    _wait_for_stage(app, target="ratings_chills", timeout_s=10.0)

    assert app.audio_scheduler.play_block_called
    assert app.audio_scheduler.last_args["block_idx"] == 2
    assert app.audio_scheduler.last_args["condition"] == "chills_oddball_passive"
    seq = app.audio_scheduler.last_args["sequence"]
    assert 15 <= len(seq) <= 30
    assert sum(seq) > 0  # at least one deviant

    ended = app.writer.ended[0]
    assert ended["trials"] is not None
    assert len(ended["trials"]) == len(seq)
    assert all(isinstance(t, TrialRow) for t in ended["trials"])
    assert ended["trials"][0].event == "tone_onset"


# ---------------------------------------------------------------------------
# Service-optional mode
# ---------------------------------------------------------------------------


def test_block_runs_without_any_services_attached(app):
    block = _short_silent_block("rest_only", duration_s=0)
    app.show_stage("block_runner", block=block)
    app.stages["block_runner"]._on_space()
    _wait_for_stage(app, target="ratings_rest")


# ---------------------------------------------------------------------------
# App.show_block / advance_after_block routing
# ---------------------------------------------------------------------------


def test_show_block_routes_calibration_to_calibration_chills(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_block(0)
    assert app.current_stage == "calibration_chills"


def test_show_block_routes_active_oddball_to_active_stage(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_block(len(app.schedule) - 1)
    assert app.current_stage == "active_oddball"


def test_show_block_routes_short_conditions_to_block_runner(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_block(1)
    assert app.current_stage == "block_runner"


def test_advance_after_block_progresses_to_next(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.advance_after_block(0)
    assert app.current_stage == "block_runner"


def test_advance_after_last_block_goes_to_completion(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.advance_after_block(len(app.schedule) - 1)
    assert app.current_stage == "completion"


def test_show_block_without_schedule_raises(app):
    with pytest.raises(RuntimeError, match="no schedule"):
        app.show_block(0)


def test_show_block_out_of_range_raises(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    with pytest.raises(IndexError):
        app.show_block(99)
