"""Tests for the intake / volume_check / instructions / completion stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from chills_oddball.config import load_config
from chills_oddball.persistence import BlockRecord, SessionWriter
from chills_oddball.schedule import generate_session_schedule


@pytest.fixture
def app(shared_app):
    return shared_app


@pytest.fixture(autouse=True)
def reset(app, tmp_path, monkeypatch):
    """Each test gets a clean app + a writable data root."""
    # Point intake at a temp data dir so no real Data/ folder is touched.
    # Symlink the assets/ directory across so ToneScheduler can still load
    # the rendered .wav files from the temp REPO_ROOT.
    import shutil

    from chills_oddball.config import REPO_ROOT as REAL_REPO_ROOT
    from chills_oddball.stages import intake as intake_module

    # Copy assets (cheap — ~1 MB).
    shutil.copytree(REAL_REPO_ROOT / "assets", tmp_path / "assets")

    monkeypatch.setattr(intake_module, "REPO_ROOT", tmp_path)

    app.outlet = None
    app.writer = None
    app.audio_scheduler = None
    app.schedule = []
    app.rng_seed = None
    app.participant_id = None
    app.show_stage("intake")
    yield
    # Best-effort teardown of any opened outlet.
    if app.outlet is not None:
        try:
            app.outlet.close()
        except Exception:  # noqa: BLE001
            pass
    app.outlet = None
    app.writer = None
    app.audio_scheduler = None


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def test_intake_auto_suggests_p001_when_no_data(app, tmp_path):
    frame = app.stages["intake"]
    # tmp_path is the new repo root; no Data/ subdir exists yet.
    frame.on_enter()
    assert frame._pid_var.get() == "P001"


def test_intake_increments_existing_pids(app, tmp_path):
    data_root = tmp_path / "Data"
    data_root.mkdir()
    (data_root / "P001").mkdir()
    (data_root / "P003").mkdir()
    frame = app.stages["intake"]
    frame.on_enter()
    assert frame._pid_var.get() == "P004"


def test_intake_summary_includes_paradigm_invariants(app):
    frame = app.stages["intake"]
    frame.on_enter()
    summary = frame._summary_text.get("1.0", "end")
    assert "1000 Hz / 2000 Hz" in summary
    assert "80% std / 20% dev" in summary
    assert "Calibration first" in summary


def test_intake_begin_requires_pid(app):
    frame = app.stages["intake"]
    frame.on_enter()
    frame._pid_var.set("")
    frame._on_begin()
    assert app.current_stage == "intake"
    assert "required" in frame._error_var.get().lower()


def test_intake_begin_initializes_services_and_advances(app, tmp_path):
    """The full happy path: pid -> services attached -> advance to volume_check."""
    frame = app.stages["intake"]
    frame.on_enter()
    frame._pid_var.set("P777")
    frame._on_begin()

    # Services attached
    assert app.outlet is not None
    assert app.outlet.is_open
    assert app.audio_scheduler is not None
    assert app.writer is not None
    assert app.participant_id == "P777"
    assert isinstance(app.rng_seed, int)
    assert len(app.schedule) == 18  # cal + 16 short + active

    # Per-participant data folder created
    assert (tmp_path / "Data" / "P777").is_dir()

    # Advanced to volume_check
    assert app.current_stage == "volume_check"


# ---------------------------------------------------------------------------
# Volume check
# ---------------------------------------------------------------------------


def test_volume_check_space_advances_to_instructions(app):
    # No audio_scheduler attached -> tone playback no-ops, but SPACE still advances.
    app.show_stage("volume_check")
    frame = app.stages["volume_check"]
    frame._on_space()
    assert app.current_stage == "instructions"


def test_volume_check_no_audio_shows_status_message(app):
    app.show_stage("volume_check")
    frame = app.stages["volume_check"]
    assert "no audio" in frame.status_var.get().lower()


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------


def test_instructions_space_calls_show_block_zero(app):
    cfg = load_config()
    app.schedule = generate_session_schedule(cfg, seed=42)
    app.show_stage("instructions")
    frame = app.stages["instructions"]
    frame._on_space()
    assert app.current_stage == "calibration_chills"


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


@dataclass
class _MockOutlet:
    closed: bool = False
    end_called: bool = False

    def session_end(self):
        self.end_called = True
        return ("session_end", 0.0)

    def close(self):
        self.closed = True


def test_completion_summary_reflects_writer_records(app, tmp_path):
    """Drive the completion stage off a writer with real BlockRecord data."""
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    writer = SessionWriter(
        data_root=tmp_path,
        participant_id="P555",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )
    # Stamp a couple of blocks with ratings so the summary has content.
    cal = writer.start_block(
        idx=0, condition="calibration", duration_s=30, start_lsl=10.0
    )
    writer.end_block(cal, end_lsl=40.0)
    writer.set_block_ratings(0, {"success": True, "intensity": 7, "quality": 8})

    rest = writer.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=50.0)
    writer.end_block(rest, end_lsl=140.0)
    writer.set_block_ratings(1, {"alertness": 6})

    writer.set_active_oddball_summary(
        {
            "practice_attempts": 2,
            "practice_passed": True,
            "main_total_trials": 250,
            "main_hits": 47,
            "main_misses": 3,
            "main_false_alarms": 12,
            "mean_rt_ms": 412.0,
            "engagement_rating": 8,
        }
    )

    app.writer = writer
    app.outlet = _MockOutlet()
    app.show_stage("completion")
    frame = app.stages["completion"]
    summary = frame.summary_var.get()
    assert "P555" in summary
    assert "Successful inductions: 1 / 1" in summary
    assert "Mean intensity: 7.0" in summary
    assert "Mean alertness: 6.0" in summary
    assert "Hits: 47 / 50" in summary  # 47 hits out of 50 deviants
    assert "Mean RT: 412 ms" in summary
    assert "Engagement self-rating: 8" in summary


def test_completion_save_and_exit_finalizes_writer(app, tmp_path):
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    writer = SessionWriter(
        data_root=tmp_path,
        participant_id="P666",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )
    rec = writer.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    writer.end_block(rec, end_lsl=40.0)

    app.writer = writer
    outlet = _MockOutlet()
    app.outlet = outlet
    app.show_stage("completion")
    frame = app.stages["completion"]

    # Patch shutdown so the test doesn't actually destroy the shared root.
    called: dict[str, bool] = {"shutdown": False}

    def _no_shutdown():
        called["shutdown"] = True

    frame.app.shutdown = _no_shutdown  # type: ignore[method-assign]
    try:
        frame._on_save_and_exit()
    finally:
        # Restore real shutdown (not strictly necessary — fixture creates new app)
        pass

    assert outlet.end_called
    assert outlet.closed
    final = Path(writer.session_dir) / SessionWriter.SESSION_FILENAME
    assert final.exists()
    partial = Path(writer.session_dir) / SessionWriter.PARTIAL_FILENAME
    assert not partial.exists()


# ---------------------------------------------------------------------------
# Empty BlockRecord smoke test (sanity: completion handles no ratings)
# ---------------------------------------------------------------------------


def test_completion_with_empty_writer_does_not_crash(app, tmp_path):
    cfg = load_config()
    schedule = generate_session_schedule(cfg, seed=42)
    writer = SessionWriter(
        data_root=tmp_path,
        participant_id="P000",
        config_snapshot=cfg.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )
    # No blocks ended yet.
    app.writer = writer
    app.show_stage("completion")
    frame = app.stages["completion"]
    summary = frame.summary_var.get()
    assert "P000" in summary
    assert "Blocks completed: 0" in summary


def test_block_record_default_unrated():
    rec = BlockRecord(idx=0, condition="rest_only", duration_s=90)
    assert rec.ratings is None
