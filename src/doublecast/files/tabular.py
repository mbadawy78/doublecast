"""Shared logic for spreadsheets: which columns hold money or quantities."""

from __future__ import annotations

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


def scramble_cell(engine: Engine, header: object, value: str) -> tuple[str, dict[str, int]]:
    """Scramble one cell, letting its column header act as context.

    A bare "094014201" in a column headed "ΑΦΜ" is a Greek VAT number; on its
    own, without the header, the pattern detectors cannot know that.
    """
    prefix = f"{header}: " if isinstance(header, str) and header.strip() else ""
    reps, spans, _ = engine.plan(prefix + value)
    n = len(prefix)
    own = [(s - n, e - n, r) for s, e, r in reps if s >= n]
    counts: dict[str, int] = {}
    for sp in spans:
        if sp.start >= n:
            counts[sp.category] = counts.get(sp.category, 0) + 1
    return apply(value, own), counts
