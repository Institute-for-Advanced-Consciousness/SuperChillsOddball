"""Tests for the per-block oddball sequence generator."""

from __future__ import annotations

import random

import pytest

from chills_oddball.config import load_config
from chills_oddball.schedule import (
    estimate_oddball_trial_count,
    generate_oddball_sequence,
)


@pytest.fixture
def config():
    return load_config()


def _check_constraints(
    seq: list[bool], min_before: int, min_between: int, max_consec: int
) -> None:
    # First-deviant rule
    first = next((i for i, t in enumerate(seq) if t), None)
    if first is not None:
        assert first >= min_before, f"first deviant at {first}; need >= {min_before}"

    # Min standards between deviants
    deviants = [i for i, t in enumerate(seq) if t]
    for prev, nxt in zip(deviants, deviants[1:], strict=False):
        gap = nxt - prev - 1
        assert gap >= min_between, (
            f"deviants at {prev},{nxt}: only {gap} standards between"
        )

    # Max consecutive standards
    run = 0
    for t in seq:
        if t:
            run = 0
        else:
            run += 1
            assert run <= max_consec, f"standard run of {run} > max_consec={max_consec}"


# ---------------------------------------------------------------------------
# Active oddball: 250 trials at 80/20
# ---------------------------------------------------------------------------


def test_active_oddball_exact_ratio(config):
    seq = generate_oddball_sequence(
        n_trials=config.active_oddball.total_trials,
        deviant_probability=config.oddball.deviant_probability,
        min_standards_before_first_deviant=config.oddball.min_standards_before_first_deviant,
        min_standards_between_deviants=config.oddball.min_standards_between_deviants,
        max_consecutive_standards=config.oddball.max_consecutive_standards,
        rng=random.Random(0),
    )
    n_deviants = sum(seq)
    assert len(seq) == 250
    # round(250 * 0.20) = 50
    assert n_deviants == 50


def test_constraints_hold_across_1000_seeds(config):
    """The headline test: 1000 sequences, every one satisfies all constraints."""
    n_trials = config.active_oddball.total_trials
    p = config.oddball.deviant_probability
    minb = config.oddball.min_standards_before_first_deviant
    minbtw = config.oddball.min_standards_between_deviants
    maxc = config.oddball.max_consecutive_standards

    for seed in range(1000):
        seq = generate_oddball_sequence(
            n_trials=n_trials,
            deviant_probability=p,
            min_standards_before_first_deviant=minb,
            min_standards_between_deviants=minbtw,
            max_consecutive_standards=maxc,
            rng=random.Random(seed),
        )
        _check_constraints(seq, minb, minbtw, maxc)


# ---------------------------------------------------------------------------
# Passive blocks: variable trial counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("duration_s", [30, 90, 150, 180])
def test_passive_block_lengths_satisfy_constraints(config, duration_s):
    """For every block duration in the spec, generate 200 sequences and validate."""
    n_trials = estimate_oddball_trial_count(
        duration_s=duration_s,
        isi_min_ms=config.oddball.isi_min_ms,
        isi_max_ms=config.oddball.isi_max_ms,
    )
    assert n_trials > 0, f"duration {duration_s}s estimated 0 trials; check ISI settings"

    for seed in range(200):
        seq = generate_oddball_sequence(
            n_trials=n_trials,
            deviant_probability=config.oddball.deviant_probability,
            min_standards_before_first_deviant=config.oddball.min_standards_before_first_deviant,
            min_standards_between_deviants=config.oddball.min_standards_between_deviants,
            max_consecutive_standards=config.oddball.max_consecutive_standards,
            rng=random.Random(seed),
        )
        _check_constraints(
            seq,
            config.oddball.min_standards_before_first_deviant,
            config.oddball.min_standards_between_deviants,
            config.oddball.max_consecutive_standards,
        )


def test_estimate_trial_count_for_180s_in_expected_range(config):
    """Sanity-check the spec's '~130 trials in 180s' claim."""
    n = estimate_oddball_trial_count(
        duration_s=180,
        isi_min_ms=config.oddball.isi_min_ms,
        isi_max_ms=config.oddball.isi_max_ms,
    )
    # Mean ISI = 1300 ms -> 180000/1300 = 138, minus 1 buffer = 137. Loose bounds:
    assert 130 <= n <= 145


def test_estimate_trial_count_zero_or_negative_duration():
    assert estimate_oddball_trial_count(0, 1100, 1500) == 0
    assert estimate_oddball_trial_count(-5, 1100, 1500) == 0


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_infeasible_constraints_raise():
    """Tighten min_between so far that 80/20 won't fit."""
    with pytest.raises(ValueError, match="infeasible"):
        generate_oddball_sequence(
            n_trials=100,
            deviant_probability=0.5,  # 50 standards, 50 deviants
            min_standards_before_first_deviant=3,
            min_standards_between_deviants=10,  # need 49*10=490 standards; impossible
            max_consecutive_standards=8,
            rng=random.Random(0),
        )


def test_max_consec_too_small_raises():
    """If we have a giant gap requirement that exceeds max_consec, raise."""
    with pytest.raises(ValueError, match="infeasible"):
        generate_oddball_sequence(
            n_trials=100,
            deviant_probability=0.20,
            min_standards_before_first_deviant=3,
            min_standards_between_deviants=20,  # 20 > max_consec 8
            max_consecutive_standards=8,
            rng=random.Random(0),
        )


def test_invalid_probability_raises():
    with pytest.raises(ValueError, match="deviant_probability"):
        generate_oddball_sequence(
            n_trials=100,
            deviant_probability=1.5,
            min_standards_before_first_deviant=3,
            min_standards_between_deviants=3,
            max_consecutive_standards=8,
            rng=random.Random(0),
        )


def test_zero_trials_returns_empty():
    assert generate_oddball_sequence(
        n_trials=0,
        deviant_probability=0.20,
        min_standards_before_first_deviant=3,
        min_standards_between_deviants=3,
        max_consecutive_standards=8,
        rng=random.Random(0),
    ) == []


def test_no_deviant_in_first_min_before_window(config):
    """Spot-check the first-deviant rule with a tight test."""
    for seed in range(50):
        seq = generate_oddball_sequence(
            n_trials=50,
            deviant_probability=config.oddball.deviant_probability,
            min_standards_before_first_deviant=5,  # tighter than default
            min_standards_between_deviants=3,
            max_consecutive_standards=8,
            rng=random.Random(seed),
        )
        first = next((i for i, t in enumerate(seq) if t), None)
        if first is not None:
            assert first >= 5
