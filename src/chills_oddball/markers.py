"""LSL marker outlet wrapper.

Single string outlet at nominal_srate=0. The stream name and source_id are
both pulled from config and MUST stay constant for the entire session —
LabRecorder loses its subscription if `source_id` changes mid-stream
(see sentiometer commit 8094ab4).

Public API:
    ChillsMarkerOutlet(lsl_config)
        .open()         # create the outlet
        .close()        # release it
        .emit(text)     # push a raw marker string
        .* methods      # one per CLAUDE.md marker type, with payload kwargs

Marker payloads use a `key=value` syntax separated by colons, e.g.
``block_start:idx=03:condition=chills_only:duration_s=90``. Parsing is
the inverse of :func:`format_marker` and lives in scripts/verify_xdf.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any

from pylsl import StreamInfo, StreamOutlet, cf_string, local_clock

from .config import LslConfig

# ---------------------------------------------------------------------------
# Marker formatting
# ---------------------------------------------------------------------------


def _bool_yn(value: bool) -> str:
    return "Y" if value else "N"


def format_marker(event: str, payload: Mapping[str, Any] | None = None) -> str:
    """Build the canonical wire format for a marker.

    >>> format_marker("session_start")
    'session_start'
    >>> format_marker("block_start", {"idx": 3, "condition": "chills_only"})
    'block_start:idx=3:condition=chills_only'
    """
    if not payload:
        return event
    parts = [event]
    for key, raw in payload.items():
        if isinstance(raw, bool):
            value = _bool_yn(raw)
        else:
            value = str(raw)
        if ":" in value or "=" in value:
            raise ValueError(
                f"marker payload contains a reserved character: {key}={value!r}"
            )
        parts.append(f"{key}={value}")
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Outlet
# ---------------------------------------------------------------------------


class ChillsMarkerOutlet:
    """Thin wrapper around a single string-typed LSL outlet."""

    def __init__(self, config: LslConfig) -> None:
        self.config = config
        self._outlet: StreamOutlet | None = None

    # ----- lifecycle ------------------------------------------------------

    def open(self) -> None:
        if self._outlet is not None:
            return
        info = StreamInfo(
            name=self.config.stream_name,
            type=self.config.stream_type,
            channel_count=1,
            nominal_srate=0,
            channel_format=cf_string,
            source_id=self.config.source_id,
        )
        self._outlet = StreamOutlet(info)

    def close(self) -> None:
        # pylsl releases the underlying handle on garbage collection; we
        # drop the reference explicitly so consumers can re-open if needed.
        self._outlet = None

    @property
    def is_open(self) -> bool:
        return self._outlet is not None

    def __enter__(self) -> ChillsMarkerOutlet:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ----- low-level emit -------------------------------------------------

    def emit(
        self,
        event: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timestamp: float | None = None,
    ) -> tuple[str, float]:
        """Push one marker. Returns (rendered_text, lsl_timestamp).

        If `timestamp` is omitted, uses `pylsl.local_clock()` at call time.
        Pass an explicit timestamp from inside the audio callback to lock
        the marker to the exact sample where the tone begins.
        """
        if self._outlet is None:
            raise RuntimeError(
                "outlet not open; call .open() (or use the context manager)"
            )
        text = format_marker(event, payload)
        ts = timestamp if timestamp is not None else local_clock()
        self._outlet.push_sample([text], timestamp=ts)
        return text, ts

    # ----- session-level convenience methods -----------------------------

    def session_start(self) -> tuple[str, float]:
        return self.emit("session_start")

    def participant_id(self, pid: str) -> tuple[str, float]:
        return self.emit("participant_id", {"pid": pid})

    def session_config_seed(self, seed: int) -> tuple[str, float]:
        return self.emit("session_config_seed", {"seed": seed})

    def session_end(self) -> tuple[str, float]:
        return self.emit("session_end")

    def session_abort(self) -> tuple[str, float]:
        return self.emit("session_abort")

    # ----- block-level convenience methods -------------------------------

    def block_start(
        self, idx: int, condition: str, duration_s: int
    ) -> tuple[str, float]:
        return self.emit(
            "block_start",
            {"idx": _idx2(idx), "condition": condition, "duration_s": duration_s},
        )

    def block_gong_start(self) -> tuple[str, float]:
        return self.emit("block_gong_start")

    def block_gong_end(self) -> tuple[str, float]:
        return self.emit("block_gong_end")

    def block_end(self, idx: int, condition: str) -> tuple[str, float]:
        return self.emit("block_end", {"idx": _idx2(idx), "condition": condition})

    def calibration_start(self) -> tuple[str, float]:
        return self.emit("calibration_start")

    def calibration_end(self) -> tuple[str, float]:
        return self.emit("calibration_end")

    # ----- oddball stimuli -----------------------------------------------

    def tone_standard(
        self, trial: int, condition: str, *, timestamp: float | None = None
    ) -> tuple[str, float]:
        return self.emit(
            "tone_standard",
            {"trial": trial, "condition": condition},
            timestamp=timestamp,
        )

    def tone_deviant(
        self, trial: int, condition: str, *, timestamp: float | None = None
    ) -> tuple[str, float]:
        return self.emit(
            "tone_deviant",
            {"trial": trial, "condition": condition},
            timestamp=timestamp,
        )

    # ----- active-block responses ----------------------------------------

    def active_response_hit(self, rt_ms: int) -> tuple[str, float]:
        return self.emit("active_response_hit", {"rt_ms": rt_ms})

    def active_response_miss(self) -> tuple[str, float]:
        return self.emit("active_response_miss")

    def active_response_false_alarm(self, rt_ms: int) -> tuple[str, float]:
        return self.emit("active_response_false_alarm", {"rt_ms": rt_ms})

    # ----- active practice -----------------------------------------------

    def active_practice_start(self, attempt: int) -> tuple[str, float]:
        return self.emit("active_practice_start", {"attempt": attempt})

    def active_practice_passed(self) -> tuple[str, float]:
        return self.emit("active_practice_passed")

    def active_practice_tone_standard(
        self, *, timestamp: float | None = None
    ) -> tuple[str, float]:
        return self.emit("active_practice_tone_standard", timestamp=timestamp)

    def active_practice_tone_deviant(
        self, *, timestamp: float | None = None
    ) -> tuple[str, float]:
        return self.emit("active_practice_tone_deviant", timestamp=timestamp)

    def active_practice_end(self, attempt: int) -> tuple[str, float]:
        return self.emit("active_practice_end", {"attempt": attempt})

    # ----- ratings panels ------------------------------------------------

    def ratings_start(self, block_idx: int) -> tuple[str, float]:
        return self.emit("ratings_start", {"block_idx": _idx2(block_idx)})

    def ratings_submit_chills(
        self,
        block_idx: int,
        success: bool,
        waves: int,
        intensity: int,
        quality: int,
        keep: bool,
    ) -> tuple[str, float]:
        return self.emit(
            "ratings_submit",
            {
                "block_idx": _idx2(block_idx),
                "success": success,
                "waves": waves,
                "intensity": intensity,
                "quality": quality,
                "keep": keep,
            },
        )

    def ratings_submit_rest(
        self, block_idx: int, alertness: int
    ) -> tuple[str, float]:
        return self.emit(
            "ratings_submit", {"block_idx": _idx2(block_idx), "alertness": alertness}
        )

    def ratings_end(self, block_idx: int) -> tuple[str, float]:
        return self.emit("ratings_end", {"block_idx": _idx2(block_idx)})


def _idx2(idx: int) -> str:
    """Two-digit zero-padded block index for marker payloads."""
    return f"{idx:02d}"
