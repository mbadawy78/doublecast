"""Auto mode: names found with no lists and no AI, then remembered."""

from doublecast.engine import Engine

from .conftest import make_config

EMAIL = """From: Theodora Vlachaki <t.vlachaki@example-retail.gr>
To: Sales Team <sales@acmefoods.gr>; Petros Linardos <p.linardos@acmefoods.gr>
Subject: New listing

Dear Petros,

Brennwald Handel GmbH and Μαρινάκης Διανομές ΑΕ asked κ. Σταματόπουλο for the new prices.
Ms Vlachaki will confirm by Friday.

Kind regards,
Theodora Vlachaki
"""


def _engine(tmp_path, **kw):
    return Engine(make_config(tmp_path, terms=[], **kw))


def test_email_structure_without_lists(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=False)
    out = e.scramble(EMAIL).text
    for name in ("Theodora Vlachaki", "Vlachaki", "Petros", "Linardos", "Brennwald", "Μαρινάκης", "Σταματόπουλ"):
        assert name not in out, name
    assert "Friday" in out and "Kind regards" in out
    assert e.restore(out) == EMAIL
    e.vault.close()


def test_names_are_learned_and_caught_later(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=False)
    e.scramble("Dear Theodora Vlachaki,\nthanks.")
    later = e.scramble("theodora vlachaki called again").text  # no structure, lower case
    assert "vlachaki" not in later.lower()
    e.vault.close()
    # learned rules survive a restart (encrypted on disk)
    e2 = _engine(tmp_path, capitalized_phrases=False)
    assert "vlachaki" not in e2.scramble("theodora vlachaki called").text.lower()
    e2.vault.close()


def test_legal_form_teaches_the_bare_name_with_a_matching_double(tmp_path):
    e = _engine(tmp_path, capitalized_phrases=False)
    full = e.scramble("Order from Brennwald Handel GmbH today.").text
    bare = e.scramble("Brennwald Handel paid.").text
    double_full = full.replace("Order from ", "").replace(" today.", "")
    double_bare = bare.replace(" paid.", "")
    assert double_full.startswith(double_bare)  # same company, same double
    e.vault.close()


def test_broad_net_catches_names_but_spares_vocabulary(tmp_path):
    e = _engine(tmp_path)
    out = e.scramble(
        "We met Georgia Konstantinou and the Zorvex Pastries team in Athens on Monday "
        "to discuss the Annual Leave Policy and the Lead Time targets."
    ).text
    assert "Konstantinou" not in out and "Zorvex" not in out
    for kept in ("Athens", "Monday", "Annual Leave Policy", "Lead Time"):
        assert kept in out, kept
    e.vault.close()


def test_nothing_learned_when_disabled(tmp_path):
    e = _engine(tmp_path, auto_learn=False, capitalized_phrases=False)
    e.scramble("Dear Theodora Vlachaki,\nthanks.")
    assert "vlachaki" in e.scramble("theodora vlachaki called").text.lower()
    e.vault.close()
