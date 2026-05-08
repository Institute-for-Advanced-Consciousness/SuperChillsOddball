"""Post-session sanity check on a recorded XDF.

Usage:
    uv run python scripts/verify_xdf.py path/to/session.xdf

Reports:
  - Marker coverage table (every expected marker type vs observed count)
  - Per-condition tone counts (standard / deviant) for passive + active blocks
  - Mean and SD of ISI within each condition
  - Constraint violations:
      - deviant inside the no-deviant window at block start
      - back-to-back deviants below min_standards_between_deviants
      - any standard run > max_consecutive_standards

Designed to load only the ``Chills_Task_Markers`` stream — EEG / CGX
streams in the same XDF are ignored. Exit code is 0 when no violations
are found, 1 if any constraint failure is reported.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Local import: re-use the same constraint constants the runtime uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chills_oddball.config import load_config  # noqa: E402

# pyxdf and rich are imported inside main() so this script doesn't blow up at
# module-load time in environments without those (e.g. pure schema tests).


MARKER_PATTERN = re.compile(r"^([a-z_]+)(?::(.+))?$")
KV_PATTERN = re.compile(r"^([a-z_]+)=(.+)$")


@dataclass
class ParsedMarker:
    raw: str
    timestamp: float
    event: str
    payload: dict[str, str] = field(default_factory=dict)


def parse_marker(raw: str, timestamp: float) -> ParsedMarker:
    m = MARKER_PATTERN.match(raw)
    if not m:
        return ParsedMarker(raw=raw, timestamp=timestamp, event=raw)
    event, rest = m.group(1), m.group(2)
    payload: dict[str, str] = {}
    if rest:
        for part in rest.split(":"):
            kv = KV_PATTERN.match(part)
            if kv:
                payload[kv.group(1)] = kv.group(2)
    return ParsedMarker(raw=raw, timestamp=timestamp, event=event, payload=payload)


def load_markers(xdf_path: Path, stream_name: str) -> list[ParsedMarker]:
    import pyxdf

    streams, _ = pyxdf.load_xdf(str(xdf_path))
    out: list[ParsedMarker] = []
    for s in streams:
        info = s.get("info") or {}
        names = info.get("name") or []
        if not names or names[0] != stream_name:
            continue
        timestamps = s.get("time_stamps")
        if timestamps is None:
            timestamps = []
        time_series = s.get("time_series")
        if time_series is None:
            time_series = []
        # XDF marker streams come as list-of-1-string lists.
        for ts, sample in zip(timestamps, time_series, strict=False):
            text = sample[0] if isinstance(sample, (list, tuple)) else sample
            out.append(parse_marker(str(text), float(ts)))
    out.sort(key=lambda m: m.timestamp)
    return out


def count_events(markers: Sequence[ParsedMarker]) -> Counter[str]:
    return Counter(m.event for m in markers)


@dataclass
class ToneStats:
    n_standard: int = 0
    n_deviant: int = 0
    isis_ms: list[float] = field(default_factory=list)


def collect_tones_by_condition(
    markers: Sequence[ParsedMarker],
) -> dict[str, ToneStats]:
    stats: dict[str, ToneStats] = defaultdict(ToneStats)
    last_ts_by_condition: dict[str, float] = {}
    for m in markers:
        if m.event not in ("tone_standard", "tone_deviant"):
            continue
        cond = m.payload.get("condition", "?")
        s = stats[cond]
        if m.event == "tone_standard":
            s.n_standard += 1
        else:
            s.n_deviant += 1
        if cond in last_ts_by_condition:
            s.isis_ms.append((m.timestamp - last_ts_by_condition[cond]) * 1000.0)
        last_ts_by_condition[cond] = m.timestamp
    return dict(stats)


def find_constraint_violations(
    markers: Sequence[ParsedMarker],
    min_before_first: int,
    min_between: int,
    max_consec: int,
) -> list[str]:
    """Walk each block; check the three sequence rules. Returns human-readable strings."""
    violations: list[str] = []

    # Group tones by block. Use block_start markers to delimit; trial number resets per block.
    in_block = False
    block_idx = "?"
    block_cond = "?"
    block_trials: list[tuple[int, bool]] = []  # (trial_idx, is_deviant)

    def _flush() -> None:
        if not block_trials:
            return
        # Sort by trial_idx (analysis-order, not LSL-time).
        trials = sorted(block_trials, key=lambda t: t[0])
        # Rule 1: no deviant in trials < min_before_first
        for trial_idx, is_dev in trials:
            if is_dev and trial_idx < min_before_first:
                violations.append(
                    f"block idx={block_idx} cond={block_cond}: "
                    f"deviant at trial {trial_idx} (< {min_before_first})"
                )
                break
        # Rule 2: standards between deviants
        deviant_positions = [t[0] for t in trials if t[1]]
        for prev, nxt in zip(
            deviant_positions, deviant_positions[1:], strict=False
        ):
            gap = nxt - prev - 1
            if gap < min_between:
                violations.append(
                    f"block idx={block_idx} cond={block_cond}: "
                    f"deviants at trials {prev},{nxt} have only {gap} standards between"
                )
                break
        # Rule 3: max consecutive standards
        run = 0
        for _, is_dev in trials:
            run = 0 if is_dev else run + 1
            if run > max_consec:
                violations.append(
                    f"block idx={block_idx} cond={block_cond}: "
                    f"standard run > {max_consec}"
                )
                break

    for m in markers:
        if m.event == "block_start":
            if in_block:
                _flush()
            in_block = True
            block_idx = m.payload.get("idx", "?")
            block_cond = m.payload.get("condition", "?")
            block_trials = []
        elif m.event == "block_end":
            if in_block:
                _flush()
            in_block = False
        elif m.event in ("tone_standard", "tone_deviant"):
            if in_block:
                trial = m.payload.get("trial")
                if trial is None:
                    continue
                try:
                    trial_idx = int(trial)
                except ValueError:
                    continue
                block_trials.append((trial_idx, m.event == "tone_deviant"))
    if in_block:
        _flush()
    return violations


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


# CLAUDE.md marker scheme: every expected event the runtime can emit.
EXPECTED_EVENTS: tuple[str, ...] = (
    "session_start",
    "participant_id",
    "session_config_seed",
    "session_end",
    "session_abort",
    "block_start",
    "block_gong_start",
    "block_gong_end",
    "block_end",
    "calibration_start",
    "calibration_end",
    "tone_standard",
    "tone_deviant",
    "active_response_hit",
    "active_response_miss",
    "active_response_false_alarm",
    "active_practice_start",
    "active_practice_passed",
    "active_practice_tone_standard",
    "active_practice_tone_deviant",
    "active_practice_end",
    "ratings_start",
    "ratings_submit",
    "ratings_end",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xdf_path", type=Path, help="Path to the recorded XDF file")
    parser.add_argument("--config", default=None, help="Optional alternate session_defaults.yaml")
    args = parser.parse_args(argv)

    if not args.xdf_path.exists():
        print(f"ERROR: file not found: {args.xdf_path}", file=sys.stderr)
        return 2

    cfg = load_config(args.config)

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print("rich is required; install via `uv sync`", file=sys.stderr)
        return 2

    console = Console()
    console.print(f"[bold]verify_xdf:[/bold] {args.xdf_path}")
    console.print(f"  stream: {cfg.lsl.stream_name}")
    console.print()

    try:
        markers = load_markers(args.xdf_path, cfg.lsl.stream_name)
    except ImportError as e:
        print(f"ERROR: {e}. Install via `uv sync`.", file=sys.stderr)
        return 2

    if not markers:
        console.print(
            f"[yellow]No markers found in stream {cfg.lsl.stream_name!r}.[/yellow]"
        )
        return 1

    counts = count_events(markers)

    # ---------- coverage table ----------
    coverage = Table(title="Marker coverage", show_header=True)
    coverage.add_column("event")
    coverage.add_column("count", justify="right")
    coverage.add_column("status")
    for ev in EXPECTED_EVENTS:
        n = counts.get(ev, 0)
        status = "[green]OK[/green]" if n > 0 else "[yellow]missing[/yellow]"
        coverage.add_row(ev, str(n), status)
    # Surface unexpected events too.
    extras = sorted(set(counts) - set(EXPECTED_EVENTS))
    for ev in extras:
        coverage.add_row(ev, str(counts[ev]), "[blue]unexpected[/blue]")
    console.print(coverage)
    console.print()

    # ---------- per-condition tone stats ----------
    tone_stats = collect_tones_by_condition(markers)
    if tone_stats:
        tones_table = Table(title="Tone counts + ISI by condition", show_header=True)
        tones_table.add_column("condition")
        tones_table.add_column("standard", justify="right")
        tones_table.add_column("deviant", justify="right")
        tones_table.add_column("ratio dev", justify="right")
        tones_table.add_column("isi mean (ms)", justify="right")
        tones_table.add_column("isi sd (ms)", justify="right")
        for cond, s in sorted(tone_stats.items()):
            total = s.n_standard + s.n_deviant
            ratio = (s.n_deviant / total) if total else 0.0
            mean_isi = statistics.mean(s.isis_ms) if s.isis_ms else 0.0
            sd_isi = statistics.pstdev(s.isis_ms) if len(s.isis_ms) > 1 else 0.0
            tones_table.add_row(
                cond,
                str(s.n_standard),
                str(s.n_deviant),
                f"{ratio:.2%}",
                f"{mean_isi:.1f}",
                f"{sd_isi:.1f}",
            )
        console.print(tones_table)
        console.print()

    # ---------- constraint violations ----------
    violations = find_constraint_violations(
        markers,
        min_before_first=cfg.oddball.min_standards_before_first_deviant,
        min_between=cfg.oddball.min_standards_between_deviants,
        max_consec=cfg.oddball.max_consecutive_standards,
    )
    if not violations:
        console.print("[green]No constraint violations detected.[/green]")
    else:
        console.print(f"[red]Found {len(violations)} constraint violations:[/red]")
        for v in violations:
            console.print(f"  • {v}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
