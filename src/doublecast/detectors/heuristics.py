"""Find names in free text without any list or AI model.

Business text gives names away by its structure:

* email headers      From: Eleni Papadopoulou <eleni@...>   Προς: ...
* greetings          Dear Nikos,   Αγαπητέ κ. Ανδρέου,   Hallo Herr Weber,
* titles             Mr Andreou, κα Παπαδοπούλου, Frau Weber, Dr. Rossi
* sign-offs          Kind regards,\\n Eleni Papadopoulou
* legal forms        Nordia Hellas S.A., Καρανίκας Τρόφιμα ΑΕ, Brennwald GmbH
* (optional) any run of 2-4 Capitalised Words in mid-sentence

The first five are "strong" signals: what they find is remembered
(self-learning), so the same name is caught everywhere afterwards, even
where no structure gives it away. The last one is a broad net that over-
protects on purpose; its finds are swapped but not remembered.
"""

from __future__ import annotations

import functools
import re

from ..data import names as N
from ..textnorm import fold, is_greek
from .base import Span

_UP = "A-ZΑ-ΩΆΈΉΊΌΎΏÀ-ÖØ-ÞĀ-Ž"
_LOW = "a-zα-ωάέήίόύώϊϋΐΰςß-öø-ÿā-ž"
_NAME_WORD = rf"[{_UP}][{_LOW}'’\-]+"
_NAME = rf"{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}}"

STOP_NAMES = {
    fold(w)
    for w in (
        "team",
        "all",
        "everyone",
        "guys",
        "colleagues",
        "sir",
        "madam",
        "sirs",
        "there",
        "friends",
        "both",
        "ομαδα",
        "ολους",
        "ολοι",
        "σας",
        "παιδια",
        "συναδελφοι",
        "κυριε",
        "κυρια",
        "kollegen",
        "zusammen",
        "alle",
        "tous",
        "equipe",
        "tutti",
        "todos",
        "equipo",
        "customer",
        "client",
        "partner",
        "support",
    )
}
# Shared mailboxes and departments are not people: "Sales Team <sales@...>"
DEPARTMENTS = {
    fold(w)
    for w in (
        "sales",
        "finance",
        "accounting",
        "accounts",
        "marketing",
        "info",
        "support",
        "admin",
        "orders",
        "order",
        "logistics",
        "hr",
        "it",
        "purchasing",
        "procurement",
        "service",
        "services",
        "office",
        "reception",
        "helpdesk",
        "noreply",
        "no-reply",
        "billing",
        "invoices",
        "export",
        "exports",
        "quality",
        "production",
        "team",
        "department",
        "desk",
        "management",
        "board",
        "newsletter",
        "notifications",
        "πωλησεις",
        "λογιστηριο",
        "προμηθειες",
        "αγορες",
        "εξαγωγες",
        "ποιοτητα",
        "παραγωγη",
        "γραμματεια",
        "τμημα",
        "verkauf",
        "vertrieb",
        "buchhaltung",
        "einkauf",
        "ventes",
        "comptabilite",
        "achats",
        "vendite",
        "contabilita",
        "acquisti",
        "ventas",
        "contabilidad",
        "compras",
    )
}

_GREETING = re.compile(
    rf"(?im)^[ \t>]*(?:Dear|Hi|Hello|Hey|Good (?:morning|afternoon|evening)|Αγαπητ[έήοί]ς?|Καλημέρα|Καλησπέρα|"
    rf"Γεια σ(?:ου|ας)|Liebe[r]?|Sehr geehrte[r]?|Hallo|Guten (?:Morgen|Tag)|Cher|Chère|Bonjour|Caro|Cara|"
    rf"Gentile|Buongiorno|Ciao|Estimad[oa]|Hola|Buenos días)[ \t]+"
    rf"(?:(?:Mr|Mrs|Ms|Dr|Herr|Frau|M|Mme|Sig|Sig\.ra|Sr|Sra|κ|κα|κας|κυρ(?:ιε|ία))\.?[ \t]+)?"
    rf"(?P<name>{_NAME})[ \t]*(?:[,!:\n]|$)"
)
_TITLE = re.compile(
    rf"(?<![\w.])(?:Mr|Mrs|Ms|Dr|Prof|Herr|Frau|Mme|Mlle|M(?=\.)|Sig\.ra|Sig|Sra|Sr|κ|κα|κας|κου|κυρ(?:ίου|ίας|ιε|ία))\.?"
    rf"[ \t]+(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
)
_HEADER = re.compile(
    r"(?im)^[ \t>]*(?:From|To|Cc|Bcc|Reply-To|Sent by|Από|Προς|Κοιν(?:οποίηση)?|Von|An|De|À|Da|A|Para|CC)[ \t]*:[ \t]*(?P<value>.+)$"
)
_HEADER_PERSON = re.compile(rf"(?P<name>{_NAME})[ \t]*(?:<[^>]+>|\[mailto:[^\]]+\]|\([^)]*@[^)]*\))")
_SIGNOFF = re.compile(
    r"(?im)^[ \t>]*(?:Kind regards|Best regards|Warm regards|Regards|Best|Thanks|Thank you|Many thanks|Cheers|Sincerely|"
    r"Με εκτίμηση|Με φιλικούς χαιρετισμούς|Φιλικά|Ευχαριστώ(?: πολύ)?|Χαιρετισμούς|Mit freundlichen Grüßen|Viele Grüße|"
    r"Beste Grüße|Cordialement|Bien à vous|Cordiali saluti|Distinti saluti|Saludos|Un saludo|Atentamente)[ \t]*[,.!]?[ \t]*\n"
    rf"[ \t>]*(?P<name>{_NAME})[ \t]*$"
)
_LEGAL = re.compile(
    rf"(?P<name>(?:{_NAME_WORD}|[{_UP}]{{2,}})(?:[ \t]+(?:&[ \t]+)?(?:{_NAME_WORD}|[{_UP}]{{2,}})){{0,4}})"
    r"[ \t]*,?[ \t]+(?P<form>S\.A\.|SA|A\.E\.|ΑΕ|Α\.Ε\.|ΑΕΒΕ|ΑΒΕΕ|Α\.Β\.Ε\.Ε\.|ΕΠΕ|Ε\.Π\.Ε\.|ΙΚΕ|Ι\.Κ\.Ε\.|Ο\.Ε\.|"
    r"Ltd\.?|Limited|LLC|Inc\.?|Corp\.?|PLC|GmbH|AG|KG|SAS|SARL|S\.p\.A\.|SpA|S\.r\.l\.|Srl|S\.L\.|B\.V\.|N\.V\.)(?![\w])"
)
_CAPS = re.compile(
    rf"(?:(?<=[{_LOW},;:(\"'] )|(?<=^[-•*] )|(?<=\n[-•*] ))(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,3}})"
)
_FIRST_LAST_AT_START = re.compile(
    rf"(?:^|(?<=[.!?:]\s)|(?<=\n))[ \t]*(?P<first>{_NAME_WORD})[ \t]+(?P<last>{_NAME_WORD})(?=[ \t,.;:!?)]|$)", re.M
)
_FIRST_NAME_ALONE = re.compile(rf"(?<=[{_LOW},;:] )(?P<name>{_NAME_WORD})(?![\w'’\-])(?![ \t]*{_NAME_WORD})")

_COMMON_CAPS = {
    fold(w)
    for w in (
        "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August "
        "September October November December Q1 Q2 Q3 Q4 Excel Word PowerPoint Outlook Teams Power BI Microsoft "
        "Google Apple Amazon LinkedIn Claude Code ChatGPT OpenAI Anthropic Gemini Codex GitHub Python Windows Mac "
        "Δευτέρα Τρίτη Τετάρτη Πέμπτη Παρασκευή Σάββατο Κυριακή Ιανουάριος Φεβρουάριος Μάρτιος Απρίλιος Μάιος "
        "Ιούνιος Ιούλιος Αύγουστος Σεπτέμβριος Οκτώβριος Νοέμβριος Δεκέμβριος Ελλάδα Αθήνα Θεσσαλονίκη Greece "
        "Athens Europe European Union EU USA UK Germany France Italy Spain Cyprus"
    ).split()
}


_FIRST_NAMES = {fold(n) for n in N.RECOGNISED_FIRST_NAMES}


# Everyday business vocabulary. A Capitalised Phrase made only of these words is a heading or a
# concept ("Supply Chain", "Price List", "Νέα Σειρά"), not a name, so the broad net leaves it alone.
BUSINESS_WORDS = {
    fold(w)
    for w in """
    supply chain net gross sales key account accounts western eastern northern southern central europe european
    price prices list lists delivery deliveries schedule trade fair board meeting meetings dashboard report reports
    plan plans planning budget forecast review reviews annual quarterly monthly weekly daily general manager
    director directors department team project product products quality new old series range line lines
    customer customers service services supplier suppliers purchase purchasing order orders invoice invoices
    payment payments terms condition conditions contract contracts agreement agreements policy policies
    marketing finance financial operations operational production logistics warehouse transport distribution
    export exports import imports market markets share growth target targets total revenue revenues cost costs
    margin margins profit loss statement balance sheet cash flow working capital capex opex kpi kpis summary
    executive committee steering strategy strategic business unit units region regional national international
    global local head office branch store stores channel channels retail wholesale online food service
    category categories brand brands promotion promotions campaign campaigns launch launches pilot phase
    data analysis analytics model system systems platform process processes procedure standard standards
    safety health environment human resources training development research innovation technology it
    action actions item items next steps update updates status open issues risks risk register minutes agenda
    the of and for to in on at by with from a an new year end start first second third final draft version
    διευθυνση διευθυνσης τμημα τμηματος πωλησεων πωλησεις ποιοτητας ποιοτητα νεα νεος νεο σειρα σειρας
    παραγωγης παραγωγη αποθηκης εφοδιαστικης αλυσιδας εξαγωγων εξαγωγες οικονομικων οικονομικη υπηρεσια
    υπηρεσιες προμηθειων αγορων εμπορικη εμπορικης γενικη γενικος διευθυντης διευθυντρια ομαδα εργου
    προυπολογισμος προυπολογισμου τιμοκαταλογος τιμοκαταλογου συμβαση συμβασης συμφωνια ετησια μηνιαια
    αναφορα αναφορας συναντηση συναντησης συμβουλιο διοικητικο διοικητικου στρατηγικη σχεδιο σχεδιασμος
    vertrieb einkauf verkauf qualität produktion lager logistik bericht planung preisliste lieferung
    ventes achats qualité production entrepôt logistique rapport planification tarif livraison
    vendite acquisti qualità produzione magazzino logistica rapporto pianificazione listino consegna
    ventas compras calidad producción almacén logística informe planificación tarifa entrega
    """.split()
}


@functools.lru_cache(maxsize=50000)
def is_common_word(word: str) -> bool:
    """True for ordinary vocabulary in any of our languages (word-frequency lists, offline)."""
    w = word.lower().strip(".,;:'’()")
    if fold(w) in BUSINESS_WORDS or fold(w) in STOP_NAMES:
        return True
    try:
        from wordfreq import zipf_frequency
    except ImportError:  # pragma: no cover - optional dependency missing
        return False
    langs = ("el",) if is_greek(w) else ("en", "de", "fr", "it", "es")
    # 3.75 separates everyday words (policy 5.2, turnover 3.8) from most names (Eichhorn 3.1, Brandl 2.8);
    # common first names are recognised separately, so "Klaus Weber" is still a person.
    return max(zipf_frequency(w, lang) for lang in langs) >= 3.75


def _person_or_org(name: str) -> str:
    return (
        "ORG"
        if re.search(r"(?i)\b(?:foods?|market|markets|trading|group|hellas|holdings?|logistics|bank)\b", name)
        else "PERSON"
    )


def _clean(name: str) -> str | None:
    words = name.split()
    if any(fold(w) in DEPARTMENTS for w in words):
        return None
    while words and fold(words[-1]) in STOP_NAMES:
        words.pop()
    if not words or all(fold(w) in STOP_NAMES or fold(w) in _COMMON_CAPS for w in words):
        return None
    name = " ".join(words)
    return name if len(name) >= 3 else None


def detect_structure(text: str, capitalized_phrases: bool = False) -> list[Span]:
    spans: list[Span] = []

    def add(start: int, name: str, category: str, kind: str, strong: bool = True) -> None:
        cleaned = _clean(name)
        if not cleaned:
            return
        s = text.find(cleaned, start)
        if s < 0:
            return
        spans.append(Span(s, s + len(cleaned), category, cleaned, "heuristic", kind=kind, meta={"strong": strong}))

    for m in _HEADER.finditer(text):
        value_start = m.start("value")
        for pm in _HEADER_PERSON.finditer(m.group("value")):
            add(value_start + pm.start("name"), pm.group("name"), _person_or_org(pm.group("name")), "email_header")
    for m in _GREETING.finditer(text):
        add(m.start("name"), m.group("name"), "PERSON", "greeting")
    for m in _TITLE.finditer(text):
        add(m.start("name"), m.group("name"), "PERSON", "title")
    for m in _SIGNOFF.finditer(text):
        add(m.start("name"), m.group("name"), "PERSON", "signoff")
    for m in _LEGAL.finditer(text):
        # the whole legal name, form included ("Nordia Hellas S.A.")
        s, e = m.start("name"), m.end("form")
        name = text[s:e]
        words = [fold(w) for w in m.group("name").split()]
        if not all(w in STOP_NAMES or w in _COMMON_CAPS for w in words):  # "Vertrieb GmbH" is a company
            spans.append(Span(s, e, "ORG", name, "heuristic", kind="legal_form", meta={"strong": True}))
    if capitalized_phrases:
        for m in _FIRST_LAST_AT_START.finditer(text):
            # "Theodora Vlachaki will confirm." at a sentence start: only when the first word is a known first name
            if fold(m.group("first")) in _FIRST_NAMES and fold(m.group("last")) not in _COMMON_CAPS:
                spans.append(
                    Span(
                        m.start("first"),
                        m.end("last"),
                        "PERSON",
                        text[m.start("first") : m.end("last")],
                        "heuristic",
                        kind="first_last",
                        confidence=0.6,
                        meta={"strong": False},
                    )
                )
        for m in _FIRST_NAME_ALONE.finditer(text):
            if fold(m.group("name")) in _FIRST_NAMES:  # "..., said Maria."
                spans.append(
                    Span(
                        m.start("name"),
                        m.end("name"),
                        "PERSON",
                        m.group("name"),
                        "heuristic",
                        kind="first_name",
                        confidence=0.5,
                        meta={"strong": False},
                    )
                )
        for m in _CAPS.finditer(text):
            name = m.group("name")
            words = [fold(w) for w in name.split()]
            if all(w in _COMMON_CAPS or w in STOP_NAMES or w in BUSINESS_WORDS for w in words):
                continue
            raw_words = name.split()
            if not any(fold(w) in _FIRST_NAMES for w in raw_words) and all(is_common_word(w) for w in raw_words):
                continue  # "Annual Leave Policy", "Πρόγραμμα Εκπαίδευσης": vocabulary, not a name
            if any(w in DEPARTMENTS for w in words):
                continue
            spans.append(
                Span(
                    m.start("name"),
                    m.end("name"),
                    _person_or_org(name),
                    name,
                    "heuristic",
                    kind="capitalized",
                    confidence=0.5,
                    meta={"strong": False},
                )
            )
    return spans
