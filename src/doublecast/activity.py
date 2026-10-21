"""What Doublecast has been doing: counts per day and the last few swaps.

Read by `doublecast status`, the menu-bar icon and the Claude Code status line.
Real values never land here: every sample is masked ("Ma•••" -> "Ky•••"), and
the file is readable by its owner only.

Several processes write it (the proxy, the clipboard command, the MCP server),
so each keeps its own small delta and adds it to whatever is on disk when it
saves.
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

KEEP_DAYS = 60
KEEP_LAST = 20


def mask(value: str) -> str:
    value = value.strip()
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}•••@{domain[:1]}•••"
    if any(c.isdigit() for c in value) and not any(c.isalpha() for c in value[:3]):
        return value[:2] + "•" * min(6, max(3, len(value) - 2))
    return value[:2] + "•••"


class Activity:
    def __init__(self, path: Path, source: str = "doublecast"):
        self.path = Path(path)
        self.source = source
        self._lock = threading.Lock()
        self._delta: dict[str, dict[str, int]] = {}
        self._last: list[dict] = []
        self._saved_at = 0.0
        atexit.register(self.flush)

    def record(self, rows: list[tuple[str, str, str]]) -> None:
        """rows: (category, original, stand-in) as Engine.scramble logs them."""
        if not rows:
            return
        day = dt.date.today().isoformat()
        now = dt.datetime.now().strftime("%H:%M")
        with self._lock:
            bucket = self._delta.setdefault(day, {})
            for cat, original, new in rows:
                bucket[cat] = bucket.get(cat, 0) + 1
                if cat not in ("MONEY", "QUANTITY", "DATE"):
                    self._last.append(
                        {"time": now, "category": cat, "from": mask(original), "to": mask(new), "via": self.source}
                    )
            self._last = self._last[-KEEP_LAST:]
        if time.monotonic() - self._saved_at > 2:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._delta and not self._last:
                return
            delta, last = self._delta, self._last
            self._delta, self._last = {}, []
        try:
            data = read(self.path)
            for day, counts in delta.items():
                bucket = data["days"].setdefault(day, {})
                for cat, n in counts.items():
                    bucket[cat] = bucket.get(cat, 0) + n
                    data["total"][cat] = data["total"].get(cat, 0) + n
            data["last"] = (data["last"] + last)[-KEEP_LAST:]
            for day in sorted(data["days"])[:-KEEP_DAYS]:
                data["days"].pop(day, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".tmp{os.getpid()}")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._saved_at = time.monotonic()
        except OSError:
            pass  # activity is a convenience; never let it break a scramble


def read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("days", {})
    data.setdefault("total", {})
    data.setdefault("last", [])
    return data


def summary(path: Path) -> dict:
    data = read(path)
    today = data["days"].get(dt.date.today().isoformat(), {})
    return {
        "today": today,
        "today_total": sum(today.values()),
        "total": data["total"],
        "total_all": sum(data["total"].values()),
        "last": data["last"][-5:][::-1],
    }
