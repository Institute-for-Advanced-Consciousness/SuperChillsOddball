"""Manual loopback test procedure for ToneScheduler timing.

This test is **skipped by default** because it requires:
  1. An audio loopback (stereo cable from headphone-out -> mic-in, OR
     a virtual loopback like VB-Cable).
  2. A microphone input device on the same machine.
  3. LabRecorder running and recording the marker stream alongside an
     audio recording (or a Python sounddevice InputStream alongside).

Run procedure (manual):

  1. Set up the loopback: route line-out into line-in.
  2. Start LabRecorder; subscribe to ``Chills_Task_Markers`` AND your
     audio input stream. Begin recording.
  3. ``uv run pytest tests/test_audio_timing.py --runaudio``
     (the marker is enabled by passing ``--runaudio`` to pytest;
      see conftest.py setup below).
  4. Stop LabRecorder. Open the .xdf in EEGLAB / mne-python / xdfutil.
  5. For each ``tone_standard`` / ``tone_deviant`` marker, find the
     matching audio onset (envelope follower threshold) and confirm the
     marker timestamp is within ±2 ms of audio onset.

Acceptance criterion: 95th percentile |marker - audio onset| < 2 ms.
"""

import pytest

pytest.skip(
    "audio loopback test — run manually per procedure in this module's docstring",
    allow_module_level=True,
)
