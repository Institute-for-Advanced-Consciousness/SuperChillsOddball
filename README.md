# IACS On-Demand Chills × Oddball Study

Single-laptop, GUI-driven experiment runner for **Protocol P-CHILLS-ODDBALL-01**.

The app drives one participant through the full ~55 min session: instructions →
chills calibration → 16 randomized condition blocks → 5 min active oddball →
done. Every event of interest is emitted on a single LSL marker stream so
concurrent EEG (BrainVision 64-ch) and CGX AIM-2 recordings line up exactly.

For the complete scientific brief and design rationale, see **[CLAUDE.md](CLAUDE.md)**.

---

## First-run install (do this once per laptop)

1. **Install Python 3.11+** from <https://www.python.org/downloads/> if you don't
   already have it. (Verify with `py --version` in a terminal.)
2. **Double-click `INSTALL.bat`**.

The installer will:

- Install `uv` (the project / venv manager) if it's not present.
- Run `uv sync` to create `.venv\` and install all Python dependencies.
- Generate the `.wav` stimuli (idempotent — skips files that already exist).
- Run a self-check confirming the LSL outlet creates, the audio device opens,
  and the Tk display works.

Total wall time: about 60 seconds on a fresh box. Re-running is safe.

If the self-check fails, you'll see exactly which check failed (`FAIL audio
device …`, `FAIL LSL outlet …`, etc.) so you know where to look.

---

## Every-session launch

1. Plug in headphones and put them on the participant.
2. Open **LabRecorder** and confirm it has discovered:
   - `Chills_Task_Markers` (this app)
   - your EEG stream (BrainVision)
   - your CGX AIM-2 stream
   Begin recording in LabRecorder.
3. **Double-click `launch.bat`**.

The GUI opens at the **Intake screen**:

- The participant ID auto-suggests the next free `P{NNN}` (one above the
  highest existing folder under `Data\`). Edit if needed.
- The right-hand panel is the pre-flight checklist; the left summarizes the
  paradigm-fixed and operator-tunable parameters that will be used.
- Click **Begin Session**.

From there the flow is:

```
Intake  →  Volume check  →  Instructions  →  Calibration (30 s chills)
        →  16 short condition blocks (chills_only / rest_only /
           chills_oddball_passive / rest_oddball_passive, randomized)
        →  Active oddball (practice gate + 250-trial main)
        →  Completion (summary + Save & Exit)
```

After every chills block the participant rates 6 items
(success / waves / intensity / quality / keep / notes); after every rest block
they rate alertness 0–10. Block transitions are gated by SPACE so the RA can
pause for a sip of water or a question between blocks.

---

## What gets saved

Every session writes to `Data\P{NNN}\`:

- `session.json` — master record (status, schedule, all block records,
  ratings, active-oddball summary). Written when the participant clicks
  **Save & Exit** or when the session is aborted.
- `block_NN_{condition}.csv` — one CSV per block. Silent blocks have two
  rows (start/end stamps); oddball blocks have one row per tone (and one
  extra row per response in the active block).
- `PARTIAL_session.json` — refreshed after every block. Deleted on a clean
  Save & Exit; **kept** as a forensic snapshot if the session was aborted or
  crashed mid-way.

The `Data\` folder is gitignored; nothing personal ever goes near version
control.

---

## Aborting

Press **Escape** at any time, or click the window's **X** button. You'll get
a confirmation dialog ("Abort session? Data so far will be saved as
PARTIAL_session.json."). On confirm, the runtime:

1. Emits a `session_abort` LSL marker.
2. Marks any in-progress block as `aborted` in the writer.
3. Writes the final `session.json` with `status: "aborted"`.
4. Closes the LSL outlet and exits.

The PARTIAL file is retained alongside `session.json` so you have the
last-known good state for forensics.

---

## After the session: verifying the recording

```
uv run python scripts\verify_xdf.py path\to\session.xdf
```

`verify_xdf` loads only the marker stream from your XDF and prints:

- a coverage table (every expected marker type vs observed count);
- per-condition tone counts + 80/20 ratio + ISI mean/SD;
- any sequence-constraint violations (deviant in early-window, deviants too
  close together, or a long standard run).

Exit code 0 = clean. Exit code 1 = there's something to investigate.

---

## Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `INSTALL.bat`: "uv not found" | uv installer needs a fresh terminal | Open a new Command Prompt and re-run |
| Self-check: "FAIL audio device" | Headphones unplugged, or the wrong device is the default | Plug in headphones, set as default; or set `audio.device_name` in `config\session_defaults.yaml` |
| Self-check: "FAIL LSL outlet" | Port in use, firewall blocking | Close other LSL apps; allow Python through Windows firewall |
| `launch.bat` opens then closes | Python crash on startup | Run `uv run python -m chills_oddball.app --self-check` manually to see the error |
| Tones sound wrong | Stale `.wav` files | `uv run python scripts\generate_tones.py --force` |
| LabRecorder doesn't see the marker stream | Multicast blocked, or app not yet started | Start LabRecorder *first*, then launch the app; refresh streams |

---

## Where the paradigm is defined

| File | What lives there |
|---|---|
| `CLAUDE.md` | The full scientific brief, hypothesis statements, and design rationale |
| `config\session_defaults.yaml` | Every operator-tunable parameter (durations, levels, thresholds). Edit on disk to change the defaults; the GUI lets the RA tweak in-memory for one session |
| `src\chills_oddball\schedule.py` | Block-list and oddball-sequence generators (constraints from CLAUDE.md) |
| `src\chills_oddball\markers.py` | LSL marker outlet + every marker type emitted by the runtime |
| `src\chills_oddball\stages\` | One file per UI stage (intake, calibration, block runner, ratings, active oddball, completion) |

Tone frequencies (1000 / 2000 Hz), ratio (80 / 20), ISI window (1100–1500 ms),
practice gate (≥75 % hits, ≤50 % FA) and the three sequence constraints are
**paradigm-fixed** for ERP CORE compatibility — change them only with PI
sign-off.

---

## Running the test suite (developers)

```
uv run pytest
uv run ruff check src\ tests\ scripts\
```

The audio-loopback test (`tests\test_audio_timing.py`) is skipped by default
because it needs a hardware loopback. The procedure for running it manually
is in that file's docstring.
