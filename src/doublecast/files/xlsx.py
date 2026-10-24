"""Excel: swap text cells, scale money columns, keep formulas working.

* Text cells go through the engine.
* Numeric cells are scaled when their column header names money
  ("Price", "Τιμή", "Umsatz"...) or their number format shows a currency.
* Formulas are left as they are: they recalculate from the scaled inputs
  when the file is opened, so totals stay consistent.
* Sheet names are swapped too (they often carry customer names).

openpyxl does not keep every Excel feature (some charts, images, pivot
caches). Always work on a copy; the original is never modified.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from openpyxl import load_workbook

from ..engine import Engine
from .tabular import column_kind, factor_for, row_kind, scale_value, scramble_cell

_CURRENCY_FMT = re.compile(r"[€$£]|EUR|USD|GBP|\[\$")
_BAD_TITLE = re.compile(r"[\[\]:*?/\\]")


def _header_row(ws) -> int | None:
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 6)):
        strings = sum(1 for c in row if isinstance(c.value, str) and c.value.strip())
        if strings >= 2:
            return row[0].row
    return None


def process_xlsx(engine: Engine, src: Path, dst: Path, direction: str):
    wb = load_workbook(src, keep_vba=src.suffix.lower() == ".xlsm")
    counts: dict[str, int] = {}
    warnings: list[str] = []
    delta = dt.timedelta(days=engine.vault.date_offset_days())
    for ws in wb.worksheets:
        # sheet title
        new_title = engine.scramble(ws.title).text if direction == "scramble" else engine.restore(ws.title)
        new_title = _BAD_TITLE.sub("-", new_title)[:31]
        if new_title != ws.title and new_title not in wb.sheetnames:
            ws.title = new_title

        header_row = _header_row(ws)
        kinds: dict[int, str] = {}
        headers: dict[int, object] = {}
        if header_row:
            for cell in ws[header_row]:
                headers[cell.column] = cell.value
                kind = column_kind(
                    engine, cell.value if direction == "scramble" else engine.restore(str(cell.value or ""))
                )
                if kind:
                    kinds[cell.column] = kind

        for row in ws.iter_rows():
            row_label = None
            for c in row:
                if isinstance(c.value, str) and c.value.strip() and not c.value.startswith("="):
                    row_label = c.value if direction == "scramble" else engine.restore(c.value)
                    break
            rkind = (
                row_kind(row_label)
                if row_label and not any(sp.category in ("ORG", "PERSON") for sp in engine.detect(row_label))
                else None
            )
            for cell in row:
                v = cell.value
                if v is None:
                    continue
                if isinstance(v, str):
                    if v.startswith("="):
                        continue
                    if direction == "scramble":
                        in_body = header_row and cell.row > header_row
                        new, found = scramble_cell(engine, headers.get(cell.column) if in_body else None, v, ws.title)
                        if found:
                            cell.value = new
                            for k, n in found.items():
                                counts[k] = counts.get(k, 0) + n
                    else:
                        cell.value = engine.restore(v)
                elif isinstance(v, bool):
                    continue
                elif isinstance(v, (int, float)):
                    if header_row and cell.row <= header_row:
                        continue
                    fmt = cell.number_format or ""
                    if "%" in fmt:
                        continue
                    kind = kinds.get(cell.column)
                    if kind is None and engine.config.scale_money and _CURRENCY_FMT.search(fmt):
                        kind = "money"
                    if rkind == "keep" or row_kind(headers.get(cell.column)) == "keep":
                        kind = None  # a switch, index, %, days, units, area: never scaled
                    elif (
                        rkind == "money"
                        and engine.config.scale_money
                        and not (header_row and cell.column == min(headers or {0: 0}))
                    ):
                        kind = kind or "money"  # "Cash at bank" under a "Value" or "2026" column
                    if kind and v == 1:
                        kind = None  # a scaled 1 would show the factor itself
                    if kind:
                        cell.value = scale_value(v, factor_for(engine, kind), direction)
                        if direction == "scramble":
                            label = "MONEY" if kind == "money" else "QUANTITY"
                            counts[label] = counts.get(label, 0) + 1
                    elif direction == "scramble" and isinstance(v, int) and abs(v) >= 10_000:
                        # long whole numbers may be IDs (ΑΦΜ, phone, account): check with the header as context
                        new, found = scramble_cell(engine, headers.get(cell.column), str(v), ws.title)
                        if not found and len(str(abs(v))) == 8:
                            # Excel drops leading zeros: 094014201 is stored as 94014201
                            new, found = scramble_cell(engine, headers.get(cell.column), str(v).zfill(9), ws.title)
                        if found:
                            cell.value = new  # stored as text, like most ID columns
                            cell.number_format = "@"
                            for k, n in found.items():
                                counts[k] = counts.get(k, 0) + n
                elif isinstance(v, (dt.date, dt.datetime)) and engine.config.shift_dates:
                    cell.value = v + delta if direction == "scramble" else v - delta
                    if direction == "scramble":
                        counts["DATE"] = counts.get("DATE", 0) + 1
    wb.save(dst)
    engine.flush_learned()
    if direction == "scramble" and any(ws._charts or ws._images for ws in wb.worksheets):  # noqa: SLF001
        warnings.append("Charts or images were found; check them in the scrambled copy.")
    return counts, warnings
