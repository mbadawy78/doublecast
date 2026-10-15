"""PDF: extract the text, scramble it, write Markdown.

A PDF's text lives in positioned fragments that cannot be reliably
rewritten, and leaving the original fragments in place would leak. So the
scrambled output is a clean Markdown file, one section per page. Scanned
PDFs (images only) have no text to extract; run OCR first.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from ..engine import Engine


def process_pdf(engine: Engine, src: Path, dst: Path):
    reader = PdfReader(str(src))
    parts = []
    empty_pages = 0
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            empty_pages += 1
        parts.append(f"## Page {i}\n\n{text.strip()}\n")
    full = "\n".join(parts)
    result = engine.scramble(full)
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        fh.write(result.text)
    warnings = list(result.warnings)
    if empty_pages:
        warnings.append(f"{empty_pages} page(s) had no extractable text (scanned images?). Run OCR first.")
    return result.summary(), warnings
