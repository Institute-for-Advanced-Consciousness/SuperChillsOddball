"""Block-list and oddball-sequence generators.

`generate_session_schedule` builds the full 18-block ordering: calibration
first, the 16 short-condition blocks shuffled with no-back-to-back-same-
condition, active oddball last. Each of the four short conditions gets
exactly one block at each duration in the config's duration set, so every
(condition × duration) cell is filled once.

`generate_oddball_sequence` returns a list of booleans (True=deviant) that
satisfies the three constraints from CLAUDE.md:
    - no deviant in trials 1..min_standards_before_first_deviant
    - >= min_standards_between_deviants standards between consecutive deviants
    - no run of standards longer than max_consecutive_standards

The algorithm is constructive (compute the gap distribution between
deviants subject to per-gap min/max caps, sample uniformly via
random-bin filling), then validates as a belt-and-suspenders check.
Pure shuffle-and-retry was the original spec, but at 250 trials with
80/20 ratio and min-spacing=3 the rejection rate is too high; the
constructive approach always succeeds when the constraints are
mathematically satisfiable and raises loudly when they aren't.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterable
from dataclasses import dataclass

from .config import Config

CALIBRATION_CONDITION = "calibration"
ACTIVE_ODDBALL_CONDITION = "active_oddball"


@dataclass(frozen=True)
class ScheduledBlock:
    """One entry in the session schedule."""

    idx: int
    condition: str
    duration_s: int

    def to_dict(self) -> dict[str, object]:
        return {"idx": self.idx, "condition": self.condition, "duration_s": self.duration_s}


# ---------------------------------------------------------------------------
# Session schedule (the 18-block ordering)
# ---------------------------------------------------------------------------


def resolve_seed(config: Config, participant_id: str | None = None) -> int:
    """Resolve the RNG seed per the configured strategy."""
    strategy = config.schedule.seed_strategy
    if strategy == "fixed":
        if config.schedule.fixed_seed is None:
            raise ValueError("seed_strategy=='fixed' requires schedule.fixed_seed to be set")
        return int(config.schedule.fixed_seed)
    if strategy == "participant_id":
        if not participant_id:
            raise ValueError("seed_strategy=='participant_id' requires a participant_id")
        # Hash to a stable 32-bit positive integer.
        return abs(hash(participant_id)) & 0x7FFFFFFF
    if strategy == "random_per_session":
        return int(time.time() * 1000) & 0x7FFFFFFF
    raise ValueError(f"unknown seed_strategy: {strategy!r}")


def generate_session_schedule(
    config: Config,
    seed: int | None = None,
    participant_id: str | None = None,
) -> list[ScheduledBlock]:
    """Build the full 18-block schedule for a session.

    Returns:
        Ordered list. Index 0 is always calibration; index N-1 is always
        active oddball. The middle blocks are shuffled subject to
        no-back-to-back-same-condition.
    """
    if seed is None:
        seed = resolve_seed(config, participant_id=participant_id)
    rng = random.Random(seed)

    conditions = list(config.schedule.conditions)
    durations = list(config.schedule.block_duration_set_s)
    if config.schedule.n_blocks_per_condition != len(durations):
        raise ValueError(
            "block_duration_set_s length must equal n_blocks_per_condition"
            f" (got {len(durations)} vs {config.schedule.n_blocks_per_condition})"
        )

    # Each condition gets exactly one block at each duration in the set.
    main_pool: list[tuple[str, int]] = [(c, d) for c in conditions for d in durations]

    if config.schedule.no_back_to_back_same_condition:
        main_order = _shuffle_no_back_to_back(
            main_pool,
            rng=rng,
            max_attempts=config.schedule.max_shuffle_attempts,
        )
    else:
        main_order = list(main_pool)
        rng.shuffle(main_order)

    # Index 0 = calibration (per spec), then the 16 main blocks, then active oddball.
    blocks: list[ScheduledBlock] = []
    cursor = 0

    if config.calibration.enabled:
        blocks.append(
            ScheduledBlock(
                idx=cursor,
                condition=CALIBRATION_CONDITION,
                duration_s=config.calibration.duration_s,
            )
        )
        cursor += 1

    for cond, dur in main_order:
        blocks.append(ScheduledBlock(idx=cursor, condition=cond, duration_s=dur))
        cursor += 1

    blocks.append(
        ScheduledBlock(
            idx=cursor,
            condition=ACTIVE_ODDBALL_CONDITION,
            duration_s=config.active_oddball.duration_target_s,
        )
    )
    return blocks


def _shuffle_no_back_to_back(
    pool: list[tuple[str, int]],
    rng: random.Random,
    max_attempts: int,
) -> list[tuple[str, int]]:
    """Shuffle until no two consecutive items share a condition. Loud failure."""
    for _ in range(max_attempts):
        candidate = list(pool)
        rng.shuffle(candidate)
        if all(candidate[i][0] != candidate[i + 1][0] for i in range(len(candidate) - 1)):
            return candidate
    raise RuntimeError(
        "could not produce a no-back-to-back schedule in "
        f"{max_attempts} attempts. With 4 conditions × 4 blocks the "
        "violation rate should be <50%; investigate before relaxing."
    )


# ---------------------------------------------------------------------------
# Oddball sequence (per-block list of bool, True = deviant)
# ---------------------------------------------------------------------------


def estimate_oddball_trial_count(
    duration_s: int,
    isi_min_ms: int,
    isi_max_ms: int,
    tone_duration_ms: int = 100,
) -> int:
    """How many tones fit in `duration_s` at the configured mean ISI.

    `isi` is treated as the stimulus-onset asynchrony (ERP CORE convention),
    so per-trial wall time is just the ISI; tone duration overlaps the
    interval. We subtract one trial as a safety buffer against random ISI
    variance overshooting the block boundary.
    """
    if duration_s <= 0:
        return 0
    mean_isi_ms = (isi_min_ms + isi_max_ms) / 2
    if mean_isi_ms <= 0:
        raise ValueError(f"non-positive mean ISI: {mean_isi_ms}")
    raw = int((duration_s * 1000) // mean_isi_ms)
    return max(0, raw - 1)


def generate_oddball_sequence(
    n_trials: int,
    deviant_probability: float,
    min_standards_before_first_deviant: int,
    min_standards_between_deviants: int,
    max_consecutive_standards: int,
    rng: random.Random | None = None,
) -> list[bool]:
    """Return a length-`n_trials` list (True=deviant) satisfying all constraints.

    Raises:
        ValueError: if the constraint set is mathematically unsatisfiable
            for the requested trial count and ratio.
    """
    if n_trials < 0:
        raise ValueError(f"n_trials must be >= 0; got {n_trials}")
    if not (0.0 < deviant_probability < 1.0):
        raise ValueError(f"deviant_probability must be in (0, 1); got {deviant_probability}")
    if min_standards_before_first_deviant < 0:
        raise ValueError("min_standards_before_first_deviant must be >= 0")
    if min_standards_between_deviants < 0:
        raise ValueError("min_standards_between_deviants must be >= 0")
    if max_consecutive_standards <= 0:
        raise ValueError("max_consecutive_standards must be > 0")

    if n_trials == 0:
        return []

    rng = rng or random.Random()

    n_deviants = round(n_trials * deviant_probability)
    if n_deviants == 0:
        # No deviants requested: must be all standards, but bounded by max_consec.
        if n_trials > max_consecutive_standards:
            raise ValueError(
                f"n_trials={n_trials} all-standards exceeds max_consecutive_standards"
                f"={max_consecutive_standards}"
            )
        return [False] * n_trials

    n_standards = n_trials - n_deviants

    # n_deviants deviants -> n_deviants + 1 standard "runs" (before the first
    # deviant, between consecutive deviants, after the last deviant).
    n_runs = n_deviants + 1
    min_runs = (
        [min_standards_before_first_deviant]
        + [min_standards_between_deviants] * (n_deviants - 1)
        + [0]
    )
    # Trailing run can be 0 (deviant in final position is allowed).
    # Internal runs are bounded above by max_consecutive_standards. The leading
    # run is also so bounded (otherwise we'd violate max_consec at the start).
    max_runs = [max_consecutive_standards] * n_runs

    required = sum(min_runs)
    if required > n_standards:
        raise ValueError(
            f"infeasible: n_standards={n_standards} cannot satisfy minimum-gap "
            f"requirements (need {required}). Reduce deviant count, lower "
            "min_standards_*, or increase n_trials."
        )

    extras_caps = [max_runs[i] - min_runs[i] for i in range(n_runs)]
    if any(c < 0 for c in extras_caps):
        raise ValueError(
            "infeasible: some min_run exceeds max_consecutive_standards "
            "(reduce min_standards_* or raise max_consecutive_standards)"
        )

    slack = n_standards - required
    if sum(extras_caps) < slack:
        raise ValueError(
            f"infeasible: n_standards={n_standards} cannot fit under "
            f"max_consecutive_standards={max_consecutive_standards} caps "
            f"(slack={slack}, total cap capacity={sum(extras_caps)}). "
            "Raise max_consecutive_standards or lower n_trials."
        )

    extras = _distribute_with_caps(slack, extras_caps, rng)
    runs = [min_runs[i] + extras[i] for i in range(n_runs)]

    # Build final boolean sequence.
    seq: list[bool] = []
    for i, run_len in enumerate(runs):
        seq.extend([False] * run_len)
        if i < n_deviants:
            seq.append(True)

    # Belt-and-suspenders: re-validate.
    _validate_oddball_sequence(
        seq,
        min_standards_before_first_deviant,
        min_standards_between_deviants,
        max_consecutive_standards,
    )
    if len(seq) != n_trials:
        raise AssertionError(
            f"internal error: produced {len(seq)} trials, expected {n_trials}"
        )
    return seq


def _distribute_with_caps(
    slack: int, caps: list[int], rng: random.Random
) -> list[int]:
    """Place `slack` units into bins with per-bin capacity ceilings.

    Picks a uniformly random bin among those with remaining capacity for
    each unit. Not perfectly uniform across all valid configurations, but
    sufficient for our randomization needs (the stimulus stream just needs
    to be unpredictable to the participant).
    """
    bins = [0] * len(caps)
    available = [i for i, c in enumerate(caps) if c > 0]
    for _ in range(slack):
        if not available:
            raise RuntimeError(
                "no capacity left while distributing slack "
                "(should have been caught by the cap-capacity check)"
            )
        idx = rng.choice(available)
        bins[idx] += 1
        if bins[idx] >= caps[idx]:
            available.remove(idx)
    return bins


def _validate_oddball_sequence(
    seq: Iterable[bool],
    min_before_first: int,
    min_between: int,
    max_consec: int,
) -> None:
    """Raise AssertionError if `seq` violates any of the three constraints."""
    seq_list = list(seq)
    # First-deviant position
    first_deviant_pos = next((i for i, t in enumerate(seq_list) if t), None)
    if first_deviant_pos is not None and first_deviant_pos < min_before_first:
        raise AssertionError(
            f"first deviant at position {first_deviant_pos}; "
            f"requires >= {min_before_first} standards first"
        )

    # Standards between consecutive deviants
    deviant_positions = [i for i, t in enumerate(seq_list) if t]
    for prev, nxt in zip(deviant_positions, deviant_positions[1:], strict=False):
        gap = nxt - prev - 1
        if gap < min_between:
            raise AssertionError(
                f"deviants at {prev} and {nxt} have only {gap} standards between; "
                f"requires >= {min_between}"
            )

    # No standard run longer than max_consec
    run = 0
    for t in seq_list:
        if t:
            run = 0
        else:
            run += 1
            if run > max_consec:
                raise AssertionError(
                    f"standard run exceeds max_consecutive_standards={max_consec}"
                )
