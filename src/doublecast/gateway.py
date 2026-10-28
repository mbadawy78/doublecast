"""Folders through Doublecast: the AI browses your folders without a copy and without seeing them.

You do not give the AI the folder. You allow it here once (`doublecast allow ~/Downloads`), then
name it in the chat. The AI asks Doublecast, which

* finds the folder by name inside the allowed places,
* lists it with file and folder names scrambled,
* opens a file scrambled as it is read (nothing is written to disk),
* saves what the AI writes with the real values put back, backing up anything it replaces.

Nothing outside the allowed places can be reached, and nothing is copied.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .files import TEXT_EXTENSIONS, read_exact, scramble_file

READABLE = {".xlsx", ".xlsm", ".docx", ".csv", ".tsv", ".pdf"} | TEXT_EXTENSIONS
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store", ".Trash"}
PAGE = 20_000  # characters per read (chat apps cap a tool result); the rest comes with offset
_BAD = re.compile(r'[\\/:*?"<>|\n\r\t]')


# ---------------------------------------------------------------- allowed places
def _allowed_path(home: Path) -> Path:
    return home / "allowed.json"


def allowed(home: Path) -> list[Path]:
    try:
        return [Path(p) for p in json.loads(_allowed_path(home).read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        return []


def allow(home: Path, folder: Path) -> Path:
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if folder == Path(folder.anchor) or folder == Path.home():
        raise ValueError("Allow specific places (Downloads, Documents, a project), not the whole disk or home folder")
    items = [p for p in allowed(home) if p != folder]
    items.append(folder)
    home.mkdir(parents=True, exist_ok=True)
    _allowed_path(home).write_text(json.dumps([str(p) for p in items], indent=1), encoding="utf-8")
    return folder


def disallow(home: Path, folder: Path) -> bool:
    folder = Path(folder).expanduser().resolve()
    items = allowed(home)
    keep = [p for p in items if p != folder]
    _allowed_path(home).write_text(json.dumps([str(p) for p in keep], indent=1), encoding="utf-8")
    return len(keep) != len(items)


# ---------------------------------------------------------------- the gateway
class Gateway:
    def __init__(self, engine, roots: list[Path] | None = None):
        self.engine = engine
        self.roots = [Path(r).resolve() for r in (roots if roots is not None else allowed(engine.config.home))]
        self._shown: dict[str, Path] = {}  # what the AI was shown -> the real path

    # ------------------------------------------------------------ names
    def _scramble_name(self, name: str, is_file: bool) -> str:
        stem, ext = os.path.splitext(name) if is_file else (name, "")
        spaced = stem.replace("_", " ")
        new = self.engine.scramble(spaced).text
        if "_" in stem and " " not in stem:
            new = new.replace(" ", "_")
        return (_BAD.sub("-", new).strip() or stem) + ext

    def _restore_name(self, name: str) -> str:
        stem, ext = os.path.splitext(name)
        spaced = stem.replace("_", " ")
        new = self.engine.restore(spaced)
        if "_" in stem and " " not in stem:
            new = new.replace(" ", "_")
        return (_BAD.sub("-", new).strip() or stem) + ext

    def _inside(self, path: Path) -> bool:
        path = path.resolve()
        return any(path == r or r in path.parents for r in self.roots)

    def _check(self, path: Path) -> Path:
        if not self.roots:
            raise PermissionError("No folders are allowed yet. The user can run: doublecast allow ~/Downloads")
        if not self._inside(path):
            raise PermissionError("That place is not one the user allowed for Doublecast.")
        return path

    def _show(self, real: Path, base_shown: str, base_real: Path) -> str:
        rel = real.relative_to(base_real)
        parts = [
            self._scramble_name(p, is_file=(i == len(rel.parts) - 1 and real.is_file()))
            for i, p in enumerate(rel.parts)
        ]
        shown = "/".join([base_shown, *parts]) if parts else base_shown
        self._shown[shown] = real
        return shown

    def resolve(self, path: str) -> Path:
        """A path as the AI wrote it -> the real path (it may be one Doublecast showed, or a real one)."""
        path = path.strip().rstrip("/")
        if path in self._shown:
            return self._check(self._shown[path])
        # the longest shown prefix, then restore the rest by name
        best = max((s for s in self._shown if path.startswith(s + "/")), key=len, default=None)
        if best:
            rest = path[len(best) + 1 :].split("/")
            real = self._shown[best].joinpath(*[self._restore_name(p) for p in rest])
            return self._check(real)
        p = Path(path).expanduser()
        if p.is_absolute():
            return self._check(p.resolve())
        hits = self.find(path, quiet=True)
        if len(hits) == 1:
            return self._check(hits[0])
        if not hits:
            raise FileNotFoundError(f"Nothing called '{path}' in the allowed places.")
        raise FileNotFoundError(f"'{path}' matches {len(hits)} folders; use list_folders to pick one.")

    # ------------------------------------------------------------ tools
    def find(self, name: str, quiet: bool = False, depth: int = 4) -> list[Path]:
        """Folders in the allowed places whose name matches (the user typed the real name)."""
        want = name.strip().strip("/").lower()
        hits: list[Path] = []
        for root in self.roots:
            if root.name.lower() == want:
                hits.append(root)
            base = len(root.parts)
            for dirpath, dirnames, _ in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
                if len(Path(dirpath).parts) - base >= depth:
                    dirnames[:] = []
                for d in dirnames:
                    if d.lower() == want:
                        hits.append(Path(dirpath) / d)
        return hits

    def list_folder(self, path: str, depth: int = 1) -> str:
        real = self.resolve(path)
        if not real.is_dir():
            raise NotADirectoryError("That is a file; use read_file.")
        shown_base = path.strip().rstrip("/")
        self._shown.setdefault(shown_base, real)
        lines, skipped = [], 0
        base = len(real.parts)
        for dirpath, dirnames, filenames in os.walk(real):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP and not d.startswith("."))
            level = len(Path(dirpath).parts) - base
            if level >= depth:
                dirnames[:] = []
            for d in dirnames:
                lines.append(self._show(Path(dirpath) / d, shown_base, real) + "/")
            for f in sorted(filenames):
                if f.startswith(".") or f.startswith("~$"):
                    continue
                full = Path(dirpath) / f
                if full.suffix.lower() not in READABLE:
                    skipped += 1
                    continue
                size = full.stat().st_size
                lines.append(f"{self._show(full, shown_base, real)}  ({_size(size)})")
        out = "\n".join(lines) or "(empty)"
        if skipped:
            out += f"\n\n{skipped} other file(s) (photos, videos, archives...) are not shown: Doublecast cannot scramble them."
        return out

    def search(self, path: str, text: str, limit: int = 30) -> str:
        """Files under a folder whose name or text contains `text` (the AI may write a stand-in)."""
        real = self.resolve(path)
        shown_base = path.strip().rstrip("/")
        self._shown.setdefault(shown_base, real)
        needle = self.engine.restore(text).lower()
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(real):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP and not d.startswith("."))
            for f in sorted(filenames):
                full = Path(dirpath) / f
                ext = full.suffix.lower()
                if ext not in READABLE or f.startswith((".", "~$")):
                    continue
                hit = needle in f.lower()
                snippet = ""
                if not hit and (ext in TEXT_EXTENSIONS or ext in (".csv", ".tsv")) and full.stat().st_size < 20_000_000:
                    try:
                        for line in read_exact(full).splitlines():
                            if needle in line.lower():
                                hit, snippet = True, self.engine.scramble(line.strip()[:200]).text
                                break
                    except (UnicodeDecodeError, OSError):
                        continue
                if hit:
                    out.append(self._show(full, shown_base, real) + (f"\n    {snippet}" if snippet else ""))
                    if len(out) >= limit:
                        return "\n".join(out) + f"\n(first {limit} matches)"
        return "\n".join(out) or "No matches."

    def read(self, path: str, offset: int = 0) -> str:
        real = self.resolve(path)
        if real.is_dir():
            return self.list_folder(path)
        ext = real.suffix.lower()
        if ext not in READABLE:
            raise ValueError(f"Doublecast cannot scramble {ext} files, so it will not open them.")
        with tempfile.TemporaryDirectory(prefix="dc-read-") as tmp:
            dst = Path(tmp) / ("doc" + (".md" if ext == ".pdf" else ext))
            scramble_file(self.engine, real, dst)
            text = _text_of(dst, self.engine)
        self.engine.check_and_log_leaks(text, str(real))  # the alarm: a known name that got through
        self.engine.activity.flush()
        page = text[offset : offset + PAGE]
        if offset + PAGE < len(text):
            page += f"\n\n[... {len(text) - offset - PAGE:,} more characters: call read_file again with offset={offset + PAGE}]"
        return page

    def write(self, path: str, content: str, overwrite: bool = False) -> str:
        real = self.resolve(path) if path.strip().rstrip("/") in self._shown else self._resolve_new(path)
        ext = real.suffix.lower()
        if ext not in TEXT_EXTENSIONS | {".csv", ".tsv"}:
            raise ValueError(
                "Write text formats (.md, .txt, .csv, .html, .json...). For tables use .csv, for documents .md."
            )
        if real.exists() and not overwrite:
            raise FileExistsError("That file exists. Call again with overwrite=true to replace it (a backup is kept).")
        self._backup(real)
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(self.engine.restore(content), encoding="utf-8")
        return "Saved, with the real values put back, in the user's folder."

    def _resolve_new(self, path: str) -> Path:
        folder, _, name = path.strip().rstrip("/").rpartition("/")
        base = self.resolve(folder) if folder else None
        if base is None or not base.is_dir():
            raise FileNotFoundError("Save into a folder Doublecast showed you (use list_folder first).")
        return self._check(base / self._restore_name(name))

    def _backup(self, real: Path) -> None:
        if not real.exists():
            return
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = self.engine.config.home / "backups" / stamp / real.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real, dst)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _text_of(path: Path, engine) -> str:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _sheet_text(path)
    if ext == ".docx":
        from docx import Document

        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for t in doc.tables:
            for row in t.rows:
                parts.append("\t".join(c.text for c in row.cells))
        return "\n".join(parts)
    return read_exact(path)


def _sheet_text(path: Path) -> str:
    """Values, with formula results filled in when LibreOffice is there (otherwise the formulas)."""
    from openpyxl import load_workbook

    from .files.recalc import recalc

    note = ""
    if path.suffix.lower() == ".xlsx" and recalc(path):
        wb = load_workbook(path, data_only=True)
    else:
        wb = load_workbook(path, data_only=False)
        note = "(Formula results are not shown: LibreOffice is not installed. Cells starting with = are formulas.)\n"
    out = [note] if note else []
    for ws in wb.worksheets:
        out.append(f"## Sheet: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if any(v is not None for v in row):
                out.append(f"{i}\t" + "\t".join("" if v is None else _cell(v) for v in row))
    return "\n".join(out)


def _cell(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}" if abs(v) < 1e15 else str(v)
    return str(v)
