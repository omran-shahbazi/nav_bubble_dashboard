"""Fetches a fresh snapshot every 10 seconds, whether or not anyone has the page open.

Used on the server (see Dockerfile): it keeps today's row of silver/data/daily.csv and the latest
snapshot (static/live.json) up to date, and the Streamlit app only reads what it writes.
Locally the app fetches by itself, so this is not needed there.
"""

import time
import traceback

import silver_data as data

INTERVAL_SECONDS = 10

if __name__ == "__main__":
    while True:
        started = time.time()
        try:
            snap = data.build_snapshot()
            print(f"{snap['fetched_at']} snapshot saved: {len(snap['funds'])} funds, {len(snap['errors'])} errors", flush=True)
        except Exception:  # noqa: BLE001 - keep collecting; the next round may succeed
            traceback.print_exc()
        time.sleep(max(1, INTERVAL_SECONDS - (time.time() - started)))
