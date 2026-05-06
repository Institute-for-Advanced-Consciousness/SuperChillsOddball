"""Audio scheduler + simple playback helpers.

`ToneScheduler` runs a persistent sounddevice OutputStream while an
oddball block plays. It pre-renders the entire block as a single
contiguous buffer, captures the LSL clock anchor for output sample 0
on the first audio-callback invocation, and emits each tone's marker
from inside the callback at the exact sample-anchored timestamp.

Why this design:

  * Pre-rendering avoids per-trial ramp-up latency and makes the entire
    block deterministic given a (sequence, ISI list) pair.
  * Anchoring to ``time.outputBufferDacTime`` gives sample-accurate LSL
    timestamps regardless of buffer size or callback jitter.
  * Emitting from inside the callback honors the spec's explicit
    requirement; pylsl ``push_sample`` for short string markers is
    cheap (microseconds) and we wrap it in try/except so a transient
    LSL hiccup can never crash the audio thread.

Buffer construction is split into pure helper functions
(``build_oddball_buffer``, ``compute_onset_samples``) so it can be
unit-tested without an audio device. The actual playback path requires
hardware and is exercised by the documented manual loopback procedure.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from .config import AudioConfig, OddballConfig
from .markers import ChillsMarkerOutlet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (testable without hardware)
# ---------------------------------------------------------------------------


def compute_onset_samples(
    isis_ms: Sequence[float], sample_rate: int
) -> list[int]:
    """Convert an ISI list into a list of trial start-sample offsets.

    Trial 0 starts at sample 0. Trial i starts at trial (i-1)'s start
    plus ISI[i-1] in samples. This matches the ERP CORE convention where
    ISI is the stimulus-onset asynchrony.
    """
    onsets = [0]
    for isi in isis_ms[:-1]:
        if isi <= 0:
            raise ValueError(f"non-positive ISI in list: {isi}")
        delta = int(round(isi * sample_rate / 1000.0))
        onsets.append(onsets[-1] + delta)
    return onsets


def build_oddball_buffer(
    sequence: Sequence[bool],
    onset_samples: Sequence[int],
    standard: np.ndarray,
    deviant: np.ndarray,
    n_channels: int,
    tail_samples: int = 0,
) -> np.ndarray:
    """Render an entire oddball block as one float32 buffer.

    `standard` and `deviant` must already be 2-D (samples, channels) and
    match `n_channels`. The output is zero-filled outside tone windows.
    """
    if len(sequence) != len(onset_samples):
        raise ValueError(
            f"sequence ({len(sequence)}) and onset_samples ({len(onset_samples)}) "
            "must be the same length"
        )
    if standard.ndim != 2 or deviant.ndim != 2:
        raise ValueError("standard and deviant must be 2-D (samples, channels)")
    if standard.shape[1] != n_channels or deviant.shape[1] != n_channels:
        raise ValueError(
            f"standard/deviant must have {n_channels} channels; "
            f"got {standard.shape[1]} / {deviant.shape[1]}"
        )
    if len(standard) != len(deviant):
        raise ValueError(
            f"standard ({len(standard)}) and deviant ({len(deviant)}) "
            "must be the same length"
        )

    if not sequence:
        return np.zeros((max(0, tail_samples), n_channels), dtype=np.float32)

    tone_len = len(standard)
    total = onset_samples[-1] + tone_len + max(0, tail_samples)
    buf = np.zeros((total, n_channels), dtype=np.float32)
    for is_dev, start in zip(sequence, onset_samples, strict=True):
        tone = deviant if is_dev else standard
        buf[start : start + tone_len] = tone
    return buf


def sample_isis(
    n: int,
    isi_min_ms: int,
    isi_max_ms: int,
    distribution: str,
    rng: random.Random,
) -> list[float]:
    """Sample `n` ISIs (one per trial) from the configured distribution."""
    if distribution == "uniform":
        return [rng.uniform(isi_min_ms, isi_max_ms) for _ in range(n)]
    if distribution == "normal":
        # Use mean=midpoint, sd such that ±2σ ≈ window. Clipped to [min, max].
        mean = (isi_min_ms + isi_max_ms) / 2.0
        sd_ms = (isi_max_ms - isi_min_ms) / 4.0
        out = []
        for _ in range(n):
            v = rng.gauss(mean, sd_ms)
            v = max(isi_min_ms, min(isi_max_ms, v))
            out.append(v)
        return out
    raise ValueError(f"unknown isi_distribution: {distribution!r}")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialRecord:
    """One row that the block runner will write to the per-block CSV."""

    trial_idx: int
    is_deviant: bool
    onset_sample: int
    onset_lsl: float


class ToneScheduler:
    """Holds the loaded tone buffers and plays oddball blocks."""

    def __init__(
        self,
        audio_config: AudioConfig,
        oddball_config: OddballConfig,
        outlet: ChillsMarkerOutlet,
        repo_root: Path,
    ) -> None:
        self.audio_config = audio_config
        self.oddball_config = oddball_config
        self.outlet = outlet
        self.repo_root = repo_root
        self._standard, self._deviant, self._sample_rate = self._load_tones()

    def _load_tones(self) -> tuple[np.ndarray, np.ndarray, int]:
        std_path = self.repo_root / self.audio_config.files.tone_standard
        dev_path = self.repo_root / self.audio_config.files.tone_deviant
        std, sr_std = _load_wav_2d(std_path, target_channels=self.audio_config.channels)
        dev, sr_dev = _load_wav_2d(dev_path, target_channels=self.audio_config.channels)
        if sr_std != sr_dev:
            raise ValueError(f"tone sample rates differ: {sr_std} vs {sr_dev}")
        if sr_std != self.audio_config.sample_rate_hz:
            raise ValueError(
                f"tone .wav sample rate ({sr_std}) does not match config "
                f"audio.sample_rate_hz ({self.audio_config.sample_rate_hz}). "
                "Re-render with scripts/generate_tones.py."
            )
        return std, dev, sr_std

    # ----- block playback (sample-accurate markers) ----------------------

    def play_block(
        self,
        sequence: Sequence[bool],
        block_idx: int,
        condition: str,
        rng: random.Random,
    ) -> list[TrialRecord]:
        """Play one oddball block. Blocks until the last tone has finished.

        Returns a list of TrialRecord for the per-block CSV.
        """
        n_trials = len(sequence)
        if n_trials == 0:
            return []

        isis_ms = sample_isis(
            n=n_trials,
            isi_min_ms=self.oddball_config.isi_min_ms,
            isi_max_ms=self.oddball_config.isi_max_ms,
            distribution=self.oddball_config.isi_distribution,
            rng=rng,
        )
        onset_samples = compute_onset_samples(isis_ms, self._sample_rate)
        # Tail: pad with one mean-ISI so the final tone fully decays before stop.
        tail = int(((self.oddball_config.isi_min_ms + self.oddball_config.isi_max_ms) / 2.0)
                   * self._sample_rate / 1000.0)
        buffer = build_oddball_buffer(
            sequence=sequence,
            onset_samples=onset_samples,
            standard=self._standard,
            deviant=self._deviant,
            n_channels=self.audio_config.channels,
            tail_samples=tail,
        )

        # Mutable state shared with the audio callback.
        cursor = {"i": 0}
        next_trial = {"i": 0}
        t0_lsl: dict[str, float | None] = {"v": None}
        done = threading.Event()
        records: list[TrialRecord] = []

        def callback(
            outdata: np.ndarray,
            frames: int,
            time_info: object,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.warning("audio callback status flag: %s", status)
            # Anchor LSL time of sample 0 on first callback.
            if t0_lsl["v"] is None:
                from pylsl import local_clock as _lsl_clock

                now = _lsl_clock()
                # outputBufferDacTime / currentTime are PortAudio seconds.
                delay = float(time_info.outputBufferDacTime) - float(time_info.currentTime)
                t0_lsl["v"] = now + delay - cursor["i"] / self._sample_rate

            i0 = cursor["i"]
            i1 = i0 + frames

            # Emit any markers whose tone-onset sample falls in [i0, i1).
            while (
                next_trial["i"] < n_trials
                and onset_samples[next_trial["i"]] < i1
            ):
                idx = next_trial["i"]
                ts = float(t0_lsl["v"]) + onset_samples[idx] / self._sample_rate
                is_dev = bool(sequence[idx])
                try:
                    if is_dev:
                        self.outlet.tone_deviant(
                            trial=idx, condition=condition, timestamp=ts
                        )
                    else:
                        self.outlet.tone_standard(
                            trial=idx, condition=condition, timestamp=ts
                        )
                except Exception:  # noqa: BLE001 — never crash the audio thread
                    logger.exception(
                        "marker push failed for trial %d in block %d", idx, block_idx
                    )
                records.append(
                    TrialRecord(
                        trial_idx=idx,
                        is_deviant=is_dev,
                        onset_sample=onset_samples[idx],
                        onset_lsl=ts,
                    )
                )
                next_trial["i"] += 1

            chunk = buffer[i0:i1]
            if len(chunk) < frames:
                outdata[: len(chunk)] = chunk
                outdata[len(chunk) :] = 0.0
                cursor["i"] = len(buffer)
                done.set()
                raise sd.CallbackStop()
            outdata[:] = chunk
            cursor["i"] = i1

        with sd.OutputStream(
            samplerate=self._sample_rate,
            channels=self.audio_config.channels,
            dtype="float32",
            blocksize=self.audio_config.buffer_blocksize,
            device=self.audio_config.device_name,
            callback=callback,
        ):
            done.wait()

        if next_trial["i"] != n_trials:
            logger.warning(
                "block %d ended before all %d trials emitted (got %d). "
                "Check buffer length / tail padding.",
                block_idx,
                n_trials,
                next_trial["i"],
            )
        records.sort(key=lambda r: r.trial_idx)
        return records


# ---------------------------------------------------------------------------
# Simple playback helpers (don't need sample-accurate markers)
# ---------------------------------------------------------------------------


def play_gong(
    audio_config: AudioConfig,
    repo_root: Path,
    which: str,
    outlet: ChillsMarkerOutlet | None = None,
    blocking: bool = True,
) -> float | None:
    """Play one of the gong cues. Returns the marker timestamp if emitted."""
    if which == "start":
        path = repo_root / audio_config.files.gong_start
        marker_fn = outlet.block_gong_start if outlet else None
    elif which == "end":
        path = repo_root / audio_config.files.gong_end
        marker_fn = outlet.block_gong_end if outlet else None
    else:
        raise ValueError(f"which must be 'start' or 'end'; got {which!r}")

    data, sr = _load_wav_2d(path, target_channels=audio_config.channels)
    ts: float | None = None
    if marker_fn is not None:
        _, ts = marker_fn()
    sd.play(data, samplerate=sr, device=audio_config.device_name)
    if blocking:
        sd.wait()
    return ts


def play_reference_tone(
    audio_config: AudioConfig, repo_root: Path, stop_event: threading.Event
) -> None:
    """Loop the volume-check tone until stop_event is set. Blocks the caller."""
    path = repo_root / audio_config.files.volume_reference
    data, sr = _load_wav_2d(path, target_channels=audio_config.channels)
    n = len(data)
    cursor = {"i": 0}

    def callback(outdata, frames, time_info, status):  # noqa: ARG001
        if status:
            logger.warning("reference-tone callback status: %s", status)
        out_i = 0
        remaining = frames
        while remaining > 0:
            available = n - cursor["i"]
            take = min(available, remaining)
            outdata[out_i : out_i + take] = data[cursor["i"] : cursor["i"] + take]
            cursor["i"] = (cursor["i"] + take) % n
            out_i += take
            remaining -= take

    with sd.OutputStream(
        samplerate=sr,
        channels=audio_config.channels,
        dtype="float32",
        blocksize=audio_config.buffer_blocksize,
        device=audio_config.device_name,
        callback=callback,
    ):
        stop_event.wait()


# ---------------------------------------------------------------------------
# .wav loading helper
# ---------------------------------------------------------------------------


def _load_wav_2d(path: Path, target_channels: int) -> tuple[np.ndarray, int]:
    """Load a .wav, return (samples_x_channels float32, sample_rate)."""
    if not path.exists():
        raise FileNotFoundError(
            f"audio asset not found: {path}. "
            "Run `uv run python scripts/generate_tones.py` to create it."
        )
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] == target_channels:
        return data, sr
    if data.shape[1] == 1 and target_channels == 2:
        return np.repeat(data, 2, axis=1), sr
    if data.shape[1] == 2 and target_channels == 1:
        return data[:, :1], sr
    raise ValueError(
        f"cannot reconcile {path.name} ({data.shape[1]} channels) "
        f"with target {target_channels} channels"
    )
