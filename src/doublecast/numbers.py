"""Secret scaling for money and quantities; secret shifting for dates.

Why scaling instead of hiding: the AI still needs numbers to do the maths.
Multiplying every amount by one secret factor k keeps every ratio, margin,
share and growth rate exactly right, while the real figures never leave.
Answers come back in the scaled world and are divided by k on the way in.

Why k > 1: amounts are rounded to their original precision after scaling.
With k > 1 the rounding error, once divided back by k, is always smaller
than half a unit, so restoring returns the exact original amount.

Limits (documented, not hidden): amounts the AI invents from general
knowledge ("a typical €100 minimum order") are also divided by k on the
way back. Percentages are never touched.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .detectors.base import Span

_CUR_BEFORE = r"(?:US\$|€|EUR|\$|USD|£|GBP|CHF|CAD|AUD|SEK|DKK|NOK|PLN|RON|BGN|HUF|CZK|TRY)"
_CUR_AFTER = r"(?:€|EUR|ευρώ|Ευρώ|ΕΥΡΩ|euros?|Euros?|\$|USD|£|GBP|CHF|CAD|AUD|SEK|DKK|NOK|PLN|RON|BGN|HUF|CZK|TRY)"
_NUM = r"\d{1,3}(?:(?:[.,]|[   ])\d{3})+(?:[.,]\d+)?(?!\d)|\d+(?:[.,]\d+)?"
_SP = r"[   ]?"

# Magnitude words: "€2.3m", "$1.2bn", "12k", "1,5 εκατ. ευρώ", "3 Mio. €", "1.2 million euros".
_MAG = (
    r"(?:k|K|m|M|mn|mln|bn|b|B|million|millions|billion|billions|thousand|"
    r"εκ\.|εκατ\.?|εκατομμύρια|εκατομμυρίων|δισ\.?|δισεκατομμύρια|χιλ\.|χιλιάδες|χιλιάδων|"
    r"Mio\.?|Mrd\.?|Millionen|Milliarden|Tsd\.?|millions?|milliards?|milioni|miliardi|millones|mil)"
)
# A number must not be cut short: no digit, or separator+digit, may follow it.
_END = r"(?!\d)(?![.,]\d)"

MONEY_RE = re.compile(
    rf"(?<![\w.,])(?:"
    rf"(?P<cb>{_CUR_BEFORE}){_SP}(?P<n1>{_NUM}){_END}(?:{_SP}(?P<m1>{_MAG}))?"
    rf"|(?P<n2>{_NUM}){_END}(?:{_SP}(?P<m2>{_MAG}))?{_SP}(?P<ca>{_CUR_AFTER})"
    rf")(?![\w])"
)

_UNITS = (
    r"kg|kgs|kilos?|κιλά|κιλ\.|tn|tons?|tonnes?|τόνοι|τόνους|τόνων|units?|pcs|pieces|τεμ\.?|τεμάχια|"
    r"cases?|cartons?|κιβώτια|κιβ\.|pallets?|παλέτες|παλ\.|lt|litres?|liters?|λίτρα|Stück|Stk\.?|"
    r"pièces|pezzi|unidades|cajas|Kisten|Paletten|palettes|bancali"
)
QTY_RE = re.compile(rf"(?<![\w.,])(?P<n>{_NUM}){_END}{_SP}(?P<u>{_UNITS})(?![\w])", re.IGNORECASE)

DATE_ISO_RE = re.compile(r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d-])")
DATE_DMY_RE = re.compile(
    r"(?<![\d./-])(?<![vV])(?<!version )(?<!Version )(?P<a>\d{1,2})(?P<sep>[./-])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})(?![\d./-])"
)


@dataclass
class NumFmt:
    thousands: str | None
    decimal: str | None
    decimals: int


def parse_number(token: str, locale: str = "auto") -> tuple[Decimal, NumFmt] | None:
    t = token
    non_digits = [i for i, c in enumerate(t) if not c.isdigit()]
    try:
        if not non_digits:
            return Decimal(t), NumFmt(None, None, 0)
        last = non_digits[-1]
        last_sep = t[last]
        after = len(t) - last - 1
        space_like = {" ", " ", " "}
        punct = [t[i] for i in non_digits if t[i] not in space_like]
        if last_sep in space_like:
            th, dec = last_sep, None
        elif t.count(last_sep) > 1:
            th, dec = last_sep, None
        elif len(set(t[i] for i in non_digits)) > 1:
            dec = last_sep
            th = t[non_digits[0]]
        else:  # one separator, used once
            head = t[:last].lstrip("-+")
            if after == 3 and (head.startswith("0") or len(head) > 3):
                th, dec = None, last_sep  # "0,215" and "1234.567" cannot be thousands groups
            elif after == 3:
                if locale == "eu":
                    th, dec = (".", None) if last_sep == "." else (None, ",")
                elif locale == "us":
                    th, dec = (",", None) if last_sep == "," else (None, ".")
                else:
                    th, dec = last_sep, None
            else:
                th, dec = None, last_sep
        del punct
        clean = t
        if th:
            clean = clean.replace(th, "")
        if dec:
            clean = clean.replace(dec, ".")
        value = Decimal(clean)
        decimals = (len(t) - t.rfind(dec) - 1) if dec else 0
        return value, NumFmt(th, dec, decimals)
    except (InvalidOperation, ValueError):
        return None


def format_number(value: Decimal, fmt: NumFmt, decimals: int | None = None, default_decimal: str = ".") -> str:
    decimals = fmt.decimals if decimals is None else decimals
    q = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    v = value.quantize(q, rounding=ROUND_HALF_UP)
    sign = "-" if v < 0 else ""
    v = abs(v)
    s = f"{v:.{decimals}f}"
    int_part, _, frac = s.partition(".")
    if fmt.thousands and len(int_part) > 3:
        groups = []
        while len(int_part) > 3:
            groups.insert(0, int_part[-3:])
            int_part = int_part[:-3]
        groups.insert(0, int_part)
        int_part = fmt.thousands.join(groups)
    if decimals:
        return sign + int_part + (fmt.decimal or default_decimal) + frac
    return sign + int_part


def guess_decimal_char(text: str) -> str:
    eu = len(re.findall(r"\d\.\d{3},\d{2}\b|\d,\d{2}\s?€|€\s?\d+,\d{2}\b", text))
    us = len(re.findall(r"\d,\d{3}\.\d{2}\b|\$\s?\d+\.\d{2}\b|€\s?\d+\.\d{2}\b", text))
    if eu > us:
        return ","
    if us > eu:
        return "."
    return "," if re.search(r"[Ͱ-Ͽ]", text) else "."


class NumberTransformer:
    def __init__(
        self,
        money_factor: float,
        qty_factor: float,
        date_offset_days: int,
        *,
        scale_money: bool = True,
        scale_quantities: bool = False,
        shift_dates: bool = False,
        locale: str = "auto",
    ):
        self.k_money = Decimal(repr(money_factor))
        self.k_qty = Decimal(repr(qty_factor))
        self.offset = dt.timedelta(days=date_offset_days)
        self.scale_money = scale_money
        self.scale_quantities = scale_quantities
        self.shift_dates = shift_dates
        self.locale = locale

    # ------------------------------------------------------------ detection
    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        if self.scale_money:
            for m in MONEY_RE.finditer(text):
                group = "n1" if m.group("n1") else "n2"
                s, e = m.span(group)
                spans.append(Span(s, e, "MONEY", text[s:e], "money", action="money"))
        if self.scale_quantities:
            for m in QTY_RE.finditer(text):
                s, e = m.span("n")
                spans.append(Span(s, e, "QUANTITY", text[s:e], "quantity", action="quantity"))
        if self.shift_dates:
            for m in DATE_ISO_RE.finditer(text):
                spans.append(Span(m.start(), m.end(), "DATE", m.group(0), "date", action="date", kind="iso"))
            for m in DATE_DMY_RE.finditer(text):
                spans.append(Span(m.start(), m.end(), "DATE", m.group(0), "date", action="date", kind="dmy"))
        return spans

    # ------------------------------------------------------------ forward
    def scale(self, token: str, factor: Decimal, default_decimal: str) -> str | None:
        parsed = parse_number(token, self.locale)
        if not parsed:
            return None
        value, fmt = parsed
        # Same precision as the original: with factor > 1, dividing back and
        # rounding to that precision always returns the original exactly.
        return format_number(value * factor, fmt, fmt.decimals, default_decimal)

    def unscale(self, token: str, factor: Decimal, default_decimal: str) -> str | None:
        parsed = parse_number(token, self.locale)
        if not parsed:
            return None
        value, fmt = parsed
        return format_number(value / factor, fmt, fmt.decimals, default_decimal)

    def forward(self, span: Span, default_decimal: str) -> str | None:
        if span.action == "money":
            return self.scale(span.text, self.k_money, default_decimal)
        if span.action == "quantity":
            return self.scale(span.text, self.k_qty, default_decimal)
        if span.action == "date":
            return self._shift_date(span.text, span.kind, self.offset)
        return None

    # ------------------------------------------------------------ dates
    def _shift_date(self, token: str, kind: str, delta: dt.timedelta) -> str | None:
        if kind == "iso" or DATE_ISO_RE.fullmatch(token):
            m = DATE_ISO_RE.fullmatch(token)
            if not m:
                return None
            try:
                d = dt.date(int(m["y"]), int(m["m"]), int(m["d"])) + delta
            except ValueError:
                return None
            return d.isoformat()
        m = DATE_DMY_RE.fullmatch(token)
        if not m:
            return None
        a, b, y_raw, sep = m["a"], m["b"], m["y"], m["sep"]
        first, second = int(a), int(b)
        us = self.locale == "us" or (second > 12 and first <= 12)
        day, month = (second, first) if us else (first, second)
        year = int(y_raw)
        if len(y_raw) == 2:
            year += 2000 if year < 70 else 1900
        try:
            d = dt.date(year, month, day) + delta
        except ValueError:
            return None
        out_year = f"{d.year % 100:02d}" if len(y_raw) == 2 else str(d.year)
        padded = a.startswith("0") or b.startswith("0")
        dd = f"{d.day:02d}" if padded else str(d.day)
        mm = f"{d.month:02d}" if padded else str(d.month)
        return f"{mm}{sep}{dd}{sep}{out_year}" if us else f"{dd}{sep}{mm}{sep}{out_year}"

    # ------------------------------------------------------------ restore
    def restore_matches(self, text: str, default_decimal: str) -> list[tuple[int, int, str]]:
        out: list[tuple[int, int, str]] = []
        # Spans cover the whole match (currency or unit included), so a stream
        # restorer never emits "€" in one chunk and leaves its number orphaned.
        if self.scale_money:
            for m in MONEY_RE.finditer(text):
                group = "n1" if m.group("n1") else "n2"
                s, e = m.span(group)
                r = self.unscale(text[s:e], self.k_money, default_decimal)
                if r is not None:
                    out.append((m.start(), m.end(), text[m.start() : s] + r + text[e : m.end()]))
        if self.scale_quantities:
            for m in QTY_RE.finditer(text):
                s, e = m.span("n")
                r = self.unscale(text[s:e], self.k_qty, default_decimal)
                if r is not None:
                    out.append((m.start(), m.end(), text[m.start() : s] + r + text[e : m.end()]))
        if self.shift_dates:
            for m in DATE_ISO_RE.finditer(text):
                r = self._shift_date(m.group(0), "iso", -self.offset)
                if r:
                    out.append((m.start(), m.end(), r))
            for m in DATE_DMY_RE.finditer(text):
                r = self._shift_date(m.group(0), "dmy", -self.offset)
                if r:
                    out.append((m.start(), m.end(), r))
        return out
