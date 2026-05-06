# IACS source audio assets

These three files are mirrored from the IACS Sentiometer Study repo and are
the canonical source material for the rendered stimuli in `assets/sounds/`:

| file | use | provenance |
|---|---|---|
| `tone_1000hz.wav` | source for `tone_standard_1000hz.wav` (renormalized to -20 dBFS RMS) | [iacs-sentiometer-study/assets/sounds/tone_1000hz.wav](https://github.com/Institute-for-Advanced-Consciousness/iacs-sentiometer-study/blob/main/assets/sounds/tone_1000hz.wav) |
| `tone_2000hz.wav` | source for `tone_deviant_2000hz.wav` (renormalized to -20 dBFS RMS) | [iacs-sentiometer-study/assets/sounds/tone_2000hz.wav](https://github.com/Institute-for-Advanced-Consciousness/iacs-sentiometer-study/blob/main/assets/sounds/tone_2000hz.wav) |
| `Simple_Gong.wav` | source for `gong_start.wav` (forward) and `gong_end.wav` (reversed for clear distinguishability) | [iacs-sentiometer-study/assets/sounds/Simple_Gong.wav](https://github.com/Institute-for-Advanced-Consciousness/iacs-sentiometer-study/blob/main/assets/sounds/Simple_Gong.wav) |

The 3-second 1 kHz volume-check tone is **not** sourced here — `scripts/generate_tones.py`
synthesizes it directly so it can be exactly the right duration / level.

To re-render every file in `assets/sounds/` from these sources:

```sh
uv run python scripts/generate_tones.py --force
```

`--force` is required because the script is idempotent — it skips existing files.
