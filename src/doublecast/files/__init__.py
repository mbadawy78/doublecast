"""Scramble and restore whole files, keeping their format.

Supported: .xlsx/.xlsm, .docx, .csv/.tsv, text files (.txt .md .json .xml
.html .eml .log .yaml ...), and .pdf (text is extracted and written out as
Markdown, because a PDF cannot be safely rewritten in place).
"""

from __future__ import annotations

from pathlib import Path

from ..engine import Engine

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".xml",
    ".html",
    ".htm",
    ".eml",
    ".log",
    ".yaml",
    ".yml",
    ".ini",
    ".toml",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".cs",
    ".rtf",
    ".srt",
    ".vtt",
}


def default_output(path: Path, direction: str) -> Path:
    suffix = path.suffix.lower()
    stem = path.stem
    for tag in (".doublecast", ".restored"):
        if stem.endswith(tag):
            stem = stem[: -len(tag)]
    tag = ".doublecast" if direction == "scramble" else ".restored"
    if suffix == ".pdf" and direction == "scramble":
        return path.with_name(f"{stem}{tag}.md")
    return path.with_name(f"{stem}{tag}{path.suffix}")


def scramble_file(engine: Engine, src: Path, dst: Path | None = None) -> tuple[Path, dict[str, int], list[str]]:
    return _run(engine, Path(src), dst, "scramble")


def restore_file(engine: Engine, src: Path, dst: Path | None = None) -> tuple[Path, dict[str, int], list[str]]:
    return _run(engine, Path(src), dst, "restore")


def _run(engine: Engine, src: Path, dst: Path | None, direction: str):
    if not src.exists():
        raise FileNotFoundError(src)
    dst = Path(dst) if dst else default_output(src, direction)
    ext = src.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from .xlsx import process_xlsx

        stats, warnings = process_xlsx(engine, src, dst, direction)
    elif ext == ".docx":
        from .docx_file import process_docx

        stats, warnings = process_docx(engine, src, dst, direction)
    elif ext in (".csv", ".tsv"):
        from .csv_file import process_csv

        stats, warnings = process_csv(engine, src, dst, direction)
    elif ext == ".pdf":
        if direction != "scramble":
            raise ValueError("A PDF is scrambled to Markdown; restore the .md file instead")
        from .pdf_file import process_pdf

        stats, warnings = process_pdf(engine, src, dst)
    elif ext in TEXT_EXTENSIONS or _looks_textual(src):
        stats, warnings = _process_text(engine, src, dst, direction)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Try saving it as .docx, .xlsx, .csv or .txt")
    return dst, stats, warnings


def _looks_textual(path: Path) -> bool:
    try:
        read_exact(path)[:2000]
        return True
    except (UnicodeDecodeError, OSError):
        return False


def read_exact(path: Path) -> str:
    """Read text without translating line endings (keeps CRLF files CRLF)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write_exact(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _process_text(engine: Engine, src: Path, dst: Path, direction: str):
    text = read_exact(src)
    if direction == "scramble":
        result = engine.scramble(text)
        write_exact(dst, result.text)
        return result.summary(), result.warnings
    write_exact(dst, engine.restore(text))
    return {}, []
