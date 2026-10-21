"""Regression tests for the second independent review of v0.2 (auto mode and discovery)."""

from __future__ import annotations

import time

import httpx
import pytest

from doublecast.detectors.heuristics import detect_structure, learnable
from doublecast.discover.microsoft import Api
from doublecast.discover.profiler import classify_column, classify_header, extract_terms
from doublecast.discover.rules import RulesStore
from doublecast.engine import Engine
from doublecast.files.tabular import scramble_cell

from .conftest import make_config


def _engine(tmp_path, **kw):
    return Engine(make_config(tmp_path, terms=[], **kw))


def _learned(e) -> set[str]:
    return {v for vals in e.rules.data["learned"].values() for v in vals}


# ---------------------------------------------------------------- C1: learning must not poison the rules
@pytest.mark.parametrize(
    "text",
    [
        "Mr President, the numbers are ready.",
        "Dear Reader,\nplease see below.",
        "Thanks,\nOperations",
        "Net Weight KG must be printed on the label.",
        "Invoice from Marketing Ltd attached.",
        "Hallo Herr Direktor,\nanbei die Zahlen.",
    ],
)
def test_ordinary_words_are_never_learned(tmp_path, text):
    e = _engine(tmp_path)
    e.scramble(text)
    assert not _learned(e), _learned(e)
    e.vault.close()


def test_real_names_are_still_learned(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=False)
    e.scramble("Dear Ms Vlachaki,\nthanks.\n\nOrder from Brennwald Handel GmbH.")
    learned = _learned(e)
    assert "Vlachaki" in learned and "Brennwald Handel GmbH" in learned and "Brennwald Handel" in learned
    e.vault.close()


def test_learnable_rules():
    assert not learnable("PERSON", "Reader")
    assert not learnable("PERSON", "President")
    assert not learnable("ORG", "Net Weight")
    assert not learnable("ORG", "ALFA")
    assert not learnable("SITE", "THE")
    assert learnable("PERSON", "Theodora Vlachaki")
    assert learnable("ORG", "Hellenic Kallergis Dairies")


# ---------------------------------------------------------------- C2: whole cells
def test_short_codes_and_common_words_in_cells_are_not_learned(tmp_path):
    e = _engine(tmp_path)
    for header, value in (("Site", "THE"), ("Customer", "Discount"), ("Company code", "ALFA"), ("Customer", "Central")):
        scramble_cell(e, header, value)
    e.flush_learned()
    assert not _learned(e), _learned(e)
    out = e.scramble("the discount for the central warehouse").text
    assert out == "the discount for the central warehouse"
    e.vault.close()


def test_extract_terms_skips_ordinary_single_words():
    terms, skipped = extract_terms("ORG", ["Discount", "THE", "Sklavenitis", "Masoutis Markets"])
    assert terms == ["Sklavenitis", "Masoutis Markets"] and skipped == 2


# ---------------------------------------------------------------- C3: a double must not collide with the text
def test_double_never_equals_another_word_in_the_same_text(tmp_path):
    e = _engine(tmp_path)
    for i in range(30):
        # many different first names in one text; none may be used as a double for another
        names = ["Maria", "Eleni", "Sofia", "Anna", "Katerina", "Georgia", "Dimitra", "Ioanna", "Nikos", "Petros"]
        text = f"Dear Eleni{'' if i == 0 else i},\n" + ", ".join(names) + " and Kostas were there."
        out = e.scramble(text).text
        assert e.restore(out) == text
    e.vault.close()


# ---------------------------------------------------------------- C4: classifier
@pytest.mark.parametrize(
    ("column", "table"),
    [
        ("MainAccountName", "MainAccounts"),
        ("Store Format", "Stores"),
        ("AddressCity", "CustomersV3"),
        ("AddressCountryRegionId", "CustomersV3"),
        ("Description", "Customer Invoice Lines"),
        ("Name", "SalesOrderLines"),
    ],
)
def test_generic_columns_are_not_sensitive(column, table):
    assert classify_header(column, table)[0] is None


def test_short_company_codes_are_not_protected():
    v = classify_column("Company code", ["ALFA", "GR01", "CY", "ALFA"], "Companies")
    assert v.category is None


def test_greek_product_descriptions_are_not_people():
    v = classify_column("Περιγραφή", ["Κρουασάν Βουτύρου", "Σφολιάτα Τυριού", "Μπουγάτσα Κρέμας"], "")
    assert v.category != "PERSON"


# ---------------------------------------------------------------- I1: strong finds win and are learned
def test_title_beats_broad_net(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=True)
    e.scramble("we talked to Ms Vlachaki yesterday")
    assert "Vlachaki" in _learned(e)
    e.vault.close()


# ---------------------------------------------------------------- I2: more leaks closed
@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("| Customer | Owner |\n|---|---|\n| x | Theodora Vlachaki |", "Vlachaki"),
        ("id,owner\n7,Theodora Vlachaki", "Vlachaki"),
        ("Μίλησα με τον Παπαδόπουλο χθες.", "Παπαδόπουλ"),
        ("Ενημέρωσε τον κο Ανδρέου.", "Ανδρέου"),
        ("Ενημέρωσε τον κύριο Ανδρέου.", "Ανδρέου"),
        ("please ask mr Vlachakis", "Vlachakis"),
        ("Ms Vlachaki's offer is better.", "Vlachaki"),
        ("Supplier: ATHANASIOS D. KOUKOUTARIS SA", "KOUKOUTARIS"),
        ("Supplier: Kallergis Foods AEBE", "Kallergis"),
        ("Χθες μίλησα με τον Γιώργο.", "Γιώργο"),
    ],
)
def test_more_leaks_closed(tmp_path, text, name):
    e = _engine(tmp_path, capitalized_phrases=True)
    out = e.scramble(text).text
    assert name not in out, out
    assert e.restore(out) == text
    e.vault.close()


def test_possessive_learned_without_s(tmp_path):
    e = _engine(tmp_path)
    e.scramble("Ms Vlachaki's offer is better.")
    assert "Vlachaki" in _learned(e) and "Vlachaki's" not in _learned(e)
    e.vault.close()


# ---------------------------------------------------------------- I3: code is not prose
def test_code_and_shell_are_left_alone(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=True)
    text = (
        "Run this:\n```bash\npip install Requests Pandas\n```\n"
        "Then `import Pandas Profiling` and\n$ git commit -m 'Fix Margin Report'\n"
        "## Release Notes Draft\n"
    )
    assert e.scramble(text).text == text
    e.vault.close()


def test_secrets_are_still_redacted_inside_code(tmp_path):
    e = _engine(tmp_path)
    out = e.scramble("```\nexport OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD\n```").text
    assert "sk-proj-abcdef" not in out


def test_no_mid_word_names():
    assert not [s for s in detect_structure("From: LinkedIn <noreply@linkedin.com>") if s.text == "In"]
    assert not detect_structure("Sr Manager, please review.")


# ---------------------------------------------------------------- I4: learning does not rebuild huge matchers
def test_learning_with_large_rule_set_is_fast(tmp_path):
    e = _engine(tmp_path)
    for i in range(20000):
        e.rules.data["learned"].setdefault("ORG", []).append(f"Zyx{i:05d} Qorptrading")
    e.rules.save()
    e.reload_rules()
    t = time.perf_counter()
    for i in range(20):
        e.scramble(f"Dear Ms Vlachakiou{chr(97 + i)}rk,\nsee attached.")
    assert time.perf_counter() - t < 2.0
    assert "zyx00042 qorptrading" not in e.scramble("zyx00042 qorptrading paid").text.lower()
    e.vault.close()


# ---------------------------------------------------------------- I5: forget is not undone by a running proxy
def test_forget_learned_is_not_undone_by_another_process(tmp_path):
    proxy = _engine(tmp_path)
    proxy.scramble("Dear Ms Vlachaki,\nok.")
    cli = _engine(tmp_path)
    cli.rules.clear_learned()
    cli.rules.save()
    proxy.scramble("Dear Mr Linardakis,\nok.")  # proxy learns something new and saves
    after = RulesStore(proxy.config.rules_path, proxy.vault)
    learned = {v for vals in after.data["learned"].values() for v in vals}
    assert "Vlachaki" not in learned and "Linardakis" in learned
    assert "Vlachaki" in proxy.scramble("Vlachaki called").text  # the proxy forgot it too
    proxy.vault.close()
    cli.vault.close()


# ---------------------------------------------------------------- I6: throttling, outages, expiry
def test_api_retries_throttling_and_refreshes_tokens():
    calls = {"n": 0}
    tokens = []

    def handler(request):
        calls["n"] += 1
        tokens.append(request.headers["Authorization"])
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if calls["n"] == 2:
            return httpx.Response(503)
        if calls["n"] == 3:
            return httpx.Response(401)
        return httpx.Response(200, json={"value": [1]})

    issued = iter(["old", "old", "old", "new"])

    def token(fresh=False):
        return next(issued)

    api = Api(token, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert api.get("https://x/y") == {"value": [1]}
    assert tokens[-1] == "Bearer new"


def test_api_turns_outages_into_source_errors():
    from doublecast.discover.sources.base import SourceError

    def handler(request):
        raise httpx.ConnectTimeout("slow")

    api = Api(lambda: "t", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(SourceError):
        api.get("https://x/y")

    api2 = Api(
        lambda: "t",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad"))),
        sleep=lambda s: None,
    )
    with pytest.raises(SourceError):
        api2.get("https://x/y")


# ---------------------------------------------------------------- I7: headers that were missed
@pytest.mark.parametrize(
    ("column", "table", "category"),
    [
        ("name", "accounts", "ORG"),
        ("name", "competitors", "ORG"),
        ("CustAccount", "SalesTable", "ORG"),
        ("InvoiceAccount", "CustInvoiceJour", "ORG"),
        ("InventLocationId", "InventDim", "SITE"),
        ("Legal Entity", "Companies", "ORG"),
        ("Region Manager", "Regions", "PERSON"),
    ],
)
def test_headers_found(column, table, category):
    assert classify_header(column, table)[0] == category


# ---------------------------------------------------------------- second pass of the review
@pytest.mark.parametrize(
    "text",
    [
        "Mr Dupont-Leroy said so. Ms Papadaki-Smith agreed.",
        "Ο κ. Παπαδάκης-Σμιθ συμφώνησε.",
        "Hallo Herr Müller-Thurgau,\nHerr Müller-Thurgau kommt.",
        "From: Anne-Marie Dupont-Leroy <a@b.fr>\n\nok",
    ],
)
def test_hyphenated_names_round_trip(tmp_path, text):
    e = _engine(tmp_path, capitalized_phrases=True)
    out = e.scramble(text).text
    assert e.restore(out) == text
    for part in ("Dupont", "Leroy", "Papadaki", "Παπαδάκ", "Thurgau"):
        assert part not in out, out
    assert not [v for v in _learned(e) if v.endswith("-")]
    e.vault.close()


def test_real_person_sharing_a_doubles_name_gets_own_double(tmp_path):
    e = _engine(tmp_path)
    e.scramble("Dear Mr Papadakis,\nok.")
    double = e.vault.get("Papadakis")
    text = f"Dear Mr Papadakis,\nour new buyer {double} called. {double} wants 5%."
    out = e.scramble(text).text
    assert e.restore(out) == text
    e.vault.close()


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("set a reminder for Dr Rossi.", "Rossi"),
        ("export sales to Kallergis Foods AEBE fell 5% (see Mr Papadakis).", "Papadakis"),
        ("import duties apply; Herr Weber confirmed (invoice 5).", "Weber"),
        ("for the record, Ms Vlachaki agreed (see attached).", "Vlachaki"),
        ("if Mr Papadakis agrees (as expected), we proceed.", "Papadakis"),
        ("return the samples to Frau Weber (Monday).", "Weber"),
        ("Sehr geehrter Herr Dr. Schmidt,\nanbei.", "Schmidt"),
        ("Dear Prof. Dr. Weber,\nProf. Dr. Weber agreed.", "Weber"),
        ("Supplier: J. P. Morgan Ltd", "J. P."),
        ("Dear Mr Spyros Pappas,\nplease call Pappas tomorrow.", "Pappas"),
    ],
)
def test_prose_is_not_code_and_titles_stack(tmp_path, text, name):
    e = _engine(tmp_path, capitalized_phrases=True)
    out = e.scramble(text).text
    assert name not in out, out
    assert e.restore(out) == text
    e.vault.close()


@pytest.mark.parametrize(
    "text",
    [
        "Dear Subscriber,\nhi",
        "Dear Stakeholders,\nhi",
        "Dear Webmaster,\nhi",
        "Dear Cardholder,\nhi",
        "Dear Mr Auditor,\nhi",
        "Thanks,\nSourcing",
        "Regards,\nPayroll Dept",
        "Liebe Kundin, lieber Kunde,\nhallo",
        "Mit freundlichen Grüßen\nIhr Vertriebsteam",
        "Αγαπητέ Συνδρομητή,\nγεια",
        "Dear Sir or Madam,\nhi",
    ],
)
def test_role_nouns_are_not_learned(tmp_path, text):
    e = _engine(tmp_path)
    e.scramble(text)
    assert not _learned(e), _learned(e)
    e.vault.close()


def test_greek_driver_header():
    assert classify_header("Οδηγός", "Δρομολόγια")[0] == "PERSON"


# ---------------------------------------------------------------- realistic doubles (user report: "looks like an anagram")
def _real_words():
    from doublecast.data import realnames as R

    words = set()
    for table in (R.FIRST, R.LAST):
        for byg in table.values():
            for names in byg.values():
                words.update(w.casefold() for n in names for w in n.replace("-", " ").split())
    words.update(w.casefold() for w in R.BRAND_WORDS + R.GREEK_TOWNS + R.GREEK_STREETS)
    return words


SAMPLE_EMAIL = """From: Eleni Papadopoulou <e.papadopoulou@masoutis.gr>
To: Nikos Andreou <n.andreou@alfapastry.com>

Αγαπητέ κ. Ανδρέου,

Η Μασούτης ΑΕ ζητά 12% έκπτωση στο Κρουασάν Βουτύρου 80g για το Q4.
Ms Vlachaki from Lidl Hellas EPE will call Tuesday.

Με εκτίμηση,
Ελένη Παπαδοπούλου"""


def test_doubles_are_real_names_with_gender_and_matching_email(tmp_path):
    from doublecast.data.realnames import GREEK_FEMALE, GREEK_FROM_LATIN, GREEK_SURNAMES_F, translit_name

    e = _engine(tmp_path, capitalized_phrases=True)
    r = e.scramble(SAMPLE_EMAIL)
    out = r.text
    assert e.restore(out) == SAMPLE_EMAIL
    reps = {orig: new for _, orig, new in r.replacements}
    real = _real_words()
    for orig, new in reps.items():
        if "@" in new or any(c.isdigit() for c in new):
            continue
        for w in new.split():
            if w in ("ΑΕ", "EPE", "Hellas", "Ms", "κ."):
                continue
            assert w.casefold() in real, (orig, new)  # no invented syllable names
    # women stay women
    eleni = reps["Eleni Papadopoulou"]
    assert eleni.split()[0] in [translit_name(n) for n in GREEK_FEMALE]
    assert eleni.split()[1] in [translit_name(n) for n in GREEK_SURNAMES_F]
    assert reps["Vlachaki"] in [translit_name(n) for n in GREEK_SURNAMES_F]
    # the same person in Greek letters gets the same double, in Greek letters
    assert reps["Ελένη Παπαδοπούλου"] == " ".join(GREEK_FROM_LATIN[w] for w in eleni.split())
    # the email follows the person and the company
    first, last = eleni.lower().split()
    assert f"{first[0]}.{last}@" in out
    # the product is not a person, the legal form stays, the first name is never kept
    assert "Κρουασάν Βουτύρου" in out and "Hellas EPE" in out
    assert not reps["Nikos Andreou"].startswith("Nikos")
    e.vault.close()


def test_german_and_italian_names_stay_in_their_language(tmp_path):
    from doublecast.data import realnames as R

    e = _engine(tmp_path)
    r = e.scramble("Dear Mr Weber,\nplease ask Frau Sabine Hoffmann.\nKind regards,\nGiulia Ferrari")
    reps = {orig: new for _, orig, new in r.replacements}
    assert reps["Weber"] in R.DE_SURNAMES
    assert reps["Sabine Hoffmann"].split()[0] in R.DE_FEMALE
    assert reps["Giulia Ferrari"].split()[0] in R.IT_FEMALE
    e.vault.close()
