# IACS On-Demand Chills × Oddball Study — Project Plan

> **For Claude Code.** This document is the complete brief for building an all-in-one Windows GUI experiment runner for a single-participant on-demand chills × auditory oddball study. Read this front-to-back before writing any code. Defaults reproduce the IACS Sentiometer Study P013 conventions and ERP CORE oddball parameters where applicable, so the data are directly comparable across protocols.

---

## What this repo is

A single-laptop, GUI-driven experiment runner for IACS Protocol **P-CHILLS-ODDBALL-01** (working name; PI to finalize). The participant sits in front of a Windows laptop with headphones, the RA enters a participant number and tweaks any parameters in the GUI, and the app drives them through the entire ~45-minute session: instructions → chills calibration → 16 randomized condition blocks → 5-minute active oddball → done. After every chills block the participant rates the experience; after every rest block they rate alertness. LSL markers are emitted on a single outlet so concurrent EEG (BrainVision 64-ch) and CGX AIM-2 recordings are perfectly time-aligned with every event of interest.

The design draws from three sibling repos in the IACS organization:

- **`iacs-sentiometer-study`** — single master YAML config, Tkinter launcher with edit affordance, per-task LSL marker conventions, ERP CORE oddball parameters, practice-gate pattern. This is the reference for everything timing- and marker-related.
- **`ChillsFrissonDeviceDemo`** — single-file `app.py` Tkinter pattern, stage-based participant flow, auto-incrementing participant IDs, partial-save on abort, JSON output schema. This is the reference for GUI workflow and data persistence.
- **`Jazzo`** — general GUI shell idioms used across IACS apps (mentioned for stylistic consistency; not pulled in directly).

---

## Scientific design

### Why these conditions

The 2×2 chills/rest × oddball-passive structure dissociates two effects that the literature usually conflates: the **endogenous neurophysiology of self-induced chills** (skin conductance bursts, autonomic arousal, schema-deactivation signatures — see Schoeller et al. 2024 *Sci Rep* and Sachs, Ellis, Schlaug, & Loui 2016 *Soc Cogn Affect Neurosci*) and the **exogenous P300 / MMN response** to deviant tones during those states. By presenting the *same* oddball stream during chills vs rest, we can ask whether volitional chills modulate the ERP to ignored deviants (a top-down × bottom-up interaction). The final active-oddball block gives us a "gold standard" P300 anchor under engaged attention, comparable to ERP CORE's published reference data ([Kappenman et al., 2021, *NeuroImage*](https://doi.org/10.1016/j.neuroimage.2020.117465)).

### Falsifiable predictions worth pre-registering

- **H1 (chills × P300 interaction):** P300 amplitude at Pz/Cz to ignored deviants will differ between chills+oddball and rest+oddball blocks. Direction is exploratory; both attenuation (top-down absorption in interoceptive content) and enhancement (heightened arousal) have literature support.
- **H2 (state classification):** A linear classifier on EEG features should separate chills-only from rest-only blocks above chance (positive control on the manipulation itself).
- **H3 (active oddball reproducibility):** P300 amplitude in the active block will fall within the published ERP CORE confidence interval for healthy adults, validating the rig.

These hypotheses are stated here so the marker scheme below is explicitly designed to support epoching for each.

---

## Repository structure

```
chills-oddball-study/
├── CLAUDE.md                           # This file
├── README.md                           # User-facing run instructions
├── pyproject.toml                      # uv project, all dependencies
├── launch.bat                          # Windows double-click launcher
├── INSTALL.bat                         # First-run installer (uv + deps)
├── config/
│   └── session_defaults.yaml           # All tunable parameters; loaded by GUI
├── src/
│   └── chills_oddball/
│       ├── __init__.py
│       ├── app.py                      # Tkinter root + stage controller (entry)
│       ├── config.py                   # YAML loader + override merging
│       ├── markers.py                  # LSL outlet creation + marker helpers
│       ├── audio.py                    # sounddevice scheduler + tone synthesis
│       ├── schedule.py                 # Block-list generation (random + constraints)
│       ├── stages/
│       │   ├── __init__.py
│       │   ├── intake.py               # Participant ID + parameter review
│       │   ├── volume_check.py         # 1 kHz reference tone + slider
│       │   ├── instructions.py         # Pre-session instructions screen
│       │   ├── calibration_chills.py   # 30s baseline chills + ratings
│       │   ├── block_runner.py         # Generic block loop (handles all 4 conditions)
│       │   ├── ratings_chills.py       # Post-chills-block rating panel
│       │   ├── ratings_rest.py         # Post-rest-block alertness panel
│       │   ├── active_oddball.py       # Practice gate + main active block
│       │   └── completion.py           # Final save + thank-you screen
│       └── persistence.py              # JSON + per-block CSV writers
├── assets/
│   ├── sounds/
│   │   ├── tone_standard_1000hz.wav    # Pre-rendered, reproducible
│   │   ├── tone_deviant_2000hz.wav
│   │   ├── gong_start.wav              # Block-start signal
│   │   ├── gong_end.wav                # Block-end signal (different timbre)
│   │   └── volume_reference_1khz.wav
│   └── instructions/
│       └── *.txt                       # Screen text per stage (editable)
├── scripts/
│   ├── generate_tones.py               # Regenerate the .wav stimuli
│   └── verify_xdf.py                   # Post-session marker coverage check
├── tests/
│   ├── test_schedule.py                # Block generation logic
│   ├── test_oddball_sequence.py        # min-standards-before-deviant constraint
│   ├── test_markers.py                 # LSL marker emission
│   └── test_config.py                  # YAML loader
└── Data/                               # gitignored; per-participant output
    └── P{NNN}/
        ├── session.json                # Master session record
        ├── block_{NN}_{condition}.csv  # One per completed block
        └── PARTIAL_session.json        # Written on abort
```

---

## Session flow (what the participant experiences)

```
RA enters participant ID + reviews parameters in GUI
        ↓
Volume check (1 kHz reference tone, participant adjusts headphones)
        ↓
Pre-session instructions (eyes-closed, gong = start, second gong = end)
        ↓
[CALIBRATION] 30s self-induced chills + ratings (sets personal baseline)
        ↓
[Block 1 of 16]   ─ random condition, random duration ∈ [30, 180] s
        ↓
[Ratings panel]   ─ chills battery OR rest alertness, depending on condition
        ↓
... repeat for blocks 2–16 (no same condition back-to-back) ...
        ↓
[ACTIVE ODDBALL]
    ├── Instructions
    ├── Practice (10 trials: 8 std + 2 dev) — repeat until ≥75% hit, ≤50% FA
    └── Main block: ~250 trials (~5 min), button press on deviant
        ↓
Completion screen + final JSON write
```

Total wall time: **~45 min** for the 16-block portion + ~5 min calibration/setup + ~5 min active oddball + ratings = **~55 min** participant-time.

---

## Conditions and block schedule

### The five conditions

| ID | Label | Audio during block | Eyes | Task |
|---|---|---|---|---|
| `calibration` | Chills calibration | Silent (just gongs) | Closed | Self-induce chills |
| `chills_only` | Chills only | Silent (just gongs) | Closed | Self-induce chills |
| `rest_only` | Rest only | Silent (just gongs) | Closed | Rest, mind-wander |
| `chills_oddball_passive` | Chills + passive oddball | Oddball tone stream | Closed | Self-induce chills, ignore tones |
| `rest_oddball_passive` | Rest + passive oddball | Oddball tone stream | Closed | Rest, ignore tones |
| `active_oddball` | Active oddball (final) | Oddball tone stream | Closed | Press space on deviant |

### Block durations and counts

Total target: ~40 min across 16 short-condition blocks → mean ~2.5 min/block.

The schedule generator (`schedule.py`) draws **4 blocks per condition × 4 conditions = 16 blocks**. Per condition, the four block durations are drawn from the set **{30, 90, 150, 180} s** in fixed assignment so each condition gets exactly one short, one medium, one medium-long, and one long block. This guarantees:

- Every condition is represented at every duration scale (so duration × condition is balanced for analysis).
- Total time per condition = 30 + 90 + 150 + 180 = **450 s = 7.5 min**, × 4 conditions = **30 min** of pure block time.
- With a 5–10 s rating panel + ~3 s gongs/instruction interstitial per block, total wall time ≈ 30 min + 16 × ~12 s overhead ≈ **~33 min** for the 16-block portion. Add calibration (~1 min) + active (~5 min) + setup gates → **~40–45 min total session**.

The 16 blocks are then **shuffled** with the constraint **no two consecutive blocks share a condition**. The shuffle is seeded from `time.time()` per session (fully random per session, even for the same participant), and the resolved order is logged to `session.json` at session start so the schedule is reproducible post-hoc.

### Active oddball (final block)

| Parameter | Value | Source |
|---|---|---|
| Standard tone | 1000 Hz, 100 ms, 10 ms cosine rise/fall, ~70 dB SPL | ERP CORE |
| Deviant tone | 2000 Hz, 100 ms, 10 ms cosine rise/fall, ~70 dB SPL | ERP CORE |
| Ratio | 80% standard / 20% deviant | ERP CORE |
| ISI | 1100–1500 ms uniform jitter | ERP CORE |
| Total trials | 250 (200 standard + 50 deviant) | sentiometer P013 |
| Duration | ~5 min | derived |
| Practice | 10 trials (8 std + 2 dev), gate at ≥75% hit AND ≤50% FA, repeat until passed | sentiometer P013 |
| Response key | **Spacebar** | spec |
| Abort key | **Escape** | spec (NOT spacebar — collision avoidance) |

### Passive oddball (within chills+oddball and rest+oddball blocks)

Same tone parameters and ratio as active. Trial count scales with block duration: each block runs as many trials as fit in its duration window with the standard ISI distribution (e.g., a 180 s block ≈ 130 trials). The sequence is **freshly generated per block** under the constraints below.

### Oddball sequence constraints (the "distribution of normal tones before any oddball")

These match the conventions of classic MMN/P300 paradigms ([Näätänen et al. 2007 *Clin Neurophysiol*](https://doi.org/10.1016/j.clinph.2007.04.026); CognitiveNeuroLab/Oddball_experiments enforces nearly identical rules):

- `min_standards_before_first_deviant`: **3** — no deviant in trials 1–3 of any block.
- `min_standards_between_deviants`: **3** — at least 3 standards between any two deviants.
- `max_consecutive_standards`: **8** — to prevent inattentive habituation.

The generator (`schedule.py::generate_oddball_sequence`) uses rejection sampling: shuffle, check constraints, reshuffle if violated, fail loudly after 1000 attempts (this should never happen at 80/20 ratio with these constraints — the constraints are loose). Unit-tested in `tests/test_oddball_sequence.py`.

---

## Ratings — exact UI

### After every chills block (`chills_only`, `chills_oddball_passive`, and the calibration block)

Six items, all in one panel, all required (except notes), with a final "Submit" button. Order matters — present in this sequence:

1. **Was the chills induction a success?** Radio: **Yes** / **No**
2. **How many waves of chills did you experience?** Integer spinner, range 0–20, default 0
3. **Overall intensity:** Slider 0 → 10 (anchors: 0 = none, 10 = maximum I have ever felt)
4. **Quality:** Slider 0 → 10 (anchors: 0 = poor / unpleasant, 10 = excellent / pleasant)
5. **Should we keep this trial in the analysis?** Radio: **Yes, keep** / **No, discard**
6. **Notes (optional):** Multi-line text box, ~3 visible rows

### After every rest block (`rest_only`, `rest_oddball_passive`)

One item:

1. **Alertness:** Slider 0 → 10 (anchors: **0 = fell asleep**, **5 = neutral**, **10 = highly alert / wired**)

> Anchor rationale: The Stanford Sleepiness Scale ([Hoddes et al. 1973, *Psychophysiology*](https://pubmed.ncbi.nlm.nih.gov/4719486/)) uses a 1–7 scale anchored at "feeling active and vital" → "almost in reverie; cannot stay awake." We're using 0–10 here for visual consistency with the chills sliders, with conceptually similar anchors.

### After active oddball

One item plus auto-computed feedback:

1. **Did you feel you stayed engaged with the task?** Slider 0 → 10
2. (Auto-displayed, read-only) Hit rate: X%, False alarm rate: Y%, Mean RT: Z ms

---

## Tech stack

- **Python 3.11+** (tested target 3.12)
- **uv** for project/venv management (matches sentiometer)
- **Tkinter** for GUI (stdlib, zero install on Windows)
- **sounddevice** for audio playback (PortAudio backend, callback-based scheduling, <1 ms jitter for our use case — see [python-sounddevice docs](https://python-sounddevice.readthedocs.io/))
- **numpy** for tone synthesis at install time (`scripts/generate_tones.py` runs once during setup)
- **scipy** for cosine ramp envelope on tone generation
- **soundfile** for `.wav` I/O
- **pylsl** for LSL marker outlet (no PsychoPy required — pure pip on Windows)
- **PyYAML** for config
- **pydantic** for config validation (typed errors > KeyErrors)
- **rich** for any CLI output (e.g., `verify_xdf.py`)
- **pytest** for tests
- **ruff** for linting (line length 100)

**No PsychoPy.** PsychoPy on Windows requires MS Visual C++ Build Tools 14+ (per the sentiometer README), which is significant friction for a single-laptop setup. Tone-pip oddball + Tkinter ratings have no PsychoPy-shaped requirements (no frame-locked visual stim).

**No Pygame.** Not needed — no game phase, no continuous animation.

---

## Audio timing strategy

Audio precision matters here because the EEG analysis will lock to tone onsets. The strategy:

1. **Pre-render all tones** to disk at install time via `scripts/generate_tones.py`. 1000 Hz and 2000 Hz pure sines, 100 ms duration, 10 ms cosine rise/fall, normalized to a fixed RMS so SPL is consistent. Reproducible from the script — `generate_tones.py` is committed; the `.wav` files are committed too so the install path doesn't rely on a successful generation step.
2. **Schedule via sounddevice callback timing.** A persistent `OutputStream` runs at 44.1 kHz throughout the oddball blocks. The block-runner pre-computes the trial sequence (tones + ISIs) and writes samples into the stream's buffer at the right offsets. The marker is emitted **inside the audio callback** at the exact sample where the tone begins, using `pylsl.local_clock()` corrected for the stream's `time` field (see `audio.py::ToneScheduler`).
3. **Test the timing.** A loopback test in `tests/test_audio_timing.py` plays a tone and records the system audio, verifying the marker timestamp is within ±2 ms of the actual onset. (Optional; document the expected procedure even if the test requires manual audio loopback.)

For the gongs and reference tone, sub-ms accuracy isn't required, so a simpler `sd.play()` call is fine.

---

## LSL marker scheme

### Outlet

- **Stream name:** `Chills_Task_Markers`
- **Stream type:** `Markers`
- **Channel format:** `cf_string`
- **Nominal rate:** 0
- **Source ID:** `CHILLS_ODDBALL_Launcher` (constant string — **stable across the whole session**, so LabRecorder doesn't lose subscription mid-session. The sentiometer team learned this the hard way at commit `8094ab4`.)

### Session-level markers

| Marker | When |
|---|---|
| `session_start` | Right after outlet creation |
| `participant_id:{pid}` | Immediately after `session_start` |
| `session_config_seed:{seed}` | The RNG seed used for block ordering this session |
| `session_end` | After the last task, before outlet release |
| `session_abort` | On Escape-confirmed abort |

### Block-level markers (every block, all conditions)

The condition and the block's index in the schedule are baked into the marker string so analysis can epoch by condition trivially:

| Marker | When |
|---|---|
| `block_start:idx={NN}:condition={cond}:duration_s={ddd}` | At the moment the block timer starts |
| `block_gong_start` | Onset of the start-gong (the participant's "go" cue) |
| `block_gong_end` | Onset of the end-gong (the participant's "stop" cue) |
| `block_end:idx={NN}:condition={cond}` | After the end-gong finishes |

### Calibration block markers

Same as above with `condition=calibration`, plus:

| Marker | When |
|---|---|
| `calibration_start` | Distinct marker for downstream filtering |
| `calibration_end` | |

### Oddball stimulus markers (passive and active)

Every tone — in **both** passive and active blocks — emits one of:

| Marker | When |
|---|---|
| `tone_standard:trial={N}:condition={cond}` | At sample-accurate tone onset |
| `tone_deviant:trial={N}:condition={cond}` | At sample-accurate tone onset |

Including `condition` in the marker string lets the analysis pipeline epoch on `tone_deviant` and split by condition without needing to cross-reference block boundaries. The `trial` counter resets per block and is logged to the per-block CSV so `(trial, condition)` is unambiguous.

### Active-oddball response markers (active block only)

| Marker | When |
|---|---|
| `active_response_hit:rt_ms={N}` | Spacebar within response window after a deviant |
| `active_response_miss` | Deviant received no response within window |
| `active_response_false_alarm:rt_ms={N}` | Spacebar after a standard |

Response window: **1500 ms post-tone**. Correct rejections (no press on standard) emit no marker — silent default.

### Practice block markers (active oddball only)

| Marker | When |
|---|---|
| `active_practice_start:attempt={N}` | Each practice attempt (N = 1, 2, 3, …) |
| `active_practice_passed` | Emitted iff the attempt cleared the gate |
| `active_practice_tone_standard` / `active_practice_tone_deviant` | Practice tones (no response markers) |
| `active_practice_end:attempt={N}` | At end of each attempt |

### Ratings markers

| Marker | When |
|---|---|
| `ratings_start:block_idx={NN}` | When the ratings panel appears |
| `ratings_submit:block_idx={NN}:success={Y/N}:waves={N}:intensity={N}:quality={N}:keep={Y/N}` | When the participant clicks Submit (chills blocks) |
| `ratings_submit:block_idx={NN}:alertness={N}` | Submit (rest blocks) |
| `ratings_end:block_idx={NN}` | Panel dismissed, next block ready |

> Marker strings can carry colon-delimited key/value payloads. We use this pattern (rather than separate markers for each field) so a single epoch can carry all behavioral context for that block. `verify_xdf.py` parses these strings with a single regex.

---

## Configurable vs. fixed parameters

Following the sentiometer convention: parameters that **define the paradigm** are hardcoded (changing them breaks the science); parameters that **tune dose and timing** are surfaced in `session_defaults.yaml` and editable in the GUI.

| Block / phase | Configurable | Fixed |
|---|---|---|
| Schedule | n_blocks_per_condition (default 4), block_duration_set (default `[30, 90, 150, 180]` s), no_back_to_back (default true), seed_strategy (`random` / `participant_id`) | 4 conditions, schedule constraint enforcement, calibration always first, active oddball always last |
| Calibration | duration_s (default 30) | Always chills, always silent, always before the main schedule |
| Passive oddball (within blocks) | tone_volume_dbfs, isi_min_ms (1100), isi_max_ms (1500), min_standards_before_first_deviant (3), min_standards_between_deviants (3), max_consecutive_standards (8) | Tone freqs (1000 / 2000 Hz), tone duration (100 ms), rise/fall (10 ms), ratio (80/20), ERP CORE compliance |
| Active oddball | total_trials (250), practice_n_trials (10), practice_n_deviants (2), practice_hit_threshold (0.75), practice_fa_ceiling (0.50), response_window_ms (1500), tone_volume_dbfs | Same fixed params as passive + active task structure (practice gate, button-press response, one-block-at-end placement) |
| Audio | gong_volume_dbfs, ref_tone_volume_dbfs | Pre-rendered .wav files, sounddevice backend |
| Ratings | (all label text editable in `session_defaults.yaml`) | Item set, scale ranges (0–10 sliders, 0–20 spinner), required-vs-optional flags |
| Output | data_root_dir (default `./Data`) | JSON+CSV schema, partial-save on abort |

---

## Launcher / GUI flow

The GUI is a single Tkinter root with a stage controller pattern (matching ChillsFrissonDeviceDemo's `app.py`). One window, frame swapping. **All stages are full-window (no dialogs) so the participant sees a single coherent screen at all times.**

### Stages

1. **Intake screen** (RA-facing): participant ID field (auto-suggests `P{NNN}` from highest existing folder + 1, editable), pre-flight checklist table (LSL outlet OK, audio device OK, sample rate OK, headphones connected reminder), parameter review table (loaded from `session_defaults.yaml`, every value clickable to edit in-place — values held in memory only, file untouched), big "Begin Session" button.
2. **Volume check**: 1 kHz reference tone loops; "Adjust headphones until comfortable" + Continue button. Spacebar continues.
3. **Instructions**: full-text instructions about eyes-closed, gong cues, ratings between blocks. "Press Space when ready."
4. **Calibration chills block**: instructions screen → spacebar → start gong → 30 s timer (no on-screen counter visible to participant, but visible to RA in a small footer) → end gong → ratings panel.
5. **Main loop** (×16): pre-block instruction screen naming the upcoming condition (e.g., "Up next: REST. Eyes closed. You'll hear tones — please ignore them.") → spacebar → start gong → block runs (silent for chills_only/rest_only, oddball stream for the +oddball variants) → end gong → ratings panel → next block.
6. **Active oddball intro**: instructions → practice block(s) until passed → main block.
7. **Completion**: "Thank you! Session complete." + summary stats (total chills success rate, mean intensity, P300 hit rate) + "Save & Exit" button.

### Abort / recovery

- **Escape at any time** → confirmation dialog ("Abort session? Data so far will be saved as PARTIAL.") → on confirm: emit `session_abort`, write `PARTIAL_session.json`, close outlet, exit.
- **Window-close (X button)** → same flow as Escape.
- **Mid-block abort** is fine; the in-progress block is logged with `status: aborted` and excluded from the count of completed blocks.
- **Crash recovery**: on next launch with the same participant ID, GUI detects `PARTIAL_session.json` and offers "Resume from block N" or "Start fresh" (resume is best-effort; the simple path is just "start fresh and the partial data is still on disk for forensics").

### RA conveniences

- Small footer status bar (RA-visible, minimal): current block index, current condition, block timer, LSL stream status.
- Volume slider always accessible in a corner (does not interfere with participant flow).
- Optional "Skip to block N" debug shortcut (Ctrl+Shift+S) — disabled by default in production via a config flag `allow_debug_shortcuts: false`.

---

## Data persistence

### `Data/P{NNN}/session.json` (master record, written incrementally)

```json
{
  "participant_id": "P001",
  "session_start_utc": "2026-05-05T14:30:52Z",
  "session_end_utc": "2026-05-05T15:23:14Z",
  "status": "completed",  // or "aborted"
  "rng_seed": 1714929052,
  "config_snapshot": { /* full session_defaults.yaml as-loaded for this session */ },
  "schedule": [
    {"idx": 0, "condition": "calibration", "duration_s": 30},
    {"idx": 1, "condition": "rest_only", "duration_s": 90},
    /* ... */
    {"idx": 17, "condition": "active_oddball", "duration_s": 300}
  ],
  "blocks": [
    {
      "idx": 0,
      "condition": "calibration",
      "duration_s": 30,
      "start_lsl": 12345.678,
      "end_lsl": 12376.123,
      "status": "completed",
      "ratings": {"success": true, "waves": 3, "intensity": 7, "quality": 8, "keep": true, "notes": ""},
      "csv_path": "block_00_calibration.csv"
    },
    /* ... */
  ],
  "active_oddball_summary": {
    "practice_attempts": 1,
    "practice_passed": true,
    "main_total_trials": 250,
    "main_hits": 47,
    "main_misses": 3,
    "main_false_alarms": 12,
    "mean_rt_ms": 412.3,
    "engagement_rating": 8
  }
}
```

### `Data/P{NNN}/block_{NN}_{condition}.csv` (per-block, all blocks)

For oddball-containing blocks, one row per tone. For silent blocks, just the start/end timestamps (single row). Columns:

```
trial_idx, t_lsl, event, tone_type, response, rt_ms
```

Example row from a `chills_oddball_passive` block:

```
5, 12378.412, tone_onset, deviant, NA, NA
```

### `Data/P{NNN}/PARTIAL_session.json`

Same schema as `session.json` but written every block (so a crash leaves the most recent state on disk) and only kept if the session aborted.

---

## Tests

The test suite must run on a developer Windows machine without audio hardware, without LSL listeners, and without an attached EEG. Strategies:

- **`tests/test_schedule.py`** — verify the block schedule generator: 4 per condition, no back-to-back, durations balanced, deterministic with fixed seed, raises clearly on impossible constraints.
- **`tests/test_oddball_sequence.py`** — verify the constraints (min_standards_before_first_deviant, min_standards_between_deviants, max_consecutive_standards) hold across 1000 generated sequences. Verify 80/20 ratio is exact at standard block lengths.
- **`tests/test_markers.py`** — round-trip an `Outlet` → `Inlet` and check every marker fires with the right string format. Use `pylsl` in-process; no LabRecorder needed.
- **`tests/test_config.py`** — load `session_defaults.yaml`, validate via pydantic, verify GUI overrides merge correctly.
- **`tests/test_persistence.py`** — write a `session.json`, abort halfway, verify `PARTIAL_session.json` is well-formed and contains all completed blocks.
- **`tests/test_audio_timing.py`** *(optional, requires loopback)* — manual procedure documented; skipped in CI.

Run with `uv run pytest`. Lint with `uv run ruff check src/ tests/`.

---

## Install + launch on Windows

### First-run install (RA does this once per laptop)

1. Install Python 3.11+ from [python.org](https://www.python.org/downloads/) (or use an existing install — verify with `py --version`).
2. Double-click **`INSTALL.bat`**. The script:
   - Detects/installs `uv` from [astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1).
   - Runs `uv sync` to create `.venv` and install all deps.
   - Runs `uv run python scripts/generate_tones.py` to produce the `.wav` files (idempotent — skips if files exist).
   - Runs `uv run python -m chills_oddball.app --self-check` to confirm the app boots, the LSL outlet creates, audio device opens. Reports OK or the specific failure.

Total first-run time: ~60 s.

### Every-session launch

1. Confirm headphones plugged in.
2. Confirm LabRecorder is running and has discovered `Chills_Task_Markers` + EEG + CGX streams.
3. Double-click **`launch.bat`**. The GUI opens at the Intake screen.

---

## Marker reference (for analysis later)

Quick reference for the analyst returning to the data. Every timestamp is `pylsl.local_clock()` at the decisive moment.

### Epoching cheatsheet

- **Passive P300 contrast** — epoch on `tone_deviant:condition=chills_oddball_passive` vs `tone_deviant:condition=rest_oddball_passive`. Window: `[-200, 800] ms`. This is the primary H1 contrast.
- **Active P300 (positive control)** — epoch on `tone_deviant:condition=active_oddball`. Same window. Should reproduce ERP CORE's published P300.
- **State-classification windows** — use the interval `[block_start, block_end]` per block. Extract spectral features → train classifier on `condition` label.
- **Chills-anchored analyses** — combine `block_start:condition=chills_only` window with the per-block ratings (intensity, waves, keep flag) joined from `session.json`.
- **Excluded epochs** — drop any tone whose timestamp falls inside `[ratings_start, ratings_end]` (shouldn't happen by design, but safety filter) and any block where `ratings.keep == false`.

### Verifying a recorded XDF

```bash
uv run python scripts/verify_xdf.py path/to/session.xdf
```

Prints: per-condition tone counts, mean ISI, marker coverage table (every expected marker type vs observed count), and any constraint violations (e.g., a deviant in trial 1 of a block).

---

## Build order for Claude Code

Implement in this order; each step ends with passing tests for that scope.

1. **Scaffolding** — `pyproject.toml`, `uv` setup, directory tree, empty modules with docstrings, `INSTALL.bat`, `launch.bat`.
2. **Config layer** — `config/session_defaults.yaml` with every parameter from the tables above; `src/chills_oddball/config.py` loader + pydantic validation. Test: load and validate.
3. **Schedule generator** — `schedule.py::generate_session_schedule` and `generate_oddball_sequence` with all constraints. Test: 1000 random schedules pass constraints.
4. **Tone generation** — `scripts/generate_tones.py` produces all `.wav` files. Run it; commit the outputs.
5. **Markers** — `markers.py::ChillsMarkerOutlet` wrapping `pylsl`. Test: round-trip every marker type.
6. **Audio scheduler** — `audio.py::ToneScheduler` for sample-accurate oddball delivery + simple `play_gong` / `play_reference_tone`. Manual loopback test documented.
7. **Persistence** — `persistence.py::SessionWriter` for JSON + per-block CSV, with incremental writes and partial-save logic. Test: simulate abort.
8. **Stage shells** — empty Tkinter frames for every stage in `stages/`, with the controller swapping between them. Manually walk through; no logic yet.
9. **Block runner** — generic block loop in `stages/block_runner.py` that handles all 4 short-condition variants. Wire in markers, audio, persistence.
10. **Ratings panels** — `stages/ratings_chills.py` and `stages/ratings_rest.py`, including marker emission with payload.
11. **Calibration block** — special-case wrapper around `block_runner` + `ratings_chills`.
12. **Active oddball + practice gate** — `stages/active_oddball.py`. Test the practice gate with a mocked response sequence.
13. **Intake + volume check + completion screens** — wire start-to-end.
14. **Abort handling** — Escape + window-close → confirmation → partial save → clean exit.
15. **`verify_xdf.py`** — analyst tool for post-session sanity checking.
16. **Self-check mode** — `--self-check` CLI flag for `INSTALL.bat`.
17. **README.md** — RA-facing run instructions (single page, screenshots optional).

---

## Open issues / decisions deferred

- **Resume-from-partial logic** — currently the spec says "start fresh, partial is forensic-only." If sessions get long enough that crash recovery becomes important, revisit. Low priority.
- **Volume calibration to absolute SPL** — we're calibrating *perceptually* via the volume check, not to a measured dB SPL. Cross-participant SPL comparisons will have headphone-position variance. If this matters, add a sound-level meter procedure to the SOP (out of scope for the app).
- **Eye-state verification** — we're trusting the participant to keep their eyes closed. EOG channels on the CGX AIM-2 will pick up eye movements/blinks post-hoc; the analyst can flag blocks with anomalous EOG. No app-level enforcement.

---

## Contacts

- **PI / Author:** Nicco Reggente, Ph.D. (IACS)
- **Reference protocols:** IACS Sentiometer Study P013, ERP CORE (Kappenman et al. 2021)

---

## Citations

- Kappenman, E. S., Farrens, J. L., Zhang, W., Stewart, A. X., & Luck, S. J. (2021). ERP CORE: An open resource for human event-related potential research. *NeuroImage*, 225, 117465. https://doi.org/10.1016/j.neuroimage.2020.117465
- Näätänen, R., Paavilainen, P., Rinne, T., & Alho, K. (2007). The mismatch negativity (MMN) in basic research of central auditory processing: A review. *Clinical Neurophysiology*, 118(12), 2544–2590. https://doi.org/10.1016/j.clinph.2007.04.026
- Hoddes, E., Zarcone, V., Smythe, H., Phillips, R., & Dement, W. C. (1973). Quantification of sleepiness: A new approach. *Psychophysiology*, 10(4), 431–436. https://doi.org/10.1111/j.1469-8986.1973.tb00801.x
- Sachs, M. E., Ellis, R. J., Schlaug, G., & Loui, P. (2016). Brain connectivity reflects human aesthetic responses to music. *Social Cognitive and Affective Neuroscience*, 11(6), 884–891. https://doi.org/10.1093/scan/nsw009
- Schoeller, F., Christov-Moore, L., Lynch, C., Diot, T., & Reggente, N. (2024). [Frontiers in chills/aesthetic emotion neuroscience.] — *Add the specific Schoeller/IACS reference Nicco wants to cite for the schema-deactivation framework here; placeholder.*

> **Note on the Schoeller citation:** I deliberately left this as a placeholder rather than fabricating a DOI. Drop in the exact paper you want cited (likely the chills + Behavioral Activation or chills + schema-deactivation piece) before this goes to anyone else.
