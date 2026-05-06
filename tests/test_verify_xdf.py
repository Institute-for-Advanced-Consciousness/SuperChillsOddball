"""Tests for verify_xdf parsing + constraint-violation logic.

Doesn't actually load an .xdf file (that would require pyxdf + a sample
XDF in the repo). Instead, tests drive the script's pure helpers
directly with synthetic ParsedMarker streams.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# verify_xdf lives under scripts/ (not packaged), so import it explicitly.
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_xdf.py"
_spec = importlib.util.spec_from_file_location("verify_xdf", _SCRIPT_PATH)
verify_xdf = importlib.util.module_from_spec(_spec)
sys.modules["verify_xdf"] = verify_xdf
_spec.loader.exec_module(verify_xdf)


# ---------------------------------------------------------------------------
# parse_marker
# ---------------------------------------------------------------------------


def test_parse_marker_no_payload():
    m = verify_xdf.parse_marker("session_start", 12345.6)
    assert m.event == "session_start"
    assert m.payload == {}
    assert m.timestamp == 12345.6


def test_parse_marker_simple_payload():
    m = verify_xdf.parse_marker("participant_id:pid=P017", 1.0)
    assert m.event == "participant_id"
    assert m.payload == {"pid": "P017"}


def test_parse_marker_multi_payload():
    m = verify_xdf.parse_marker(
        "block_start:idx=03:condition=chills_only:duration_s=90", 1.0
    )
    assert m.event == "block_start"
    assert m.payload == {"idx": "03", "condition": "chills_only", "duration_s": "90"}


def test_parse_marker_unrecognized_returns_event_only():
    m = verify_xdf.parse_marker("Some Other Stream Marker With Spaces", 1.0)
    assert m.event == "Some Other Stream Marker With Spaces"
    assert m.payload == {}


# ---------------------------------------------------------------------------
# count_events
# ---------------------------------------------------------------------------


def test_count_events_groups_by_event_name():
    markers = [
        verify_xdf.parse_marker("session_start", 1.0),
        verify_xdf.parse_marker("tone_standard:trial=0:condition=x", 1.1),
        verify_xdf.parse_marker("tone_standard:trial=1:condition=x", 1.2),
        verify_xdf.parse_marker("tone_deviant:trial=2:condition=x", 1.3),
    ]
    counts = verify_xdf.count_events(markers)
    assert counts["session_start"] == 1
    assert counts["tone_standard"] == 2
    assert counts["tone_deviant"] == 1


# ---------------------------------------------------------------------------
# collect_tones_by_condition
# ---------------------------------------------------------------------------


def test_collect_tones_by_condition_separates_per_condition():
    markers = [
        verify_xdf.parse_marker("tone_standard:trial=0:condition=A", 0.0),
        verify_xdf.parse_marker("tone_standard:trial=1:condition=A", 1.3),
        verify_xdf.parse_marker("tone_deviant:trial=2:condition=A", 2.6),
        verify_xdf.parse_marker("tone_standard:trial=0:condition=B", 5.0),
    ]
    stats = verify_xdf.collect_tones_by_condition(markers)
    assert stats["A"].n_standard == 2
    assert stats["A"].n_deviant == 1
    assert len(stats["A"].isis_ms) == 2
    assert stats["A"].isis_ms[0] == pytest.approx(1300.0)
    assert stats["B"].n_standard == 1


# ---------------------------------------------------------------------------
# find_constraint_violations
# ---------------------------------------------------------------------------


def _block(idx: int, cond: str, sequence: list[bool], start_t: float = 100.0):
    """Build the marker list for one block from a True/False sequence."""
    out = [verify_xdf.parse_marker(
        f"block_start:idx={idx:02d}:condition={cond}:duration_s=90", start_t
    )]
    for trial_idx, is_dev in enumerate(sequence):
        evt = "tone_deviant" if is_dev else "tone_standard"
        out.append(
            verify_xdf.parse_marker(
                f"{evt}:trial={trial_idx}:condition={cond}",
                start_t + 1.0 + trial_idx * 1.3,
            )
        )
    out.append(
        verify_xdf.parse_marker(f"block_end:idx={idx:02d}:condition={cond}", start_t + 200.0)
    )
    return out


def test_violations_clean_sequence_returns_empty():
    seq = [False, False, False, True, False, False, False, True, False, False]
    markers = _block(1, "chills_oddball_passive", seq)
    v = verify_xdf.find_constraint_violations(
        markers, min_before_first=3, min_between=3, max_consec=8
    )
    assert v == []


def test_violations_deviant_too_early_caught():
    seq = [True, False, False, False, False, False, False, False, False, False]
    markers = _block(1, "chills_oddball_passive", seq)
    v = verify_xdf.find_constraint_violations(
        markers, min_before_first=3, min_between=3, max_consec=8
    )
    assert v
    assert "trial 0" in v[0]


def test_violations_too_close_deviants_caught():
    # Deviants at trial 3 and trial 5 -> only 1 standard between
    seq = [False, False, False, True, False, True, False, False, False, False]
    markers = _block(2, "chills_oddball_passive", seq)
    v = verify_xdf.find_constraint_violations(
        markers, min_before_first=3, min_between=3, max_consec=8
    )
    assert v
    assert "3,5" in v[0] or "trials 3,5" in v[0]


def test_violations_long_standard_run_caught():
    # 10 standards in a row -> exceeds max_consec=8
    seq = [False] * 10 + [True, False, False, False]
    markers = _block(3, "rest_oddball_passive", seq)
    v = verify_xdf.find_constraint_violations(
        markers, min_before_first=3, min_between=3, max_consec=8
    )
    assert v
    assert "standard run" in v[0]


def test_violations_separate_per_block():
    """A clean block followed by a violating block should attribute every reported
    violation to the violating block only."""
    clean = [False, False, False, True, False, False, False, True, False, False]
    # Bad: deviant at trial 0 + then 9 consecutive standards.
    bad = [True, False, False, False, False, False, False, False, False, False]
    markers = _block(1, "chills_oddball_passive", clean, start_t=0.0)
    markers += _block(2, "rest_oddball_passive", bad, start_t=300.0)
    v = verify_xdf.find_constraint_violations(
        markers, min_before_first=3, min_between=3, max_consec=8
    )
    assert len(v) >= 1
    # No clean-block (idx=01) violation should appear.
    assert all("idx=01" not in line for line in v)
    assert all("idx=02" in line for line in v)
