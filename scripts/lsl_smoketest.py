"""Open the real ChillsMarkerOutlet and hold it open for inspection.

Run: uv run python scripts/lsl_smoketest.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from chills_oddball.config import load_config
from chills_oddball.markers import ChillsMarkerOutlet


def main() -> None:
    cfg = load_config(REPO / "config" / "session_defaults.yaml")
    outlet = ChillsMarkerOutlet(cfg.lsl)
    outlet.open()
    print(
        f"[smoketest] outlet OPEN  name={cfg.lsl.stream_name!r}  "
        f"type={cfg.lsl.stream_type!r}  source_id={cfg.lsl.source_id!r}",
        flush=True,
    )
    outlet.session_start()
    outlet.participant_id("SMOKETEST")
    print("[smoketest] pushed: session_start, participant_id:pid=SMOKETEST", flush=True)

    n = 0
    try:
        while True:
            time.sleep(2.0)
            n += 1
            text, ts = outlet.emit("smoketest_heartbeat", {"n": n})
            print(f"[smoketest] pushed: {text}  ts={ts:.3f}", flush=True)
    except KeyboardInterrupt:
        outlet.emit("session_end")
        outlet.close()
        print("[smoketest] outlet CLOSED", flush=True)


if __name__ == "__main__":
    main()
