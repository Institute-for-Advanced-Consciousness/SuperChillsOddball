"""Tests for the session-schedule generator."""

from __future__ import annotations

import pytest

from chills_oddball.config import load_config, merge_overrides
from chills_oddball.schedule import (
    ACTIVE_ODDBALL_CONDITION,
    CALIBRATION_CONDITION,
    ScheduledBlock,
    generate_session_schedule,
    resolve_seed,
)


@pytest.fixture
def config():
    return load_config()


def _short_blocks(blocks: list[ScheduledBlock]) -> list[ScheduledBlock]:
    """The 16 middle blocks (excluding calibration and active)."""
    return [
        b
        for b in blocks
        if b.condition not in (CALIBRATION_CONDITION, ACTIVE_ODDBALL_CONDITION)
    ]


def test_schedule_total_block_count(config):
    blocks = generate_session_schedule(config, seed=42)
    # 1 calibration + 16 short + 1 active = 18
    assert len(blocks) == 18


def test_schedule_first_is_calibration(config):
    blocks = generate_session_schedule(config, seed=42)
    assert blocks[0].condition == CALIBRATION_CONDITION
    assert blocks[0].duration_s == config.calibration.duration_s


def test_schedule_last_is_active_oddball(config):
    blocks = generate_session_schedule(config, seed=42)
    assert blocks[-1].condition == ACTIVE_ODDBALL_CONDITION
    assert blocks[-1].duration_s == config.active_oddball.duration_target_s


def test_schedule_calibration_disabled_skips_index_0(config):
    cfg = merge_overrides(config, {"calibration": {"enabled": False}})
    blocks = generate_session_schedule(cfg, seed=42)
    assert len(blocks) == 17
    assert blocks[0].condition != CALIBRATION_CONDITION
    assert blocks[-1].condition == ACTIVE_ODDBALL_CONDITION


def test_schedule_idx_is_contiguous(config):
    blocks = generate_session_schedule(config, seed=42)
    assert [b.idx for b in blocks] == list(range(len(blocks)))


def test_schedule_each_condition_has_n_per_condition_blocks(config):
    blocks = generate_session_schedule(config, seed=42)
    middle = _short_blocks(blocks)
    for cond in config.schedule.conditions:
        assert sum(1 for b in middle if b.condition == cond) == config.schedule.n_blocks_per_condition


def test_schedule_each_condition_gets_each_duration_exactly_once(config):
    blocks = generate_session_schedule(config, seed=42)
    middle = _short_blocks(blocks)
    expected_durations = sorted(config.schedule.block_duration_set_s)
    for cond in config.schedule.conditions:
        durs = sorted(b.duration_s for b in middle if b.condition == cond)
        assert durs == expected_durations, f"{cond}: got {durs}, expected {expected_durations}"


def test_schedule_no_back_to_back_same_condition_in_middle(config):
    blocks = generate_session_schedule(config, seed=42)
    middle = _short_blocks(blocks)
    for prev, nxt in zip(middle, middle[1:], strict=False):
        assert prev.condition != nxt.condition


def test_schedule_deterministic_with_same_seed(config):
    a = generate_session_schedule(config, seed=12345)
    b = generate_session_schedule(config, seed=12345)
    assert [b_.to_dict() for b_ in a] == [b_.to_dict() for b_ in b]


def test_schedule_different_seeds_produce_different_orderings(config):
    a = generate_session_schedule(config, seed=1)
    b = generate_session_schedule(config, seed=999)
    assert [(blk.condition, blk.duration_s) for blk in a] != [
        (blk.condition, blk.duration_s) for blk in b
    ]


def test_schedule_satisfies_constraints_under_many_seeds(config):
    """Run 1000 random seeds; every schedule must satisfy all constraints."""
    for seed in range(1000):
        blocks = generate_session_schedule(config, seed=seed)
        middle = _short_blocks(blocks)
        # 16 middle blocks
        assert len(middle) == 16
        # Each condition × each duration == 1
        for cond in config.schedule.conditions:
            durs = sorted(b.duration_s for b in middle if b.condition == cond)
            assert durs == sorted(config.schedule.block_duration_set_s)
        # No back-to-back
        for prev, nxt in zip(middle, middle[1:], strict=False):
            assert prev.condition != nxt.condition


def test_schedule_to_dict_round_trip(config):
    blocks = generate_session_schedule(config, seed=42)
    d = blocks[0].to_dict()
    assert set(d.keys()) == {"idx", "condition", "duration_s"}
    assert d["idx"] == 0


def test_resolve_seed_fixed_strategy(config):
    cfg = merge_overrides(
        config, {"schedule": {"seed_strategy": "fixed", "fixed_seed": 7}}
    )
    assert resolve_seed(cfg) == 7


def test_resolve_seed_participant_id_is_stable(config):
    cfg = merge_overrides(config, {"schedule": {"seed_strategy": "participant_id"}})
    s1 = resolve_seed(cfg, participant_id="P001")
    s2 = resolve_seed(cfg, participant_id="P001")
    s3 = resolve_seed(cfg, participant_id="P002")
    assert s1 == s2
    assert s1 != s3


def test_resolve_seed_participant_id_requires_id(config):
    cfg = merge_overrides(config, {"schedule": {"seed_strategy": "participant_id"}})
    with pytest.raises(ValueError, match="participant_id"):
        resolve_seed(cfg, participant_id=None)


def test_resolve_seed_random_per_session_changes(config):
    # Two consecutive calls should differ (millisecond-resolution clock).
    import time as _t

    s1 = resolve_seed(config)
    _t.sleep(0.005)
    s2 = resolve_seed(config)
    # They might collide if the test runs faster than the clock; allow that
    # but require at least one change across many calls.
    seeds = {resolve_seed(config) for _ in range(5)}
    assert len(seeds) >= 2 or s1 != s2
