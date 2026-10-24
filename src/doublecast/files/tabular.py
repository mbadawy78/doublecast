"""Shared logic for spreadsheets: which columns hold money or quantities."""

from __future__ import annotations

import functools
import re

from ..engine import Engine
from ..restore import apply
from ..textnorm import fold


def column_kind(engine: Engine, header: object) -> str | None:
    if not isinstance(header, str):
        return None
    h = fold(header).strip()
    if not h:
        return None
    if "%" in h or any(w in h for w in ("percent", "ποσοστό", "rate", "ratio", "share", "μερίδιο")):
        return None
    if engine.config.scale_money and any(_word_in(word, h) for word in engine.money_headers):
        return "money"
    if engine.config.scale_quantities and any(_word_in(word, h) for word in engine.quantity_headers):
        return "quantity"
    return None


# Row labels in financial models ("Cost index", "Days to collect", "Rent per sq ft").
# Models keep money and non-money inputs in one "Value" column or under year columns,
# so the row's label decides. Scaling a switch or an index breaks the model and,
# worse, a scaled 1 shows the secret factor itself.
_KEEP = re.compile(  # never money, whatever else the label says
    r"%|\b(?:percent|ratio|share|growth|index|factor|switch|flag|scenario|version|multiple|elasticity|yield"
    r"|days?|months?|weeks?|years?|hours?|minutes?|age|term|dso|dpo|dio|lead time"
    r"|rate|margin|markup|discount)\b|\(\s*[01]\s*=|\b[01]\s*=\s*\w|\byes\b|\bno\b"
    r"|\b(?:ποσοστ|δεικτ|ημερ|μηνες|μηνων|ετη\b|περιθωρ|εκπτωσ)"
)
_MEASURE = re.compile(  # quantities: kept, unless the label is a price or cost of them ("Unit price")
    r"\b(?:sq ?ft|ft2|m2|sqm|area|units?|qty|quantity|volume|pieces|pcs|cases|pallets?|packs?|kg|tons?|tonnes?"
    r"|litres?|liters?|headcount|fte|count|number of|capacity|speed|shifts?|people|staff)\b"
    r"|\b(?:τεμαχ|ποσοτητ|ογκ|κιλα|κιλο|τονο|ατομ|βαρδι)"
)
_UNIT_MONEY = re.compile(r"\b(?:price|prices|cost|costs|rent|fees?)\b|\b(?:τιμ|κοστ|ενοικ)")
_MONEY = re.compile(
    r"[€$£]|\b(?:eur|usd|cad|gbp|chf|cost|costs|price|prices|rent|cash|revenue|revenues|sales|turnover|payroll|salary"
    r"|salaries|wages?|amount|budget|limit|balance|capex|opex|ebitda|ebit|profit|loss|expenses?|fees?|spend|investment"
    r"|loan|debt|payment|payments|income|value|fund|funding|equity|price list|tax|taxes|interest expense|insurance"
    r"|materials?|energy|freight|distribution|marketing|promotion|utilities|maintenance|depreciation|cogs|overheads?)\b"
    r"|\b(?:τιμ|κοστ|ενοικ|ταμει|πωλησ|εσοδ|μισθ|δαπαν|ποσο|κερδ|ζημι|δανει|επενδυσ)"
)
_PRICE = re.compile(r"\b(?:rate|price|cost|rent|fee)s?\b.*\bper\b|\bper\b.*\b(?:price|cost|rent)\b|[€$£]\s*/")


def row_kind(label: object) -> str | None:
    """'money', 'keep' or None (no opinion) for a model row, from its label."""
    if not isinstance(label, str):
        return None
    t = fold(label)
    if not t.strip():
        return None
    if _PRICE.search(t):
        return "money"  # "Rate per sq ft", "Cost per pack"
    if _KEEP.search(t):
        return "keep"
    if _MEASURE.search(t):
        return "money" if _UNIT_MONEY.search(t) else "keep"
    if _MONEY.search(t):
        return "money"
    return None


def _word_in(word: str, header: str) -> bool:
    if len(word) <= 3:
        return word in header.replace("(", " ").replace(")", " ").replace("/", " ").split()
    return word in header


def factor_for(engine: Engine, kind: str) -> float:
    return float(engine.numbers.k_money if kind == "money" else engine.numbers.k_qty)


def _decimals(value: float | int) -> int:
    if isinstance(value, int):
        return 0
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 6
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def _scramble_number(value: float | int, factor: float) -> float:
    # Always 6 decimals: with a fixed precision and a factor > 1 the mapping is
    # one-to-one for originals with up to 6 decimals, so restore is exact.
    # (The cell's number format still displays it as an ordinary amount.)
    return round(value * factor, 6)


def scale_value(value: float | int, factor: float, direction: str) -> float | int:
    """Scale a spreadsheet number.

    Restoring tries each precision from coarsest to finest and keeps the first
    candidate that scrambles back to exactly the stored value. Two different
    originals (up to 6 decimals) always differ by at least 1e-6; times a
    factor > 1 they cannot round to the same 6-decimal value, so the first
    match is the original.
    """
    if direction == "scramble":
        return _scramble_number(value, factor)
    raw = value / factor
    for places in range(0, 7):
        candidate = round(raw, places)
        if abs(_scramble_number(candidate, factor) - value) < 1e-9:
            if places == 0 or abs(candidate - round(candidate)) < 1e-12:
                return int(round(candidate))
            return candidate
    return round(raw, 6)


WHOLE_CELL = ("ORG", "PERSON", "PRODUCT", "SITE", "PROJECT", "ADDRESS")


@functools.lru_cache(maxsize=4096)
def _header_category(header: str, table: str) -> str | None:
    from ..discover.profiler import classify_header

    category, _, is_code = classify_header(header, table)
    if is_code:
        return "ID"
    return category


def scramble_cell(engine: Engine, header: object, value: str, table: str = "") -> tuple[str, dict[str, int]]:
    """Scramble one cell, letting its column header act as context.

    * A column headed "Customer", "Πελάτης", "Salesperson", "Product", "Αποθήκη"...
      is swapped cell by cell, whatever the cell says: no list needed.
    * A bare "094014201" in a column headed "ΑΦΜ" is a Greek VAT number; on its
      own, without the header, the pattern detectors cannot know that.
    """
    category = _header_category(header, table) if isinstance(header, str) and header.strip() else None
    stripped = value.strip()
    is_code_cell = category == "ID" and any(c.isdigit() for c in stripped) and " " not in stripped
    if (
        (category in WHOLE_CELL or is_code_cell)
        and stripped
        and not stripped.replace(".", "").replace(",", "").isdigit()
    ):
        from ..discover.profiler import PLACEHOLDERS

        if fold(stripped) not in PLACEHOLDERS and len(stripped) >= 2:
            from ..surrogates import match_case

            double = match_case(stripped, engine.stand_in(category, stripped))
            engine.learn_value(category, stripped)
            lead = value[: len(value) - len(value.lstrip())]
            trail = value[len(value.rstrip()) :]
            return f"{lead}{double}{trail}", {category: 1}
    prefix = f"{header}: " if isinstance(header, str) and header.strip() else ""
    reps, spans, _ = engine.plan(prefix + value)
    n = len(prefix)
    own = [(s - n, e - n, r) for s, e, r in reps if s >= n]
    counts: dict[str, int] = {}
    for sp in spans:
        if sp.start >= n:
            counts[sp.category] = counts.get(sp.category, 0) + 1
    return apply(value, own), counts
