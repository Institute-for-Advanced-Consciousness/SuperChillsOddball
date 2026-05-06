"""Tests for the active oddball stage and its pure helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from chills_oddball.audio import TrialRecord
from chills_oddball.config import load_config
from chills_oddball.schedule import ScheduledBlock, generate_session_schedule
from chills_oddball.stages.active_oddball import (
    PracticeOutcome,
    ResponseRecord,
    classify_responses,
    evaluate_practice,
)

# ---------------------------------------------------------------------------
# Pure-function tests (no Tk needed)
# ---------------------------------------------------------------------------


def _tone(idx: int, t: float, *, deviant: bool = False) -> TrialRecord:
    return TrialRecord(trial_idx=idx, is_deviant=deviant, onset_sample=idx * 1000, onset_lsl=t)


def test_classify_responses_hit_within_window():
    tones = [_tone(0, t=10.0, deviant=True)]
    presses = [10.4]  # 400 ms after deviant
    results = classify_responses(tones, presses, window_s=1.5)
    assert len(results) == 1
    assert results[0].kind == "hit"
    assert results[0].rt_ms == 400


def test_classify_responses_miss_when_no_press():
    tones = [_tone(0, t=10.0, deviant=True)]
    results = classify_responses(tones, press_times=[], window_s=1.5)
    assert results[0].kind == "miss"
    assert results[0].rt_ms is None


def test_classify_responses_false_alarm_on_standard():
    tones = [_tone(0, t=10.0, deviant=False)]
    presses = [10.5]
    results = classify_responses(tones, presses, window_s=1.5)
    assert results[0].kind == "false_alarm"
    assert results[0].rt_ms == 500


def test_classify_responses_correct_rejection_on_standard_no_press():
    tones = [_tone(0, t=10.0, deviant=False)]
    results = classify_responses(tones, press_times=[], window_s=1.5)
    assert results[0].kind == "correct_rejection"


def test_classify_responses_press_outside_window_ignored():
    tones = [_tone(0, t=10.0, deviant=True)]
    presses = [12.5]  # 2500 ms — beyond 1500 ms window
    results = classify_responses(tones, presses, window_s=1.5)
    assert results[0].kind == "miss"


def test_classify_responses_one_press_consumed_by_first_match():
    """A press attributed to the first eligible tone shouldn't double-attribute."""
    tones = [
        _tone(0, t=10.0, deviant=True),
        _tone(1, t=10.5, deviant=True),  # within 500 ms of tone 0
    ]
    presses = [10.3]
    results = classify_responses(tones, presses, window_s=1.5)
    # First deviant gets the hit; second is a miss.
    assert results[0].kind == "hit"
    assert results[1].kind == "miss"


def test_classify_responses_attributes_to_correct_tone_in_sequence():
    tones = [
        _tone(0, t=10.0, deviant=False),  # standard
        _tone(1, t=11.5, deviant=True),  # deviant
        _tone(2, t=13.0, deviant=False),  # standard
    ]
    presses = [11.7]  # 200 ms after deviant
    results = classify_responses(tones, presses, window_s=1.5)
    kinds = [r.kind for r in results]
    assert kinds == ["correct_rejection", "hit", "correct_rejection"]


# ---------------------------------------------------------------------------
# evaluate_practice
# ---------------------------------------------------------------------------


def _mk_records(hits: int, misses: int, fas: int, crs: int) -> list[ResponseRecord]:
    out = []
    idx = 0
    for _ in range(hits):
        out.append(ResponseRecord(idx, True, idx * 1.3, "hit", 400))
        idx += 1
    for _ in range(misses):
        out.append(ResponseRecord(idx, True, idx * 1.3, "miss", None))
        idx += 1
    for _ in range(fas):
        out.append(ResponseRecord(idx, False, idx * 1.3, "false_alarm", 500))
        idx += 1
    for _ in range(crs):
        out.append(ResponseRecord(idx, False, idx * 1.3, "correct_rejection", None))
        idx += 1
    return out


def test_evaluate_practice_passes_at_default_thresholds():
    # 2 deviants, 2 hits, 0 misses, 8 standards, 0 FAs, 8 CRs -> 100% / 0%
    records = _mk_records(hits=2, misses=0, fas=0, crs=8)
    o = evaluate_practice(records, hit_threshold=0.75, fa_ceiling=0.50)
    assert o.hit_rate == 1.0
    assert o.fa_rate == 0.0
    assert o.passed


def test_evaluate_practice_fails_on_low_hit_rate():
    # 2 deviants, 1 hit, 1 miss -> 50% hit rate -> below 75%
    records = _mk_records(hits=1, misses=1, fas=0, crs=8)
    o = evaluate_practice(records, hit_threshold=0.75, fa_ceiling=0.50)
    assert o.hit_rate == 0.5
    assert not o.passed


def test_evaluate_practice_fails_on_high_fa_rate():
    # 8 standards, 5 false alarms -> 62.5% FA rate -> above 50%
    records = _mk_records(hits=2, misses=0, fas=5, crs=3)
    o = evaluate_practice(records, hit_threshold=0.75, fa_ceiling=0.50)
    assert o.hit_rate == 1.0
    assert o.fa_rate > 0.5
    assert not o.passed


def test_evaluate_practice_zero_division_safe():
    o = evaluate_practice([], hit_threshold=0.75, fa_ceiling=0.50)
    assert o.hit_rate == 0.0
    assert o.fa_rate == 0.0
    assert isinstance(o, PracticeOutcome)


# ---------------------------------------------------------------------------
# Stage integration (Tk + mocked services)
# ---------------------------------------------------------------------------


@pytest.fixture
def app(shared_app):
    return shared_app


@dataclass
class MockOutlet:
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def block_start(self, *, idx, condition, duration_s):
        self.calls.append(("block_start", {"idx": idx, "condition": condition}))
        return ("block_start", 100.0)

    def block_end(self, *, idx, condition):
        self.calls.append(("block_end", {"idx": idx, "condition": condition}))
        return ("block_end", 200.0)

    def active_practice_start(self, *, attempt):
        self.calls.append(("active_practice_start", {"attempt": attempt}))
        return ("aps", 0.0)

    def active_practice_end(self, *, attempt):
        self.calls.append(("active_practice_end", {"attempt": attempt}))
        return ("ape", 0.0)

    def active_practice_passed(self):
        self.calls.append(("active_practice_passed", {}))
        return ("app_p", 0.0)

    def active_response_hit(self, *, rt_ms):
        self.calls.append(("active_response_hit", {"rt_ms": rt_ms}))
        return ("hit", 0.0)

    def active_response_miss(self):
        self.calls.append(("active_response_miss", {}))
        return ("miss", 0.0)

    def active_response_false_alarm(self, *, rt_ms):
        self.calls.append(("active_response_false_alarm", {"rt_ms": rt_ms}))
        return ("fa", 0.0)


@dataclass
class MockWriter:
    """Stores BlockRecord objects so the completion stage's summary works."""

    blocks: list = field(default_factory=list)
    ended: list = field(default_factory=list)
    summary: dict | None = None
    participant_id: str = "P_TEST"
    active_oddball_summary: dict | None = None

    def start_block(self, *, idx, condition, duration_s, start_lsl):
        from chills_oddball.persistence import BlockRecord

        rec = BlockRecord(
            idx=idx, condition=condition, duration_s=duration_s,
            start_lsl=start_lsl, status="pending",
        )
        self.blocks.append(rec)
        return rec

    def end_block(self, *, record, end_lsl, trials, ratings, status):
        record.end_lsl = end_lsl
        record.status = status
        record.ratings = ratings
        self.ended.append({"record": record, "end_lsl": end_lsl,
                           "trials": trials, "status": status})

    def set_active_oddball_summary(self, summary):
        self.summary = summary
        self.active_oddball_summary = summary


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


def test_active_on_enter_shows_intro_phase(app):
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]
    assert frame._phase == "intro"
    assert "HIGH" in frame.body_var.get() or "high" in frame.body_var.get()


def _prep_practice_records(deviant_positions: list[int], n_trials: int = 10) -> list[TrialRecord]:
    """Build a fake practice tone-record list. ``deviant_positions`` lists trial indices."""
    return [
        TrialRecord(
            trial_idx=i,
            is_deviant=(i in deviant_positions),
            onset_sample=i * 1000,
            onset_lsl=10.0 + i * 1.3,
        )
        for i in range(n_trials)
    ]


def test_active_practice_pass_advances_to_post_practice(app):
    """All hits + 0 FAs -> gate passes -> post_practice."""
    app.outlet = MockOutlet()
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]

    # Bypass the audio worker: stage the records and presses directly,
    # then call _on_practice_audio_done as if the worker just finished.
    frame._practice_attempt = 1
    frame._phase = "practice"
    frame._worker_records = _prep_practice_records(deviant_positions=[3, 7])
    frame._press_log = [
        r.onset_lsl + 0.4 for r in frame._worker_records if r.is_deviant
    ]
    frame._on_practice_audio_done()

    assert frame._phase == "post_practice"
    events = [c[0] for c in app.outlet.calls]
    assert "active_practice_passed" in events
    assert "active_practice_end" in events


def test_active_practice_fail_returns_to_intro_for_retry(app):
    """No presses -> all deviants miss -> gate fails -> phase becomes intro again."""
    app.outlet = MockOutlet()
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]

    frame._practice_attempt = 1
    frame._phase = "practice"
    frame._worker_records = _prep_practice_records(deviant_positions=[3, 7])
    frame._press_log = []  # zero responses
    frame._on_practice_audio_done()

    assert frame._phase == "intro"  # retry-ready
    events = [c[0] for c in app.outlet.calls]
    assert "active_practice_passed" not in events
    assert "active_practice_end" in events


def test_active_main_block_writes_summary_and_advances_to_completion(app):
    """Bypass audio for both practice and main; verify writer + summary + routing."""
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]

    # Bypass practice gate.
    frame._practice_attempt = 1
    frame._phase = "practice"
    frame._worker_records = _prep_practice_records(deviant_positions=[3, 7])
    frame._press_log = [r.onset_lsl + 0.4 for r in frame._worker_records if r.is_deviant]
    frame._on_practice_audio_done()
    assert frame._phase == "post_practice"

    # Bypass _on_post_practice_space (which would launch real audio).
    # Manually set up main-phase state and call the audio-done handler.
    frame._phase = "main"
    frame._record = app.writer.start_block(
        idx=17, condition="active_oddball", duration_s=300, start_lsl=100.0
    )
    main_records = [
        TrialRecord(
            trial_idx=i,
            is_deviant=(i % 5 == 0),
            onset_sample=i * 1000,
            onset_lsl=100.0 + i * 1.3,
        )
        for i in range(20)
    ]
    frame._worker_records = main_records
    frame._press_log = [r.onset_lsl + 0.4 for r in main_records if r.is_deviant]
    frame._on_main_audio_done()
    assert frame._phase == "engagement"

    # Submit engagement.
    frame._engagement_var.set(8)
    frame._on_engagement_submit()
    assert app.current_stage == "completion"
    assert app.writer.summary is not None
    assert app.writer.summary["engagement_rating"] == 8
    assert app.writer.summary["main_total_trials"] == 20
    assert app.writer.summary["main_hits"] == 4  # 4 deviants in 20 trials at i%5
    assert app.writer.summary["main_false_alarms"] == 0
    assert len(app.writer.ended) == 1


def test_active_main_shows_eyes_closed_view(app, monkeypatch):
    """The active-main phase shows the eyes-closed body with the SPACE reminder.

    We patch _launch_audio_worker so the worker never auto-completes —
    otherwise the no-audio path fabricates records instantly and the
    phase races to 'engagement' before we can read the body text.
    """
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]
    # Suppress the audio worker so _start_main returns with phase=='main'.
    monkeypatch.setattr(frame, "_launch_audio_worker", lambda **kw: None)
    frame._start_main()
    assert frame._phase == "main"
    body = frame.body_var.get()
    assert "Your eyes should be closed" in body
    assert "ACTIVE LISTENING" in body
    assert "SPACE" in body


def test_active_main_emits_response_markers_for_all_deviants(app):
    app.outlet = MockOutlet()
    app.writer = MockWriter()
    block = ScheduledBlock(idx=17, condition="active_oddball", duration_s=300)
    app.show_stage("active_oddball", block=block)
    frame = app.stages["active_oddball"]
    # Skip directly to main.
    frame._phase = "main"
    frame._record = app.writer.start_block(
        idx=17, condition="active_oddball", duration_s=300, start_lsl=100.0
    )
    main_records = _prep_practice_records(deviant_positions=[3, 7])
    frame._worker_records = main_records
    # Press only on the first deviant.
    frame._press_log = [main_records[3].onset_lsl + 0.4]
    frame._on_main_audio_done()
    events = [c[0] for c in app.outlet.calls]
    # 1 hit + 1 miss + 0 FAs.
    assert events.count("active_response_hit") == 1
    assert events.count("active_response_miss") == 1
    assert events.count("active_response_false_alarm") == 0


def test_active_requires_block_payload(app):
    with pytest.raises(ValueError, match="block="):
        app.show_stage("active_oddball")
