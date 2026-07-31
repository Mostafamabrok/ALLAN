"""
log.py — the append-only ledger. ALLAN's single source of truth.

Every meaningful event — you spoke, a model was called, AP replied, an error
happened — is written here as one line of JSON. Two rules make this the
foundation everything else stands on:

  1. Append-only. We only ever add lines to the end. Nothing is edited or
     deleted, ever. That is what makes the ledger trustworthy: it is a
     faithful record of what actually happened, not a summary of it.

  2. Everything else in ALLAN (memory, summaries, and so on) will be
     REBUILDABLE from this file. So this is the one thing that must be kept
     safe. If a fancier layer ever gets corrupted, we regenerate it from here.

The format is JSON Lines (one JSON object per line): deliberately boring and
human-readable. Open the file in any text editor and you can read ALLAN's
entire history.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator


def _utc_now_iso() -> str:
    """Current time as an ISO-8601 string in UTC, e.g. 2026-07-31T09:15:00+00:00."""
    return datetime.now(timezone.utc).isoformat()


class Log:
    def __init__(self, path: Path):
        self.path = Path(path)
        # Make sure the folder exists before we open the file for writing.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One id per program run, so separate sessions are easy to tell apart.
        self.session_id = uuid.uuid4().hex[:8]
        # Open once in append mode ("a"): every write goes to the end of the file.
        self._fh = open(self.path, "a", encoding="utf-8")

    def record(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Write one event to the ledger, and return the event that was written."""
        event = {
            "id": uuid.uuid4().hex[:12],   # unique id for this single event
            "ts": _utc_now_iso(),          # when it happened
            "session": self.session_id,    # which run of the program
            "type": event_type,            # what kind of event (see run.py / ap.py)
            "data": data,                  # the details
        }
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()
        # Force the bytes to disk right now. The ledger must survive a crash.
        os.fsync(self._fh.fileno())
        return event

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    @staticmethod
    def read_all(path: Path) -> Iterator[Dict[str, Any]]:
        """Replay the whole ledger, event by event. For inspecting or rebuilding."""
        p = Path(path)
        if not p.exists():
            return
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
