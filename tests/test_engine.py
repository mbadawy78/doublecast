import pytest

from doublecast.engine import Engine

from .conftest import make_config

SAMPLE = (
    "Nordia Hellas wants 12% more volume from Larissa Plant. Eleni Papadopoulou "
    "(eleni.papadopoulou@acmefoods.gr, +30 697 123 4567) says the account pays €1.234.567,89 a year. "
    "ΑΦΜ: 094014201, IBAN GR16 0110 1250 0000 0001 2300 695. Invoice No: INV-2024/0187. "
    "Golden Twist 80g launches in Greece under Project Falcon."
)
ORIGINALS = [
    "Nordia",
    "Larissa",
    "Papadopoulou",
    "eleni.papadopoulou@acmefoods.gr",
    "697 123 4567",
    "1.234.567,89",
    "094014201",
    "GR16 0110",
    "INV-2024/0187",
    "Golden Twist",
    "Falcon",
]


def test_nothing_sensitive_survives(engine):
    out = engine.scramble(SAMPLE).text
    for value in ORIGINALS:
        assert value not in out, value
    assert "Greece" in out  # allow list
    assert "12%" in out  # percentages are never touched


def test_round_trip_is_exact(engine):
    out = engine.scramble(SAMPLE).text
    assert engine.restore(out) == SAMPLE


def test_stand_ins_are_consistent_and_persistent(engine_factory):
    e1 = engine_factory()
    first = e1.scramble("Meeting with Nordia Hellas").text
    second = e1.scramble("Nordia Hellas again").text
    assert first.split("with ")[1] == second.split(" again")[0]
    e1.vault.close()
    e2 = engine_factory()  # new process, same vault
    assert e2.scramble("Meeting with Nordia Hellas").text == first


def test_case_and_accent_insensitive(engine):
    a = engine.scramble("NORDIA HELLAS").text
    b = engine.scramble("nordia hellas").text
    assert "nordia" not in a.lower() and "nordia" not in b.lower()


def test_greek_alias_and_inflection(engine):
    text = "Η παραγγελία του Καλλέργη και της Καρανίκα Τρόφιμα."
    out = engine.scramble(text).text
    assert "Καλλέργ" not in out and "Καρανίκ" not in out
    restored = engine.restore(out)
    assert "Καρανίκα Τρόφιμα" in restored  # genitive kept exactly
    assert "Kallergis" in restored  # alias restores to the canonical name


def test_restore_survives_model_mangling(engine):
    out = engine.scramble("Talk to Nordia Hellas").text
    stand_in = out.replace("Talk to ", "")
    assert engine.restore(f"{stand_in.upper()}'s margin") == "NORDIA HELLAS's margin"  # case follows the text
    assert engine.restore(f"{stand_in}'s margin") == "Nordia Hellas's margin"


def test_secrets_are_removed_and_never_restored(engine):
    key = "sk-ant-api03-" + "a" * 40
    out = engine.scramble(f"use key {key} please").text
    assert key not in out and "[REDACTED:anthropic_key]" in out
    assert key not in engine.restore(out)


def test_iban_digits_are_not_mistaken_for_cards(engine):
    out = engine.scramble("IBAN GR53 0222 7918 0588 8718 0334 018").text
    assert "REDACTED" not in out
    assert out.startswith("IBAN GR")


def test_structured_doubles_are_never_rescrambled(engine):
    once = engine.scramble(SAMPLE).text
    twice = engine.scramble(once).text
    # emails, phones, IBANs, tax IDs and invoice numbers that are already doubles stay as they are.
    # Names may be swapped again on purpose: a real person can share a name with a double.
    import re

    structured = r"[\w.]+@[\w.]+|\+30 [\d ]+|GR\d\d[\d ]+|ΑΦΜ: \d+|INV-[\d/]+"
    assert re.findall(structured, once) == re.findall(structured, twice)


def test_money_scaling_keeps_ratios_and_restores(engine):
    out = engine.scramble("Revenue €200.00 vs cost €50.00").text
    nums = [float(x.replace(",", "")) for x in __import__("re").findall(r"€([\d,]+\.\d\d)", out)]
    assert nums[0] != 200.0
    assert abs(nums[0] / nums[1] - 4.0) < 0.01
    assert engine.restore(out) == "Revenue €200.00 vs cost €50.00"


def test_model_computed_amount_restores_to_the_cent(engine):
    # Amounts the AI computes from scaled inputs carry the inputs' rounding:
    # originals restore exactly, derived totals to within a cent or two.
    import re

    out = engine.scramble("Price €10.00 per case").text
    scaled = float(re.search(r"€(\d+\.\d\d)", out).group(1))
    reply = f"For 3 cases you pay €{scaled * 3:.2f}."
    restored = engine.restore(reply)
    value = float(re.search(r"€(\d+\.\d\d)", restored).group(1))
    assert abs(value - 30.00) <= 0.02


def test_surname_alone_is_caught(engine):
    engine.scramble("Eleni Papadopoulou joined.")
    out = engine.scramble("Ms Papadopoulou agreed.").text
    assert "Papadopoulou" not in out
    assert engine.restore(out) == "Ms Papadopoulou agreed."


def test_dates_shift_by_whole_weeks(tmp_path):
    e = Engine(make_config(tmp_path, shift_dates=True))
    out = e.scramble("Delivery on 2026-03-02 (Monday).").text
    assert "2026-03-02" not in out
    import datetime as dt

    shifted = dt.date.fromisoformat(out.split("on ")[1][:10])
    assert shifted.weekday() == 0  # still a Monday
    assert e.restore(out) == "Delivery on 2026-03-02 (Monday)."
    e.vault.close()


def test_unlisted_names_are_caught_on_the_fly(engine):
    res = engine.scramble("Please call Theodora Vlachaki about it.")
    assert "Theodora Vlachaki" not in res.text


def test_unlisted_name_hint_when_broad_net_is_off(tmp_path):
    e = Engine(make_config(tmp_path, capitalized_phrases=False))
    res = e.scramble("Please call Theodora Vlachaki about it.")
    assert any("Theodora Vlachaki" in w for w in res.warnings)
    e.vault.close()


def test_pack_patterns_need_digits(engine):
    out = engine.scramble("The contract renewal is due; invoice no. 2024/551 attached.").text
    assert "renewal" in out
    assert "2024/551" not in out


def test_surname_alone_needs_a_capital(tmp_path):
    from doublecast.config import Term

    e = Engine(make_config(tmp_path, terms=[Term("PERSON", "Anna Rose")]))
    e.scramble("Anna Rose signed.")
    out = e.scramble("A rose by any other name; Rose agreed.").text
    assert out.startswith("A rose by any other name; ")
    assert "Rose agreed" not in out
    restored = e.restore(out)
    assert restored == "A rose by any other name; Rose agreed."
    e.vault.close()


@pytest.mark.parametrize(
    "sentence",
    [
        "Ο Γιώργος Καλλέργης συμφωνεί.",
        "Μίλησα με τον Γιώργο Καλλέργη.",
        "Η γνώμη του Γιώργου Καλλέργη.",
        "Η Δέσποινα Μαυρίδου και η ομάδα της Δέσποινας Μαυρίδου.",
        "ΣΥΝΑΝΤΗΣΗ ΜΕ ΤΟΝ ΓΙΩΡΓΟ ΚΑΛΛΕΡΓΗ",
    ],
)
def test_greek_names_keep_their_case(tmp_path, sentence):
    from doublecast.config import Term

    e = Engine(make_config(tmp_path, terms=[Term("PERSON", "Γιώργος Καλλέργης"), Term("PERSON", "Δέσποινα Μαυρίδου")]))
    out = e.scramble(sentence).text
    assert "Καλλέργ" not in out and "Μαυρίδ" not in out and "ΚΑΛΛΕΡΓ" not in out
    assert e.restore(out) == sentence
    e.vault.close()


def test_alias_comes_back_as_written(engine_factory):
    from doublecast.config import Term

    e = engine_factory(terms=[Term("ORG", "Trio Bakery", ["Trio"])])
    text = "Distributors FOB Trio; contract with Trio Bakery."
    out = e.scramble(text).text
    assert "Trio" not in out
    assert e.restore(out) == text


def test_name_known_in_capitals_comes_back_in_the_case_it_was_written(engine):
    engine.stand_in("ORG", "SOLEROX")
    text = "Price list: Solerox / Gala, SOLEROX club"
    engine.learn_value("ORG", "SOLEROX")
    engine.flush_learned()
    out = engine.scramble(text).text
    assert "olerox" not in out.lower()
    assert engine.restore(out) == text
