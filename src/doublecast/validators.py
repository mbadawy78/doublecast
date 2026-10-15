"""Checksum validators and generators for structured identifiers.

Validators cut false positives (a random 9-digit number is not a Greek VAT
number unless its checksum works). Generators produce stand-ins that pass
the same checks, so downstream tools that validate formats keep working.
"""

from __future__ import annotations

import random
import string

# ---------------------------------------------------------------- Luhn


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def luhn_complete(prefix: str) -> str:
    for check in "0123456789":
        if luhn_valid(prefix + check):
            return prefix + check
    raise ValueError("unreachable")


# ---------------------------------------------------------------- IBAN


def _iban_numeric(s: str) -> int:
    converted = "".join(str(int(c, 36)) for c in s)
    return int(converted)


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if len(s) < 15 or len(s) > 34 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    if not s.isalnum():
        return False
    rearranged = s[4:] + s[:4]
    return _iban_numeric(rearranged) % 97 == 1


def iban_with_check(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    check = 98 - (_iban_numeric(rearranged) % 97)
    return f"{country}{check:02d}{bban}"


# ---------------------------------------------------------------- Greek ΑΦΜ (VAT)


def afm_valid(afm: str) -> bool:
    if len(afm) != 9 or not afm.isdigit() or afm == "000000000":
        return False
    total = sum(int(afm[i]) * (2 ** (8 - i)) for i in range(8))
    return (total % 11) % 10 == int(afm[8])


def afm_complete(prefix8: str) -> str:
    total = sum(int(prefix8[i]) * (2 ** (8 - i)) for i in range(8))
    return prefix8 + str((total % 11) % 10)


# ---------------------------------------------------------------- Greek ΑΜΚΑ (social security)


def amka_valid(amka: str) -> bool:
    if len(amka) != 11 or not amka.isdigit():
        return False
    dd, mm = int(amka[0:2]), int(amka[2:4])
    if not (1 <= dd <= 31 and 1 <= mm <= 12):
        return False
    return luhn_valid(amka)


# ---------------------------------------------------------------- EAN-13


def ean13_valid(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


def ean13_complete(prefix12: str) -> str:
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


# ---------------------------------------------------------------- Spanish DNI / NIE

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def dni_valid(dni: str) -> bool:
    s = dni.upper().replace("-", "")
    if len(s) != 9:
        return False
    body, letter = s[:8], s[8]
    if body[0] in "XYZ":
        body = str("XYZ".index(body[0])) + body[1:]
    if not body.isdigit():
        return False
    return _DNI_LETTERS[int(body) % 23] == letter


def dni_letter(number8: str) -> str:
    return _DNI_LETTERS[int(number8) % 23]


# ---------------------------------------------------------------- format-preserving shuffle


def shape_preserving(value: str, rng: random.Random, keep_prefix: int = 0) -> str:
    """Replace digits with digits and letters with letters, keeping punctuation.

    Greek letters map to Greek letters, Latin to Latin, case is preserved.
    """
    out = []
    greek_upper = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    greek_lower = greek_upper.lower()
    for i, ch in enumerate(value):
        if i < keep_prefix:
            out.append(ch)
        elif ch.isdigit():
            out.append(rng.choice(string.digits))
        elif ch in greek_upper:
            out.append(rng.choice(greek_upper))
        elif ch in greek_lower:
            out.append(rng.choice(greek_lower))
        elif ch.isupper():
            out.append(rng.choice(string.ascii_uppercase))
        elif ch.islower():
            out.append(rng.choice(string.ascii_lowercase))
        else:
            out.append(ch)
    return "".join(out)
