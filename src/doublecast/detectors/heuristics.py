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
from ..textnorm import fold, greek_stem, is_greek
from .base import Span

_UP = "A-ZΑ-ΩΆΈΉΊΌΎΏÀ-ÖØ-ÞĀ-Ž"
_LOW = "a-zα-ωάέήίόύώϊϋΐΰςß-öø-ÿā-ž"
# "Weber", "O'Neil", "Dupont-Leroy", "Müller-thurgau"; never ends in a hyphen
_NAME_WORD = rf"[{_UP}][{_LOW}'’]+(?:-[{_UP}{_LOW}][{_LOW}'’]*)*"
_NAME = rf"{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}}"
_B = r"(?<![\w'’\-])"  # left word boundary: "LinkedIn" never yields "In"

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
        "or",
        "and",
        "und",
        "oder",
        "et",
        "ou",
        "e",
        "o",
        "y",
        "και",
        "ή",
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
    rf"(?:(?:Mr|Mrs|Ms|Dr|Prof|med|Herr|Frau|M|Mme|Sig|Sig\.ra|Sr|Sra|κ|κα|κας|κε|κος|κυρ(?:ιε|ία)|κύρι(?:ε|ο)|Δρ)\.?[ \t]+)*"
    rf"(?P<name>{_NAME})[ \t]*(?:[,!:\n]|$)"
)
_TITLE = re.compile(
    # Latin titles in any case ("mr Andreou"); Sr./Sra./Sig. only with their dot ("Sr Manager" is "Senior")
    # stacked titles count as one: "Herr Dr. Schmidt", "Prof. Dr. med. Weber", "κύριε Δρ. Παπαδάκη"
    rf"(?<![\w.])(?:(?:(?i:mr|mrs|ms|dr|prof|herr|frau|mme|mlle)\.?|M\.|Sig\.ra|Sig\.|Sra\.|Sr\.|med\.|Δρ\.?|"
    rf"(?:κ|κα|κας|κε|κος|κο|κου|κυρ(?:ίου|ίας|ιε|ία)|κύρι(?:ε|ο|ος|ου))\.?)[ \t]+)+"
    rf"(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
)
_HEADER = re.compile(
    r"(?im)^[ \t>]*(?:From|To|Cc|Bcc|Reply-To|Sent by|Από|Προς|Κοιν(?:οποίηση)?|Von|An|De|À|Da|A|Para|CC)[ \t]*:[ \t]*(?P<value>.+)$"
)
_HEADER_PERSON = re.compile(rf"{_B}(?P<name>{_NAME})[ \t]*(?:<[^>]+>|\[mailto:[^\]]+\]|\([^)]*@[^)]*\))")
_SIGNOFF = re.compile(
    r"(?im)^[ \t>]*(?:Kind regards|Best regards|Warm regards|Regards|Best|Thanks|Thank you|Many thanks|Cheers|Sincerely|"
    r"Με εκτίμηση|Με φιλικούς χαιρετισμούς|Φιλικά|Ευχαριστώ(?: πολύ)?|Χαιρετισμούς|Mit freundlichen Grüßen|Viele Grüße|"
    r"Beste Grüße|Cordialement|Bien à vous|Cordiali saluti|Distinti saluti|Saludos|Un saludo|Atentamente)[ \t]*[,.!]?[ \t]*\n"
    rf"[ \t>]*(?P<name>{_NAME})[ \t]*$"
)
_LEGAL = re.compile(
    rf"{_B}(?P<name>(?:[{_UP}]\.[ \t]*)*(?:{_NAME_WORD}|[{_UP}]{{2,}})(?:[ \t]+(?:&[ \t]+)?(?:{_NAME_WORD}|[{_UP}]{{2,}}|[{_UP}]\.)){{0,4}})"
    r"[ \t]*,?[ \t]+(?P<form>S\.A\.|SA|A\.E\.|AEBE|ABEE|AE|EPE|IKE|ΑΕ|Α\.Ε\.|ΑΕΒΕ|ΑΒΕΕ|Α\.Β\.Ε\.Ε\.|ΕΠΕ|Ε\.Π\.Ε\.|ΙΚΕ|Ι\.Κ\.Ε\.|Ο\.Ε\.|"
    r"Ltd\.?|Limited|LLC|Inc\.?|Corp\.?|PLC|GmbH|AG|KG|SAS|SARL|S\.p\.A\.|SpA|S\.r\.l\.|Srl|S\.L\.|B\.V\.|N\.V\.)(?![\w])"
)
_CAPS = re.compile(
    rf"(?:(?<=[{_LOW},;:(\"'|] )|(?<=[,;|\t])|(?<=^[-•*] )|(?<=\n[-•*] ))(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,3}})"
    rf"(?![\w'’\-])"
)
_FIRST_LAST_AT_START = re.compile(
    rf"(?:^|(?<=[.!?:]\s)|(?<=\n))[ \t]*(?P<first>{_NAME_WORD})[ \t]+(?P<last>{_NAME_WORD})(?=[ \t,.;:!?)]|$)", re.M
)
# Greek article + one capitalised word: "ο Παπαδόπουλος", "της Καρανίκα", "τον Γιώργο" (nouns after an
# article are lower case in Greek, so a capital marks a proper noun)
_GREEK_ARTICLE = re.compile(
    r"(?<![\w])(?:ο|η|οι|του|της|τον|την|στον|στην|στου|στης|με τον|με την)[ \t]+"
    r"(?P<name>[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰς]+)(?![\w'’\-])"
)
_FIRST_NAME_ALONE = re.compile(rf"(?<=[{_LOW},;:] )(?P<name>{_NAME_WORD})(?![\w'’\-])(?![ \t]*{_NAME_WORD})")

_COMMON_CAPS_WORDS = (
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August "
    "September October November December Q1 Q2 Q3 Q4 Excel Word PowerPoint Outlook Teams Power BI Microsoft "
    "Google Apple Amazon LinkedIn Claude Code ChatGPT OpenAI Anthropic Gemini Codex GitHub Python Windows Mac "
    "Δευτέρα Τρίτη Τετάρτη Πέμπτη Παρασκευή Σάββατο Κυριακή Ιανουάριος Φεβρουάριος Μάρτιος Απρίλιος Μάιος "
    "Ιούνιος Ιούλιος Αύγουστος Σεπτέμβριος Οκτώβριος Νοέμβριος Δεκέμβριος Ελλάδα Αθήνα Θεσσαλονίκη Greece "
    "Athens Europe European Union EU USA UK Germany France Italy Spain Cyprus "
    # software and tech names that turn up capitalised in prompts and code
    "Pandas NumPy Requests Django Flask FastAPI Pydantic React Angular Vue Node Docker Kubernetes PostgreSQL "
    "MySQL SQLite SQL Server Azure AWS Linux Ubuntu Debian JavaScript TypeScript Java Rust Go Git Visual Studio "
    "Jupyter Notebook Spark Kafka Redis PyTorch TensorFlow SAP Oracle Salesforce Dynamics SharePoint OneDrive "
    "Fabric Databricks Snowflake Tableau Qlik Looker Notion Slack Zoom Jira Confluence Copilot Bash PowerShell "
    "Homebrew Pip Npm Conda Anaconda Chrome Firefox Safari Edge Android iOS iPhone iPad macOS Office "
    "Dataverse Navision Business Central Finance Operations Supply Chain Management"
).split()
_COMMON_CAPS = {fold(w) for w in _COMMON_CAPS_WORDS}
# accents kept: "Αθήνα" (Athens) is not "Αθηνά" (a first name)
_COMMON_CAPS_EXACT = {w.lower() for w in _COMMON_CAPS_WORDS}

# Roles and job titles: "Mr President", "Dear Reader", "Hallo Herr Direktor" are not names.
JOB_TITLES = {
    fold(w)
    for w in """
    president vice ceo cfo coo cto cio chairman chairwoman chair director manager head lead officer chief
    reader customer client colleague colleagues partner partners supplier user users member members
    candidate applicant secretary assistant consultant engineer analyst specialist coordinator supervisor
    owner founder representative agent driver buyer seller student professor doctor minister mayor
    senior junior associate executive general deputy acting interim regional national global group
    πρόεδρος προεδρε διευθυντης διευθυντη διευθυντρια υπευθυνος υπευθυνε συνεργατη συνεργατες πελατη πελατες
    direktor direktorin leiter leiterin geschaftsfuhrer kunde kunden président directeur directrice
    presidente direttore direttrice director directora gerente
    subscriber subscribers stakeholder stakeholders webmaster franchisee franchisees cardholder cardholders
    auditor auditors recruiter recruiters interviewer foreman headmistress headmaster shopper shoppers
    payroll sourcing dept treasury compliance legal procurement recruitment admissions shareholders shareholder
    investor investors employee employees staff applicants participants attendees guests patient patients
    kundin kunde kunden kundenservice personalabteilung geschaftsleitung geschaftspartner vertriebsteam
    mitarbeiter mitarbeiterin abonnent abonnenten cliente clienti abonne abonnee collaborateur socio soci
    συνδρομητη συνδρομητες συνδρομητα μετοχος μετοχοι μετοχους επενδυτες εργαζομενοι προμηθευτη προμηθευτες
    """.split()
}


_FIRST_NAMES = {fold(n) for n in N.RECOGNISED_FIRST_NAMES}
_FIRST_NAME_STEMS = {st for n in _FIRST_NAMES if (st := greek_stem(n))}


def is_first_name(word: str) -> bool:
    """A known first name, in any Greek case: Γιώργος / Γιώργο / Γιώργου."""
    w = fold(_POSSESSIVE_RE.sub("", word))
    if w in _FIRST_NAMES:
        return True
    st = greek_stem(w) if is_greek(w) else None
    return bool(st) and st in _FIRST_NAME_STEMS


_POSSESSIVE_RE = re.compile(r"['’]s?$")


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


def _zipf(word: str, lang: str) -> float:
    try:
        from wordfreq import zipf_frequency
    except ImportError:  # pragma: no cover
        return 0.0
    return zipf_frequency(word.lower(), lang)


def _person_or_org(name: str) -> str:
    return (
        "ORG"
        if re.search(r"(?i)\b(?:foods?|market|markets|trading|group|hellas|holdings?|logistics|bank)\b", name)
        else "PERSON"
    )


_POSSESSIVE = re.compile(r"['’]s?$")


def _clean(name: str) -> str | None:
    words = name.split()
    if words:
        words[-1] = _POSSESSIVE.sub("", words[-1])  # "Andreou's" -> "Andreou"
    if any(fold(w) in DEPARTMENTS for w in words):
        return None
    while words and fold(words[-1]) in STOP_NAMES:
        words.pop()
    if not words or all(fold(w) in STOP_NAMES or w.lower() in _COMMON_CAPS_EXACT for w in words):
        return None
    name = " ".join(words)
    return name if len(name) >= 3 else None


# Code is not prose: fenced blocks, inline `code`, shell and import lines, Markdown headings.
_CODE_FENCE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?(?:^[ \t]*\1[^\n]*$|\Z)")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_CODE_LINE = re.compile(
    r"(?m)^[ \t]*(?:\$[ \t]+\S|"
    r"(?:pip3?|python3?|npm|npx|yarn|git|brew|conda|docker|kubectl|curl|wget|sudo|uv|poetry|doublecast|claude|codex)"
    r"[ \t]+-*[a-z][\w.\-]*(?:[ \t]|$)|"
    r"(?:export|set)[ \t]+[A-Za-z_]\w*=|"
    r"import[ \t]+[\w.]+(?:[ \t]+as[ \t]+\w+)?[ \t]*(?:,[ \t]*[\w.]+)*[ \t]*$|"
    r"from[ \t]+[\w.]+[ \t]+import[ \t]|"
    r"(?:def|class)[ \t]+\w+[ \t]*[(:]|"
    r"(?:const|let|var)[ \t]+\w+[ \t]*=|function[ \t]*\w*[ \t]*\(|"
    r"(?:if|for|while)[ \t]*\(.*\)[ \t]*\{?[ \t]*$|return[ \t]+[^\n]*;[ \t]*$"
    r")[^\n]*$"
)
_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t][^\n]*$")


_GREEK_SURNAME_END_ARTICLE = tuple(
    fold(e) for e in ("ου", "ης", "ος", "ας", "η", "ιδη", "ακη", "οπουλο", "ατο", "ιδου", "ιου")
)


_FEMALE_TITLES = re.compile(
    r"(?i)(?:\b(?:mrs|ms|miss|frau|mme|mlle|sra|sig\.ra)\b|(?<![\w])(?:κα|κας|κυρία|κυρίας)(?![\w]))"
)
_MALE_TITLES = re.compile(r"(?i)(?:\b(?:mr|herr|sr|sig)\b|(?<![\w])(?:κος|κο|κε|κύριε|κύριο|κύριος|κυρίου)(?![\w]))")


def _title_gender(prefix: str) -> str | None:
    if _FEMALE_TITLES.search(prefix):
        return "f"
    if _MALE_TITLES.search(prefix):
        return "m"
    return None


def code_regions(text: str) -> list[tuple[int, int]]:
    regions = [m.span() for m in _CODE_FENCE.finditer(text)]
    regions += [m.span() for m in _INLINE_CODE.finditer(text)]
    regions += [m.span() for m in _CODE_LINE.finditer(text)]
    return regions


def _inside(regions: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(s <= start and end <= e for s, e in regions)


_ROLE_SUFFIX = re.compile(
    r"(?i)(?:holders?|ees|team|teams|abteilung|leitung|service|partner|partnerin|gruppe|dienst|mitglieder)$"
)
_GREEK_SURNAME_END = tuple(
    fold(e)
    for e in ("ου", "ης", "ος", "ας", "ιδη", "ιδης", "ακη", "ακης", "οπουλο", "οπουλος", "ελλη", "ατου", "ογλου")
)


@functools.lru_cache(maxsize=1)
def _known_surnames() -> frozenset[str]:
    return frozenset(fold(n) for names in N.LAST_NAMES.values() for n in names)


def _max_zipf(word: str) -> float:
    langs = ("el",) if is_greek(word) else ("en", "de", "fr", "it", "es")
    return max(_zipf(word, lang) for lang in langs)


def learnable(category: str, value: str, kind: str = "") -> bool:
    """May this value be remembered and then swapped *everywhere*?

    Remembering is powerful and so dangerous: a learned "Reader" would be swapped in every
    sentence from then on. Only values that cannot be ordinary language are learned.
    `kind` is how the value was found ("title", "greeting", "email_header"...).
    """
    value = value.strip()
    words = value.split()
    if len(value) < 4 or not words or len(words) > 8 or value.endswith("-"):
        return False
    folded = [fold(w.strip(".,;:()")) for w in words]
    banned = DEPARTMENTS | BUSINESS_WORDS | STOP_NAMES | _COMMON_CAPS | JOB_TITLES
    if any(_ROLE_SUFFIX.search(w) for w in folded):
        return False  # "Cardholders", "Vertriebsteam", "Kundenservice"
    if category == "PERSON":
        if any(w in banned for w in folded):
            return False
        if len(words) == 1:
            w, f = words[0], folded[0]
            # Lone first names are not learned: they collide with too many people.
            if len(w) < 4 or is_first_name(w):
                return False
            if f in _known_surnames():
                return True  # "Weber", "Rossi": frequent words, but known surnames
            # Word frequency cannot tell a rare surname from a role noun on its own, so the bar
            # depends on the clue: after "Mr"/"κ." almost anything rare is a surname; after
            # "Dear" a lone word is often a role ("Dear Subscriber"), so only very rare words.
            if is_greek(w):
                if f.endswith(_GREEK_SURNAME_END) and kind in ("title", "email_header", "signoff"):
                    return _max_zipf(w) < 4.0
                return _max_zipf(w) < 2.5
            return _max_zipf(w) < (3.0 if kind in ("title", "email_header", "signoff") else 2.5)
        # at least one word must be name-like: a known first name, or not a dictionary word
        return any(
            is_first_name(w) or f in _known_surnames() or not is_common_word(w)
            for w, f in zip(words, folded, strict=False)
        )
    # ORG and the rest: the name may contain ordinary words ("Hellenic Dairies") but not only those
    core = [w for w, f in zip(words, folded, strict=False) if f not in banned]
    if not core:
        return False
    if all(is_common_word(w) for w in core):
        return False  # "Net Weight", "Discount", "Marketing"
    if len(words) == 1 and words[0].isupper() and len(words[0]) <= 5 and not any(c.isdigit() for c in words[0]):
        return False  # "ALFA", "THE", "ATH": short codes collide with ordinary words
    return True


def detect_structure(text: str, capitalized_phrases: bool = False) -> list[Span]:
    spans: list[Span] = []
    code = code_regions(text)

    def add(start: int, name: str, category: str, kind: str, strong: bool = True, gender: str | None = None) -> None:
        cleaned = _clean(name)
        if not cleaned:
            return
        s = text.find(cleaned, start)
        if s < 0:
            return
        meta = {"strong": strong}
        if gender:
            meta["gender"] = gender  # "Ms Vlachaki" gets a woman's surname
        spans.append(Span(s, s + len(cleaned), category, cleaned, "heuristic", kind=kind, meta=meta))

    def weak(start: int, end: int, category: str, kind: str, confidence: float) -> None:
        name = _clean(text[start:end])
        if name:
            spans.append(
                Span(
                    start,
                    start + len(name),
                    category,
                    name,
                    "heuristic",
                    kind=kind,
                    confidence=confidence,
                    meta={"strong": False},
                )
            )

    for m in _HEADER.finditer(text):
        value_start = m.start("value")
        for pm in _HEADER_PERSON.finditer(m.group("value")):
            add(value_start + pm.start("name"), pm.group("name"), _person_or_org(pm.group("name")), "email_header")
    for m in _GREETING.finditer(text):
        add(
            m.start("name"),
            m.group("name"),
            "PERSON",
            "greeting",
            gender=_title_gender(text[m.start() : m.start("name")]),
        )
    for m in _TITLE.finditer(text):
        add(
            m.start("name"), m.group("name"), "PERSON", "title", gender=_title_gender(text[m.start() : m.start("name")])
        )
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
        headings = [m.span() for m in _HEADING.finditer(text)]
        for m in _FIRST_LAST_AT_START.finditer(text):
            # "Theodora Vlachaki will confirm." at a sentence start: only when the first word is a known first name
            if is_first_name(m.group("first")) and fold(m.group("last")) not in _COMMON_CAPS:
                weak(m.start("first"), m.end("last"), "PERSON", "first_last", 0.6)
        for m in _FIRST_NAME_ALONE.finditer(text):
            if is_first_name(m.group("name")):  # "..., said Maria."
                weak(m.start("name"), m.end("name"), "PERSON", "first_name", 0.5)
        for m in _GREEK_ARTICLE.finditer(text):
            w = m.group("name")
            if fold(w) in _COMMON_CAPS or fold(w) in BUSINESS_WORDS:
                continue
            # Greek nouns after an article are lower case, so a capital already says "proper noun";
            # only very frequent words (zipf >= 4.5) are let through as vocabulary
            # and it must end like a Greek name: "στο Κρουασάν", "η Μπουγάτσα" are products, not people
            if is_first_name(w) or (_zipf(w, "el") < 4.5 and fold(w).endswith(_GREEK_SURNAME_END_ARTICLE)):
                weak(m.start("name"), m.end("name"), "PERSON", "greek_article", 0.5)
        for m in _CAPS.finditer(text):
            if _inside(headings, m.start(), m.end()):
                continue
            name = m.group("name")
            words = [fold(w) for w in name.split()]
            if all(w in _COMMON_CAPS or w in STOP_NAMES or w in BUSINESS_WORDS for w in words):
                continue
            raw_words = name.split()
            has_first = any(is_first_name(w) for w in raw_words)
            if is_greek(name) and not has_first:
                continue  # Greek capitalises products and places too ("Κρουασάν Βουτύρου"): needs a first name
            if not has_first and all(is_common_word(w) for w in raw_words):
                continue  # "Annual Leave Policy", "Πρόγραμμα Εκπαίδευσης": vocabulary, not a name
            if any(w in DEPARTMENTS for w in words):
                continue
            weak(m.start("name"), m.end("name"), _person_or_org(name), "capitalized", 0.5)
    if code:
        spans = [s for s in spans if not any(cs < s.end and s.start < ce for cs, ce in code)]
    # a strong find (title, greeting, header, legal form) must not lose to the broad net, or it is not remembered
    strong = [s for s in spans if s.meta.get("strong")]
    if strong:
        spans = strong + [
            s
            for s in spans
            if not s.meta.get("strong") and not any(s.start < t.end and t.start < s.end for t in strong)
        ]
    return spans
