"""Full-call transcript recording (PRD §9).

Saves each call to ``logs/<call_id>.transcript.json`` with, per entry, the
speaker, text, timestamps, any tool calls (name + args + result), and whether a
turn was interrupted.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class TranscriptRecorder:
    """Collects conversation items and tool calls, then writes them to JSON."""

    def __init__(self, call_id: str, customer_id: str) -> None:
        self.call_id = call_id
        self.customer_id = customer_id
        self.started_at = time.time()
        self.entries: list[dict[str, Any]] = []

    def _entry(self, **fields: Any) -> None:
        now = time.time()
        self.entries.append({"ts": round(now, 3), "time": _iso(now), **fields})

    def add_message(self, speaker: str, text: str, interrupted: bool = False) -> None:
        """Record a spoken turn. ``speaker`` is 'customer' or 'agent'."""
        if not text:
            return
        self._entry(
            type="message",
            speaker=speaker,
            text=text,
            interrupted=interrupted,
        )

    def add_tool_call(self, tool: str, args: dict[str, Any], result: Any) -> None:
        self._entry(type="tool_call", tool=tool, args=args, result=result)

    def add_interruption(self, detail: str | None = None) -> None:
        self._entry(type="interruption", detail=detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "customer_id": self.customer_id,
            "started_at": _iso(self.started_at),
            "ended_at": _iso(time.time()),
            "entries": self.entries,
        }

    def dump(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
