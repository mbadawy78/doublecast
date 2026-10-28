"""`doublecast schedule`: refresh discovery every night, so names are known before any file is read.

macOS: a LaunchAgent. Windows: a Task Scheduler task. Linux: a user crontab line. The run is
`doublecast discover run --yes --quiet`, which never waits for a sign-in (see discover/microsoft.py)
and leaves a log in ~/.doublecast/discover.log.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .config import default_home

LABEL = "com.doublecast.discover"


def _command() -> list[str]:
    exe = shutil.which("doublecast")
    base = [exe] if exe else [sys.executable, "-m", "doublecast"]
    return [*base, "discover", "run", "--yes", "--quiet"]


def _parse(at: str) -> tuple[int, int]:
    hh, _, mm = at.partition(":")
    h, m = int(hh), int(mm or 0)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("Use --at HH:MM, e.g. 02:30")
    return h, m


def schedule(enable: bool = True, at: str = "02:30") -> str:
    system = platform.system()
    log = default_home() / "discover.log"
    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)
        if not enable:
            if plist.exists():
                plist.unlink()
            return "Nightly discovery stopped."
        h, m = _parse(at)
        args = "".join(f"<string>{a}</string>" for a in _command())
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            f"<key>Label</key><string>{LABEL}</string>"
            f"<key>ProgramArguments</key><array>{args}</array>"
            f"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{h}</integer>"
            f"<key>Minute</key><integer>{m}</integer></dict>"
            f"<key>StandardOutPath</key><string>{log}</string>"
            f"<key>StandardErrorPath</key><string>{log}</string>"
            "</dict></plist>\n",
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True, check=False)
        return f"Discovery will refresh every night at {h:02d}:{m:02d} (if the Mac is asleep, at wake). Log: {log}"
    if system == "Windows":
        name = "Doublecast discover"
        if not enable:
            subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True, check=False)
            return "Nightly discovery stopped."
        h, m = _parse(at)
        cmd = " ".join(f'"{a}"' for a in _command())
        subprocess.run(
            ["schtasks", "/Create", "/TN", name, "/TR", cmd, "/SC", "DAILY", "/ST", f"{h:02d}:{m:02d}", "/F"],
            capture_output=True,
            check=False,
        )
        return f"Discovery will refresh every night at {h:02d}:{m:02d}."
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False).stdout
    lines = [ln for ln in current.splitlines() if LABEL not in ln]
    if enable:
        h, m = _parse(at)
        lines.append(f"{m} {h} * * * {' '.join(_command())} >> {log} 2>&1  # {LABEL}")
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=False)
    return "Nightly discovery stopped." if not enable else f"Discovery will refresh every night at {at}. Log: {log}"
