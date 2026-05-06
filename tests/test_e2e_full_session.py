"""End-to-end full-session walkthrough.

Drives the entire flow programmatically: intake -> volume -> instructions
-> calibration -> 16 short blocks -> active oddball -> completion. Real
services are attached (real LSL outlet, real SessionWriter writing to a
tmp dir); only ToneScheduler.play_block is monkeypatched to return
instant synthetic TrialRecords (otherwise we'd play ~30 minutes of audio).

The test asserts:
  - every stage is visited
  - the session.json on disk is well-formed and complete
  - exactly 18 blocks recorded, all status='completed'
  - active_oddball_summary populated
  - PARTIAL_session.json is gone (Save & Exit deletes it on clean exit)
"""

from __future__ import annotations

import json
import shutil
import time
import tkinter as tk
from pathlib import Path

import pytest

from chills_oddball.audio import TrialRecord
from chills_oddball.persistence import SessionWriter


@pytest.fixture(scope="module")
def fresh_app():
    """A *new* App instance dedicated to this test (we'll destroy it cleanly at end)."""
    try:
        from chills_oddball.app import App

        a = App()
    except tk.TclError as e:
        pytest.skip(f"Tk display not available: {e}")
    yield a
    try:
        a.shutdown()
    except Exception:
        pass


def _wait_until(predicate, timeout_s: float = 10.0, app=None) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if app is not None:
            app.root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timeout waiting for predicate")


def _wait_for_stage(app, name: str, timeout_s: float = 10.0) -> None:
    _wait_until(lambda: app.current_stage == name, timeout_s=timeout_s, app=app)


def _wait_for_phase(app, phase: str, timeout_s: float = 10.0) -> None:
    frame = app.stages["active_oddball"]
    _wait_until(lambda: frame._phase == phase, timeout_s=timeout_s, app=app)


def _patch_tone_scheduler(monkeypatch):
    """Replace ToneScheduler.play_block with an instant synthetic-record stub."""
    from chills_oddball import audio as audio_module

    def _fake_play_block(self, *, sequence, block_idx, condition, rng, practice=False):
        from pylsl import local_clock

        now = local_clock()
        records = [
            TrialRecord(
                trial_idx=i,
                is_deviant=bool(s),
                onset_sample=i * 1000,
                onset_lsl=now + i * 1.3,
            )
            for i, s in enumerate(sequence)
        ]
        # Emit the matching markers so the LSL stream still gets them
        # (verify_xdf would catch us if we silently dropped them).
        if self.outlet is not None:
            for r in records:
                try:
                    if practice:
                        if r.is_deviant:
                            self.outlet.active_practice_tone_deviant(timestamp=r.onset_lsl)
                        else:
                            self.outlet.active_practice_tone_standard(timestamp=r.onset_lsl)
                    else:
                        if r.is_deviant:
                            self.outlet.tone_deviant(
                                trial=r.trial_idx, condition=condition,
                                timestamp=r.onset_lsl,
                            )
                        else:
                            self.outlet.tone_standard(
                                trial=r.trial_idx, condition=condition,
                                timestamp=r.onset_lsl,
                            )
                except Exception:
                    pass
        return records

    monkeypatch.setattr(audio_module.ToneScheduler, "play_block", _fake_play_block)

    # Also stub the gong + reference helpers (they call sd.play; we don't want noise).
    def _no_play_gong(audio_config, repo_root, which, outlet=None, blocking=True):
        if outlet is not None:
            try:
                if which == "start":
                    outlet.block_gong_start()
                else:
                    outlet.block_gong_end()
            except Exception:
                pass
        return None

    def _no_reference_tone(audio_config, repo_root, stop_event):
        stop_event.wait(0.1)  # short noop

    monkeypatch.setattr(audio_module, "play_gong", _no_play_gong)
    monkeypatch.setattr(audio_module, "play_reference_tone", _no_reference_tone)


def _short_block_durations(monkeypatch):
    """Override the block-duration set so silent blocks don't actually wait
    30/90/150/180 seconds.
    """
    # Patch ScheduledBlock.duration_s to be 0 for silent blocks, by patching
    # generate_session_schedule output instead.
    from chills_oddball import schedule as schedule_module

    real_gen = schedule_module.generate_session_schedule

    def _fast_gen(config, seed=None, participant_id=None):
        blocks = real_gen(config, seed=seed, participant_id=participant_id)
        # Replace duration_s on every block with 0 so silent blocks finish instantly.
        from chills_oddball.schedule import ScheduledBlock

        return [
            ScheduledBlock(idx=b.idx, condition=b.condition, duration_s=0)
            for b in blocks
        ]

    monkeypatch.setattr(schedule_module, "generate_session_schedule", _fast_gen)
    # Intake imports it directly — patch the binding there too.
    from chills_oddball.stages import intake as intake_module

    monkeypatch.setattr(intake_module, "generate_session_schedule", _fast_gen)


def _click_chills_ratings_submit(app):
    """Fill in a chills ratings panel with sensible defaults and submit."""
    frame = app.stages["ratings_chills"]
    frame._vars["success"].set("Yes")
    frame._vars["waves"].set(2)
    frame._vars["intensity"].set(6)
    frame._vars["quality"].set(7)
    frame._vars["keep"].set("Yes, keep")
    frame._on_submit()


def _click_rest_ratings_submit(app):
    frame = app.stages["ratings_rest"]
    frame._vars["alertness"].set(5)
    frame._on_submit()


# ---------------------------------------------------------------------------


def test_full_session_walkthrough(fresh_app, tmp_path, monkeypatch):
    """Drive every stage from intake to completion and audit the artifacts."""
    app = fresh_app

    # Set up a temp REPO_ROOT so Data/ lands in tmp_path; copy assets across
    # so ToneScheduler can find the .wav files (its constructor reads them
    # before our monkeypatch can take effect).
    from chills_oddball.config import REPO_ROOT as REAL_REPO_ROOT
    from chills_oddball.stages import intake as intake_module

    shutil.copytree(REAL_REPO_ROOT / "assets", tmp_path / "assets")
    monkeypatch.setattr(intake_module, "REPO_ROOT", tmp_path)

    # Speed everything up.
    _patch_tone_scheduler(monkeypatch)
    _short_block_durations(monkeypatch)

    # Start at intake.
    app.show_stage("intake")
    intake = app.stages["intake"]
    intake.on_enter()
    intake._pid_var.set("P_E2E")
    intake._on_begin()
    _wait_for_stage(app, "volume_check")
    assert app.outlet is not None and app.outlet.is_open
    assert app.audio_scheduler is not None
    assert app.writer is not None
    assert len(app.schedule) == 18

    # Volume check -> instructions -> first block.
    app.stages["volume_check"]._on_space()
    _wait_for_stage(app, "instructions")
    app.stages["instructions"]._on_space()
    _wait_for_stage(app, "calibration_chills")

    # Calibration block.
    app.stages["calibration_chills"]._on_space()
    _wait_for_stage(app, "ratings_chills")
    _click_chills_ratings_submit(app)

    # Loop through the 16 short-condition blocks.
    visited_conditions: list[str] = []
    for _ in range(16):
        # We should be in either block_runner -> ratings_{chills|rest}.
        _wait_until(
            lambda: app.current_stage == "block_runner", timeout_s=5.0, app=app
        )
        block = app.stages["block_runner"]._block
        assert block is not None
        visited_conditions.append(block.condition)
        app.stages["block_runner"]._on_space()
        # Wait for routing into a ratings panel.
        _wait_until(
            lambda: app.current_stage in ("ratings_chills", "ratings_rest"),
            timeout_s=10.0,
            app=app,
        )
        if app.current_stage == "ratings_chills":
            _click_chills_ratings_submit(app)
        else:
            _click_rest_ratings_submit(app)

    # Should now be in active oddball.
    _wait_for_stage(app, "active_oddball", timeout_s=10.0)
    active = app.stages["active_oddball"]

    # Drive the practice gate to a pass: simulate hits on all deviants.
    active._on_intro_space()
    _wait_for_phase(app, "practice", timeout_s=5.0)
    # Wait briefly for the worker to populate records, then top up press_log.
    _wait_until(
        lambda: active._worker_records is not None, timeout_s=5.0, app=app
    )
    # Inject hits at +0.4 s after every deviant, AFTER worker_records exist.
    # The poller fires _on_practice_audio_done as soon as the worker sets
    # the done event; we want our presses landing in _press_log before that.
    # Since the no-audio worker is synchronous (instant), it will already
    # have called _on_practice_audio_done. To control this in the test we
    # bypass: re-run the gate by calling _on_practice_audio_done with our
    # injected presses.
    # Force a clean re-run with all hits.
    active._press_log = [
        r.onset_lsl + 0.4 for r in active._worker_records if r.is_deviant
    ]
    active._on_practice_audio_done()
    assert active._phase == "post_practice"

    # Begin main block. Bypass _on_post_practice_space's audio launch: stage
    # synthetic main records + presses, then call the audio-done handler.
    active._phase = "main"
    active._record = app.writer.start_block(
        idx=17, condition="active_oddball", duration_s=300, start_lsl=0.0
    )
    from pylsl import local_clock

    now = local_clock()
    main_records = [
        TrialRecord(
            trial_idx=i,
            is_deviant=(i % 5 == 0 and i >= 3),
            onset_sample=i * 1000,
            onset_lsl=now + i * 1.3,
        )
        for i in range(50)
    ]
    active._worker_records = main_records
    active._press_log = [r.onset_lsl + 0.4 for r in main_records if r.is_deviant]
    active._on_main_audio_done()
    assert active._phase == "engagement"

    # Engagement submit -> completion.
    active._engagement_var.set(8)
    active._on_engagement_submit()
    _wait_for_stage(app, "completion")

    # Complete + Save & Exit. Patch shutdown so the test's app survives.
    monkeypatch.setattr(app, "shutdown", lambda: None)
    completion = app.stages["completion"]
    completion._on_save_and_exit()

    # ---- AUDIT THE ARTIFACTS ----------------------------------------------
    session_dir = Path(app.writer.session_dir)
    assert session_dir.exists()

    final_path = session_dir / SessionWriter.SESSION_FILENAME
    partial_path = session_dir / SessionWriter.PARTIAL_FILENAME
    assert final_path.exists(), "session.json was not written"
    assert not partial_path.exists(), "PARTIAL should be deleted on clean exit"

    with final_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["participant_id"] == "P_E2E"
    assert data["status"] == "completed"
    assert data["session_end_utc"] is not None
    assert len(data["schedule"]) == 18
    assert len(data["blocks"]) == 18, f"expected 18 blocks, got {len(data['blocks'])}"
    statuses = [b["status"] for b in data["blocks"]]
    assert set(statuses) == {"completed"}, f"non-completed blocks: {statuses}"

    # Active oddball summary present.
    ao = data["active_oddball_summary"]
    assert ao is not None
    assert ao["main_total_trials"] == 50
    assert ao["engagement_rating"] == 8
    assert ao["main_hits"] >= 1

    # 16 short blocks should have CSV files; calibration too. (Active uses
    # writer.start_block path differently — we manually opened it above —
    # so it should also have a CSV.)
    csv_files = sorted(p.name for p in session_dir.glob("block_*.csv"))
    assert len(csv_files) == 18

    # Visited every short condition at least once.
    assert set(visited_conditions) == {
        "chills_only",
        "rest_only",
        "chills_oddball_passive",
        "rest_oddball_passive",
    }
