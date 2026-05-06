"""Audio scheduler tests — pure-function pieces only.

The actual playback path requires real audio hardware and is exercised
by the documented manual loopback procedure, not pytest.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from chills_oddball.audio import (
    _load_wav_2d,
    build_oddball_buffer,
    compute_onset_samples,
    sample_isis,
)
from chills_oddball.config import REPO_ROOT, load_config

# ---------------------------------------------------------------------------
# compute_onset_samples
# ---------------------------------------------------------------------------


def test_compute_onset_samples_first_is_zero():
    onsets = compute_onset_samples([1300, 1300, 1300], sample_rate=44100)
    assert onsets[0] == 0


def test_compute_onset_samples_uses_n_minus_one_isis():
    """N trials need N-1 spacings; the trailing ISI doesn't shift any onset."""
    onsets_a = compute_onset_samples([1100, 1200, 1300], sample_rate=44100)
    onsets_b = compute_onset_samples([1100, 1200, 9999], sample_rate=44100)
    assert onsets_a == onsets_b


def test_compute_onset_samples_monotonic():
    rng = random.Random(0)
    isis = [rng.uniform(1100, 1500) for _ in range(50)]
    onsets = compute_onset_samples(isis, sample_rate=44100)
    assert all(b > a for a, b in zip(onsets, onsets[1:], strict=False))


def test_compute_onset_samples_negative_isi_raises():
    with pytest.raises(ValueError, match="non-positive"):
        compute_onset_samples([1300, -100, 1300], sample_rate=44100)


def test_compute_onset_samples_spacing_matches_round_trip():
    """ISI 1300 ms at 44100 Hz -> 57330 samples between adjacent onsets."""
    onsets = compute_onset_samples([1300, 1300], sample_rate=44100)
    assert onsets[1] - onsets[0] == 57330


# ---------------------------------------------------------------------------
# build_oddball_buffer
# ---------------------------------------------------------------------------


def _fake_tone(value: float, n_samples: int = 100, n_channels: int = 2) -> np.ndarray:
    return np.full((n_samples, n_channels), value, dtype=np.float32)


def test_build_oddball_buffer_places_tones_at_onsets():
    standard = _fake_tone(0.1)
    deviant = _fake_tone(0.5)
    onsets = [0, 200, 400, 600]
    sequence = [False, True, False, True]
    buf = build_oddball_buffer(
        sequence=sequence,
        onset_samples=onsets,
        standard=standard,
        deviant=deviant,
        n_channels=2,
        tail_samples=50,
    )
    # Total = last onset + tone len + tail
    assert buf.shape == (600 + 100 + 50, 2)
    # Standards at 0..99
    assert np.allclose(buf[0:100], 0.1)
    # Deviant at 200..299
    assert np.allclose(buf[200:300], 0.5)
    # Standard at 400..499
    assert np.allclose(buf[400:500], 0.1)
    # Deviant at 600..699
    assert np.allclose(buf[600:700], 0.5)
    # Silence between
    assert np.allclose(buf[100:200], 0.0)


def test_build_oddball_buffer_empty_sequence():
    standard = _fake_tone(0.1)
    deviant = _fake_tone(0.5)
    buf = build_oddball_buffer(
        sequence=[],
        onset_samples=[],
        standard=standard,
        deviant=deviant,
        n_channels=2,
        tail_samples=50,
    )
    assert buf.shape == (50, 2)


def test_build_oddball_buffer_length_mismatch_raises():
    standard = _fake_tone(0.1)
    deviant = _fake_tone(0.5)
    with pytest.raises(ValueError, match="same length"):
        build_oddball_buffer(
            sequence=[True, False],
            onset_samples=[0],
            standard=standard,
            deviant=deviant,
            n_channels=2,
        )


def test_build_oddball_buffer_channel_mismatch_raises():
    standard = _fake_tone(0.1, n_channels=1)
    deviant = _fake_tone(0.5, n_channels=2)
    with pytest.raises(ValueError, match="channels"):
        build_oddball_buffer(
            sequence=[True],
            onset_samples=[0],
            standard=standard,
            deviant=deviant,
            n_channels=2,
        )


# ---------------------------------------------------------------------------
# sample_isis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dist", ["uniform", "normal"])
def test_sample_isis_within_bounds(dist):
    rng = random.Random(0)
    isis = sample_isis(n=500, isi_min_ms=1100, isi_max_ms=1500, distribution=dist, rng=rng)
    assert len(isis) == 500
    assert all(1100 <= v <= 1500 for v in isis)


def test_sample_isis_uniform_mean_close_to_midpoint():
    rng = random.Random(0)
    isis = sample_isis(n=2000, isi_min_ms=1100, isi_max_ms=1500, distribution="uniform", rng=rng)
    mean = sum(isis) / len(isis)
    assert 1280 < mean < 1320  # midpoint = 1300


def test_sample_isis_unknown_distribution_raises():
    rng = random.Random(0)
    with pytest.raises(ValueError, match="isi_distribution"):
        sample_isis(n=10, isi_min_ms=1100, isi_max_ms=1500, distribution="lognormal", rng=rng)


# ---------------------------------------------------------------------------
# .wav loading + integration with the rendered assets
# ---------------------------------------------------------------------------


def test_load_standard_tone_matches_config():
    cfg = load_config()
    path = REPO_ROOT / cfg.audio.files.tone_standard
    data, sr = _load_wav_2d(path, target_channels=cfg.audio.channels)
    assert sr == cfg.audio.sample_rate_hz
    assert data.shape[1] == cfg.audio.channels
    # 100 ms at 44100 Hz = 4410 samples
    assert data.shape[0] == 4410


def test_load_deviant_tone_matches_config():
    cfg = load_config()
    path = REPO_ROOT / cfg.audio.files.tone_deviant
    data, sr = _load_wav_2d(path, target_channels=cfg.audio.channels)
    assert sr == cfg.audio.sample_rate_hz
    assert data.shape[1] == cfg.audio.channels
    assert data.shape[0] == 4410


def test_load_volume_reference_matches_config():
    cfg = load_config()
    path = REPO_ROOT / cfg.audio.files.volume_reference
    data, sr = _load_wav_2d(path, target_channels=cfg.audio.channels)
    assert sr == cfg.audio.sample_rate_hz
    # 3000 ms at 44100 Hz = 132300 samples
    assert data.shape[0] == 132300


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="audio asset not found"):
        _load_wav_2d(tmp_path / "nope.wav", target_channels=2)
