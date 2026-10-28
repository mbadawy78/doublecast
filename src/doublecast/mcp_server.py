"""MCP server: let AI agents read your files without seeing the real values.

Design rule: no tool ever hands a real value to the model.

* read_scrambled(path)      -> the file's content, with stand-ins
* make_scrambled_copy(path) -> writes a scrambled copy next to the file
* write_restored(path, ...) -> the agent writes text with stand-ins; real
                               values are put back on disk, locally
* restore_file(path)        -> restores a scrambled file into a new local copy
* vault_stats()             -> counts per category, no values

There is deliberately no "restore_text" tool: it would send real values
straight back to the model, defeating the purpose.

Register with Claude Code:
    claude mcp add doublecast -- doublecast mcp
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .config import load_config
from .engine import Engine
from .files import TEXT_EXTENSIONS, restore_file, scramble_file

INSTRUCTIONS = (
    'Doublecast protects sensitive business data. When the user names a folder or file ("use Doublecast on '
    'Trio bakery"), use list_folder, search_folder and read_file: names and contents come back scrambled, '
    "and nothing is copied. Use the paths exactly as list_folder shows them. Save results with save_file. "
    "Never use other file tools on the user's folders. After every answer built on data from Doublecast "
    "(folders or a connector such as Power BI), call show_answer with that answer in Markdown so the user "
    "sees it with the real values. Use read_scrambled to read other local files: "
    "you will see realistic stand-ins (fake company names, people, IDs, and money scaled by a secret "
    "factor, so ratios are correct but absolute amounts are not real). Work with the stand-ins as if they "
    "were real. To save results, call write_restored: real values are restored on the user's machine. "
    "Never ask the user for the real values."
)


def _engine() -> Engine:
    engine = Engine(load_config())
    engine.activity.source = "mcp"
    return engine


def _text_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, data_only=False)
        out = []
        for ws in wb.worksheets:
            out.append(f"## Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                if any(v is not None for v in row):
                    out.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(out)
    if ext == ".docx":
        from docx import Document

        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for t in doc.tables:
            for row in t.rows:
                parts.append("\t".join(c.text for c in row.cells))
        return "\n".join(parts)
    from .files import read_exact

    return read_exact(path)


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:  # pragma: no cover
        from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x

    server = Server("doublecast", instructions=INSTRUCTIONS)
    engine = _engine()

    from .gateway import Gateway, allowed

    gate = Gateway(engine)

    def _safe(fn, *a, **kw) -> str:
        gate.roots = [r.resolve() for r in allowed(engine.config.home)]  # pick up `doublecast allow` live
        try:
            return fn(*a, **kw)
        except (PermissionError, FileNotFoundError, FileExistsError, NotADirectoryError, ValueError) as exc:
            return f"Refused: {exc}"

    @server.tool()
    def list_folder(path: str, depth: int = 1) -> str:
        """List a folder the user named (e.g. "Trio bakery"), with scrambled file and folder names.
        depth=2 or 3 shows subfolders too. Use the returned paths with read_file."""
        return _safe(gate.list_folder, path, depth)

    @server.tool()
    def search_folder(path: str, text: str) -> str:
        """Find files under a folder whose name or text contains `text`. Results are scrambled."""
        return _safe(gate.search, path, text)

    @server.tool()
    def read_file(path: str, offset: int = 0) -> str:
        """Read a file from list_folder or search_folder, scrambled as it is read (Excel shows each sheet with
        row numbers and formula results). Long files come in pages: call again with the offset it gives."""
        return _safe(gate.read, path, offset)

    @server.tool()
    def save_file(path: str, content: str, overwrite: bool = False) -> str:
        """Save text (md, txt, csv, html, json...) into a folder list_folder showed you, e.g.
        "Trio bakery/IT/summary.md". Real values are put back on the user's computer; replaced files are
        backed up."""
        return _safe(gate.write, path, content, overwrite)

    @server.tool()
    def show_answer(markdown: str, title: str = "") -> str:
        """Show the user your answer with the real names and amounts. Call this after every answer that
        uses data from Doublecast (folders or a connector such as Power BI): pass the answer as Markdown,
        exactly as you wrote it. It opens in the user's browser with the real values; you only get a
        confirmation."""
        from .answers import CONFIRMATION
        from .answers import show_answer as _show

        _show(engine, markdown, title)
        return CONFIRMATION

    @server.tool()
    def read_scrambled(path: str) -> str:
        """Read a local file (txt, md, csv, xlsx, docx, pdf, json...) with sensitive values replaced by stand-ins."""
        src = Path(path).expanduser().resolve()
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / (src.stem + (".md" if src.suffix.lower() == ".pdf" else src.suffix))
            scramble_file(engine, src, dst)
            return _text_of(dst)

    @server.tool()
    def make_scrambled_copy(path: str) -> str:
        """Write a scrambled copy of a local file next to it (for uploading elsewhere). Returns the new path."""
        dst, counts, warnings = scramble_file(engine, Path(path).expanduser().resolve())
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nothing sensitive found"
        return f"Wrote {dst} ({summary}). " + " ".join(warnings)

    @server.tool()
    def write_restored(path: str, content: str, overwrite: bool = False) -> str:
        """Write text to a local file after putting the real values back (text formats only)."""
        dst = Path(path).expanduser().resolve()
        if dst.suffix.lower() not in TEXT_EXTENSIONS | {".csv", ".tsv"}:
            return f"Refused: {dst.suffix} is not a text format. Write a .md/.txt/.csv file instead."
        if dst.exists() and not overwrite:
            return f"Refused: {dst} exists. Call again with overwrite=true to replace it."
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(engine.restore(content), encoding="utf-8")
        return f"Wrote {dst} with real values restored locally."

    @server.tool()
    def restore_file_copy(path: str) -> str:
        """Restore a scrambled file (xlsx, docx, csv, text) into a new local copy. Returns the new path only."""
        dst, _, _ = restore_file(engine, Path(path).expanduser().resolve())
        return f"Wrote {dst}."

    @server.tool()
    def vault_stats() -> str:
        """How many values of each kind are protected in this workspace (no values are shown)."""
        stats = engine.vault.stats()
        return ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "Vault is empty."

    return server


def main() -> None:
    build_server().run("stdio")
