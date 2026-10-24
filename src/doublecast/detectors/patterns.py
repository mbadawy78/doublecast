"""Structured identifiers: emails, phones, IBANs, tax and national IDs.

Every pattern that could fire on a random number needs either a checksum
or a nearby context word ("ΑΦΜ", "VAT", "AMKA"...). That keeps false
positives, which break analysis, low.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Callable

import yaml

from ..textnorm import fold
from ..validators import afm_valid, amka_valid, dni_valid, ean13_valid, iban_valid, luhn_valid
from .base import Span

VALIDATORS: dict[str, Callable[[str], bool]] = {
    "luhn": lambda s: luhn_valid(re.sub(r"\D", "", s)),
    "iban": iban_valid,
    "afm": lambda s: afm_valid(re.sub(r"\D", "", s)[-9:]),
    "amka": lambda s: amka_valid(re.sub(r"\D", "", s)),
    "ean13": lambda s: ean13_valid(re.sub(r"\D", "", s)),
    "dni": dni_valid,
    "ten_digits": lambda s: len(re.sub(r"\D", "", s)) == 10,
    "private_url": lambda s: not _public_host(s),
    # loopback, unspecified, netmasks/broadcast and the classic "1.2.3.4" example are not sensitive
    "ip": lambda s: not s.startswith(("0.", "127.", "255.")) and s != "1.2.3.4",
}


# Public sites stay as they are (a link to docs or a search engine names nobody); the rest of a
# web address names a company as surely as its name does.
_PUBLIC = {
    "google.com",
    "microsoft.com",
    "github.com",
    "apple.com",
    "amazon.com",
    "aws.amazon.com",
    "wikipedia.org",
    "youtube.com",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "anthropic.com",
    "claude.ai",
    "openai.com",
    "chatgpt.com",
    "python.org",
    "pypi.org",
    "w3.org",
    "mozilla.org",
    "office.com",
    "sharepoint.com",
    "live.com",
    "outlook.com",
    "zoom.us",
    "dropbox.com",
    "europa.eu",
    "who.int",
    "gov.gr",
    "gov.uk",
    "canada.ca",
    "gc.ca",
    "irs.gov",
    "sap.com",
    "oracle.com",
    "dynamics.com",
    "powerbi.com",
}


def _public_host(url: str) -> bool:
    host = re.sub(r"^[a-z]+://", "", url.strip(), flags=re.I).split("/")[0].split("?")[0].lower()
    host = re.sub(r"^www\d?\.", "", host)
    labels = host.split(".")
    if labels[-1] in ("gov", "edu", "int", "mil"):
        return True
    return any(host == p or host.endswith("." + p) for p in _PUBLIC)


@dataclass
class PatternSpec:
    name: str
    category: str
    regex: re.Pattern[str]
    group: int = 0
    validator: str | None = None
    context: list[str] = field(default_factory=list)
    window: int = 40
    detector: str = "pattern"
    languages: list[str] = field(default_factory=list)
    require_digit: bool = False

    def context_ok(self, text: str, start: int, end: int) -> bool:
        if not self.context:
            return True
        before = fold(text[max(0, start - self.window) : start])
        after = fold(text[end : end + 12])
        return any(word in before or word in after for word in self.context)


def _spec(name, category, regex, group=0, validator=None, context=(), window=40, flags=0, languages=()):
    return PatternSpec(
        name=name,
        category=category,
        regex=re.compile(regex, flags),
        group=group,
        validator=validator,
        context=[fold(c) for c in context],
        window=window,
        languages=list(languages),
    )


_PHONE_CONTEXT = [
    "tel",
    "phone",
    "mobile",
    "mob",
    "fax",
    "cell",
    "τηλ",
    "κιν",
    "τηλέφωνο",
    "κινητό",
    "φαξ",
    "telefon",
    "handy",
    "téléphone",
    "tél",
    "portable",
    "telefono",
    "cellulare",
    "teléfono",
    "móvil",
]

CORE_PATTERNS: list[PatternSpec] = [
    _spec(
        "url",
        "URL",
        r"(?<![\w@/.\-])(?:https?://|www\d?\.)[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s<>\"'\)\]]*)?",
        validator="private_url",
    ),
    _spec("email", "EMAIL", r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b"),
    _spec(
        "phone_international",
        "PHONE",
        r"(?<![\w+])(?:\+|00)(?:30|44|49|33|39|34|357|1|31|32|43|41|351|353|359|40|48|90)[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)",
    ),
    # Greek numbers as people write them: 6977 412 390, 697 741 2390, 6977412390, 210 55 92 410, 24610 92 300
    _spec("phone_gr_mobile", "PHONE", r"(?<![\d.,])69\d(?:[ -]?\d){7}(?!\d)(?![.,]\d)"),
    _spec(
        "phone_gr_landline",
        "PHONE",
        r"(?<![\d.,/-])2\d{1,4}(?: \d{2,4}){1,3}(?!\d)(?![.,/-]\d)",
        validator="ten_digits",
        languages=["el"],
    ),
    _spec("phone_uk_mobile", "PHONE", r"(?<![\d.,])07\d{3}[ ]?\d{3}[ ]?\d{3}(?!\d)(?![.,]\d)"),
    _spec("phone_intl_any", "PHONE", r"(?<![\w+])\+\d{1,3}(?:[ -]?\(?\d{1,4}\)?)(?:[ -]?\d{2,4}){2,4}(?!\d)(?![.,]\d)"),
    _spec("phone_fr", "PHONE", r"(?<![\d.,])0[1-9](?:[ .]\d{2}){4}(?!\d)(?![.,]\d)"),
    _spec(
        "phone_es",
        "PHONE",
        r"(?<![\d.,])[6-9]\d{2}(?: \d{2}){3}(?!\d)(?![.,]\d)|(?<![\d.,])[6-9]\d{2} \d{3} \d{3}(?!\d)(?![.,]\d)",
    ),
    _spec("phone_it", "PHONE", r"(?<![\d.,])0\d{1,3} \d{3} \d{3,4}(?!\d)(?![.,]\d)"),
    _spec(
        "phone_gr_compact",
        "PHONE",
        r"(?<![\d.,])2\d{9}(?!\d)(?![.,]\d)",
        context=_PHONE_CONTEXT + [":", "στο", "at"],
        window=30,
    ),
    _spec(
        "phone_with_context",
        "PHONE",
        r"(?<![\d])\(?\d{2,5}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}(?:[\s.-]?\d{2,4})?(?![\d])",
        context=_PHONE_CONTEXT,
        window=25,
    ),
    _spec(
        "greek_vat",
        "TAX_ID",
        r"(?<![\w])(?:EL|GR)?\s?\d{9}(?![\d])",
        validator="afm",
        context=["αφμ", "α.φ.μ", "afm", "vat", "φπα", "tin", "tax id", "tax no", "αριθμός φορολογικού"],
        languages=["el"],
    ),
    _spec("greek_vat_prefixed", "TAX_ID", r"(?<![\w])EL\d{9}(?![\d])"),
    # a number right after a tax label is a tax number, checksum or not (typos and test data included)
    _spec(
        "tax_labelled",
        "TAX_ID",
        r"(?i)(?:\bα\.?φ\.?μ\.?|\bafm|\bvat(?:\s*(?:no|number|reg(?:istration)?(?:\s*no)?)\.?)?|\btin|\bein|ust-?id(?:nr)?\.?|"
        r"\btva|p\.?\s?iva|partita iva|\bnif|\bcif|\bsiret|\bsiren|tax id|tax no\.?)\s*[:#]?\s*"
        r"((?:[A-Z]{2}[ ]?)?[A-Z]?\d[\d -]{6,16}\d[A-Z]?)(?![\w])",
        group=1,
    ),
    _spec("gb_vat", "TAX_ID", r"(?<![\w])GB[ ]?\d{3}[ ]?\d{4}[ ]?\d{2}(?![\d])"),
    _spec("se_vat", "TAX_ID", r"(?<![\w])SE\d{10}01(?![\d])"),
    _spec("es_cif", "TAX_ID", r"(?<![\w])[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J](?![\w])"),
    _spec(
        "eu_vat",
        "TAX_ID",
        r"(?<![\w])(?:DE\d{9}|FR[0-9A-Z]{2}\d{9}|IT\d{11}|ES[0-9A-Z]\d{7}[0-9A-Z]|NL\d{9}B\d{2}|BE0?\d{9}|ATU\d{8}|PT\d{9}|CY\d{8}[A-Z]|BG\d{9,10}|RO\d{2,10}|PL\d{10}|IE\d{7}[A-Z]{1,2})(?![\w])",
    ),
    _spec(
        "greek_amka",
        "NATIONAL_ID",
        r"(?<![\d])\d{11}(?![\d])",
        validator="amka",
        context=["αμκα", "α.μ.κ.α", "amka", "social security", "κοινωνικής ασφάλισης"],
        languages=["el"],
    ),
    _spec(
        "greek_id_card",
        "NATIONAL_ID",
        r"(?<![\w])[Α-ΩA-Z]{1,2}[\s-]?\d{6}(?![\d])",
        context=["αδτ", "α.δ.τ", "ταυτότητα", "ταυτοτητας", "id card", "identity card"],
        languages=["el"],
    ),
    _spec("spanish_dni", "TAX_ID", r"(?<![\w])\d{8}-?[A-HJ-NP-TV-Z](?![\w])", validator="dni", languages=["es"]),
    _spec("spanish_nie", "TAX_ID", r"(?<![\w])[XYZ]-?\d{7}-?[A-HJ-NP-TV-Z](?![\w])", validator="dni", languages=["es"]),
    _spec(
        "italian_codice_fiscale",
        "NATIONAL_ID",
        r"(?<![\w])[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z](?![\w])",
        languages=["it"],
    ),
    _spec(
        "french_nir",
        "NATIONAL_ID",
        r"(?<![\d])[12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}(?:\s?\d{2})?(?![\d])",
        context=["sécurité sociale", "securite sociale", "nir", "insee", "numéro de sécu", "n° ss"],
        languages=["fr"],
    ),
    _spec(
        "german_tax_id",
        "TAX_ID",
        r"(?<![\d])\d{2}\s?\d{3}\s?\d{3}\s?\d{3}(?![\d])",
        context=["steuer-id", "steueridentifikationsnummer", "idnr", "steuernummer"],
        languages=["de"],
    ),
    _spec(
        "passport",
        "NATIONAL_ID",
        r"(?i)\b(?:passport|διαβατήριο|διαβατηρίου|reisepass|passeport|passaporto|pasaporte)\b\s*(?:no\.?|number|αρ\.?|nr\.?|n°|núm\.?)?\s*[:#]?\s*([A-Z0-9]{6,9})\b",
        group=1,
    ),
    # street addresses: a street word, a name, a number, then optionally a postcode and town
    _spec(
        "address_gr",
        "ADDRESS",
        r"(?:(?<![\w])(?:Λεωφ\.|Λεωφόρος|Λ\.|Οδός|οδός|Οδ\.|Πλατεία|Πλ\.|Βι\.?Πε\.?|Θέση|Ακτή|Παραλία)"
        r"[ \t]+[^\n,;()]{2,40}?|(?<![\w])[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰς]{2,}(?:[ \t][Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰς]+)?)"
        r"[ \t]+\d{1,4}[Α-Ωα-ω]?(?:[ \t]*,[ \t]*(?:Τ\.?Κ\.?[ \t]*)?\d{3}[ ]?\d{2}(?:[ \t]+[Α-ΩΆΈΉΊΌΎΏ][\wά-ώ.\-]+)+)",
    ),
    _spec(
        "address_gr_street",
        "ADDRESS",
        r"(?<![\w])(?:Λεωφ\.|Λεωφόρος|Λ\.|Οδός|Οδ\.|Πλατεία|Βι\.?Πε\.?|Ακτή)[ \t]+[Α-ΩΆΈΉΊΌΎΏ][^\n,;()]{1,40}?[ \t]+\d{1,4}(?![\d.,])",
    ),
    _spec(
        "address_latin",
        "ADDRESS",
        r"(?<![\w])(?:(?:Unit|Suite|Flat)[ \t]+\d+[A-Z]?[ \t,]+)?"
        r"(?:\d{1,5}[ \t]+(?:[A-Z][\w'’.\-]*[ \t]+){1,4}(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Drive|Dr\.?|Lane|Ln\.?|"
        r"Way|Boulevard|Blvd\.?|Place|Pl\.?|Court|Ct\.?|Estate|Park|Square|Sq\.?)(?![\w])"
        r"|(?:[A-Z][\w'’.\-]*[ \t]+){1,4}(?:Industrial Estate|Business Park|Trading Estate|Street|Road|Avenue|Lane)(?![\w])"
        r"|(?:Via|Viale|Piazza|Corso|Calle|Avenida|Av\.|Paseo|Rue|Avenue|Boulevard|Bd|Chemin|Allée)[ \t]+(?:[\w'’.\-]+[ \t]+){0,4}?\d{1,4}"
        r"|[A-ZÄÖÜ][\wäöüß\-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|dijk|straat|laan|gatan|vägen|plein)[ \t]+\d{1,4}[a-z]?)"
        r"(?:[ \t]*,[ \t]*(?:[A-Z]{1,2}\d[A-Z\d]?[ ]?\d[A-Z]{2}|\d{3,5}(?:[ ]?[A-Z]{2})?|\d{3}[ ]\d{2})?[ \t]*[A-Z][\w\-]+(?:[ \t]+[A-Z][\w\-]+)?(?:[ \t]+[A-Z]{1,2}\d[A-Z\d]?[ ]?\d[A-Z]{2})?)?"
        r"(?:,[ \t]*[A-Z]{2}[ \t]+\d{5})?",
    ),
    _spec(
        "ipv4",
        "IP",
        r"(?<![\d.])(?<![vV])(?<![=@])(?<!version )(?<!Version )(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])",
        validator="ip",
    ),
]

# Expected IBAN lengths for the countries we care about most; others: 15-34.
IBAN_LENGTHS = {
    "GR": 27,
    "CY": 28,
    "DE": 22,
    "FR": 27,
    "IT": 27,
    "ES": 24,
    "GB": 22,
    "NL": 18,
    "BE": 16,
    "AT": 20,
    "PT": 25,
    "IE": 22,
    "LU": 20,
    "CH": 21,
    "BG": 22,
    "RO": 24,
    "PL": 28,
    "MT": 31,
    "SI": 19,
    "SK": 24,
    "CZ": 24,
    "HU": 28,
    "HR": 21,
    "DK": 18,
    "SE": 24,
    "FI": 18,
    "NO": 15,
    "EE": 20,
    "LV": 21,
    "LT": 20,
    "AL": 28,
    "MK": 19,
    "RS": 22,
    "TR": 26,
    "AE": 23,
    "SA": 24,
}
_IBAN_CANDIDATE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30})", re.IGNORECASE)


def _plausible_bban(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    digits = sum(c.isdigit() for c in compact[4:])
    return digits >= len(compact[4:]) * 0.6 and compact[:2].isalpha() and compact[:2].isupper()


def detect_ibans(text: str) -> list[Span]:
    spans: list[Span] = []
    for m in _IBAN_CANDIDATE.finditer(text):
        raw = m.group(1)
        country = raw[:2].upper()
        expected = IBAN_LENGTHS.get(country)
        # walk the raw candidate, counting alphanumerics, to find the true end
        lengths = [expected] if expected else list(range(34, 14, -1))
        for target in lengths:
            count = 0
            end_idx = None
            for i, ch in enumerate(raw):
                if ch.isalnum():
                    count += 1
                    if count == target:
                        end_idx = i + 1
                        break
            if end_idx is None:
                continue
            candidate = raw[:end_idx]
            nxt = raw[end_idx : end_idx + 1]
            if nxt and nxt.isalnum():
                continue
            # a typo or a test value with a wrong check digit is still someone's bank account shape
            if iban_valid(candidate) or (expected and candidate[2:4].isdigit() and _plausible_bban(candidate)):
                s = m.start(1)
                spans.append(Span(s, s + end_idx, "IBAN", candidate, "pattern", kind="iban"))
                break
    return spans


# "No." in the languages we support: no, nr, n°, nº, n.º, n., núm., αρ., #, number
REF_MARKER = r"(?:no\.?|nr\.?|n\.?\s?[º°o]\.?|n\.|núm\.?|num\.?|αρ\.?|αριθ\.?|#|number)"


def load_pack(name: str) -> list[PatternSpec]:
    raw = resources.files("doublecast.packs").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    specs: list[PatternSpec] = []
    for p in data.get("patterns", []) or []:
        flags = re.IGNORECASE if p.get("ignore_case", True) else 0
        spec = _spec(
            p["name"],
            p["category"],
            p["regex"].replace("{MARKER}", REF_MARKER),
            group=int(p.get("group", 0)),
            validator=p.get("validator"),
            context=p.get("context", []),
            window=int(p.get("window", 40)),
            flags=flags,
            languages=p.get("languages", []),
        )
        spec.detector = "pack"
        spec.require_digit = bool(p.get("require_digit", p["category"] in ("ID", "NATIONAL_ID")))
        specs.append(spec)
    return specs


def load_pack_meta(name: str) -> dict:
    raw = resources.files("doublecast.packs").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw) or {}


def detect_patterns(text: str, specs: list[PatternSpec], languages: list[str]) -> list[Span]:
    spans: list[Span] = []
    for spec in specs:
        if spec.languages and not any(lang in languages for lang in spec.languages):
            continue
        for m in spec.regex.finditer(text):
            s, e = m.span(spec.group)
            if e <= s:
                continue
            value = text[s:e]
            stripped = value.strip()
            if stripped != value:
                lead = len(value) - len(value.lstrip())
                s, e, value = s + lead, s + lead + len(stripped), stripped
            if spec.require_digit:
                if not any(c.isdigit() for c in value):
                    continue
                if value.isdigit() and len(value) < 5:  # years, small counts
                    continue
            if spec.validator and not VALIDATORS[spec.validator](value):
                continue
            if not spec.context_ok(text, s, e):
                continue
            spans.append(Span(s, e, spec.category, value, spec.detector, kind=spec.name))
    return spans
