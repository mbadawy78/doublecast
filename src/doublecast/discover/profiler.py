"""Classify a column (or a spreadsheet header) as a kind of sensitive data.

Two signals, combined:

1. **The name** of the column, read together with its table name, in six
   languages: "Customer", "Πελάτης", "Kunde", "Lieferant", "Είδος",
   "Salesperson", "Αποθήκη", "ΑΦΜ", "IBAN"...
2. **The values**, from a sample: share of emails, IBANs (checksum),
   Greek VAT numbers (checksum), phone numbers, values that look like
   people's names, values that carry a company legal form ("S.A.", "ΑΕ",
   "GmbH"), short codes.

The verdict says what the column holds, how sure we are and why.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..data import names as N
from ..textnorm import fold, is_greek
from ..validators import afm_valid, iban_valid

# Categories that become protection rules (terms).
TERM_CATEGORIES = ("ORG", "PERSON", "PRODUCT", "SITE", "PROJECT", "ADDRESS", "ID", "PHONE", "TAX_ID", "IBAN")


def _f(words: str) -> list[str]:
    return [fold(w.strip()) for w in words.split(",") if w.strip()]


# Keywords are folded (lower case, no accents). Long keywords match as substrings,
# short ones (<= 4 letters) only as whole words.
HEADER_KEYWORDS: dict[str, list[str]] = {
    "ORG": _f(
        "customer,client,account name,chain,retailer,distributor,wholesaler,supplier,vendor,company,partner,buyer,"
        "consignee,sold-to,ship-to,bill-to,sold to,ship to,bill to,debtor,creditor,payer,payee,organisation,"
        "organization,banner,key account,cust,vend,invoice account,legal entity,πελατ,προμηθευτ,εταιρ,αλυσιδ,συνεργατ,επωνυμια,αντισυμβαλλ,χρεωστ,πιστωτ,"
        "kunde,lieferant,firma,unternehmen,handelspartner,fournisseur,societe,raison sociale,cliente,fornitore,"
        "azienda,ragione sociale,proveedor,empresa,razon social"
    ),
    "PERSON": _f(
        "employee,worker,staff,personnel,fullname,contact,firstname,lastname,salesperson,sales rep,salesman,account manager,manager,driver,contact person,"
        "contact name,owner,first name,last name,full name,surname,given name,created by,modified by,approved by,"
        "assigned to,requester,representative,agent,technician,operator,user name,username,υπαλλ,εργαζομ,πωλητ,"
        "οδηγο,οδηγου,υπευθυν,επαφη,ονοματεπωνυμο,επωνυμο,μισθωτ,χειριστ,mitarbeiter,verkaufer,fahrer,"
        "ansprechpartner,vorname,nachname,sachbearbeiter,employe,commercial,chauffeur,prenom,interlocuteur,"
        "dipendente,venditore,autista,cognome,referente,empleado,vendedor,conductor,apellido,responsable"
    ),
    "PRODUCT": _f(
        "product,item,sku,article,material,brand,recipe,formula,ειδος,ειδους,προιον,μαρκα,συνταγ,αρθρο,artikel,produkt,"
        "marke,rezept,produit,marque,recette,prodotto,articolo,ricetta,producto,receta"
    ),
    "SITE": _f(
        "warehouse,plant,factory,store,shop,branch,depot,site,outlet,point of sale,distribution center,αποθηκ,"
        "εργοστασ,καταστημ,υποκαταστ,κεντρο διανομ,lager,werk,filiale,standort,entrepot,usine,magasin,magazzino,"
        "stabilimento,negozio,filiale,almacen,fabrica,tienda,sucursal,invent location,inventlocation"
    ),
    "ADDRESS": _f("address,street,addr,διευθυνσ,οδος,adresse,strasse,anschrift,indirizzo,via,direccion,calle"),
    "PROJECT": _f("project,εργο,projekt,projet,progetto,proyecto"),
    "EMAIL": _f("email,e-mail,mail"),
    "PHONE": _f(
        "phone,tel,telephone,mobile,fax,cell,τηλ,τηλεφων,κινητ,telefon,handy,telephone,portable,telefono,movil"
    ),
    "TAX_ID": _f(
        "vat,tax id,tax no,tin,afm,αφμ,a.f.m,ust-id,ustid,steuernummer,siret,siren,tva,partita iva,p.iva,nif,cif"
    ),
    "IBAN": _f("iban"),
    "URL": _f("url,website,web site,homepage,home page,webpage,linkedin,facebook,twitter,instagram,ιστοσελιδ"),
}
CODE_WORDS = _f("code,id,no,nr,number,num,key,account,acct,κωδ,κωδικος,αρ,αριθμος,nummer,numero,numéro,codice,codigo")
# Columns that hold names but are not sensitive on their own (geography, classifications, time...).
NOT_SENSITIVE = _f(
    "city,town,country,region,area,territory,zone,category,group,class,type,status,date,year,month,week,day,"
    "quarter,period,unit,uom,currency,channel,segment,family,season,language,πολη,χωρα,νομος,περιοχ,κατηγορ,"
    "ομαδα,τυπος,κατασταση,ημερομηνια,ετος,μηνας,μοναδα,νομισμα,καναλι,stadt,land,region,kategorie,gruppe,"
    "ville,pays,categorie,citta,paese,categoria,ciudad,pais,format,main account,ledger,gl,chart of accounts,"
    "cost center,cost centre,profit center,dimension,λογαριασμ,λογιστικ,kostenstelle,sachkonto,"
    "zip,postal,postcode,τ.κ.,plz"
)
# Roles beat geography and classification: "Region Manager" is a person, "Region" is not.
PERSON_ROLES = _f(
    "manager,salesperson,sales rep,representative,owner,driver,employee,supervisor,υπευθυν,πωλητ,οδηγο,οδηγου,"
    "leiter,verkaufer,responsable,responsabile"
)
# Table names that mark a master-data table for a bare Name column (Dataverse "accounts", "competitors")
TABLE_KEYWORDS = {
    "ORG": _f("accounts,account,competitor,competitors,customers,vendors,suppliers"),
    "PERSON": _f("contacts,systemusers,leads,employees,workers"),
}
# Bare Name/Description columns in these tables describe transactions, not master data
TRANSACTION_TABLES = _f(
    "invoice,order,line,lines,trans,journal,posting,entry,entries,ledger,τιμολογ,παραγγελ,κινησ,"
    "rechnung,auftrag,buchung,facture,commande,fattura,ordine,factura,pedido"
)
_NAME_ONLY = _f(
    "name,ονομα,επωνυμια,nom,nome,nombre,bezeichnung,alias,namealias,known as,knownas,nickname,short name,"
    "shortname,search name,searchname,trade name,tradename,διακριτικος τιτλος"
)
NAME_WORDS = _f("name,ονομα,περιγραφη,description,bezeichnung,nom,libelle,nome,descrizione,nombre,descripcion")

LEGAL_FORMS_RE = re.compile(
    r"(?:^|[\s,])(?:S\.?A\.?|A\.?E\.?|ΑΕ|Α\.Ε\.|ΑΕΒΕ|ΑΒΕΕ|Α\.Β\.Ε\.Ε\.|ΕΠΕ|Ε\.Π\.Ε\.|ΙΚΕ|Ι\.Κ\.Ε\.|Ο\.Ε\.|ΟΕ|Ε\.Ε\.|EE|IKE|"
    r"Ltd\.?|Limited|LLC|Inc\.?|Corp\.?|PLC|GmbH|AG|KG|SAS|SARL|S\.p\.A\.|SpA|S\.r\.l\.|Srl|S\.L\.|SL|B\.V\.|BV|N\.V\.|NV|Co\.)$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,24}$")
_PHONE = re.compile(r"^\+?[\d\s().\-/]{7,20}$")
_CODE = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9._/\-]{3,24}$")
_FIRST_NAMES = {fold(n) for n in N.RECOGNISED_FIRST_NAMES}
_GREEK_SURNAME_ENDINGS = tuple(
    fold(e) for e in ("ου", "ης", "ος", "ας", "ιδης", "ακης", "οπουλος", "ιδου", "ακη", "οπουλου", "ελλη", "ατου")
)

PLACEHOLDERS = {
    fold(v)
    for v in (
        "n/a",
        "na",
        "none",
        "null",
        "-",
        "--",
        "unknown",
        "other",
        "others",
        "various",
        "total",
        "grand total",
        "subtotal",
        "blank",
        "(blank)",
        "test",
        "tbd",
        "misc",
        "miscellaneous",
        "cash",
        "cash customer",
        "retail customer",
        "λοιποι",
        "λοιπα",
        "διαφοροι",
        "συνολο",
        "γενικο συνολο",
        "πελατης λιανικης",
        "πελατες λιανικης",
        "λιανικη",
        "αγνωστο",
        "sonstige",
        "gesamt",
        "autres",
        "total general",
        "altri",
        "totale",
        "otros",
        "varios",
    )
}


def _departments() -> set[str]:
    from ..detectors.heuristics import DEPARTMENTS

    return DEPARTMENTS


_DEPARTMENTS = _departments()


@dataclass
class ColumnVerdict:
    category: str | None  # one of TERM_CATEGORIES, "EMAIL", "MONEY" or None (not sensitive)
    confidence: float
    reason: str

    @property
    def sensitive(self) -> bool:
        return self.category is not None


def _has_keyword(text: str, keywords: list[str]) -> str | None:
    words = set(re.split(r"[\s_\-./()\[\]:#]+", text))
    for kw in keywords:
        if len(kw) <= 4 and " " not in kw:
            if kw in words:
                return kw
        elif kw in text:
            return kw
    return None


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def classify_header(column: str, table: str = "") -> tuple[str | None, str, bool]:
    """Classify from names only. Returns (category, matched keyword, is_code_column)."""
    col = fold(_CAMEL.sub(" ", str(column))).strip()  # "CustomerAccount" -> "customer account"
    col = col.replace("phonetic", "spoken ")  # ORGANIZATIONPHONETICNAME is a name, not a phone
    tab = fold(_CAMEL.sub(" ", str(table))).strip()
    if not col:
        return None, "", False
    is_code = _has_keyword(col, CODE_WORDS) is not None
    if " " not in col and col.endswith(("url", "website")) or (" " not in col and "url" in col and "curl" not in col):
        return "URL", "url", False  # PRIMARYCONTACTURL, CompanyWebsite (glued exports)
    for category in ("IBAN", "TAX_ID", "EMAIL", "PHONE", "URL"):
        kw = _has_keyword(col, HEADER_KEYWORDS[category])
        if kw:
            return category, kw, False
    role = _has_keyword(col, PERSON_ROLES)
    if role and not is_code:
        return "PERSON", role, False  # "Region Manager", "Store Owner"
    if _has_keyword(col, NOT_SENSITIVE):
        return None, "", False  # "Customer Group", "Store Format", "Address City", "MainAccountName"
    kw = _has_keyword(col, HEADER_KEYWORDS["ADDRESS"])
    if kw:
        return "ADDRESS", kw, False
    for category in ("PERSON", "ORG", "PRODUCT", "SITE", "PROJECT"):
        kw = _has_keyword(col, HEADER_KEYWORDS[category])
        if kw:
            return category, kw, is_code
    # a bare "Name" column takes its meaning from the table: Customers[Name], accounts.name.
    # "Description" only counts in product tables; transaction tables (invoice lines) never count.
    if _has_keyword(tab, TRANSACTION_TABLES):
        return None, "", False
    bare_name = _has_keyword(col, _NAME_ONLY) is not None
    if bare_name or is_code or _has_keyword(col, NAME_WORDS):
        for category in ("PERSON", "ORG", "PRODUCT", "SITE", "PROJECT"):
            if category != "PRODUCT" and not (bare_name or is_code):
                continue
            kw = _has_keyword(tab, HEADER_KEYWORDS[category] + TABLE_KEYWORDS.get(category, []))
            if kw:
                return category, f"{tab}.{col}", is_code
    return None, "", False


def _looks_like_person(value: str) -> bool:
    words = value.replace(",", " ").split()
    if not 2 <= len(words) <= 4 or any(any(c.isdigit() for c in w) for w in words):
        return False
    if not all(w[:1].isupper() for w in words if len(w) > 1):
        return False
    folded = [fold(w.strip(".")) for w in words]
    if any(w in _FIRST_NAMES for w in folded):
        return True
    if not is_greek(value):
        return False
    # "Κρουασάν Βουτύρου" ends like a surname but is a product: its words are ordinary Greek.
    # Greek word-frequency lists are thinner, so a lower bar than for English.
    return any(f.endswith(_GREEK_SURNAME_ENDINGS) and _zipf_el(w) < 3.0 for w, f in zip(words, folded, strict=False))


def _zipf_el(word: str) -> float:
    try:
        from wordfreq import zipf_frequency
    except ImportError:  # pragma: no cover
        return 0.0
    return zipf_frequency(word.lower(), "el")


def _ratio(values: list[str], test) -> float:
    return sum(1 for v in values if test(v)) / len(values) if values else 0.0


def _phone_like(v: str) -> bool:
    """A phone number, not an amount: "-45,212.5" and "7520035.25" are P&L figures (a real misfire, Oct 2026)."""
    if v.startswith("-") or re.fullmatch(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,4})?|\d+[.,]\d{1,4}", v):
        return False
    return _PHONE.match(v) is not None and sum(c.isdigit() for c in v) >= 8


def classify_column(column: str, values: Iterable[object], table: str = "") -> ColumnVerdict:
    sample = [str(v).strip() for v in values if v is not None and str(v).strip()]
    sample = sample[:500]
    header_cat, kw, is_code = classify_header(column, table)

    if not sample:
        if header_cat:
            return ColumnVerdict(header_cat, 0.5, f"column name ({kw}); no values to confirm")
        return ColumnVerdict(None, 0.0, "empty")

    numeric = _ratio(sample, lambda v: re.fullmatch(r"-?[\d.,\s]+", v) is not None)
    # strong value signals win regardless of the name
    if _ratio(sample, lambda v: _EMAIL.match(v) is not None) >= 0.6:
        return ColumnVerdict("EMAIL", 0.95, "values are email addresses")
    if _ratio(sample, lambda v: iban_valid(v)) >= 0.6:
        return ColumnVerdict("IBAN", 0.97, "values are valid IBANs")
    afm_share = _ratio(
        sample, lambda v: afm_valid(re.sub(r"\D", "", v)[-9:].zfill(9)) and 8 <= len(re.sub(r"\D", "", v)) <= 11
    )
    if afm_share >= 0.8 and (header_cat == "TAX_ID" or numeric >= 0.8):
        return ColumnVerdict("TAX_ID", 0.9 if header_cat == "TAX_ID" else 0.7, "values pass the Greek VAT checksum")
    if header_cat in ("TAX_ID", "IBAN", "EMAIL", "ADDRESS"):
        return ColumnVerdict(header_cat, 0.85, f"column name ({kw})")
    if header_cat == "PHONE" or (_ratio(sample, _phone_like) >= 0.8 and numeric < 1.0):
        if _ratio(sample, lambda v: sum(c.isdigit() for c in v) >= 7) >= 0.6:
            return ColumnVerdict("PHONE", 0.9, "values are phone numbers")

    if numeric >= 0.9 and not is_code:
        return ColumnVerdict(None, 0.0, "numbers (amounts are handled by money scaling)")

    person = _ratio(sample, _looks_like_person)
    legal = _ratio(sample, lambda v: LEGAL_FORMS_RE.search(v) is not None)
    codes = _ratio(sample, lambda v: _CODE.match(v) is not None)

    if header_cat in ("ORG", "PERSON", "PRODUCT", "SITE", "PROJECT"):
        if is_code and codes >= 0.6:
            return ColumnVerdict("ID", 0.85, f"{header_cat.lower()} codes ({kw})")
        if is_code and _ratio(sample, lambda v: " " not in v and len(v) <= 6) >= 0.6:
            # "Company code" = ALFA, GR01: too short and generic to swap everywhere
            return ColumnVerdict(None, 0.0, f"short {header_cat.lower()} codes ({kw}); too generic to protect")
        if header_cat in ("ORG", "PERSON"):
            if legal >= 0.2:
                return ColumnVerdict("ORG", 0.9, f"column name ({kw}) and company legal forms in the values")
            if person >= 0.5:
                return ColumnVerdict("PERSON", 0.9, f"column name ({kw}) and values look like people's names")
        return ColumnVerdict(header_cat, 0.85, f"column name ({kw})")

    # no telling name: the values have to speak for themselves
    if legal >= 0.3:
        return ColumnVerdict("ORG", 0.75, "values carry company legal forms (S.A., ΑΕ, GmbH...)")
    if person >= 0.6:
        return ColumnVerdict("PERSON", 0.7, "values look like people's names")
    return ColumnVerdict(None, 0.0, "no sign of sensitive data")


def _ordinary(word: str) -> bool:
    from ..detectors.heuristics import is_common_word

    if word.isupper() and len(word) <= 5:
        return True
    return is_common_word(word)


def extract_terms(category: str, values: Iterable[object], limit: int = 50000) -> tuple[list[str], int]:
    """Turn a column's values into protection terms. Returns (terms, skipped)."""
    out: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for raw in values:
        if raw is None:
            continue
        v = re.sub(r"\s+", " ", str(raw)).strip().strip(",;")
        if not v:
            continue
        key = fold(v)
        if key in seen:
            continue
        seen.add(key)
        if key in PLACEHOLDERS or len(v) < (3 if category in ("ID", "PHONE", "TAX_ID", "IBAN") else 4):
            skipped += 1
            continue
        digits = sum(c.isdigit() for c in v)
        if category in ("PHONE", "TAX_ID", "IBAN"):
            if digits < 7:
                skipped += 1
                continue
        elif category == "ID":
            if not (_CODE.match(v) and (any(c.isalpha() for c in v) and len(v) >= 5 or digits >= 6)):
                skipped += 1
                continue
        elif v.replace(".", "").replace(",", "").replace(" ", "").isdigit():
            skipped += 1
            continue
        elif category == "PERSON" and any(fold(w) in _DEPARTMENTS for w in v.split()):
            skipped += 1  # "Sales Team", "Λογιστήριο": shared mailboxes, not people
            continue
        elif category not in ("ADDRESS",) and " " not in v and not any(c.isdigit() for c in v) and _ordinary(v):
            skipped += 1  # "Discount", "Central", "THE": one ordinary word or a short code would be swapped everywhere
            continue
        elif category == "PRODUCT" and " " not in v and not any(c.isdigit() for c in v):
            # a one-word product ("Croissant", "Butter") is an ordinary word: protecting it
            # would swap the word everywhere. Full descriptions and coded names are kept.
            skipped += 1
            continue
        out.append(v)
        if len(out) >= limit:
            break
    return out, skipped
