"""Per-session JSON + per-block CSV writers, with incremental partial-save.

A session writes:

  Data/{pid}/session.json           — final master record (clean exit OR abort)
  Data/{pid}/PARTIAL_session.json   — refreshed every block; deleted on clean
                                      finalize, retained as forensic if aborted
  Data/{pid}/block_{NN}_{cond}.csv  — per-block trial records (silent blocks
                                      get one start/end row each)

The writer also auto-suggests the next participant ID (highest existing
P{NNN} + 1 under the data root). The runtime ALWAYS writes both the
PARTIAL and the per-block CSV at the end of every block, so a Windows
hard-crash leaves the most recent state on disk.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schedule import ScheduledBlock

# ---------------------------------------------------------------------------
# Row + record dataclasses
# ---------------------------------------------------------------------------


CSV_FIELDS = ["trial_idx", "t_lsl", "event", "tone_type", "response", "rt_ms"]


@dataclass(frozen=True)
class TrialRow:
    """One row of a per-block CSV.

    Use `event="tone_onset"` for stimulus tones; `event="block_start"` /
    `"block_end"` are used as the only two rows in silent-block CSVs.
    Active responses use `event="response"` with `response` set to one of
    {"hit", "miss", "false_alarm"}.
    """

    trial_idx: int | None
    t_lsl: float
    event: str
    tone_type: str | None = None
    response: str | None = None
    rt_ms: int | None = None

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "trial_idx": "NA" if self.trial_idx is None else self.trial_idx,
            "t_lsl": f"{self.t_lsl:.6f}",
            "event": self.event,
            "tone_type": self.tone_type or "NA",
            "response": self.response or "NA",
            "rt_ms": "NA" if self.rt_ms is None else self.rt_ms,
        }


@dataclass
class BlockRecord:
    idx: int
    condition: str
    duration_s: int
    start_lsl: float | None = None
    end_lsl: float | None = None
    status: str = "pending"  # pending | completed | aborted
    ratings: dict[str, Any] | None = None
    csv_path: str | None = None

    # Internal — not serialized.
    _trials: list[TrialRow] = field(default_factory=list, repr=False)

    def to_json(self) -> dict[str, Any]:
        out = {
            "idx": self.idx,
            "condition": self.condition,
            "duration_s": self.duration_s,
            "start_lsl": self.start_lsl,
            "end_lsl": self.end_lsl,
            "status": self.status,
            "ratings": self.ratings,
            "csv_path": self.csv_path,
        }
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Z-suffixed ISO 8601 in UTC, second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_participant_id(
    data_root: Path, prefix: str = "P", zfill: int = 3
) -> str:
    """Suggest the next participant ID by scanning existing folders.

    Folders not matching ``{prefix}\\d+`` are ignored. If no matching folder
    exists, returns ``P001`` (with the configured prefix and zero-fill).
    """
    if not data_root.exists():
        return f"{prefix}{1:0{zfill}d}"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_n = 0
    for entry in data_root.iterdir():
        if not entry.is_dir():
            continue
        m = pattern.match(entry.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}{max_n + 1:0{zfill}d}"


def block_csv_filename(idx: int, condition: str) -> str:
    """Per-CLAUDE.md: block_{NN}_{condition}.csv."""
    return f"block_{idx:02d}_{condition}.csv"


# ---------------------------------------------------------------------------
# SessionWriter
# ---------------------------------------------------------------------------


class SessionWriter:
    """Owns the on-disk state for one participant's session."""

    PARTIAL_FILENAME = "PARTIAL_session.json"
    SESSION_FILENAME = "session.json"

    def __init__(
        self,
        data_root: Path,
        participant_id: str,
        config_snapshot: dict[str, Any],
        schedule: list[ScheduledBlock],
        rng_seed: int,
    ) -> None:
        self.data_root = Path(data_root)
        self.participant_id = participant_id
        self.session_dir = self.data_root / participant_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.session_start_utc = utc_now_iso()
        self.session_end_utc: str | None = None
        self.status: str = "in_progress"
        self.rng_seed = rng_seed
        self.config_snapshot = config_snapshot
        self.schedule = schedule
        self.blocks: list[BlockRecord] = []
        self.active_oddball_summary: dict[str, Any] | None = None
        self._finalized = False

    # ------- block lifecycle -------------------------------------------------

    def start_block(
        self, idx: int, condition: str, duration_s: int, start_lsl: float
    ) -> BlockRecord:
        """Open a new block record. Caller holds the reference until end_block."""
        record = BlockRecord(
            idx=idx,
            condition=condition,
            duration_s=duration_s,
            start_lsl=start_lsl,
            status="pending",
        )
        self.blocks.append(record)
        return record

    def end_block(
        self,
        record: BlockRecord,
        end_lsl: float,
        trials: list[TrialRow] | None = None,
        ratings: dict[str, Any] | None = None,
        status: str = "completed",
    ) -> None:
        """Close a block: write its CSV, update the record, refresh PARTIAL."""
        record.end_lsl = end_lsl
        record.status = status
        record.ratings = ratings
        if trials is None:
            # Silent-block default: two-row CSV with start/end stamps.
            trials = [
                TrialRow(trial_idx=None, t_lsl=record.start_lsl or 0.0, event="block_start"),
                TrialRow(trial_idx=None, t_lsl=end_lsl, event="block_end"),
            ]
        record._trials = list(trials)
        record.csv_path = block_csv_filename(record.idx, record.condition)
        self._write_block_csv(record)
        self._write_partial()

    def set_block_ratings(self, idx: int, ratings: dict[str, Any]) -> None:
        """Attach ratings to an already-ended block and refresh PARTIAL.

        Used by the post-block ratings panels — block_runner writes the CSV
        and emits the end markers immediately, then the next stage gathers
        the participant's ratings and stamps them onto the same record.
        """
        for rec in self.blocks:
            if rec.idx == idx:
                rec.ratings = ratings
                self._write_partial()
                return
        raise KeyError(f"no block with idx={idx} in current session")

    # ------- summaries / finalization ---------------------------------------

    def set_active_oddball_summary(self, summary: dict[str, Any]) -> None:
        self.active_oddball_summary = summary
        self._write_partial()

    def finalize(self, status: str = "completed") -> Path:
        """Write the final session.json. On clean status, delete PARTIAL.

        Returns the path of the written session.json.
        """
        if status not in ("completed", "aborted"):
            raise ValueError(f"finalize status must be 'completed' or 'aborted'; got {status!r}")
        self.status = status
        self.session_end_utc = utc_now_iso()
        target = self.session_dir / self.SESSION_FILENAME
        self._atomic_write_json(target, self._snapshot_dict())
        if status == "completed":
            partial = self.session_dir / self.PARTIAL_FILENAME
            if partial.exists():
                partial.unlink()
        self._finalized = True
        return target

    # ------- CSV / JSON writers ---------------------------------------------

    def _write_block_csv(self, record: BlockRecord) -> Path:
        path = self.session_dir / record.csv_path
        rows = [r.to_csv_dict() for r in record._trials]
        # Write atomically: tmp -> rename.
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)
        return path

    def _write_partial(self) -> Path:
        path = self.session_dir / self.PARTIAL_FILENAME
        self._atomic_write_json(path, self._snapshot_dict(in_progress=True))
        return path

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _snapshot_dict(self, *, in_progress: bool = False) -> dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "session_start_utc": self.session_start_utc,
            "session_end_utc": self.session_end_utc,
            "status": "in_progress" if in_progress else self.status,
            "rng_seed": self.rng_seed,
            "config_snapshot": self.config_snapshot,
            "schedule": [b.to_dict() for b in self.schedule],
            "blocks": [b.to_json() for b in self.blocks],
            "active_oddball_summary": self.active_oddball_summary,
        }

    # ------- recovery helpers ------------------------------------------------

    @classmethod
    def has_partial(cls, data_root: Path, participant_id: str) -> bool:
        return (data_root / participant_id / cls.PARTIAL_FILENAME).exists()

    @classmethod
    def discard_partial(cls, data_root: Path, participant_id: str) -> None:
        path = data_root / participant_id / cls.PARTIAL_FILENAME
        if path.exists():
            path.unlink()

    @classmethod
    def archive_partial(cls, data_root: Path, participant_id: str) -> Path | None:
        """Move PARTIAL_session.json aside with a timestamp, returns new path."""
        path = data_root / participant_id / cls.PARTIAL_FILENAME
        if not path.exists():
            return None
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archived = path.with_name(f"PARTIAL_session_{ts}.json")
        shutil.move(str(path), str(archived))
        return archived


# Re-export common dataclasses for stages that don't want to import schedule.
__all__ = [
    "BlockRecord",
    "CSV_FIELDS",
    "SessionWriter",
    "TrialRow",
    "block_csv_filename",
    "next_participant_id",
    "utc_now_iso",
]


# Quiet unused-import warning when stages import asdict only sometimes.
_ = asdict
