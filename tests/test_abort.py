"""Tests for the abort flow (Escape key + window close + abort()).

Each test patches ``app.shutdown`` and ``app.confirm_abort`` so we don't
actually destroy the shared Tk root or pop a modal dialog.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from chills_oddball.config import load_config
from chills_oddball.persistence import SessionWriter
from chills_oddball.schedule import generate_session_schedule


@pytest.fixture
def app(shared_app):
    return shared_app


@dataclass
class _MockOutlet:
    abort_called: bool = False
    closed: bool = False
    calls: list[str] = field(default_factory=list)

    def session_abort(self):
        self.abort_called = True
        self.calls.append("session_abort")
        return ("session_abort", 0.0)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset(app, monkeypatch):
    """Don't actually destroy the shared root in abort tests."""
    monkeypatch.setattr(app, "shutdown", lambda: None)
    # Also default to "confirm" so we don't pop a modal dialog.
    monkeypatch.setattr(app, "confirm_abort", lambda: True)
    app.outlet = None
    app.writer = None
    app.audio_scheduler = None
    app.schedule = []
    app.show_stage("intake")
    yield
    app.outlet = None
    app.writer = None


def _make_writer(tmp_path: Path) -> SessionWriter:
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    return SessionWriter(
        data_root=tmp_path,
        participant_id="P_ABORT",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )


# ---------------------------------------------------------------------------
# Confirmation gating
# ---------------------------------------------------------------------------


def test_escape_does_nothing_when_user_cancels(app, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "confirm_abort", lambda: False)
    app.outlet = _MockOutlet()
    app.writer = _make_writer(tmp_path)
    app._on_escape()
    assert not app.outlet.abort_called
    final = app.writer.session_dir / SessionWriter.SESSION_FILENAME
    assert not final.exists()


def test_window_close_does_nothing_when_user_cancels(app, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "confirm_abort", lambda: False)
    app.outlet = _MockOutlet()
    app.writer = _make_writer(tmp_path)
    app._on_window_close()
    assert not app.outlet.abort_called


def test_abort_emits_marker_and_finalizes_writer(app, tmp_path):
    outlet = _MockOutlet()
    writer = _make_writer(tmp_path)
    rec = writer.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    writer.end_block(rec, end_lsl=40.0)
    app.outlet = outlet
    app.writer = writer
    app._on_escape()
    assert outlet.abort_called
    assert outlet.closed
    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    partial = writer.session_dir / SessionWriter.PARTIAL_FILENAME
    assert final.exists()
    assert partial.exists()  # partial is forensic-kept on abort
    with final.open() as fh:
        data = json.load(fh)
    assert data["status"] == "aborted"


def test_abort_marks_pending_block_as_aborted(app, tmp_path):
    """A block that started but never end_block'd should land as 'aborted'."""
    outlet = _MockOutlet()
    writer = _make_writer(tmp_path)
    # Open a block but DON'T call end_block.
    writer.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=50.0)
    app.outlet = outlet
    app.writer = writer

    app._on_escape()

    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    with final.open() as fh:
        data = json.load(fh)
    block_status = {b["idx"]: b["status"] for b in data["blocks"]}
    assert block_status[1] == "aborted"


def test_abort_with_no_services_attached_is_a_noop(app):
    # No outlet, no writer — abort should still complete without raising.
    app.abort()  # Just shouldn't raise.


def test_window_close_protocol_routes_to_abort(app, tmp_path):
    """Verify the WM_DELETE_WINDOW handler is wired up."""
    outlet = _MockOutlet()
    writer = _make_writer(tmp_path)
    app.outlet = outlet
    app.writer = writer
    app._on_window_close()
    assert outlet.abort_called


def test_session_abort_marker_disabled_via_config(app, tmp_path, monkeypatch):
    """When config.abort.emit_session_abort_marker is False, no marker push."""
    cfg = load_config()
    cfg = cfg.model_copy(
        update={
            "abort": cfg.abort.model_copy(update={"emit_session_abort_marker": False})
        }
    )
    monkeypatch.setattr(app, "config", cfg)

    outlet = _MockOutlet()
    writer = _make_writer(tmp_path)
    app.outlet = outlet
    app.writer = writer
    app._on_escape()
    assert not outlet.abort_called  # marker suppressed
    assert outlet.closed  # outlet still closed
    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    assert final.exists()


def test_require_confirmation_false_skips_dialog(app, tmp_path, monkeypatch):
    """When require_confirmation=False, escape aborts immediately without asking."""
    cfg = load_config()
    cfg = cfg.model_copy(
        update={"abort": cfg.abort.model_copy(update={"require_confirmation": False})}
    )
    monkeypatch.setattr(app, "config", cfg)

    # Confirm dialog should NOT be called even if it would say no.
    confirm_called = {"v": False}

    def _spy():
        confirm_called["v"] = True
        return False

    monkeypatch.setattr(app, "confirm_abort", _spy)

    outlet = _MockOutlet()
    writer = _make_writer(tmp_path)
    app.outlet = outlet
    app.writer = writer
    app._on_escape()
    assert not confirm_called["v"]  # dialog skipped
    assert outlet.abort_called  # abort still happened


# ---------------------------------------------------------------------------
# mark_pending_blocks_aborted unit
# ---------------------------------------------------------------------------


def test_mark_pending_blocks_aborted_only_touches_pending(tmp_path):
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    w = SessionWriter(
        data_root=tmp_path,
        participant_id="P_PEND",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )
    a = w.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    w.end_block(a, end_lsl=40.0)
    w.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=50.0)
    n = w.mark_pending_blocks_aborted()
    assert n == 1
    assert w.blocks[0].status == "completed"
    assert w.blocks[1].status == "aborted"


def test_mark_pending_blocks_aborted_idempotent(tmp_path):
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    w = SessionWriter(
        data_root=tmp_path,
        participant_id="P_IDEM",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )
    w.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=50.0)
    assert w.mark_pending_blocks_aborted() == 1
    assert w.mark_pending_blocks_aborted() == 0
