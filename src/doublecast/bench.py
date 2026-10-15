"""Leak benchmark on synthetic multilingual business text.

What it measures (all on generated data, nothing real):

* Leak rate: share of sensitive values still present verbatim after scrambling,
  split by "listed" (in your term lists or caught by patterns) and
  "unlisted" names (not listed, no AI detector), which shows the gap honestly.
* Round-trip: restore(scramble(doc)) == doc.
* Mangled restore: the stand-in is restored even after a model upper-cases it,
  adds a possessive, or (Greek) puts it in the genitive.
* Ratio error: how far ratios between amounts drift after scaling.
* Speed.
"""

from __future__ import annotations

import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from decimal import Decimal

from .data.names import FIRST_NAMES as N_FIRST
from .numbers import MONEY_RE, parse_number
from .textnorm import fold, stem_key
from .validators import afm_complete, iban_with_check, luhn_complete

LANGS = ["el", "en", "de", "fr", "it", "es"]

ORGS = {
    "el": ["Καρανίκας Τρόφιμα", "Μελισσάκης", "Ζαφειρόπουλος", "Αργυράκης", "Στεφανίδης Διανομές", "Παλαμίδης"],
    "en": [
        "Harborline Foods",
        "Kestrel Retail",
        "Bramwell Grocers",
        "Northgate Wholesale",
        "Ashby Markets",
        "Calder Trading",
    ],
    "de": [
        "Brennwald Handel",
        "Feldkamp Lebensmittel",
        "Hollmann Markt",
        "Stauffen Großhandel",
        "Wiesberg Frische",
        "Lindtal Vertrieb",
    ],
    "fr": [
        "Maisonneuve Distribution",
        "Bellerive Marchés",
        "Duverger Alimentaire",
        "Clairmont Épiceries",
        "Valcourt Négoce",
        "Rochebrune",
    ],
    "it": [
        "Valdarno Alimentari",
        "Bellandi Distribuzione",
        "Castellari Market",
        "Ferrandi Grossisti",
        "Montevago",
        "Ronchetti Food",
    ],
    "es": [
        "Alcázar Distribución",
        "Montoro Alimentación",
        "Valdecañas Market",
        "Herrera Mayoristas",
        "Torrealba",
        "Castellón Frescos",
    ],
}
PEOPLE = {
    "el": ["Ευάγγελος Μπαλτάς", "Σταυρούλα Κανελλοπούλου", "Ηλίας Τσολάκης", "Ροδάνθη Βέργου"],
    "en": ["Gregory Ashcombe", "Philippa Rowntree", "Desmond Okafor", "Imogen Faulkner"],
    "de": ["Reinhard Oberholzer", "Gisela Pfannkuch", "Detlef Ammermann", "Ulrike Stöckl"],
    "fr": ["Gaspard Lemoine", "Ségolène Marchais", "Thibault Vasseur", "Apolline Ricard"],
    "it": ["Ottavio Bersani", "Ludovica Sartori", "Gianmarco Pellegrini", "Benedetta Fumagalli"],
    "es": ["Fermín Arriaga", "Remedios Valcárcel", "Anselmo Quiroga", "Inmaculada Ferrer"],
}
UNLISTED = {
    "el": ["Παρασκευάς Γιαννόπουλος", "Αικατερίνη Δούκα"],
    "en": ["Bartholomew Pennington", "Henrietta Clarke"],
    "de": ["Wolfgang Eichhorn", "Hildegard Brandl"],
    "fr": ["Edmond Labrousse", "Bérénice Fauchet"],
    "it": ["Teodoro Brambilla", "Annunziata Cerri"],
    "es": ["Eusebio Larrañaga", "Encarnación Ochoa"],
}
SITES = {
    "el": ["Εργοστάσιο Λάρισας", "Αποθήκη Ασπροπύργου"],
    "en": ["Leeds Bakery Plant", "Didcot Warehouse"],
    "de": ["Werk Biberach", "Lager Kassel"],
    "fr": ["Usine de Vitré", "Entrepôt de Rungis"],
    "it": ["Stabilimento di Lodi", "Magazzino di Nola"],
    "es": ["Fábrica de Alcalá", "Almacén de Getafe"],
}
TEMPLATES = {
    "el": [
        "Η {org} ζητά έκπτωση {pct}% στο τιμολόγιο αρ. {inv}. Ο {person} θα στείλει τα στοιχεία στο {email}.",
        "Σύμφωνα με τον {person}, οι πωλήσεις της {org_gen} έφτασαν τα {money}. Τηλ. {phone}.",
        "Πληρωμή στο IBAN {iban}, ΑΦΜ {afm}. Παράδοση από {site}. Υπεύθυνος: {unlisted}.",
        "Ο λογαριασμός της {org_gen} έκλεισε με {money} και ΑΜΚΑ υπαλλήλου {amka}. Κλειδί: {secret}",
    ],
    "en": [
        "{org} is asking for {pct}% off invoice no. {inv}. {person} will send details to {email}.",
        "According to {person}, sales at {org} reached {money}. Call {phone} for the breakdown.",
        "Pay to IBAN {iban}, VAT {afm}. Ship from {site}. Contact: {unlisted}.",
        "{org}'s account closed at {money}; their API key {secret} must be rotated.",
    ],
    "de": [
        "{org} verlangt {pct}% Rabatt auf Rechnung Nr. {inv}. {person} schickt die Daten an {email}.",
        "Laut {person} erreichte der Umsatz bei {org} {money}. Telefon {phone}.",
        "Zahlung an IBAN {iban}, VAT {afm}. Lieferung ab {site}. Ansprechpartner: {unlisted}.",
    ],
    "fr": [
        "{org} demande {pct}% de remise sur la facture n° {inv}. {person} enverra les détails à {email}.",
        "Selon {person}, les ventes chez {org} ont atteint {money}. Tél. {phone}.",
        "Paiement sur IBAN {iban}, VAT {afm}. Expédition depuis {site}. Contact : {unlisted}.",
    ],
    "it": [
        "{org} chiede uno sconto del {pct}% sulla fattura n. {inv}. {person} invierà i dettagli a {email}.",
        "Secondo {person}, le vendite di {org} hanno raggiunto {money}. Tel. {phone}.",
        "Pagamento su IBAN {iban}, VAT {afm}. Spedizione da {site}. Referente: {unlisted}.",
    ],
    "es": [
        "{org} pide un {pct}% de descuento en la factura n.º {inv}. {person} enviará los datos a {email}.",
        "Según {person}, las ventas de {org} alcanzaron {money}. Tel. {phone}.",
        "Pago al IBAN {iban}, VAT {afm}. Envío desde {site}. Contacto: {unlisted}.",
    ],
}
COUNTRY = {"el": "GR", "en": "GB", "de": "DE", "fr": "FR", "it": "IT", "es": "ES"}
IBAN_LEN = {"GR": 27, "GB": 22, "DE": 22, "FR": 27, "IT": 27, "ES": 24}


def _greek_genitive(name: str) -> str:
    words = name.split()
    w = words[0]
    if w.endswith("ης"):
        w = w[:-2] + "η"
    elif w.endswith("ος"):
        w = w[:-2] + "ου"
    elif w.endswith("ας"):
        w = w[:-2] + "α"
    return " ".join([w] + words[1:])


@dataclass
class Doc:
    lang: str
    text: str
    values: dict[str, list[str]] = field(default_factory=dict)
    amounts: list[Decimal] = field(default_factory=list)


def _money(rng: random.Random, lang: str) -> tuple[str, Decimal]:
    value = Decimal(rng.randint(1000, 9_000_000)) / 100
    whole, cents = f"{value:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    if lang == "en":
        return f"€{','.join(groups)}.{cents}", value
    return f"{'.'.join(groups)},{cents} €", value


def make_corpus(n: int, seed: int) -> list[Doc]:
    rng = random.Random(seed)
    docs = []
    for lang in LANGS:
        for _ in range(n):
            t = rng.choice(TEMPLATES[lang])
            org = rng.choice(ORGS[lang])
            person = rng.choice(PEOPLE[lang])
            unlisted = rng.choice(UNLISTED[lang])
            site = rng.choice(SITES[lang])
            email = f"{rng.choice(['sales', 'orders', 'j.doe', 'acc'])}{rng.randint(1, 99)}@{rng.choice(['harbor', 'kestrel', 'brenn', 'valcourt'])}-co.com"
            phone = (
                "+30 69" + str(rng.randint(10_000_000, 99_999_999))
                if lang == "el"
                else f"+44 7{rng.randint(100, 999)} {rng.randint(100000, 999999)}"
            )
            cc = COUNTRY[lang]
            bban_len = IBAN_LEN[cc] - 4
            bban = "".join(rng.choice("0123456789") for _ in range(bban_len))
            iban = iban_with_check(cc, bban)
            iban = " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
            afm = afm_complete(str(rng.randint(10_000_000, 99_999_999)))
            amka = luhn_complete(
                f"{rng.randint(1, 28):02d}{rng.randint(1, 12):02d}{rng.randint(50, 99)}" + str(rng.randint(1000, 9999))
            )
            inv = f"INV-{rng.randint(2020, 2026)}/{rng.randint(1000, 9999)}"
            secret = "sk-ant-api03-" + "".join(rng.choice("abcdefghijkmnpqrstuvwxyz0123456789") for _ in range(32))
            money1, v1 = _money(rng, lang)
            fields = {
                "org": org,
                "org_gen": _greek_genitive(org) if lang == "el" else org,
                "person": person,
                "unlisted": unlisted,
                "site": site,
                "email": email,
                "phone": phone,
                "iban": iban,
                "afm": afm,
                "amka": amka,
                "inv": inv,
                "secret": secret,
                "money": money1,
                "pct": rng.randint(2, 15),
            }
            text = t.format(**fields)
            values: dict[str, list[str]] = {}
            used = set(re.findall(r"{(\w+)}", t))
            mapping = {
                "org": "ORG",
                "org_gen": "ORG",
                "person": "PERSON",
                "site": "SITE",
                "email": "EMAIL",
                "phone": "PHONE",
                "iban": "IBAN",
                "afm": "TAX_ID",
                "amka": "NATIONAL_ID",
                "inv": "ID",
                "secret": "SECRET",
                "unlisted": "UNLISTED_PERSON",
                "money": "MONEY",
            }
            for k in used:
                if k in mapping:
                    values.setdefault(mapping[k], []).append(str(fields[k]))
            docs.append(Doc(lang, text, values, [v1] if "money" in used else []))
    return docs


def run_benchmark(n: int = 300, seed: int = 7) -> str:
    from .config import Config, Term
    from .engine import Engine

    with tempfile.TemporaryDirectory() as tmp:
        terms = [Term("ORG", o) for lang in LANGS for o in ORGS[lang]]
        terms += [Term("PERSON", p) for lang in LANGS for p in PEOPLE[lang]]
        terms += [Term("SITE", s) for lang in LANGS for s in SITES[lang]]
        cfg = Config(workspace="bench", home=__import__("pathlib").Path(tmp), terms=terms, ner_enabled="off")
        engine = Engine(cfg)
        docs = make_corpus(n, seed)

        leaks: dict[str, list[int]] = {}
        roundtrip_ok = roundtrip_total = 0
        mangled_ok = mangled_total = 0
        ratio_errors: list[float] = []
        chars = 0
        t0 = time.perf_counter()
        rng = random.Random(seed + 1)
        scramble_time = 0.0
        for doc in docs:
            ts = time.perf_counter()
            result = engine.scramble(doc.text)
            scramble_time += time.perf_counter() - ts
            chars += len(doc.text)
            for cat, vals in doc.values.items():
                bucket = leaks.setdefault(cat, [0, 0])
                for v in vals:
                    if cat == "MONEY":
                        continue
                    bucket[1] += 1
                    if v in result.text:
                        bucket[0] += 1
            if "SECRET" not in doc.values:
                roundtrip_total += 1
                if engine.restore(result.text) == doc.text:
                    roundtrip_ok += 1
            reverse = {m.surrogate: m.original for m in engine.vault.mappings()}
            for cat, _original, stand_in in result.replacements:
                if cat not in ("ORG", "PERSON", "SITE") or stand_in not in reverse:
                    continue
                mangled_total += 1
                variant = rng.choice(["upper", "possessive", "genitive" if doc.lang == "el" else "upper"])
                if variant == "upper":
                    mangled = stand_in.upper()
                elif variant == "possessive":
                    mangled = stand_in + "'s"
                else:
                    mangled = _greek_genitive(stand_in)
                restored = fold(engine.restore(f"Report on {mangled} today."))
                if stem_key(fold(reverse[stand_in])).replace("\x00", "") in stem_key(restored).replace("\x00", ""):
                    mangled_ok += 1
            for amount in doc.amounts:
                for m in MONEY_RE.finditer(result.text):
                    token = m.group("n1") or m.group("n2")
                    parsed = parse_number(token)
                    if parsed:
                        scaled_value = parsed[0]
                        ratio_errors.append(float(abs(scaled_value / (engine.numbers.k_money * amount) - 1)))
                    break
        elapsed = time.perf_counter() - t0
        engine.vault.close()

    lines = [
        "# Doublecast leak benchmark",
        "",
        f"Synthetic corpus: {len(docs)} short business documents, {n} per language ({', '.join(LANGS)}), seed {seed}.",
        "Listed = in the term lists or caught by a pattern detector. Unlisted = a person name nobody listed (AI detector off).",
        "",
        "| Category | Values | Leaked | Leak rate |",
        "|---|---:|---:|---:|",
    ]
    for cat in sorted(leaks, key=lambda c: (c == "UNLISTED_PERSON", c)):
        leaked, total = leaks[cat]
        if total:
            lines.append(f"| {cat} | {total} | {leaked} | {leaked / total:.1%} |")
    lines += [
        "",
        f"- **Round-trip exact restore:** {roundtrip_ok}/{roundtrip_total} ({roundtrip_ok / max(roundtrip_total, 1):.1%})",
        f"- **Restore after model mangling** (upper-case, possessive, Greek genitive): {mangled_ok}/{mangled_total} ({mangled_ok / max(mangled_total, 1):.1%})",
        f"- **Ratio drift from money scaling** (rounding to cents): max {max(ratio_errors, default=0):.2e}, mean {sum(ratio_errors) / max(len(ratio_errors), 1):.2e}",
        f"- **Scramble speed:** {chars / max(scramble_time, 1e-9) / 1024:.0f} KB/s on this machine, starting from an empty vault ({elapsed:.1f}s for the whole benchmark)",
        "",
        "Unlisted names leak by design when no AI detector is installed: list your people and partners,",
        "or install the optional detector (`pip install 'doublecast[ner]'`) as a safety net.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("DOUBLECAST_HOME", tempfile.mkdtemp())
    print(run_benchmark())


# ---------------------------------------------------------------- auto mode (no lists at all)
LEGAL = {"el": "ΑΕ", "en": "Ltd", "de": "GmbH", "fr": "SAS", "it": "S.r.l.", "es": "S.L."}
GREET = {"el": "Αγαπητέ", "en": "Dear", "de": "Hallo", "fr": "Bonjour", "it": "Ciao", "es": "Hola"}
SIGN = {
    "el": "Με εκτίμηση",
    "en": "Kind regards",
    "de": "Viele Grüße",
    "fr": "Cordialement",
    "it": "Cordiali saluti",
    "es": "Saludos",
}
TITLE = {"el": "κ.", "en": "Mr", "de": "Herr", "fr": "M.", "it": "Sig.", "es": "Sr."}
MID = {
    "el": "Χθες μιλήσαμε με τον {name} για την παραγγελία.",
    "en": "Yesterday we spoke with {name} about the order.",
    "de": "Gestern haben wir mit {name} über die Bestellung gesprochen.",
    "fr": "Hier nous avons parlé avec {name} de la commande.",
    "it": "Ieri abbiamo parlato con {name} dell'ordine.",
    "es": "Ayer hablamos con {name} sobre el pedido.",
}
START = {
    "el": "{name} θα επιβεβαιώσει αύριο.",
    "en": "{name} will confirm tomorrow.",
    "de": "{name} bestätigt morgen.",
    "fr": "{name} confirmera demain.",
    "it": "{name} confermerà domani.",
    "es": "{name} confirmará mañana.",
}


_SYL = {
    "el": (
        ["Παπα", "Καρα", "Μαυρο", "Χατζη", "Σταυρο", "Λαζα", "Μπου", "Τσου", "Γιαννα", "Κουτσο"],
        ["δάκης", "πουλος", "γιάννης", "ρίδης", "λάκης", "νίδης", "κάκης", "μάνος"],
    ),
    "en": (
        ["Ash", "Brad", "Carr", "Dun", "Elling", "Fair", "Gold", "Hart", "Kings", "Lang"],
        ["worth", "ley", "ford", "ham", "ton", "wick", "more", "by"],
    ),
    "de": (
        ["Ober", "Stein", "Kling", "Ross", "Wald", "Hollen", "Eber", "Brand"],
        ["mann", "hauser", "berger", "maier", "hofer", "bach", "feld", "kamp"],
    ),
    "fr": (
        ["Beau", "Mont", "Ville", "Roche", "Belle", "Font", "Lac", "Clair"],
        ["mont", "ville", "fort", "champ", "lieu", "mard", "rive", "court"],
    ),
    "it": (
        ["Bel", "Mon", "Ross", "Ber", "Casa", "Fonta", "Lom", "Mar"],
        ["lini", "tani", "vecchi", "nardi", "relli", "zotti", "betti", "ghini"],
    ),
    "es": (
        ["Al", "Bel", "Cas", "Mon", "Val", "Ri", "Oli", "Fer"],
        ["varez", "monte", "tillo", "garra", "verde", "zuela", "cedo", "ranz"],
    ),
}


def _unique_names(lang: str, rng: random.Random, used: set[str]):
    """Endless supply of realistic, never-repeated full names for one language."""
    firsts = N_FIRST[lang if lang in N_FIRST else "en"]
    heads, tails = _SYL[lang]
    mids = (
        ["", "νο", "λο", "ρο", "μα", "τζο", "κο", "πα", "τα", "σο", "βα", "δο"]
        if lang == "el"
        else ["", "en", "ar", "il", "or", "um", "an", "et", "ol", "is", "ad", "ur"]
    )
    for _ in range(1_000_000):
        surname = f"{rng.choice(heads)}{rng.choice(mids)}{rng.choice(tails)}"
        if surname not in used:
            used.add(surname)
            yield f"{rng.choice(firsts)} {surname}"
    raise RuntimeError("name pool exhausted")


RARE_FIRST = {
    "el": ["Ευδοκία", "Λεωνίδας", "Ισιδώρα", "Αριστείδης", "Πολυξένη", "Ευστάθιος"],
    "en": ["Gwendolyn", "Ignatius", "Philippa", "Lysander", "Winifred", "Bartholomew"],
    "de": ["Wilhelmina", "Gottfried", "Hildegard", "Ludwig", "Irmgard", "Siegfried"],
    "fr": ["Aurèle", "Bérénice", "Gaspard", "Solange", "Anatole", "Ermeline"],
    "it": ["Ignazio", "Annunziata", "Ottavio", "Liliana", "Tancredi", "Eufemia"],
    "es": ["Leocadia", "Eusebio", "Remedios", "Anselmo", "Inmaculada", "Fermín"],
}
# Held out: none of these sentences was used to build the business-vocabulary filter.
ORDINARY = [
    "Last week we discussed the Annual Leave Policy and the Customer Satisfaction Survey with HR.",
    "The plan covers the Cold Storage Upgrade, Inventory Turnover and Lead Time targets.",
    "Το νέο Πρόγραμμα Εκπαίδευσης ξεκινά μετά την Ετήσια Απογραφή στην αποθήκη.",
    "Please review the Purchase Requisition and the Shelf Life data before the Line Trial.",
]


def run_auto_benchmark(n: int = 100, seed: int = 11) -> str:
    """Leak rates with NO term lists: only structure, the broad net and self-learning."""
    import pathlib

    from .config import Config
    from .engine import Engine

    rng = random.Random(seed)
    buckets: dict[str, list[int]] = {}

    def check(bucket: str, value: str, out: str) -> None:
        b = buckets.setdefault(bucket, [0, 0])
        b[1] += 1
        if value in out:
            b[0] += 1

    with tempfile.TemporaryDirectory() as tmp:
        engine = Engine(Config(workspace="auto", home=pathlib.Path(tmp), ner_enabled="off"))
        used: set[str] = set()
        for lang in LANGS:
            names = _unique_names(lang, rng, used)
            for _ in range(n):
                # every name is new: nothing can have been learned from an earlier email
                sender, recipient, third, fourth = next(names), next(names), next(names), next(names)
                heads, tails = _SYL[lang]
                org_core = f"{next(names).split()[-1]} {rng.choice(ORGS[lang]).split()[-1]}"
                org = f"{org_core} {LEGAL[lang]}"
                first = recipient.split()[0]
                surname = sender.split()[-1]
                email = (
                    f"From: {sender} <{surname.lower()}@example.com>\nTo: {recipient} <x@example.org>\n\n"
                    f"{GREET[lang]} {first},\n\n{org} — {TITLE[lang]} {surname}.\n\n{SIGN[lang]},\n{sender}\n"
                )
                out = engine.scramble(email).text
                check("1 email header names", sender, out.split("\n\n")[0])
                check("2 greeting first names", first, out.split("\n\n")[1] if "\n\n" in out else out)
                check("3 company with legal form", org_core, out)
                check("4 title + surname", f"{TITLE[lang]} {surname}", out)
                later = engine.scramble(f"{org_core.lower()} — {sender.lower()}").text
                check("5 seen before, mentioned later without structure", sender.lower(), later)
                mid = engine.scramble(MID[lang].format(name=third)).text
                check("6 new name mid-sentence (broad net)", third, mid)
                start = engine.scramble(START[lang].format(name=fourth)).text
                check("7 new name at sentence start, common first name", fourth, start)
                rare = f"{rng.choice(RARE_FIRST[lang])} {next(names).split()[-1]}"
                rare_out = engine.scramble(START[lang].format(name=rare)).text
                check("8 new name at sentence start, uncommon first name (known gap)", rare, rare_out)
        # cost of over-protection: ordinary capitalised business phrases that get swapped anyway
        phrases = [
            "Annual Leave Policy",
            "Customer Satisfaction Survey",
            "Cold Storage Upgrade",
            "Inventory Turnover",
            "Lead Time",
            "Πρόγραμμα Εκπαίδευσης",
            "Ετήσια Απογραφή",
            "Purchase Requisition",
            "Shelf Life",
            "Line Trial",
        ]
        joined = " ".join(engine.scramble(t).text for t in ORDINARY)
        swapped = [ph for ph in phrases if ph not in joined]
        engine.vault.close()

    lines = [
        "# Doublecast auto-mode benchmark (no lists)",
        "",
        f"{n} synthetic emails per language ({', '.join(LANGS)}), seed {seed}. No term lists, no AI model:",
        "only email structure, company legal forms, the capitalised-name net and self-learning.",
        "",
        "| Situation | Values | Leaked | Leak rate |",
        "|---|---:|---:|---:|",
    ]
    for k in sorted(buckets):
        leaked, total = buckets[k]
        lines.append(f"| {k[2:]} | {total} | {leaked} | {leaked / total:.1%} |")
    lines += [
        "",
        f"**Over-protection** (held-out phrases): {len(swapped)} of {len(phrases)} ordinary capitalised business phrases were swapped "
        f"too ({', '.join(swapped) or 'none'}). Harmless for privacy, but the AI sees an invented name instead. "
        "Set `auto.capitalized_phrases: false` to trade some recall for cleaner text.",
        "",
        "A name that appears for the first time at the start of a sentence is caught when its first name",
        "is a common one; otherwise it is the remaining gap without lists or an AI model.",
        "`doublecast discover` closes it for every name that exists in your systems.",
    ]
    return "\n".join(lines)
