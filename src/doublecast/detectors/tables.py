"""Tables pasted as text: CSV rows and Markdown tables.

A column headed "Customer", "Επαφή", "ΑΦΜ" or "nif_cif" says what every cell
below it is, so each cell is swapped whole, exactly as in a spreadsheet, even
when the value alone (a 9-digit number, a one-word company name) gives
nothing away.
"""

from __future__ import annotations

import re

from ..textnorm import fold
from .base import Span

_CELL_CATEGORIES = {"ORG", "PERSON", "PRODUCT", "SITE", "PROJECT", "ADDRESS", "TAX_ID", "PHONE", "IBAN", "ID"}
_LINE = re.compile(r"^[^\n]*", re.M)


def _cells(line: str, delim: str) -> list[tuple[int, int]]:
    """(start, end) of each cell's content, quotes and padding excluded."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(line)
    while i <= n:
        start = i
        if i < n and line[i] == '"':
            j = i + 1
            while j < n:
                if line[j] == '"' and (j + 1 >= n or line[j + 1] != '"'):
                    break
                j += 2 if line[j] == '"' else 1
            out.append((i + 1, min(j, n)))
            k = line.find(delim, j)
            i = (k + 1) if k >= 0 else n + 1
            continue
        k = line.find(delim, i)
        end = k if k >= 0 else n
        a, b = start, end
        while a < b and line[a] in " \t":
            a += 1
        while b > a and line[b - 1] in " \t":
            b -= 1
        out.append((a, b))
        i = end + 1
    return out


def _delimiter(line: str) -> str | None:
    s = line.strip()
    if s.startswith("|") and s.count("|") >= 3:
        return "|"
    for d in (";", "\t", ","):
        if line.count(d) >= 2:
            return d
    return None


def detect_tables(text: str) -> list[Span]:
    from ..discover.profiler import PLACEHOLDERS, classify_header

    lines = [(m.start(), m.group(0)) for m in _LINE.finditer(text)]
    spans: list[Span] = []
    i = 0
    while i < len(lines):
        start, line = lines[i]
        delim = _delimiter(line)
        if not delim:
            i += 1
            continue
        header_cells = _cells(line, delim)
        if delim == "|":
            header_cells = header_cells[1:-1]
        headers = [line[a:b] for a, b in header_cells]
        if len(headers) < 2 or sum(1 for h in headers if re.search(r"\d", h)) > len(headers) / 2:
            i += 1
            continue
        cats = []
        for h in headers:
            cat, _, is_code = classify_header(h)
            cats.append("ID" if is_code and cat in ("ORG", "PERSON", "PRODUCT", "SITE") else cat)
        j = i + 1
        rows = 0
        while j < len(lines) and _delimiter(lines[j][1]) == delim:
            row_start, row = lines[j]
            if delim == "|" and set(row.strip()) <= set("|-: "):
                j += 1
                continue  # the |---|---| rule
            cells = _cells(row, delim)
            if delim == "|":
                cells = cells[1:-1]
            for (a, b), cat in zip(cells, cats, strict=False):
                value = row[a:b]
                if cat not in _CELL_CATEGORIES or not value.strip() or fold(value.strip()) in PLACEHOLDERS:
                    continue
                if cat in ("ORG", "PERSON", "PRODUCT", "SITE", "PROJECT") and not re.search(r"[^\W\d_]", value):
                    continue  # a number in a name column is not a name
                if cat in ("TAX_ID", "PHONE", "IBAN", "ID") and not re.search(r"\d", value):
                    continue
                spans.append(
                    Span(row_start + a, row_start + b, cat, value, "column", kind="table_cell", meta={"strong": False})
                )
            rows += 1
            j += 1
        i = j if rows else i + 1
    return spans
