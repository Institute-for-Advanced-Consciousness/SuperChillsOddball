# SuperChillsOddball

**IACS On-Demand Chills × Oddball Study — Protocol P-CHILLS-ODDBALL-01**

A single-laptop, GUI-driven experiment runner for a 2 × 2 chills/rest × oddball/passive
study with a final active oddball gold-standard block. Designed for concurrent
recording with a BrainVision 64-channel EEG and a CGX AIM-2 — every event of
interest is emitted on a single LSL marker stream, so post-hoc epoching against
EEG is exact.

> Full scientific brief, hypothesis statements, and design rationale live in
> **[CLAUDE.md](CLAUDE.md)**. This README is the operational + developer guide.

---

## What the study tests

The 2 × 2 chills/rest × oddball/passive structure dissociates two effects the
literature usually conflates: the **endogenous neurophysiology of self-induced
chills** (autonomic arousal, schema-deactivation signatures) and the
**exogenous P300 / MMN response** to deviant tones during those states. By
presenting the *same* oddball stream during chills vs. rest, we can ask
whether volitional chills modulate the ERP to ignored deviants. The final
active block gives us a P300 anchor under engaged attention, comparable to
[ERP CORE](https://doi.org/10.1016/j.neuroimage.2020.117465) reference data.

Three falsifiable predictions are baked into the marker scheme so analysis
can epoch each contrast directly from the XDF (see **[CLAUDE.md §
Falsifiable predictions](CLAUDE.md)**):

- **H1** — P300 to ignored deviants differs between chills + oddball and
  rest + oddball blocks (top-down × bottom-up interaction).
- **H2** — A linear classifier on EEG features separates chills-only from
  rest-only blocks above chance (positive control on the manipulation itself).
- **H3** — P300 in the active block falls within the published ERP CORE
  confidence interval, validating the rig.

---

## Session structure (~55 min)

```
Intake (RA)  →  Volume check  →  Pre-session instructions
             →  Calibration: 30 s self-induced chills + ratings
             →  16 short blocks, randomly ordered with no back-to-back
                same-condition:
                   {chills_only, rest_only,
                    chills_oddball_passive, rest_oddball_passive}
                   × 4 durations {30, 90, 150, 180} s
                Each chills block ends with a 6-item rating;
                each rest block with a 0–10 alertness slider.
             →  Active oddball (~5 min): practice-to-criterion
                (≥75 % hits & ≤50 % FA) then 250-trial main block
                with spacebar response on deviants.
             →  Engagement self-rating + summary  →  Save & Exit
```

Tone parameters (1000 / 2000 Hz, 100 ms, 10 ms cosine ramps, 80 / 20 ratio,
1100–1500 ms ISI, the three sequence constraints, the practice gate
thresholds) are paradigm-fixed for ERP CORE compatibility — see
[`session_defaults.yaml`](config/session_defaults.yaml) for everything that
*is* operator-tunable.

---

## Tech stack

- **Python 3.11+** (tested on 3.12 and 3.14)
- **uv** for project / venv management
- **Tkinter** for the GUI (stdlib, zero install on Windows)
- **sounddevice** for callback-based audio playback (~ sample-accurate marker
  emission via `outputBufferDacTime` → LSL clock conversion)
- **numpy / scipy / soundfile** for tone synthesis at install time
- **pylsl** for the LSL marker outlet
- **PyYAML / pydantic** for the master config + validation
- **pytest / ruff** for tests + lint
- **pyxdf** for the post-session analyst tool
- *No PsychoPy, no Pygame.* Tone-pip oddball + Tk ratings have no
  PsychoPy-shaped requirements; PsychoPy on Windows wants MS Visual C++
  Build Tools, which is significant install friction for a single-laptop
  setup.

---

## Repository layout

```
SuperChillsOddball/
├── CLAUDE.md                         # Full scientific + design brief
├── README.md                         # This file
├── INSTALL.bat                       # One-shot first-run installer
├── launch.bat                        # Every-session launcher
├── pyproject.toml                    # uv project + deps + ruff/pytest config
├── config/
│   └── session_defaults.yaml         # Master config (loaded by GUI at start)
├── src/chills_oddball/
│   ├── app.py                        # Tk root + stage controller + abort + --self-check
│   ├── config.py                     # YAML loader + pydantic models
│   ├── schedule.py                   # 18-block schedule + oddball-sequence generators
│   ├── markers.py                    # LSL outlet wrapper, one method per marker type
│   ├── audio.py                      # ToneScheduler (sample-anchored markers) + helpers
│   ├── persistence.py                # SessionWriter (JSON + per-block CSV + partial-on-abort)
│   └── stages/                       # 9 Tk frames swapped by the controller
│       ├── intake.py                 # RA-facing PID + paradigm review + Begin Session
│       ├── volume_check.py           # Loops 1 kHz reference tone
│       ├── instructions.py           # Pre-session text + SPACE -> first block
│       ├── calibration_chills.py     # 30 s baseline chills + cal markers
│       ├── block_runner.py           # Generic 4-condition block lifecycle
│       ├── ratings_chills.py         # 6-item chills battery
│       ├── ratings_rest.py           # 0–10 alertness slider
│       ├── active_oddball.py         # Practice gate + 250-trial main + engagement
│       └── completion.py             # Summary + Save & Exit
├── assets/
│   └── sounds/                       # 5 rendered .wav stimuli (committed)
├── scripts/
│   ├── generate_tones.py             # Idempotent tone renderer
│   └── verify_xdf.py                 # Post-session marker / constraint audit
├── tests/                            # 190 tests covering every module
└── Data/                             # gitignored; per-participant output lands here
```

---

## Quickstart for operators (RAs)

### First-run install (do this once per laptop)

1. Install **Python 3.11+** from <https://www.python.org/downloads/> if you
   don't have it (`py --version` to verify).
2. Double-click **`INSTALL.bat`**.

The installer:
- Installs `uv` if absent.
- `uv sync` creates `.venv\` and installs all dependencies.
- Generates the `.wav` stimuli (idempotent).
- Runs a self-check confirming the LSL outlet, the audio device, and the Tk
  display all work.

Total wall time: ~60 s.

### Every session

1. Plug in headphones; put them on the participant.
2. Open **LabRecorder** and confirm it has discovered:
   `Chills_Task_Markers` (this app), your EEG stream, and your CGX stream.
   Begin recording.
3. Double-click **`launch.bat`**. The GUI opens at the **Intake screen**
   (auto-suggests the next free `P{NNN}` and lists every parameter the run
   will use).
4. Click **Begin Session**. Hand the laptop to the participant.

### Aborting

Press **Escape** or click the window's **X** at any time. A confirmation
dialog appears; on confirm:

1. `session_abort` marker is emitted.
2. Any in-progress block is recorded with `status: "aborted"`.
3. `session.json` is written with `status: "aborted"`.
4. `PARTIAL_session.json` is **retained** as a forensic snapshot.
5. The LSL outlet closes and the app exits.

### Where data lands

Every session writes to `Data\P{NNN}\`:

| File | When written | Lifecycle |
|---|---|---|
| `session.json` | Save & Exit, or on abort | Final master record (status, schedule, all blocks, ratings, active-oddball summary) |
| `block_NN_{condition}.csv` | At the end of each block | Per-block trial records (silent: 2 rows; oddball: 1 row per tone; active: + 1 row per response) |
| `PARTIAL_session.json` | After every block | Refreshed continuously; **deleted** on clean Save & Exit, **retained** on abort |

`Data\` is gitignored; nothing personal goes near version control.

### Verifying a recording

After the session, audit the XDF that LabRecorder produced:

```sh
uv run python scripts\verify_xdf.py path\to\session.xdf
```

`verify_xdf` parses only the `Chills_Task_Markers` stream and prints:

- A coverage table — every expected marker type vs. observed count.
- Per-condition tone counts + 80/20 ratio + ISI mean/SD.
- Any constraint violations (deviant in early-window, deviants too close,
  long standard runs).

Exit 0 = clean; exit 1 = at least one violation worth investigating.

### Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `INSTALL.bat`: "uv not found" | New install needs a fresh shell | Open a new Command Prompt and re-run |
| Self-check: `FAIL audio device` | Headphones unplugged, or wrong default device | Plug in; or set `audio.device_name` in `config\session_defaults.yaml` to a device-name substring |
| Self-check: `FAIL LSL outlet` | Port in use, firewall blocking | Close other LSL apps; allow Python through Windows firewall |
| `launch.bat` opens then closes | Python crash on startup | Run `uv run python -m chills_oddball.app --self-check` to see the error |
| Tones sound wrong | Stale `.wav` files | `uv run python scripts\generate_tones.py --force` |
| LabRecorder doesn't see `Chills_Task_Markers` | Started after the app, multicast blocked | Start LabRecorder *first*, then launch the app; refresh streams |

---

## Quickstart for developers

```sh
# clone
git clone https://github.com/Institute-for-Advanced-Consciousness/SuperChillsOddball.git
cd SuperChillsOddball

# create venv + install all deps (incl. dev group)
uv sync

# render audio assets
uv run python scripts/generate_tones.py

# tests + lint
uv run pytest                         # 190 tests, ~6 s without the e2e
uv run ruff check src/ tests/ scripts/

# launch the GUI
uv run python -m chills_oddball.app
# or: uv run python -m chills_oddball.app --self-check
```

### How responses are saved

Both **locally** (`session.json` + per-block CSV) and **on LSL**, with one
exception:

- Chills ratings → `ratings_submit:block_idx=NN:success=Y:waves=N:intensity=N:quality=N:keep=Y`
  marker + `block.ratings` dict in JSON. Free-text **notes** are saved
  locally only (LSL marker payloads can't safely encode `:` or `=`).
- Rest ratings → `ratings_submit:block_idx=NN:alertness=N` marker +
  `block.ratings` in JSON.
- Active spacebar presses → captured live, classified post-hoc against tone
  timestamps within a 1500 ms window. Each tone gets one of
  `active_response_hit:rt_ms=N` / `active_response_miss` /
  `active_response_false_alarm:rt_ms=N`. Per-tone CSV rows + aggregated
  `active_oddball_summary` in JSON.
- The final engagement-rating slider is currently saved to JSON only (no
  LSL marker — easy to add if you want symmetry).

### Architecture cheatsheet

- **Frame swapping.** `App.show_stage(name, **payload)` in `app.py` is the
  single transition point. Each `StageFrame` overrides `on_enter` /
  `on_leave`. Stages call `app.show_stage(...)` or `app.show_block(idx)` /
  `app.advance_after_block(idx)` to move the cursor.
- **Worker-thread + Tk poller.** Audio playback (silent timer for plain
  blocks, `ToneScheduler.play_block` for oddball blocks) runs in a daemon
  thread that sets a `threading.Event` when done; the Tk thread polls via
  `after(50, …)` and continues on the main thread once the worker
  signals. Calling `tk.after()` cross-thread is not safe under uv's
  bundled Tk.
- **Sample-anchored markers.** `ToneScheduler` captures the LSL clock at
  the first audio callback (using PortAudio's `outputBufferDacTime` →
  `local_clock` delta), then emits each tone's marker with a precomputed
  timestamp `t0 + onset_sample / sr`.
- **Service-optional stages.** Every stage tolerates `app.outlet`,
  `app.writer`, and `app.audio_scheduler` being `None` — the
  side-effects are skipped. This is what lets the test suite drive the
  full UI flow with mocks (and lets a developer walk the GUI without
  LSL/audio just to check layout).
- **Atomic writes.** Both `session.json` and the per-block CSVs go via
  `tmp + rename`, so a Windows hard-crash mid-write never leaves a
  half-formed file.

### Test layout

| Test module | Coverage |
|---|---|
| `test_config.py` | YAML loader, pydantic invariants, GUI-override merging |
| `test_schedule.py` | Schedule generator (1000-seed stress test) |
| `test_oddball_sequence.py` | Sequence constraint generator (1000-seed) |
| `test_markers.py` | Outlet → Inlet round-trip for every marker type |
| `test_audio.py` | Pure helpers (buffer building, ISI sampling, .wav loading) |
| `test_persistence.py` | SessionWriter lifecycle (clean + aborted), ID auto-suggest |
| `test_app.py`, `test_block_runner.py`, `test_calibration.py`, `test_ratings.py`, `test_active_oddball.py`, `test_intake_volume_completion.py`, `test_abort.py` | Tk integration with mocked services (shared App fixture) |
| `test_verify_xdf.py` | Marker parser + per-block constraint detector |
| `test_e2e_full_session.py` | Full intake→completion walkthrough with real outlet + writer |
| `test_audio_timing.py` | **Skipped by default.** Manual loopback procedure documented in the file's docstring |

Run with `uv run pytest` (≈ 60 s; the e2e test alone is ~50 s).

---

## Citations

- Kappenman, E. S., Farrens, J. L., Zhang, W., Stewart, A. X., & Luck, S. J.
  (2021). ERP CORE: An open resource for human event-related potential
  research. *NeuroImage*, 225, 117465.
  <https://doi.org/10.1016/j.neuroimage.2020.117465>
- Näätänen, R., Paavilainen, P., Rinne, T., & Alho, K. (2007). The mismatch
  negativity (MMN) in basic research of central auditory processing: A
  review. *Clinical Neurophysiology*, 118(12), 2544–2590.
  <https://doi.org/10.1016/j.clinph.2007.04.026>
- Hoddes, E., Zarcone, V., Smythe, H., Phillips, R., & Dement, W. C. (1973).
  Quantification of sleepiness: A new approach. *Psychophysiology*, 10(4),
  431–436. <https://doi.org/10.1111/j.1469-8986.1973.tb00801.x>
- Sachs, M. E., Ellis, R. J., Schlaug, G., & Loui, P. (2016). Brain
  connectivity reflects human aesthetic responses to music. *Social
  Cognitive and Affective Neuroscience*, 11(6), 884–891.
  <https://doi.org/10.1093/scan/nsw009>

The Schoeller / IACS reference for the schema-deactivation framework is
intentionally left as a placeholder in CLAUDE.md — drop in the specific
paper before this goes to anyone external.

---

## Sister projects

- [`iacs-sentiometer-study`](https://github.com/Institute-for-Advanced-Consciousness/iacs-sentiometer-study)
  — single master YAML, Tk launcher, ERP CORE oddball params, practice-gate
  pattern. Reference for everything timing / marker.
- [`ChillsFrissonDeviceDemo`](https://github.com/Institute-for-Advanced-Consciousness/ChillsFrissonDeviceDemo)
  — single-file `app.py` Tk pattern, stage-based participant flow,
  partial-save on abort. Reference for the GUI workflow + persistence
  schema.

---

## Contact

**PI / author:** Nicco Reggente, Ph.D. (IACS)
