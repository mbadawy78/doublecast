"""Realistic stand-ins ("doubles") for each kind of sensitive value.

Every stand-in is deterministic for a given vault seed, so the same real
value always gets the same double. That keeps answers consistent across
messages and keeps provider prompt-caching working.
"""

from __future__ import annotations

import hashlib
import hmac
import random
import re
import unicodedata

from .data import names as N
from .textnorm import fold, is_greek
from .validators import afm_complete, dni_letter, ean13_complete, iban_with_check, luhn_complete, shape_preserving

_GREEK_LATIN_HINT = re.compile(r"(opoulos|opoulou|akis|aki|idis|idou|iadis|ou|as|is|os)$", re.IGNORECASE)


def _rng(seed: bytes, category: str, folded: str, attempt: int) -> random.Random:
    digest = hmac.new(seed, f"{category}\x00{folded}\x00{attempt}".encode("utf-8"), hashlib.sha256).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def match_case(template: str, value: str) -> str:
    letters = [c for c in template if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 1:
        return value.upper() if not is_greek(value) else _strip_accents(value).upper()
    if letters and all(c.islower() for c in letters):
        return value.lower()
    return value


def guess_language(value: str, default: str, allowed: list[str]) -> str:
    if is_greek(value):
        return "el"
    last = value.strip().split()[-1] if value.strip() else ""
    if "el" in allowed and _GREEK_LATIN_HINT.search(last) and len(last) > 4:
        return "el_latin"
    return default if default in N.FIRST_NAMES else "en"


def split_legal_form(value: str) -> tuple[str, str]:
    stripped = value.strip()
    for form in sorted(N.LEGAL_FORMS, key=len, reverse=True):
        pattern = r"[\s,]+" + re.escape(form) + r"$"
        m = re.search(pattern, stripped, flags=re.IGNORECASE)
        if m:
            return stripped[: m.start()], stripped[m.start() :]
    return stripped, ""


_ALL_FIRST_NAMES = {fold(n) for n in N.RECOGNISED_FIRST_NAMES}


def _ending(word: str) -> str:
    fw = fold(word)
    for ending in ("ους", "ου", "ων", "ης", "ας", "ος", "ες", "οι", "η", "α", "ο", "ι"):
        e = ending.replace("ς", "σ")
        if fw.endswith(e):
            return e
    return ""


def _same_class(pool: list[str], like: str, rng: random.Random) -> str:
    """Pick a Greek name with the same ending as `like`, so both decline the same way.

    "Γιώργος" gets another -ος name, so "του Γιώργου" can become "του Νίκου".
    The original may already be inflected (genitive "Καλλέργη"); then any name
    whose stem takes that ending will do.
    """
    want = _ending(like)
    same = [n for n in pool if _ending(n) == want]
    if not same and want in ("η", "ου", "ο", "α", "ι"):
        # inflected forms: map back to the nominative classes that produce them
        nominative = {"η": ("ησ",), "ου": ("οσ",), "ο": ("οσ",), "α": ("ασ", "α"), "ι": ("ησ",)}[want]
        same = [n for n in pool if _ending(n) in nominative]
    return rng.choice(same or pool)


def _greek_declinable(core: str, rng: random.Random) -> str | None:
    """Invented Greek name whose ending matches the original's first word."""
    first = fold(core.split()[0]) if core.split() else ""
    for ending in sorted(N.GREEK_TAIL_BY_ENDING, key=len, reverse=True):
        folded_ending = ending.replace("ς", "σ")
        if first.endswith(folded_ending) and len(first) - len(folded_ending) >= 3:
            word = rng.choice(N.ORG_HEAD["greek"]) + rng.choice(N.GREEK_TAIL_BY_ENDING[ending])
            return word[0].upper() + word[1:]
    return None


def _invented(rng: random.Random, heads: list[str], tails: list[str]) -> str:
    word = rng.choice(heads) + rng.choice(tails)
    return word[0].upper() + word[1:]


class SurrogateFactory:
    def __init__(self, seed: bytes, default_language: str = "en", languages: list[str] | None = None):
        self.seed = seed
        self.default_language = default_language
        self.languages = languages or ["en"]

    def make(self, category: str, original: str, attempt: int = 0) -> str:
        folded = fold(original)
        rng = _rng(self.seed, category, folded, attempt)
        self._attempt = attempt
        maker = getattr(self, f"_make_{category.lower()}", None)
        value = maker(original, rng) if maker else self._make_custom(original, rng)
        if attempt >= 12 and category in ("ORG", "SITE", "PRODUCT", "PROJECT", "CUSTOM"):
            # after many collisions (huge vaults), extend the invented word to stay unique
            value = value + rng.choice(["ex", "ora", "ion", "ica", "en"])
        return match_case(original, value)

    # ------------------------------------------------------------ people & organisations
    def _make_person(self, original: str, rng: random.Random) -> str:
        lang = guess_language(original, self.default_language, self.languages)
        parts = original.split()
        firsts, lasts = N.FIRST_NAMES[lang], N.LAST_NAMES[lang]
        if getattr(self, "_attempt", 0) >= 2 or rng.random() < 0.35:
            # the curated lists are small; synthetic surnames keep doubles unique at any scale
            heads, tails = N.SURNAME_PARTS.get(lang, N.SURNAME_PARTS["en"])
            lasts = [h + t for h in rng.sample(heads, min(6, len(heads))) for t in tails]
        pick = (
            (lambda pool, like: _same_class(pool, like, rng)) if lang == "el" else (lambda pool, like: rng.choice(pool))
        )
        if len(parts) == 1:
            if fold(parts[0]) in _ALL_FIRST_NAMES:
                return pick(firsts, parts[0])  # "Dear Petros" -> "Dear Kostas"
            return pick(lasts, parts[0])  # otherwise a surname: distinctive, unlike common first names
        title = ""
        if parts[0].rstrip(".").lower() in (
            "mr",
            "mrs",
            "ms",
            "dr",
            "κ",
            "κα",
            "herr",
            "frau",
            "m",
            "mme",
            "sig",
            "sr",
            "sra",
        ):
            title, parts = parts[0] + " ", parts[1:]
        if len(parts) == 1:
            return title + pick(lasts, parts[0])
        return f"{title}{pick(firsts, parts[0])} {pick(lasts, parts[-1])}"

    def _make_org(self, original: str, rng: random.Random) -> str:
        core, legal = split_legal_form(original)
        script = "greek" if is_greek(core) else "latin"
        if script == "greek":
            # one invented word per original word, each in the same declension class,
            # so the double can take the same grammatical case as the original
            words = core.split()[:3]
            name = " ".join(
                _greek_declinable(w, rng) or _invented(rng, N.ORG_HEAD["greek"], N.ORG_TAIL["greek"]) for w in words
            )
        else:
            name = _invented(rng, N.ORG_HEAD[script], N.ORG_TAIL[script])
            if len(core.split()) >= 3:
                name = name + " " + _invented(rng, N.ORG_HEAD[script], N.ORG_TAIL[script])
        return name + legal

    def _make_site(self, original: str, rng: random.Random) -> str:
        script = "greek" if is_greek(original) else "latin"
        name = None
        if script == "greek" and len(original.split()) == 1:
            name = _greek_declinable(original, rng)
        name = name or _invented(rng, N.SITE_HEAD[script], N.SITE_TAIL[script])
        words = original.split()
        if len(words) > 1:
            # keep descriptive words like "Plant", "Warehouse", "Εργοστάσιο"
            descriptors = [w for w in words if w.lower() in _SITE_DESCRIPTORS]
            if descriptors:
                if words[-1].lower() in _SITE_DESCRIPTORS:
                    return f"{name} {' '.join(descriptors)}"
                return f"{' '.join(descriptors)} {name}"
        return name

    def _make_address(self, original: str, rng: random.Random) -> str:
        script = "greek" if is_greek(original) else "latin"
        street = _invented(rng, N.SITE_HEAD[script], N.SITE_TAIL[script])
        prefix = "Οδός " if script == "greek" else ""
        suffix = "" if script == "greek" else " Street"
        number = f" {rng.randint(1, 180)}" if any(c.isdigit() for c in original) else ""
        return f"{prefix}{street}{suffix}{number}"

    def _make_product(self, original: str, rng: random.Random) -> str:
        script = "greek" if is_greek(original) else "latin"
        brand = _invented(rng, N.ORG_HEAD[script], N.ORG_TAIL[script])
        if re.search(r"\d", original) and len(original.split()) == 1:
            return shape_preserving(original, rng)
        return f"{brand} {rng.choice(N.PRODUCT_WORDS[script])}"

    def _make_project(self, original: str, rng: random.Random) -> str:
        words = original.split()
        prefix = ""
        if words and words[0].lower() in ("project", "projekt", "projet", "progetto", "proyecto", "έργο", "project:"):
            prefix = words[0] + " "
        return prefix + rng.choice(N.PROJECT_CODENAMES)

    def _make_custom(self, original: str, rng: random.Random) -> str:
        if re.search(r"\d", original):
            return shape_preserving(original, rng)
        script = "greek" if is_greek(original) else "latin"
        return _invented(rng, N.ORG_HEAD[script], N.ORG_TAIL[script])

    # ------------------------------------------------------------ contact & identifiers
    def _make_email(self, original: str, rng: random.Random) -> str:
        local, _, domain = original.partition("@")
        lang = "en"
        first = _strip_accents(rng.choice(N.FIRST_NAMES[lang])).lower()
        last = _strip_accents(rng.choice(N.LAST_NAMES[lang])).lower().replace(" ", "")
        sep = "." if "." in local else ("_" if "_" in local else "")
        new_local = f"{first}{sep}{last}" if sep or len(local) > 6 else first[0] + last
        if domain.lower() in N.FREE_MAIL_DOMAINS:
            new_domain = domain
        else:
            tld = domain.rsplit(".", 1)[-1] if "." in domain else "com"
            new_domain = _invented(rng, N.ORG_HEAD["latin"], N.ORG_TAIL["latin"]).lower() + "." + tld
        return f"{new_local}@{new_domain}"

    def _make_phone(self, original: str, rng: random.Random) -> str:
        keep = 0
        m = re.match(r"^\s*(\+|00)\d{1,3}[\s.-]?", original)
        if m:
            keep = m.end()
        digits_seen = 0
        for i, ch in enumerate(original[keep:], start=keep):
            if ch.isdigit():
                digits_seen += 1
                if digits_seen == 2:  # keep operator/area prefix's first two digits
                    keep = i + 1
                    break
        return shape_preserving(original, rng, keep_prefix=keep)

    def _make_iban(self, original: str, rng: random.Random) -> str:
        compact = original.replace(" ", "").upper()
        country, bban = compact[:2], compact[4:]
        new_bban = shape_preserving(bban, rng)
        new = iban_with_check(country, new_bban)
        if " " in original.strip():
            return " ".join(new[i : i + 4] for i in range(0, len(new), 4))
        return new

    def _make_tax_id(self, original: str, rng: random.Random) -> str:
        m = re.match(r"^([A-Za-z]{2})?(\s?)(\d{9})$", original.strip())
        if m:  # Greek ΑΦΜ (optionally EL-prefixed)
            prefix8 = "".join(rng.choice("0123456789") for _ in range(8))
            if prefix8[0] == "0":
                prefix8 = "1" + prefix8[1:]
            return (m.group(1) or "") + m.group(2) + afm_complete(prefix8)
        dni = re.match(r"^(\d{8})-?([A-Za-z])$", original.strip())
        if dni:
            num = "".join(rng.choice("0123456789") for _ in range(8))
            return num + ("-" if "-" in original else "") + dni_letter(num)
        prefix = re.match(r"^[A-Za-z]{2}", original.strip())
        return shape_preserving(original, rng, keep_prefix=2 if prefix else 0)

    def _make_national_id(self, original: str, rng: random.Random) -> str:
        s = original.strip()
        if re.fullmatch(r"\d{11}", s):  # Greek ΑΜΚΑ: ddmmyy + 4 digits + Luhn
            day = rng.randint(1, 28)
            month = rng.randint(1, 12)
            year = rng.randint(40, 99)
            body = f"{day:02d}{month:02d}{year:02d}" + "".join(rng.choice("0123456789") for _ in range(4))
            return luhn_complete(body)
        return shape_preserving(original, rng, keep_prefix=0)

    def _make_id(self, original: str, rng: random.Random) -> str:
        s = original
        if re.fullmatch(r"\d{13}", s.strip()):  # EAN-13: keep GS1 country prefix
            return ean13_complete(s.strip()[:3] + "".join(rng.choice("0123456789") for _ in range(9)))
        m = re.match(r"^[^\d]*", s)
        keep = m.end() if m else 0
        return shape_preserving(s, rng, keep_prefix=keep)

    def _make_url(self, original: str, rng: random.Random) -> str:
        return re.sub(
            r"(?<=://)([^/:]+)",
            lambda m: (
                _invented(rng, N.ORG_HEAD["latin"], N.ORG_TAIL["latin"]).lower() + "." + m.group(1).rsplit(".", 1)[-1]
            ),
            original,
            count=1,
        )

    def _make_ip(self, original: str, rng: random.Random) -> str:
        parts = original.split(".")
        if len(parts) == 4:
            private_b = parts[0] == "192" and parts[1] == "168" or parts[0] == "172" and 16 <= int(parts[1]) <= 31
            keep = 2 if private_b else 1  # stay in the same kind of network (private stays private)
            return ".".join(parts[:keep] + [str(rng.randint(1, 254)) for _ in range(4 - keep)])
        return shape_preserving(original, rng)


_SITE_DESCRIPTORS = {
    "plant",
    "factory",
    "warehouse",
    "depot",
    "store",
    "branch",
    "office",
    "hub",
    "dc",
    "site",
    "εργοστάσιο",
    "αποθήκη",
    "κατάστημα",
    "υποκατάστημα",
    "γραφείο",
    "κέντρο",
    "werk",
    "lager",
    "filiale",
    "usine",
    "entrepôt",
    "magasin",
    "stabilimento",
    "magazzino",
    "fábrica",
    "almacén",
    "tienda",
    "north",
    "south",
    "east",
    "west",
    "βόρειο",
    "νότιο",
}
