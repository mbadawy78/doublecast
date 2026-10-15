from __future__ import annotations

import csv
import io
from pathlib import Path

from ..engine import Engine
from ..numbers import parse_number
from .tabular import column_kind, scramble_cell


def process_csv(engine: Engine, src: Path, dst: Path, direction: str):
    with open(src, encoding="utf-8-sig", newline="") as fh:
        raw = fh.read()
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if src.suffix.lower() == ".tsv" else csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    counts: dict[str, int] = {}
    if not rows:
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            fh.write(raw)
        return counts, []
    default_decimal = "," if dialect.delimiter == ";" else "."
    kinds = {}
    for i, h in enumerate(rows[0]):
        k = column_kind(engine, h if direction == "scramble" else engine.restore(h))
        if k:
            kinds[i] = k
    nums = engine.numbers
    out_rows = []
    for r_idx, row in enumerate(rows):
        new_row = []
        for c_idx, value in enumerate(row):
            kind = kinds.get(c_idx) if r_idx > 0 else None
            token = value.strip()
            if kind and token and parse_number(token, engine.config.number_locale):
                factor = nums.k_money if kind == "money" else nums.k_qty
                if direction == "scramble":
                    new = nums.scale(token, factor, default_decimal)
                    label = "MONEY" if kind == "money" else "QUANTITY"
                    counts[label] = counts.get(label, 0) + 1
                else:
                    new = nums.unscale(token, factor, default_decimal)
                new_row.append(new if new is not None else value)
            elif value:
                if direction == "scramble":
                    header = rows[0][c_idx] if r_idx > 0 and c_idx < len(rows[0]) else None
                    new, found = scramble_cell(engine, header, value, src.stem)
                    new_row.append(new)
                    for k, n in found.items():
                        counts[k] = counts.get(k, 0) + n
                else:
                    new_row.append(engine.restore(value))
            else:
                new_row.append(value)
        out_rows.append(new_row)
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, dialect).writerows(out_rows)
    engine.flush_learned()
    return counts, []
