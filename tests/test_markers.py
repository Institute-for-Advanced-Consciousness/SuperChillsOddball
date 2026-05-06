"""LSL marker round-trip tests.

Spins up an Outlet and a matching Inlet in-process and verifies every
marker convenience method emits the right wire format. No LabRecorder.
The tests skip cleanly if the local LSL stack can't resolve a stream
within a few seconds (common in firewalled CI environments).
"""

from __future__ import annotations

import pytest
from pylsl import StreamInlet, resolve_byprop

from chills_oddball.config import load_config
from chills_oddball.markers import ChillsMarkerOutlet, format_marker

# Generous discovery timeout so we don't flake on slow first-resolve.
_RESOLVE_TIMEOUT_S = 5.0
_PULL_TIMEOUT_S = 1.0


# ---------------------------------------------------------------------------
# format_marker pure-function tests (don't need LSL)
# ---------------------------------------------------------------------------


def test_format_marker_no_payload():
    assert format_marker("session_start") == "session_start"


def test_format_marker_with_payload():
    s = format_marker("block_start", {"idx": "03", "condition": "rest_only", "duration_s": 90})
    assert s == "block_start:idx=03:condition=rest_only:duration_s=90"


def test_format_marker_bool_payload_renders_yn():
    s = format_marker("ratings_submit", {"success": True, "keep": False})
    assert s == "ratings_submit:success=Y:keep=N"


def test_format_marker_rejects_reserved_chars_in_value():
    with pytest.raises(ValueError, match="reserved character"):
        format_marker("foo", {"key": "has:colon"})
    with pytest.raises(ValueError, match="reserved character"):
        format_marker("foo", {"key": "has=equals"})


# ---------------------------------------------------------------------------
# Round-trip via Inlet
# ---------------------------------------------------------------------------


@pytest.fixture
def lsl_round_trip():
    """Open outlet, resolve it as an Inlet, yield (outlet, inlet); skip on failure."""
    cfg = load_config().lsl
    outlet = ChillsMarkerOutlet(cfg)
    outlet.open()
    streams = resolve_byprop("name", cfg.stream_name, timeout=_RESOLVE_TIMEOUT_S)
    if not streams:
        outlet.close()
        pytest.skip(
            "LSL stream did not resolve locally within timeout — likely a "
            "firewall blocking multicast loopback. Not a real failure."
        )
    inlet = StreamInlet(streams[0], max_buflen=120, recover=False)
    # Open the stream connection up front so the first push isn't dropped.
    inlet.open_stream(timeout=_RESOLVE_TIMEOUT_S)
    try:
        yield outlet, inlet
    finally:
        inlet.close_stream()
        outlet.close()


def _pull(inlet: StreamInlet) -> str:
    sample, _ts = inlet.pull_sample(timeout=_PULL_TIMEOUT_S)
    if sample is None:
        raise AssertionError("no marker received within timeout")
    return sample[0]


def test_round_trip_session_start(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    text, _ = outlet.session_start()
    assert _pull(inlet) == text == "session_start"


def test_round_trip_participant_id(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    text, _ = outlet.participant_id("P017")
    assert _pull(inlet) == text == "participant_id:pid=P017"


def test_round_trip_session_seed(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    text, _ = outlet.session_config_seed(123456789)
    assert _pull(inlet) == text == "session_config_seed:seed=123456789"


def test_round_trip_block_start(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    text, _ = outlet.block_start(idx=3, condition="chills_only", duration_s=90)
    assert _pull(inlet) == text == "block_start:idx=03:condition=chills_only:duration_s=90"


def test_round_trip_block_end(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    text, _ = outlet.block_end(idx=12, condition="rest_oddball_passive")
    assert _pull(inlet) == text == "block_end:idx=12:condition=rest_oddball_passive"


def test_round_trip_gong_markers(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    a, _ = outlet.block_gong_start()
    b, _ = outlet.block_gong_end()
    assert _pull(inlet) == a == "block_gong_start"
    assert _pull(inlet) == b == "block_gong_end"


def test_round_trip_calibration_markers(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    a, _ = outlet.calibration_start()
    b, _ = outlet.calibration_end()
    assert _pull(inlet) == a == "calibration_start"
    assert _pull(inlet) == b == "calibration_end"


def test_round_trip_tone_markers(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    s, _ = outlet.tone_standard(trial=5, condition="chills_oddball_passive")
    d, _ = outlet.tone_deviant(trial=6, condition="chills_oddball_passive")
    assert _pull(inlet) == s == "tone_standard:trial=5:condition=chills_oddball_passive"
    assert _pull(inlet) == d == "tone_deviant:trial=6:condition=chills_oddball_passive"


def test_round_trip_active_response_markers(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    h, _ = outlet.active_response_hit(rt_ms=412)
    m, _ = outlet.active_response_miss()
    f, _ = outlet.active_response_false_alarm(rt_ms=850)
    assert _pull(inlet) == h == "active_response_hit:rt_ms=412"
    assert _pull(inlet) == m == "active_response_miss"
    assert _pull(inlet) == f == "active_response_false_alarm:rt_ms=850"


def test_round_trip_active_practice_markers(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    a, _ = outlet.active_practice_start(attempt=2)
    s, _ = outlet.active_practice_tone_standard()
    d, _ = outlet.active_practice_tone_deviant()
    p, _ = outlet.active_practice_passed()
    e, _ = outlet.active_practice_end(attempt=2)
    assert _pull(inlet) == a == "active_practice_start:attempt=2"
    assert _pull(inlet) == s == "active_practice_tone_standard"
    assert _pull(inlet) == d == "active_practice_tone_deviant"
    assert _pull(inlet) == p == "active_practice_passed"
    assert _pull(inlet) == e == "active_practice_end:attempt=2"


def test_round_trip_ratings_chills(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    s, _ = outlet.ratings_start(block_idx=4)
    sub, _ = outlet.ratings_submit_chills(
        block_idx=4, success=True, waves=3, intensity=7, quality=8, keep=True
    )
    e, _ = outlet.ratings_end(block_idx=4)
    assert _pull(inlet) == s == "ratings_start:block_idx=04"
    assert (
        _pull(inlet)
        == sub
        == "ratings_submit:block_idx=04:success=Y:waves=3:intensity=7:quality=8:keep=Y"
    )
    assert _pull(inlet) == e == "ratings_end:block_idx=04"


def test_round_trip_ratings_rest(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    sub, _ = outlet.ratings_submit_rest(block_idx=7, alertness=4)
    assert _pull(inlet) == sub == "ratings_submit:block_idx=07:alertness=4"


def test_round_trip_session_end_and_abort(lsl_round_trip):
    outlet, inlet = lsl_round_trip
    e, _ = outlet.session_end()
    a, _ = outlet.session_abort()
    assert _pull(inlet) == e == "session_end"
    assert _pull(inlet) == a == "session_abort"


# ---------------------------------------------------------------------------
# Outlet lifecycle
# ---------------------------------------------------------------------------


def test_emit_before_open_raises():
    cfg = load_config().lsl
    outlet = ChillsMarkerOutlet(cfg)
    with pytest.raises(RuntimeError, match="not open"):
        outlet.session_start()


def test_outlet_context_manager():
    cfg = load_config().lsl
    with ChillsMarkerOutlet(cfg) as outlet:
        assert outlet.is_open
    assert not outlet.is_open
