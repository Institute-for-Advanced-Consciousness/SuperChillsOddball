"""Pre-render the .wav stimuli used by the experiment.

Produces five files under assets/sounds/:

    tone_standard_1000hz.wav    1000 Hz, 100 ms, 10 ms cosine rise/fall  (ERP CORE)
    tone_deviant_2000hz.wav     2000 Hz, 100 ms, 10 ms cosine rise/fall  (ERP CORE)
    volume_reference_1khz.wav   1000 Hz, 3000 ms, 10 ms ramps            (vol-check)
    gong_start.wav              ~1.5 s low-pitched gong (block start)
    gong_end.wav                ~1.5 s higher-pitched gong (block end)

All output is 44.1 kHz / 16-bit / stereo (identical L/R). Tones and the
reference are normalized to the same RMS level so a single volume slider
calibrates them all together; gongs are normalized to a higher level.

Idempotent: skips files that already exist unless --force is passed.
Tone parameters are paradigm-fixed (see CLAUDE.md "Configurable vs.
fixed parameters") and live as constants in this script — do not change
the frequencies, durations, or envelope without PI sign-off.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
SOUNDS_DIR = REPO_ROOT / "assets" / "sounds"

SAMPLE_RATE = 44100  # Hz
CHANNELS = 2

# --- Paradigm-fixed tone parameters (DO NOT CHANGE — ERP CORE compliance) ---
STANDARD_FREQ_HZ = 1000.0
DEVIANT_FREQ_HZ = 2000.0
TONE_DURATION_MS = 100.0
TONE_RAMP_MS = 10.0  # cosine rise/fall

# --- Volume reference ---
REFERENCE_FREQ_HZ = 1000.0
REFERENCE_DURATION_MS = 3000.0
REFERENCE_RAMP_MS = 10.0

# --- Gong synthesis ---
GONG_START_FUND_HZ = 196.0  # ~G3
GONG_END_FUND_HZ = 392.0    # ~G4 (one octave up — easily distinguishable)
GONG_DURATION_MS = 1500.0
GONG_DECAY_TAU_S = 0.5      # exponential decay constant

# --- Loudness targets (dBFS, applied as RMS normalization to stereo mono signal) ---
# Tones and reference share a level so the volume check transfers directly.
TONE_TARGET_DBFS = -20.0
GONG_TARGET_DBFS = -18.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cosine_envelope(n_samples: int, ramp_samples: int) -> np.ndarray:
    """Smooth cosine rise/fall envelope. Centre is unity, edges are zero."""
    if ramp_samples <= 0:
        return np.ones(n_samples, dtype=np.float64)
    if 2 * ramp_samples > n_samples:
        raise ValueError(
            f"ramp ({ramp_samples}) is too long for a {n_samples}-sample tone"
        )
    env = np.ones(n_samples, dtype=np.float64)
    rise = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, ramp_samples, endpoint=False)))
    fall = rise[::-1]
    env[:ramp_samples] = rise
    env[-ramp_samples:] = fall
    return env


def normalize_rms_to_dbfs(signal: np.ndarray, target_dbfs: float) -> np.ndarray:
    """Scale `signal` so its RMS equals `target_dbfs` (relative to full scale 1.0)."""
    rms = float(np.sqrt(np.mean(signal**2)))
    if rms == 0.0:
        return signal
    target_rms = 10 ** (target_dbfs / 20.0)
    return signal * (target_rms / rms)


def sine_tone(freq_hz: float, duration_ms: float, ramp_ms: float) -> np.ndarray:
    """Pure sine with cosine-ramped onset and offset, mono float64."""
    n = int(round(SAMPLE_RATE * duration_ms / 1000.0))
    ramp_samples = int(round(SAMPLE_RATE * ramp_ms / 1000.0))
    t = np.arange(n) / SAMPLE_RATE
    raw = np.sin(2.0 * np.pi * freq_hz * t)
    env = cosine_envelope(n, ramp_samples)
    return raw * env


def gong(
    fundamental_hz: float, duration_ms: float, decay_tau_s: float, ramp_ms: float = 5.0
) -> np.ndarray:
    """Cheap gong-ish synthesis: fundamental + 2nd/3rd partials, exponential decay.

    Not a real gong — just a recognizable, pleasant onset/offset cue with
    enough timbral difference between start and end variants to be
    distinguishable to the participant.
    """
    n = int(round(SAMPLE_RATE * duration_ms / 1000.0))
    ramp_samples = int(round(SAMPLE_RATE * ramp_ms / 1000.0))
    t = np.arange(n) / SAMPLE_RATE
    # Slightly inharmonic partials make it sound less synthetic than pure ratios.
    partials = [
        (1.0, 1.00),
        (2.01, 0.55),
        (3.04, 0.30),
        (4.10, 0.15),
    ]
    raw = np.zeros(n, dtype=np.float64)
    for ratio, amp in partials:
        raw += amp * np.sin(2.0 * np.pi * fundamental_hz * ratio * t)
    raw /= len(partials)
    decay = np.exp(-t / decay_tau_s)
    env = cosine_envelope(n, ramp_samples)
    return raw * decay * env


def to_stereo(mono: np.ndarray) -> np.ndarray:
    """Duplicate a mono signal across L/R channels."""
    return np.column_stack((mono, mono)).astype(np.float32)


def write_wav(path: Path, signal_stereo: np.ndarray) -> None:
    """16-bit PCM WAV at SAMPLE_RATE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), signal_stereo, SAMPLE_RATE, subtype="PCM_16")


def render_and_save(
    name: str, mono: np.ndarray, target_dbfs: float, force: bool
) -> tuple[Path, bool]:
    """Apply RMS normalization, write to disk. Returns (path, was_written)."""
    path = SOUNDS_DIR / name
    if path.exists() and not force:
        return path, False
    normalized = normalize_rms_to_dbfs(mono, target_dbfs)
    # Clip-protect: if peaks exceed full scale, scale the whole signal down.
    peak = float(np.max(np.abs(normalized)))
    if peak > 0.99:
        normalized = normalized * (0.99 / peak)
    write_wav(path, to_stereo(normalized))
    return path, True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Re-render even if files exist"
    )
    args = parser.parse_args(argv)

    standard = sine_tone(STANDARD_FREQ_HZ, TONE_DURATION_MS, TONE_RAMP_MS)
    deviant = sine_tone(DEVIANT_FREQ_HZ, TONE_DURATION_MS, TONE_RAMP_MS)
    reference = sine_tone(REFERENCE_FREQ_HZ, REFERENCE_DURATION_MS, REFERENCE_RAMP_MS)
    gstart = gong(GONG_START_FUND_HZ, GONG_DURATION_MS, GONG_DECAY_TAU_S)
    gend = gong(GONG_END_FUND_HZ, GONG_DURATION_MS, GONG_DECAY_TAU_S)

    targets = [
        ("tone_standard_1000hz.wav", standard, TONE_TARGET_DBFS),
        ("tone_deviant_2000hz.wav", deviant, TONE_TARGET_DBFS),
        ("volume_reference_1khz.wav", reference, TONE_TARGET_DBFS),
        ("gong_start.wav", gstart, GONG_TARGET_DBFS),
        ("gong_end.wav", gend, GONG_TARGET_DBFS),
    ]

    print(f"Writing stimuli to {SOUNDS_DIR.relative_to(REPO_ROOT)}/")
    for name, mono, dbfs in targets:
        path, written = render_and_save(name, mono, dbfs, force=args.force)
        status = "wrote" if written else "skipped (exists)"
        print(f"  {status:<18}  {path.name}  ({dbfs:+.1f} dBFS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
