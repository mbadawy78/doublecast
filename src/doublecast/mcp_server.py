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
    "Doublecast protects sensitive business data. Use read_scrambled to read local files: "
    "you will see realistic stand-ins (fake company names, people, IDs, and money scaled by a secret "
    "factor, so ratios are correct but absolute amounts are not real). Work with the stand-ins as if they "
    "were real. To save results, call write_restored: real values are restored on the user's machine. "
    "Never ask the user for the real values."
)


def _engine() -> Engine:
    return Engine(load_config())


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
