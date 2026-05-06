"""Render the .wav stimuli used by the experiment.

Source material lives under ``assets/sources/iacs/`` (mirrored from the
IACS Sentiometer Study repo — see that folder's README for provenance).
This script reads those sources, renormalizes them to the configured
levels, and writes the final files to ``assets/sounds/``:

    tone_standard_1000hz.wav    iacs/tone_1000hz.wav -> -20 dBFS RMS, stereo
    tone_deviant_2000hz.wav     iacs/tone_2000hz.wav -> -20 dBFS RMS, stereo
    gong_start.wav              iacs/Simple_Gong.wav -> -18 dBFS RMS, stereo
    gong_end.wav                iacs/Simple_Gong.wav reversed -> -18 dBFS RMS, stereo
                                (the time-reversed gong has a distinct
                                "swell-then-stop" envelope that's easy to
                                tell apart from the forward block-start gong)
    volume_reference_1khz.wav   synthesized 1 kHz, 3 s, -20 dBFS RMS, stereo

Idempotent: skips files that already exist unless --force is passed.
Tone duration / frequency are paradigm-fixed; the renormalization step
preserves the IACS recording while bringing it into our calibrated level
window.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = REPO_ROOT / "assets" / "sources" / "iacs"
SOUNDS_DIR = REPO_ROOT / "assets" / "sounds"

# Output config (matches config/session_defaults.yaml audio section).
SAMPLE_RATE = 44100
CHANNELS = 2
TONE_TARGET_DBFS = -20.0
GONG_TARGET_DBFS = -18.0

# Volume-reference synthesis (no IACS source).
REFERENCE_FREQ_HZ = 1000.0
REFERENCE_DURATION_MS = 3000.0
REFERENCE_RAMP_MS = 10.0

# The IACS gong rings out for ~10.6 s. Played in full it would dominate
# every block (a 30 s block would be 10 + 30 + 10 = 50 s wall time). Trim
# to a brief audible cue with a smooth fade-out.
GONG_TRIM_MS = 2000.0
GONG_FADE_OUT_MS = 200.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_source(name: str) -> tuple[np.ndarray, int]:
    path = SOURCES_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"missing IACS source asset: {path}. "
            "See assets/sources/iacs/README.md for where these come from."
        )
    data, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return data, sr


def cosine_envelope(n_samples: int, ramp_samples: int) -> np.ndarray:
    if ramp_samples <= 0:
        return np.ones(n_samples, dtype=np.float64)
    if 2 * ramp_samples > n_samples:
        raise ValueError(
            f"ramp ({ramp_samples}) too long for a {n_samples}-sample tone"
        )
    env = np.ones(n_samples, dtype=np.float64)
    rise = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, ramp_samples, endpoint=False)))
    env[:ramp_samples] = rise
    env[-ramp_samples:] = rise[::-1]
    return env


def normalize_rms_to_dbfs(signal: np.ndarray, target_dbfs: float) -> np.ndarray:
    rms = float(np.sqrt(np.mean(signal**2)))
    if rms == 0.0:
        return signal
    target_rms = 10 ** (target_dbfs / 20.0)
    return signal * (target_rms / rms)


def to_stereo(mono: np.ndarray) -> np.ndarray:
    """Duplicate a mono signal across L/R channels (or pass stereo through)."""
    if mono.ndim == 1:
        stereo = np.column_stack((mono, mono))
    elif mono.shape[1] == 1:
        stereo = np.repeat(mono, 2, axis=1)
    elif mono.shape[1] == 2:
        stereo = mono
    else:
        raise ValueError(f"unexpected channel count: {mono.shape[1]}")
    return stereo.astype(np.float32)


def write_wav(path: Path, signal_stereo: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), signal_stereo, SAMPLE_RATE, subtype="PCM_16")


def render_and_save(
    name: str, signal: np.ndarray, sr: int, target_dbfs: float, force: bool
) -> tuple[Path, bool]:
    """Normalize, clip-protect, write to disk. Returns (path, was_written)."""
    path = SOUNDS_DIR / name
    if path.exists() and not force:
        return path, False
    if sr != SAMPLE_RATE:
        raise ValueError(
            f"{name}: source sr={sr} doesn't match required {SAMPLE_RATE}. "
            "Re-record the IACS source at 44.1 kHz."
        )
    normalized = normalize_rms_to_dbfs(signal, target_dbfs)
    peak = float(np.max(np.abs(normalized)))
    if peak > 0.99:
        normalized = normalized * (0.99 / peak)
    write_wav(path, to_stereo(normalized))
    return path, True


def trim_with_fadeout(
    signal: np.ndarray, sr: int, duration_ms: float, fade_ms: float
) -> np.ndarray:
    """Take the first ``duration_ms`` of `signal` and fade the tail to zero."""
    n_keep = int(round(sr * duration_ms / 1000.0))
    n_keep = min(n_keep, len(signal))
    out = signal[:n_keep].copy()
    n_fade = int(round(sr * fade_ms / 1000.0))
    n_fade = min(n_fade, n_keep)
    if n_fade > 0:
        # Half-cosine taper from 1 -> 0
        ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, n_fade)))
        if out.ndim == 2:
            out[-n_fade:] *= ramp[:, None]
        else:
            out[-n_fade:] *= ramp
    return out


def synthesize_volume_reference() -> tuple[np.ndarray, int]:
    """1 kHz, 3 s, 10 ms ramps. Mono float64 (will be broadcast to stereo)."""
    n = int(round(SAMPLE_RATE * REFERENCE_DURATION_MS / 1000.0))
    ramp = int(round(SAMPLE_RATE * REFERENCE_RAMP_MS / 1000.0))
    t = np.arange(n) / SAMPLE_RATE
    raw = np.sin(2.0 * np.pi * REFERENCE_FREQ_HZ * t)
    return raw * cosine_envelope(n, ramp), SAMPLE_RATE


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Re-render even if files exist"
    )
    args = parser.parse_args(argv)

    print(f"Rendering stimuli to {SOUNDS_DIR.relative_to(REPO_ROOT)}/")

    # Tones (mono in source -> stereo in output, renormalized to -20 dBFS RMS).
    standard_src, sr_std = load_source("tone_1000hz.wav")
    deviant_src, sr_dev = load_source("tone_2000hz.wav")

    # Gongs: forward = block start, reversed = block end (distinguishable timbre).
    # Trim to a brief audible cue + fade-out so each block doesn't get a
    # ~10 s gong on each end of its silent body.
    gong_src_full, sr_gong = load_source("Simple_Gong.wav")
    gong_src = trim_with_fadeout(gong_src_full, sr_gong, GONG_TRIM_MS, GONG_FADE_OUT_MS)
    gong_reversed = trim_with_fadeout(
        gong_src_full[::-1].copy(), sr_gong, GONG_TRIM_MS, GONG_FADE_OUT_MS
    )

    # Reference: synthesized.
    ref_signal, sr_ref = synthesize_volume_reference()

    targets = [
        ("tone_standard_1000hz.wav", standard_src, sr_std,  TONE_TARGET_DBFS, "from iacs/tone_1000hz.wav"),
        ("tone_deviant_2000hz.wav",  deviant_src,  sr_dev,  TONE_TARGET_DBFS, "from iacs/tone_2000hz.wav"),
        ("gong_start.wav",           gong_src,     sr_gong, GONG_TARGET_DBFS, "from iacs/Simple_Gong.wav (forward)"),
        ("gong_end.wav",             gong_reversed, sr_gong, GONG_TARGET_DBFS, "from iacs/Simple_Gong.wav (reversed)"),
        ("volume_reference_1khz.wav", ref_signal,  sr_ref,  TONE_TARGET_DBFS, "synthesized 1 kHz / 3 s"),
    ]

    for name, sig, sr, dbfs, provenance in targets:
        path, written = render_and_save(name, sig, sr, dbfs, force=args.force)
        status = "wrote" if written else "skipped (exists)"
        print(f"  {status:<18}  {path.name:<32}  {dbfs:+.1f} dBFS  {provenance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
