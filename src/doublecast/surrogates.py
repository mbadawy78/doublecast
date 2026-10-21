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
from .data import realnames as R
from .textnorm import fold, greek_stem, is_greek
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
    words = [R.strip_accents(w).lower().strip(".,'’") for w in value.split()]
    # a known name decides: "Sabine Hoffmann" is German, "Giulia Ferrari" Italian
    for w in reversed(words):  # the surname says more than the first name
        for lang in ("de", "fr", "it", "es", "el_latin", "en"):
            if w in R.LANG_NAMES[lang] and (lang != "el_latin" or "el" in allowed):
                return lang
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

_TITLE_GENDER = {
    fold(t): g
    for t, g in (
        ("mr", "m"),
        ("herr", "m"),
        ("m", "m"),
        ("sr", "m"),
        ("sig", "m"),
        ("κος", "m"),
        ("κο", "m"),
        ("κε", "m"),
        ("κύριος", "m"),
        ("κύριο", "m"),
        ("κύριε", "m"),
        ("κυρίου", "m"),
        ("mrs", "f"),
        ("ms", "f"),
        ("miss", "f"),
        ("frau", "f"),
        ("mme", "f"),
        ("mlle", "f"),
        ("sra", "f"),
        ("sig.ra", "f"),
        ("κα", "f"),
        ("κας", "f"),
        ("κυρία", "f"),
        ("κυρίας", "f"),
        ("dr", None),
        ("prof", None),
        ("κ", None),
    )
}
_GENDER_OF: dict[str, str] = {}
for _lang, _byg in R.FIRST.items():
    for _g, _names in _byg.items():
        for _n in _names:
            _GENDER_OF.setdefault(fold(_n), _g)
_GENDER_OF_STEM = {st: g for n, g in _GENDER_OF.items() if is_greek(n) and (st := greek_stem(n))}


def first_name_gender(word: str) -> str | None:
    """m / f / None for a first name in any of our languages (Greek in any case: Ελένη, Ελένης, Γιώργο)."""
    w = fold(word.strip(".,'’"))
    if w in _GENDER_OF:
        return _GENDER_OF[w]
    if is_greek(w):
        st = greek_stem(w)
        if st and st in _GENDER_OF_STEM:
            return _GENDER_OF_STEM[st]
        if w.endswith(("α", "η")):
            return "f"
        if w.endswith(("οσ", "ησ", "ασ", "ο")):
            return "m"
    return None


def _same_latin_ending(pool: list[str], like: str, rng: random.Random) -> str:
    """Greek names in Latin letters keep their ending ("Andreou" -> "Konstantinou", "Eleni" -> "Zoi"),
    so the Greek-script twin of the double takes the same grammatical case as the original."""
    w = R.strip_accents(like).lower()
    for n in (3, 2, 1):
        same = [p for p in pool if R.strip_accents(p).lower().endswith(w[-n:])]
        if len(same) >= 3:
            return rng.choice(same)
    return rng.choice(pool)


def _compound_surnames(pool: list[str], lang: str, rng: random.Random) -> list[str]:
    """More real-looking surnames once a big vault has used the plain ones:
    Χατζηγιάννης, Καραδούκας; Hartley-Brooks, Müller-Weber."""
    sample = rng.sample(pool, min(40, len(pool)))
    if lang == "el":
        out = []
        for s in sample:
            if s.startswith(tuple(R.GREEK_COMPOUND_PREFIX)) or fold(s[0]) in "αεηιουω":
                continue  # no "Παπααλεξίου"
            out.append(rng.choice(R.GREEK_COMPOUND_PREFIX) + s[0].lower() + s[1:])
        return out or pool
    return [f"{a}-{rng.choice(pool)}" for a in sample]


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
    own = fold(like)
    pool = [n for n in pool if fold(n) != own] or pool  # never the original name itself
    same = [n for n in pool if _ending(n) == want]
    if not same and want in ("η", "ου", "ο", "α", "ι"):
        # inflected forms: map back to the nominative classes that produce them
        nominative = {"η": ("ησ",), "ου": ("οσ",), "ο": ("οσ",), "α": ("ασ", "α"), "ι": ("ησ",)}[want]
        same = [n for n in pool if _ending(n) in nominative]
    return rng.choice(same or pool)


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
        return match_case(original, value)

    # ------------------------------------------------------------ people & organisations
    def _make_person(self, original: str, rng: random.Random) -> str:
        """Same language, same gender, same Greek declension class: a name nobody would look at twice."""
        lang = guess_language(original, self.default_language, self.languages)
        if lang not in R.FIRST:
            lang = "en"
        parts = original.split()
        title = ""
        if len(parts) > 1 and fold(parts[0].rstrip(".")) in _TITLE_GENDER:
            title, parts = parts[0] + " ", parts[1:]
        gender = _TITLE_GENDER.get(fold(title.strip().rstrip("."))) if title else None
        gender = gender or getattr(self, "gender_hint", None)
        if gender is None and (len(parts) > 1 or fold(parts[0]) in _ALL_FIRST_NAMES):
            gender = first_name_gender(parts[0])
        attempt = getattr(self, "_attempt", 0)

        def pool(table: dict) -> list[str]:
            byg = table[lang]
            return byg[gender] if gender else byg["m"] + byg["f"]

        firsts = pool(R.FIRST)
        lasts = _compound_surnames(pool(R.LAST), lang, rng) if attempt >= 8 else pool(R.LAST)
        if lang == "el":
            pick = lambda p, like: _same_class(p, like, rng)  # noqa: E731
        elif lang == "el_latin":
            pick = lambda p, like: _same_latin_ending(p, like, rng)  # noqa: E731
        else:
            pick = lambda p, like: rng.choice(p)  # noqa: E731
        if len(parts) == 1:
            if not title and fold(parts[0]) in _ALL_FIRST_NAMES:
                return pick(firsts, parts[0])  # "Dear Petros" -> "Dear Kostas"
            return title + pick(lasts, parts[0])  # "Ms Vlachaki" -> "Ms Georgiou"
        return f"{title}{pick(firsts, parts[0])} {pick(lasts, parts[-1])}"

    def _brand(self, word: str, rng: random.Random, index: int) -> str:
        attempt = getattr(self, "_attempt", 0)
        if is_greek(word):
            pool = R.GREEK_SURNAMES_M if attempt < 8 else _compound_surnames(R.GREEK_SURNAMES_M, "el", rng)
            return _same_class(pool, word, rng)  # "της Μασούτη" -> "της Δούκα"
        if index == 0:
            name = rng.choice(R.BRAND_WORDS)
            if attempt >= 20:  # big vaults: two words ("Meridian Thistle")
                name += " " + rng.choice([b for b in R.BRAND_WORDS if b != name])
            elif attempt >= 8:
                name += " " + rng.choice(["Ridge", "Vale", "Hill", "Bay", "Point", "Field", "Park", "Grove"])
            return name
        return rng.choice(R.EN_SURNAMES)

    def _make_org(self, original: str, rng: random.Random) -> str:
        """Generic words and the legal form stay ("Hellas", "Foods", "Τρόφιμα", "EPE"); the name changes."""
        core, legal = split_legal_form(original)
        words = core.split()
        out, n = [], 0
        for w in words:
            if w.strip(",.()").casefold() in R.GENERIC_ORG_WORDS and len(words) > 1:
                out.append(w)
            else:
                out.append(self._brand(w, rng, n))
                n += 1
        if n == 0:  # every word generic ("Hellas Foods"): name it anyway
            out.insert(0, self._brand(words[0] if words else original, rng, 0))
        return " ".join(out) + legal

    def _make_site(self, original: str, rng: random.Random) -> str:
        words = original.split()
        descriptors = [w for w in words if w.lower() in _SITE_DESCRIPTORS]
        names = [w for w in words if w.lower() not in _SITE_DESCRIPTORS]
        like = names[0] if names else original
        if is_greek(original):
            name = _same_class(R.GREEK_TOWNS, like, rng)
        else:
            name = rng.choice(R.BRAND_WORDS)
        attempt = getattr(self, "_attempt", 0)
        if attempt >= 20:
            pool = R.GREEK_TOWNS if is_greek(original) else R.BRAND_WORDS
            name += " " + rng.choice([p for p in pool if p != name])
        elif attempt >= 8:
            name += " " + (rng.choice(["Βόρειο", "Νότιο"]) if is_greek(original) else rng.choice(["North", "South"]))
        if descriptors:
            if words[-1].lower() in _SITE_DESCRIPTORS:
                return f"{name} {' '.join(descriptors)}"
            return f"{' '.join(descriptors)} {name}"
        return name

    def _make_address(self, original: str, rng: random.Random) -> str:
        number = str(rng.randint(1, 180)) if any(c.isdigit() for c in original) else ""
        if is_greek(original):
            return f"{rng.choice(R.GREEK_STREETS)} {number}".strip()
        word = rng.choice(R.BRAND_WORDS)
        lang = self.default_language if self.default_language in R.STREET_SUFFIX else "en"
        if lang == "de":
            return f"{word}straße {number}".strip()
        if lang == "en":
            return f"{number} {word} Road".strip()
        return f"{R.STREET_SUFFIX[lang]} {word} {number}".strip()

    def _make_product(self, original: str, rng: random.Random) -> str:
        script = "greek" if is_greek(original) else "latin"
        if re.search(r"\d", original) and len(original.split()) == 1:
            return shape_preserving(original, rng)
        return f"{rng.choice(R.BRAND_WORDS)} {rng.choice(N.PRODUCT_WORDS[script])}"

    def _make_project(self, original: str, rng: random.Random) -> str:
        words = original.split()
        prefix = ""
        if words and words[0].lower() in ("project", "projekt", "projet", "progetto", "proyecto", "έργο", "project:"):
            prefix = words[0] + " "
        return prefix + rng.choice(N.PROJECT_CODENAMES)

    def _make_custom(self, original: str, rng: random.Random) -> str:
        if re.search(r"\d", original):
            return shape_preserving(original, rng)
        return rng.choice(R.BRAND_WORDS)

    # ------------------------------------------------------------ contact & identifiers
    def _make_email(self, original: str, rng: random.Random) -> str:
        local, _, domain = original.partition("@")
        tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else "com"
        lang = "el_latin" if tld in ("gr", "cy") else ({"de": "de", "fr": "fr", "it": "it", "es": "es"}.get(tld, "en"))
        first = R.strip_accents(rng.choice(R.FIRST[lang]["m"] + R.FIRST[lang]["f"])).lower()
        last = R.strip_accents(rng.choice(R.LAST[lang]["m"])).lower().replace(" ", "").replace("'", "")
        sep = "." if "." in local else ("_" if "_" in local else "")
        if sep and len(local.split(sep)[0]) <= 2:
            new_local = f"{first[0]}{sep}{last}"  # e.papadopoulou -> g.dimitriou
        else:
            new_local = f"{first}{sep}{last}" if sep or len(local) > 6 else first[0] + last
        if domain.lower() in N.FREE_MAIL_DOMAINS:
            new_domain = domain
        else:
            new_domain = rng.choice(R.BRAND_WORDS).lower() + "." + tld
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
            lambda m: rng.choice(R.BRAND_WORDS).lower() + "." + m.group(1).rsplit(".", 1)[-1],
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
