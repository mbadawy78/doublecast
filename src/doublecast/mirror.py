"""Mirror folders: a scrambled twin of a real folder, kept in sync both ways.

    ~/Projects/Bakeshack       real files; you work here
    ~/Projects/Bakeshack-AI    the twin; the only folder you give the AI

* Real -> twin: every supported file (xlsx, docx, csv, text, code, pdf as
  Markdown) is written to the twin scrambled. File and folder names are
  scrambled too. Photos, videos, archives and other formats Doublecast cannot
  read are NOT copied: copying them as they are would leak.
* Twin -> real: when the AI edits a twin file or creates a new one, the real
  values are put back and the result is written into the real folder.
* Nothing is ever deleted in the real folder. If both sides changed the same
  file, the AI's version is saved next to yours as "name (AI).ext".

The bookkeeping (which twin file belongs to which real file) lives in
~/.doublecast/mirrors/, never in the twin, because it holds real names.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .files import TEXT_EXTENSIONS, restore_file, scramble_file

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".DS_Store",
}
SCRAMBLED = {".xlsx", ".xlsm", ".docx", ".csv", ".tsv", ".pdf"} | TEXT_EXTENSIONS
RESTORABLE = {".xlsx", ".xlsm", ".docx", ".csv", ".tsv"} | TEXT_EXTENSIONS
NOTE = "_DOUBLECAST.md"
MARKER = ".doublecast-twin"  # which Doublecast owns this twin (a random id, nothing else)
MAX_BRING_BACK = 20  # more AI changes than this in one go looks like a fault, not work: hold them
STATE_VERSION = 1
MAX_TEXT_BYTES = 20_000_000
_SYNC_LOCK = threading.Lock()  # one engine, several mirrors: sync one at a time


def _skip_name(name: str) -> bool:
    return (
        name in SKIP_DIRS
        or name.startswith("~$")  # Office lock files
        or name.startswith(".~lock")
        or name.endswith((".tmp", ".part", ".crdownload"))
        or ".dc-tmp" in name
        or name == ".DS_Store"
        or name == NOTE
    )


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sig(path: Path) -> list:
    st = path.stat()
    return [int(st.st_mtime_ns), st.st_size]


def default_twin(src: Path) -> Path:
    return src.with_name(f"{src.name}-AI")


@dataclass
class Report:
    scrambled: int = 0
    restored: int = 0
    conflicts: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    failed: int = 0
    values: int = 0
    models_ok: int = 0
    models_off: list[str] = field(default_factory=list)
    not_recalculated: int = 0
    held: int = 0

    def line(self) -> str:
        skipped = sum(self.skipped.values())
        parts = [f"{self.scrambled} scrambled", f"{self.restored} brought back"]
        if self.conflicts:
            parts.append(f"{self.conflicts} kept side by side")
        if skipped:
            parts.append(f"{skipped} not copied")
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.models_ok or self.models_off:
            parts.append(f"{self.models_ok} model(s) checked and adding up")
        if self.models_off:
            parts.append(f"{len(self.models_off)} model(s) NOT adding up")
        if self.held:
            parts.append(f"{self.held} AI change(s) HELD (too many at once; check, then --accept)")
        return ", ".join(parts)


class Mirror:
    def __init__(self, engine, src: Path, twin: Path | None = None):
        self.engine = engine
        self.src = Path(src).expanduser().resolve()
        self.twin = Path(twin).expanduser().resolve() if twin else default_twin(self.src)
        if not self.src.is_dir():
            raise FileNotFoundError(f"Folder not found: {self.src}")
        if self.twin == self.src or self.src in self.twin.parents or self.twin in self.src.parents:
            raise ValueError("The twin must be a separate folder, not inside the real one (or the other way round)")
        key = hashlib.sha256(str(self.src).encode()).hexdigest()[:16]
        self.state_path = engine.config.home / "mirrors" / f"{key}.json"
        self.state = self._load()
        self.last_report = Report()
        self.error: str | None = None
        self.last_sync: str | None = self.state.get("last_sync")

    # ------------------------------------------------------------ state
    def _load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("version") == STATE_VERSION and data.get("twin") == str(self.twin):
                return data
        except (OSError, ValueError):
            pass
        return {"version": STATE_VERSION, "src": str(self.src), "twin": str(self.twin), "files": {}, "dirs": {}}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_path.parent, 0o700)
        tmp = self.state_path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------ names
    def _scramble_name(self, name: str, is_file: bool) -> str:
        stem, ext = os.path.splitext(name) if is_file else (name, "")
        spaced = stem.replace("_", " ")
        new = self.engine.scramble(spaced).text
        if "_" in stem and " " not in stem:
            new = new.replace(" ", "_")
        new = re.sub(r'[\\/:*?"<>|\n\r\t]', "-", new).strip() or stem
        return new + ext

    def _restore_name(self, name: str, is_file: bool) -> str:
        stem, ext = os.path.splitext(name) if is_file else (name, "")
        spaced = stem.replace("_", " ")
        new = self.engine.restore(spaced)
        if "_" in stem and " " not in stem:
            new = new.replace(" ", "_")
        return (re.sub(r'[\\/:*?"<>|\n\r\t]', "-", new).strip() or stem) + ext

    def _twin_dir(self, real_rel_dir: str) -> str:
        """Scrambled relative path of a real folder (cached, so it never changes)."""
        if real_rel_dir in ("", "."):
            return ""
        cached = self.state["dirs"].get(real_rel_dir)
        if cached:
            return cached
        parent, name = os.path.split(real_rel_dir)
        twin = os.path.join(self._twin_dir(parent), self._scramble_name(name, is_file=False))
        self.state["dirs"][real_rel_dir] = twin
        return twin

    def _real_dir(self, twin_rel_dir: str) -> str:
        if twin_rel_dir in ("", "."):
            return ""
        for real, twin in self.state["dirs"].items():
            if twin == twin_rel_dir:
                return real
        parent, name = os.path.split(twin_rel_dir)
        real = os.path.join(self._real_dir(parent), self._restore_name(name, is_file=False))
        self.state["dirs"][real] = twin_rel_dir
        return real

    def _twin_name_for(self, real_rel: str) -> str:
        folder, name = os.path.split(real_rel)
        twin_name = self._scramble_name(name, is_file=True)
        if os.path.splitext(name)[1].lower() == ".pdf":
            twin_name = os.path.splitext(twin_name)[0] + ".pdf.md"
        candidate = os.path.join(self._twin_dir(folder), twin_name)
        taken = {e["twin"] for k, e in self.state["files"].items() if k != real_rel}
        base, ext = os.path.splitext(candidate)
        n = 2
        while candidate in taken:
            candidate = f"{base} ({n}){ext}"
            n += 1
        return candidate

    # ------------------------------------------------------------ walking
    def _walk(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not _skip_name(d) and not d.startswith("."))
            for f in sorted(filenames):
                if _skip_name(f) or f.startswith("."):
                    continue
                full = Path(dirpath) / f
                if full.is_file():
                    yield os.path.relpath(full, root), full

    # ------------------------------------------------------------ sync
    def _claim(self) -> None:
        """One twin, one Doublecast. Two vaults writing one twin feed each other's files back as new."""
        import secrets

        owner = self.state.setdefault("owner", secrets.token_hex(8))
        marker = self.twin / MARKER
        if marker.exists():
            if marker.read_text(encoding="utf-8").strip() != owner:
                raise RuntimeError(
                    f"{self.twin} is kept by another Doublecast (another computer, vault or workspace). "
                    "Stop that one, or give this mirror a different twin folder (--to)."
                )
            return
        if any(self._walk(self.twin)):
            raise RuntimeError(f"{self.twin} already has files in it. Give the twin an empty or new folder.")
        marker.write_text(owner, encoding="utf-8")

    def sync(self, accept: bool = False) -> Report:
        with _SYNC_LOCK:
            report = Report()
            self.twin.mkdir(parents=True, exist_ok=True)
            self._claim()
            first = not self.state.get("last_sync")
            self._pull(report)
            self._push(report, adopt_new=not first, accept=accept)
            self._write_note(report)
            self.last_sync = dt.datetime.now().strftime("%H:%M:%S")
            self.state["last_sync"] = self.last_sync
            self._save()
            self.engine.activity.flush()
            self.last_report = report
            return report

    def _pull(self, report: Report) -> None:
        """Real -> twin."""
        files = self.state["files"]
        saved = time.monotonic()
        for real_rel, real in self._walk(self.src):
            if time.monotonic() - saved > 10:  # a long first sync can be interrupted and resumed
                self._save()
                saved = time.monotonic()
            ext = real.suffix.lower()
            if ext not in SCRAMBLED or (ext in TEXT_EXTENSIONS and real.stat().st_size > MAX_TEXT_BYTES):
                key = ext or "(no extension)"
                report.skipped[key] = report.skipped.get(key, 0) + 1
                continue
            entry = files.get(real_rel)
            sig = _sig(real)
            twin_path = self.twin / entry["twin"] if entry else None
            if entry and entry["sig"] == sig and twin_path.exists():
                continue
            if entry and twin_path.exists() and entry.get("hash") and _sha(twin_path) != entry["hash"]:
                # the AI changed the twin and you changed the real file: keep the AI's version next to yours
                if entry.get("kind") == "scrambled" and ext in RESTORABLE:
                    self._restore_to(twin_path, self._side_name(real), report, conflict=True)
            twin_rel = entry["twin"] if entry else self._twin_name_for(real_rel)
            target = self.twin / twin_rel
            try:
                stats = self._atomic(lambda tmp, src=real: scramble_file(self.engine, src, tmp)[1], target)
            except Exception:  # noqa: BLE001 - one bad file must not stop the mirror
                report.failed += 1
                continue
            report.values += sum(stats.values())
            report.scrambled += 1
            model = self._model_check(real, target, twin_rel, report) if ext == ".xlsx" else None
            files[real_rel] = {
                "twin": twin_rel,
                "sig": sig,
                "hash": _sha(target),
                "kind": "derived" if ext == ".pdf" else "scrambled",
            }
            if model:
                files[real_rel]["model"] = model

    def _model_check(self, real: Path, target: Path, twin_rel: str, report: Report) -> list | None:
        """Fill in formula results in the twin, and check the model still adds up."""
        from .files.recalc import check_model, find_soffice, has_formulas, recalc

        try:
            if not has_formulas(real):
                return None
            if not find_soffice() or not recalc(target):
                report.not_recalculated += 1
                return None
            compared, off = check_model(real, target, float(self.engine.numbers.k_money))
        except Exception:  # noqa: BLE001
            report.not_recalculated += 1
            return None
        if off:
            report.models_off.append(twin_rel)
        else:
            report.models_ok += 1
        return [compared, off]

    def _push(self, report: Report, adopt_new: bool = True, accept: bool = False) -> None:
        """Twin -> real: the AI's edits and new files.

        Until a first sync has finished, unknown files in the twin are leftovers of an interrupted
        run, not the AI's work, so they are not copied back. More than MAX_BRING_BACK changes at
        once are held until accepted."""
        files = self.state["files"]
        by_twin = {e["twin"]: k for k, e in files.items()}
        ignored = set(self.state.get("ignored", []))
        pending = []
        for twin_rel, twin_path in self._walk(self.twin):
            entry = files.get(by_twin.get(twin_rel, ""), {})
            if twin_rel in ignored or (entry and entry.get("kind") == "derived"):
                continue
            if not entry and not adopt_new:
                continue
            if _sha(twin_path) != entry.get("hash"):
                pending.append(twin_rel)
        if len(pending) > MAX_BRING_BACK and not accept:
            report.held = len(pending)
            return
        for twin_rel, twin_path in self._walk(self.twin):
            real_rel = by_twin.get(twin_rel)
            h = _sha(twin_path)
            if real_rel is not None:
                entry = files[real_rel]
                if h == entry.get("hash") or entry.get("kind") == "derived":
                    continue
                real = self.src / real_rel
                if real.exists() and _sig(real) != entry["sig"]:
                    continue  # you changed it too; _pull handles that next round
                if not self._restore_to(twin_path, real, report):
                    continue
                entry["hash"], entry["sig"] = h, _sig(real)
                continue
            ignored = self.state.setdefault("ignored", [])
            if twin_rel in ignored:
                continue
            if not adopt_new:
                ignored.append(twin_rel)
                continue
            # a file the AI created
            folder, name = os.path.split(twin_rel)
            real_rel = os.path.join(self._real_dir(folder), self._restore_name(name, is_file=True))
            real = self.src / real_rel
            if real.exists():
                real = self._side_name(real)
                real_rel = os.path.relpath(real, self.src)
            if not self._restore_to(twin_path, real, report):
                continue
            files[real_rel] = {"twin": twin_rel, "sig": _sig(real), "hash": h, "kind": "scrambled"}

    def _restore_to(self, twin_path: Path, real: Path, report: Report, conflict: bool = False) -> bool:
        real.parent.mkdir(parents=True, exist_ok=True)
        if real.exists():  # keep the version being replaced, outside the folder
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.state_path.parent / "backups" / self.state_path.stem / stamp / real.relative_to(self.src)
            try:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(real, backup)
            except OSError:
                report.failed += 1
                return False  # no backup, no overwrite
        try:
            if twin_path.suffix.lower() in RESTORABLE:
                self._atomic(lambda tmp: restore_file(self.engine, twin_path, tmp), real)
            else:
                self._atomic(lambda tmp: shutil.copyfile(twin_path, tmp), real)
        except Exception:  # noqa: BLE001
            report.failed += 1
            return False
        if conflict:
            report.conflicts += 1
        else:
            report.restored += 1
        return True

    @staticmethod
    def _side_name(real: Path) -> Path:
        candidate = real.with_name(f"{real.stem} (AI){real.suffix}")
        n = 2
        while candidate.exists():
            candidate = real.with_name(f"{real.stem} (AI {n}){real.suffix}")
            n += 1
        return candidate

    @staticmethod
    def _atomic(write, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.stem}.dc-tmp{target.suffix}")
        try:
            out = write(tmp)
            os.replace(tmp, target)
            return out
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _write_note(self, report: Report) -> None:
        skipped = sum(report.skipped.values())
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(report.skipped.items(), key=lambda kv: -kv[1]))
        text = (
            "# This folder is a Doublecast twin\n\n"
            "Names of people and companies, emails, phones, IBANs, tax numbers and addresses in these files are\n"
            "realistic stand-ins, and money amounts are scaled by a secret factor (ratios, margins and rankings\n"
            "stay correct). Work with them as they are; do not try to guess the real values.\n\n"
            "Files you create or edit here are copied back to the owner's real folder with the real values restored.\n"
            "PDFs appear as `.pdf.md` text and are read-only.\n"
        )
        if skipped:
            text += f"\n{skipped} file(s) were not copied because they cannot be scrambled ({kinds}).\n"
        off = sorted(e["twin"] for e in self.state["files"].values() if (e.get("model") or [0, 0])[1])
        if off:
            text += (
                "\n**Do not rely on the figures in these spreadsheets.** After scrambling, some formula results\n"
                "no longer match the original model:\n\n" + "".join(f"- `{x}`\n" for x in off)
            )
        if report.not_recalculated:
            text += (
                f"\n{report.not_recalculated} spreadsheet model(s) could not be recalculated (LibreOffice is not "
                "installed): formula cells hold formulas without results. Open them with a tool that recalculates.\n"
            )
        path = self.twin / NOTE
        try:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def watch(self, interval: float = 3.0, stop: threading.Event | None = None, on_sync=None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                report = self.sync()
                self.error = None
                if on_sync:
                    on_sync(self, report)
            except Exception as exc:  # noqa: BLE001 - keep watching, show why in the menu
                self.error = str(exc)
            stop.wait(interval)


# ---------------------------------------------------------------- registry
def _registry_path(home: Path) -> Path:
    return home / "mirrors.json"


def registered(home: Path) -> list[dict]:
    try:
        return json.loads(_registry_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def register(home: Path, src: Path, twin: Path, workspace: str = "default") -> None:
    items = [m for m in registered(home) if m["src"] != str(src)]
    items.append({"src": str(src), "twin": str(twin), "workspace": workspace})
    _registry_path(home).parent.mkdir(parents=True, exist_ok=True)
    _registry_path(home).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def unregister(home: Path, src: Path) -> bool:
    items = registered(home)
    keep = [m for m in items if m["src"] != str(Path(src).expanduser().resolve())]
    _registry_path(home).write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(keep) != len(items)


def run_all(engine, interval: float = 3.0, stop: threading.Event | None = None) -> list[Mirror]:
    """Start every registered mirror in a background thread (used by the tray)."""
    mirrors = []
    for m in registered(engine.config.home):
        if m.get("workspace", "default") != engine.config.workspace:
            continue
        try:
            mirror = Mirror(engine, Path(m["src"]), Path(m["twin"]))
        except (FileNotFoundError, ValueError):
            continue
        threading.Thread(target=mirror.watch, kwargs={"interval": interval, "stop": stop}, daemon=True).start()
        mirrors.append(mirror)
    return mirrors
