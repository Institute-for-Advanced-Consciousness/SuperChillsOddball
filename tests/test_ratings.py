"""Tests for the ratings panels (chills + rest)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from chills_oddball.config import load_config
from chills_oddball.persistence import BlockRecord
from chills_oddball.schedule import generate_session_schedule


@pytest.fixture
def app(shared_app):
    return shared_app


@dataclass
class MockOutlet:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def ratings_start(self, *, block_idx):
        self.calls.append(("ratings_start", {"block_idx": block_idx}))
        return ("ratings_start", 1.0)

    def ratings_end(self, *, block_idx):
        self.calls.append(("ratings_end", {"block_idx": block_idx}))
        return ("ratings_end", 1.0)

    def ratings_submit_chills(self, *, block_idx, success, waves, intensity, quality, keep):
        self.calls.append(
            (
                "ratings_submit_chills",
                {
                    "block_idx": block_idx,
                    "success": success,
                    "waves": waves,
                    "intensity": intensity,
                    "quality": quality,
                    "keep": keep,
                },
            )
        )
        return ("submit", 2.0)

    def ratings_submit_rest(self, *, block_idx, alertness):
        self.calls.append(
            ("ratings_submit_rest", {"block_idx": block_idx, "alertness": alertness})
        )
        return ("submit", 2.0)


@dataclass
class MockWriter:
    """Stand-in with the bits the ratings frame touches (set_block_ratings)."""

    blocks: list[BlockRecord] = field(default_factory=list)

    def set_block_ratings(self, idx, ratings):
        for rec in self.blocks:
            if rec.idx == idx:
                rec.ratings = ratings
                return
        raise KeyError(idx)


@pytest.fixture(autouse=True)
def reset_app(app):
    app.outlet = None
    app.writer = None
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_stage("intake")
    yield
    app.outlet = None
    app.writer = None
    app.schedule = []


# ---------------------------------------------------------------------------
# Chills panel
# ---------------------------------------------------------------------------


def test_chills_panel_emits_start_marker_on_enter(app):
    app.outlet = MockOutlet()
    app.show_stage("ratings_chills", block_idx=3, condition="chills_only")
    assert app.outlet.calls[0] == ("ratings_start", {"block_idx": 3})


def test_chills_panel_builds_all_items(app):
    app.show_stage("ratings_chills", block_idx=3, condition="chills_only")
    frame = app.stages["ratings_chills"]
    expected_ids = {"success", "waves", "intensity", "quality", "keep"}
    assert expected_ids.issubset(set(frame._vars.keys()))
    assert "notes" in frame._text_widgets


def test_chills_panel_validates_required_radio_unset(app):
    app.show_stage("ratings_chills", block_idx=3, condition="chills_only")
    frame = app.stages["ratings_chills"]
    # success / keep both radios unset by default
    frame._on_submit()
    # Should NOT have advanced (still on ratings_chills)
    assert app.current_stage == "ratings_chills"
    # Submit button should show a validation hint
    assert "⚠" in frame._submit_btn["text"]


def test_chills_panel_submit_emits_marker_with_payload(app):
    app.outlet = MockOutlet()
    block = BlockRecord(idx=3, condition="chills_only", duration_s=90, status="completed")
    app.writer = MockWriter(blocks=[block])
    app.show_stage("ratings_chills", block_idx=3, condition="chills_only")

    frame = app.stages["ratings_chills"]
    frame._vars["success"].set("Yes")
    frame._vars["waves"].set(3)
    frame._vars["intensity"].set(7)
    frame._vars["quality"].set(8)
    frame._vars["keep"].set("Yes, keep")
    frame._text_widgets["notes"].insert("1.0", "felt warm")
    frame._on_submit()

    submitted = [c for c in app.outlet.calls if c[0] == "ratings_submit_chills"]
    assert len(submitted) == 1
    payload = submitted[0][1]
    assert payload == {
        "block_idx": 3,
        "success": True,
        "waves": 3,
        "intensity": 7,
        "quality": 8,
        "keep": True,
    }
    # Writer received normalized ratings
    assert block.ratings is not None
    assert block.ratings["success"] is True
    assert block.ratings["waves"] == 3
    assert block.ratings["notes"] == "felt warm"


def test_chills_panel_submit_advances_to_next_block(app):
    app.outlet = MockOutlet()
    block = BlockRecord(idx=2, condition="chills_only", duration_s=90, status="completed")
    app.writer = MockWriter(blocks=[block])
    app.show_stage("ratings_chills", block_idx=2, condition="chills_only")
    frame = app.stages["ratings_chills"]
    frame._vars["success"].set("No")
    frame._vars["waves"].set(0)
    frame._vars["keep"].set("No, discard")
    frame._on_submit()
    assert app.current_stage in ("block_runner", "ratings_chills_or_rest")
    # block 2 is followed by some short condition -> block_runner
    assert app.current_stage == "block_runner"


# ---------------------------------------------------------------------------
# Rest panel
# ---------------------------------------------------------------------------


def test_rest_panel_emits_start_marker_on_enter(app):
    app.outlet = MockOutlet()
    app.show_stage("ratings_rest", block_idx=4, condition="rest_only")
    assert app.outlet.calls[0] == ("ratings_start", {"block_idx": 4})


def test_rest_panel_submit_emits_alertness_marker(app):
    app.outlet = MockOutlet()
    block = BlockRecord(idx=4, condition="rest_only", duration_s=90, status="completed")
    app.writer = MockWriter(blocks=[block])
    app.show_stage("ratings_rest", block_idx=4, condition="rest_only")
    frame = app.stages["ratings_rest"]
    frame._vars["alertness"].set(7)
    frame._on_submit()

    submitted = [c for c in app.outlet.calls if c[0] == "ratings_submit_rest"]
    assert len(submitted) == 1
    assert submitted[0][1] == {"block_idx": 4, "alertness": 7}
    assert block.ratings == {"alertness": 7}


def test_rest_panel_advances_to_next_block(app):
    block = BlockRecord(idx=2, condition="rest_only", duration_s=90, status="completed")
    app.writer = MockWriter(blocks=[block])
    app.show_stage("ratings_rest", block_idx=2, condition="rest_only")
    frame = app.stages["ratings_rest"]
    frame._vars["alertness"].set(5)
    frame._on_submit()
    assert app.current_stage in ("block_runner", "active_oddball", "completion")


def test_chills_panel_requires_block_idx(app):
    with pytest.raises(ValueError, match="block_idx"):
        app.show_stage("ratings_chills")


def test_rest_panel_requires_block_idx(app):
    with pytest.raises(ValueError, match="block_idx"):
        app.show_stage("ratings_rest")


# ---------------------------------------------------------------------------
# set_block_ratings (writer side)
# ---------------------------------------------------------------------------


def test_set_block_ratings_attaches_to_existing_record(tmp_path):
    from chills_oddball.persistence import SessionWriter

    cfg = load_config()
    sched = generate_session_schedule(cfg, seed=42)
    w = SessionWriter(
        data_root=tmp_path,
        participant_id="P900",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=sched,
        rng_seed=42,
    )
    rec = w.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    w.end_block(rec, end_lsl=40.0)
    w.set_block_ratings(0, {"success": True, "intensity": 8})
    assert rec.ratings == {"success": True, "intensity": 8}


def test_set_block_ratings_unknown_idx_raises(tmp_path):
    from chills_oddball.persistence import SessionWriter

    cfg = load_config()
    sched = generate_session_schedule(cfg, seed=42)
    w = SessionWriter(
        data_root=tmp_path,
        participant_id="P901",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=sched,
        rng_seed=42,
    )
    with pytest.raises(KeyError):
        w.set_block_ratings(0, {"success": True})
