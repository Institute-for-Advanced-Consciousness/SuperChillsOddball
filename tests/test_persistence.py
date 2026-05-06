"""SessionWriter tests: clean completion, mid-session abort, ID auto-suggest."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from chills_oddball.config import load_config
from chills_oddball.persistence import (
    BlockRecord,
    SessionWriter,
    TrialRow,
    block_csv_filename,
    next_participant_id,
)
from chills_oddball.schedule import generate_session_schedule

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def schedule(config):
    return generate_session_schedule(config, seed=42)


@pytest.fixture
def writer(tmp_path: Path, config, schedule) -> SessionWriter:
    return SessionWriter(
        data_root=tmp_path,
        participant_id="P001",
        config_snapshot=config.model_dump(mode="json"),
        schedule=schedule,
        rng_seed=42,
    )


# ---------------------------------------------------------------------------
# Auto-incrementing participant ID
# ---------------------------------------------------------------------------


def test_next_participant_id_empty_root(tmp_path: Path):
    assert next_participant_id(tmp_path) == "P001"


def test_next_participant_id_root_does_not_exist(tmp_path: Path):
    assert next_participant_id(tmp_path / "does-not-exist-yet") == "P001"


def test_next_participant_id_increments(tmp_path: Path):
    (tmp_path / "P001").mkdir()
    (tmp_path / "P003").mkdir()
    (tmp_path / "P002").mkdir()
    assert next_participant_id(tmp_path) == "P004"


def test_next_participant_id_ignores_non_matching_dirs(tmp_path: Path):
    (tmp_path / "P001").mkdir()
    (tmp_path / "scratch").mkdir()
    (tmp_path / "PXX").mkdir()
    (tmp_path / "X007").mkdir()
    assert next_participant_id(tmp_path) == "P002"


def test_next_participant_id_ignores_files(tmp_path: Path):
    (tmp_path / "P005").mkdir()
    (tmp_path / "P099").write_text("not a directory", encoding="utf-8")
    assert next_participant_id(tmp_path) == "P006"


def test_next_participant_id_respects_zfill(tmp_path: Path):
    assert next_participant_id(tmp_path, prefix="S", zfill=4) == "S0001"


# ---------------------------------------------------------------------------
# Block CSV writing
# ---------------------------------------------------------------------------


def test_block_csv_filename_format():
    assert block_csv_filename(0, "calibration") == "block_00_calibration.csv"
    assert block_csv_filename(7, "rest_oddball_passive") == "block_07_rest_oddball_passive.csv"


def test_silent_block_writes_two_row_csv(writer: SessionWriter):
    rec = writer.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=100.0)
    writer.end_block(rec, end_lsl=190.0, ratings={"alertness": 5})

    csv_path = writer.session_dir / "block_01_rest_only.csv"
    assert csv_path.exists()

    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["event"] == "block_start"
    assert rows[0]["t_lsl"] == "100.000000"
    assert rows[1]["event"] == "block_end"
    assert rows[1]["t_lsl"] == "190.000000"
    # Silent blocks have NA in trial-related columns.
    assert rows[0]["trial_idx"] == "NA"
    assert rows[0]["tone_type"] == "NA"


def test_oddball_block_writes_one_row_per_tone(writer: SessionWriter):
    rec = writer.start_block(
        idx=2, condition="chills_oddball_passive", duration_s=90, start_lsl=200.0
    )
    trials = [
        TrialRow(trial_idx=0, t_lsl=200.012, event="tone_onset", tone_type="standard"),
        TrialRow(trial_idx=1, t_lsl=201.412, event="tone_onset", tone_type="standard"),
        TrialRow(trial_idx=2, t_lsl=202.812, event="tone_onset", tone_type="deviant"),
    ]
    writer.end_block(rec, end_lsl=290.0, trials=trials, ratings={"success": True})

    csv_path = writer.session_dir / "block_02_chills_oddball_passive.csv"
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert rows[2]["tone_type"] == "deviant"
    assert rows[2]["trial_idx"] == "2"
    assert rows[2]["response"] == "NA"


def test_active_block_writes_response_rows(writer: SessionWriter):
    rec = writer.start_block(
        idx=17, condition="active_oddball", duration_s=300, start_lsl=500.0
    )
    trials = [
        TrialRow(trial_idx=0, t_lsl=500.0, event="tone_onset", tone_type="standard"),
        TrialRow(trial_idx=1, t_lsl=501.4, event="tone_onset", tone_type="deviant"),
        TrialRow(
            trial_idx=1,
            t_lsl=501.812,
            event="response",
            tone_type="deviant",
            response="hit",
            rt_ms=412,
        ),
    ]
    writer.end_block(rec, end_lsl=800.0, trials=trials)

    csv_path = writer.session_dir / "block_17_active_oddball.csv"
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[2]["response"] == "hit"
    assert rows[2]["rt_ms"] == "412"


# ---------------------------------------------------------------------------
# JSON snapshot + finalize
# ---------------------------------------------------------------------------


def test_partial_written_after_each_block(writer: SessionWriter):
    rec = writer.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    writer.end_block(rec, end_lsl=40.0, ratings={"success": True, "waves": 2})

    partial = writer.session_dir / SessionWriter.PARTIAL_FILENAME
    assert partial.exists()
    with partial.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["status"] == "in_progress"
    assert data["session_end_utc"] is None
    assert len(data["blocks"]) == 1
    assert data["blocks"][0]["status"] == "completed"
    assert data["blocks"][0]["csv_path"] == "block_00_calibration.csv"


def test_finalize_completed_writes_session_and_deletes_partial(writer: SessionWriter):
    rec = writer.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    writer.end_block(rec, end_lsl=40.0)

    writer.finalize(status="completed")

    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    partial = writer.session_dir / SessionWriter.PARTIAL_FILENAME
    assert final.exists()
    assert not partial.exists()

    with final.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["status"] == "completed"
    assert data["session_end_utc"] is not None
    assert data["rng_seed"] == 42


def test_finalize_aborted_keeps_partial(writer: SessionWriter):
    """Mid-session abort: PARTIAL stays as forensic snapshot."""
    rec0 = writer.start_block(idx=0, condition="calibration", duration_s=30, start_lsl=10.0)
    writer.end_block(rec0, end_lsl=40.0)
    rec1 = writer.start_block(idx=1, condition="rest_only", duration_s=90, start_lsl=50.0)
    writer.end_block(rec1, end_lsl=140.0, status="aborted")

    writer.finalize(status="aborted")

    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    partial = writer.session_dir / SessionWriter.PARTIAL_FILENAME
    assert final.exists()
    assert partial.exists()  # forensic
    with final.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["status"] == "aborted"
    assert data["blocks"][1]["status"] == "aborted"


def test_finalize_invalid_status_raises(writer: SessionWriter):
    with pytest.raises(ValueError, match="status"):
        writer.finalize(status="exploded")


def test_session_json_includes_full_schedule(writer: SessionWriter, schedule):
    writer.finalize(status="completed")
    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    with final.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["schedule"]) == len(schedule)
    assert data["schedule"][0]["condition"] == "calibration"
    assert data["schedule"][-1]["condition"] == "active_oddball"


def test_active_oddball_summary_persisted(writer: SessionWriter):
    summary = {
        "practice_attempts": 1,
        "practice_passed": True,
        "main_total_trials": 250,
        "main_hits": 47,
        "main_misses": 3,
        "main_false_alarms": 12,
        "mean_rt_ms": 412.3,
        "engagement_rating": 8,
    }
    writer.set_active_oddball_summary(summary)
    writer.finalize(status="completed")

    final = writer.session_dir / SessionWriter.SESSION_FILENAME
    with final.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["active_oddball_summary"] == summary


def test_block_record_to_json_includes_csv_path(writer: SessionWriter):
    rec = writer.start_block(idx=3, condition="chills_only", duration_s=150, start_lsl=300.0)
    writer.end_block(rec, end_lsl=450.0, ratings={"success": True})
    j = rec.to_json()
    assert j["csv_path"] == "block_03_chills_only.csv"
    assert j["start_lsl"] == 300.0
    assert j["end_lsl"] == 450.0


# ---------------------------------------------------------------------------
# Recovery helpers
# ---------------------------------------------------------------------------


def test_has_partial_detects_existing_partial(tmp_path: Path):
    pdir = tmp_path / "P001"
    pdir.mkdir()
    (pdir / SessionWriter.PARTIAL_FILENAME).write_text("{}", encoding="utf-8")
    assert SessionWriter.has_partial(tmp_path, "P001")
    assert not SessionWriter.has_partial(tmp_path, "P002")


def test_discard_partial_is_idempotent(tmp_path: Path):
    (tmp_path / "P001").mkdir()
    SessionWriter.discard_partial(tmp_path, "P001")  # no error when absent
    (tmp_path / "P001" / SessionWriter.PARTIAL_FILENAME).write_text("{}")
    assert SessionWriter.has_partial(tmp_path, "P001")
    SessionWriter.discard_partial(tmp_path, "P001")
    assert not SessionWriter.has_partial(tmp_path, "P001")


def test_archive_partial_renames_with_timestamp(tmp_path: Path):
    (tmp_path / "P001").mkdir()
    (tmp_path / "P001" / SessionWriter.PARTIAL_FILENAME).write_text("{}")
    archived = SessionWriter.archive_partial(tmp_path, "P001")
    assert archived is not None
    assert archived.exists()
    assert archived.name.startswith("PARTIAL_session_")
    assert not (tmp_path / "P001" / SessionWriter.PARTIAL_FILENAME).exists()


# ---------------------------------------------------------------------------
# Direct BlockRecord smoke test (no writer)
# ---------------------------------------------------------------------------


def test_block_record_default_status():
    rec = BlockRecord(idx=0, condition="rest_only", duration_s=90)
    assert rec.status == "pending"
    assert rec.start_lsl is None
