"""Word: swap text in place while keeping run formatting where possible.

A swap that falls inside one formatted run keeps that run's formatting.
A swap that spans several runs (e.g. a name half in bold) merges those
runs into the first one. Body, tables (including nested), headers and
footers are processed.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from ..engine import Engine


def _paragraphs(container):
    for p in container.paragraphs:
        yield p
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def _all_paragraphs(doc):
    yield from _paragraphs(doc)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            try:
                yield from _paragraphs(part)
            except Exception:  # some sections lack these parts
                continue


def _apply_to_runs(paragraph, replacements: list[tuple[int, int, str]]) -> None:
    runs = list(paragraph.runs)
    if not runs:
        return
    # process right-to-left so earlier offsets stay valid
    for start, end, new in sorted(replacements, key=lambda r: r[0], reverse=True):
        bounds, pos = [], 0
        for r in runs:
            bounds.append((pos, pos + len(r.text)))
            pos += len(r.text)
        first = next((i for i, (s, e) in enumerate(bounds) if s <= start < e), None)
        last = next((i for i, (s, e) in enumerate(bounds) if s < end <= e), None)
        if first is None or last is None:
            continue
        if first != last:
            merged = "".join(runs[i].text for i in range(first, last + 1))
            runs[first].text = merged
            for i in range(first + 1, last + 1):
                runs[i].text = ""
            bounds[first] = (bounds[first][0], bounds[last][1])
        rs = bounds[first][0]
        t = runs[first].text
        runs[first].text = t[: start - rs] + new + t[end - rs :]


def process_docx(engine: Engine, src: Path, dst: Path, direction: str):
    doc = Document(str(src))
    counts: dict[str, int] = {}
    warnings: list[str] = []
    seen = set()
    for p in _all_paragraphs(doc):
        if id(p._p) in seen:  # noqa: SLF001 - merged table cells repeat paragraphs
            continue
        seen.add(id(p._p))  # noqa: SLF001
        text = "".join(r.text for r in p.runs)
        if not text.strip():
            continue
        if direction == "scramble":
            reps, spans, _ = engine.plan(text)
            for s in spans:
                counts[s.category] = counts.get(s.category, 0) + 1
        else:
            reps = engine.restore_plan(text)
        if reps:
            _apply_to_runs(p, reps)
    core = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "comments"):
        value = getattr(core, attr, None)
        if value:
            new = engine.scramble(value).text if direction == "scramble" else engine.restore(value)
            setattr(core, attr, new)
    doc.save(str(dst))
    return counts, warnings
