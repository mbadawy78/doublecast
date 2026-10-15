from decimal import Decimal

import pytest

from doublecast.numbers import NumberTransformer, format_number, parse_number


@pytest.mark.parametrize(
    "token,value,decimals",
    [
        ("1.234.567,89", Decimal("1234567.89"), 2),
        ("1,234,567.89", Decimal("1234567.89"), 2),
        ("12,50", Decimal("12.50"), 2),
        ("4.50", Decimal("4.50"), 2),
        ("1.234", Decimal("1234"), 0),
        ("1,234", Decimal("1234"), 0),
        ("1 234,56", Decimal("1234.56"), 2),
        ("7", Decimal("7"), 0),
    ],
)
def test_parse(token, value, decimals):
    v, fmt = parse_number(token)
    assert v == value
    assert fmt.decimals == decimals


def test_format_round_trip_style():
    v, fmt = parse_number("1.234.567,89")
    assert format_number(v, fmt) == "1.234.567,89"


@pytest.mark.parametrize("amount", ["7", "12", "999", "1.500", "12,50", "1.234.567,89", "0,99", "250000"])
@pytest.mark.parametrize("k", [1.17, 1.9, 2.71, 3.4])
def test_scale_then_unscale_is_exact(amount, k):
    nt = NumberTransformer(k, 1.5, 0)
    scaled = nt.scale(amount, nt.k_money, ",")
    back = nt.unscale(scaled, nt.k_money, ",")
    assert parse_number(back)[0] == parse_number(amount)[0], (amount, scaled, back)


@pytest.mark.parametrize(
    "text",
    [
        "budget €2.3m",
        "a $3.2B deal",
        "€12k budget",
        "2.5m€ capex",
        "1,5 εκατ. ευρώ",
        "12 χιλιάδες ευρώ",
        "1.2 million euros",
    ],
)
def test_money_with_magnitude_words(tmp_path, text):
    from doublecast.engine import Engine

    from .conftest import make_config

    e = Engine(make_config(tmp_path))
    out = e.scramble(text).text
    assert out != text
    assert out.count(".") <= text.count(".") + 1  # no "€3.8.3m" garbage
    assert e.restore(out) == text
    e.vault.close()


def test_dates_keep_their_written_form(tmp_path):
    from doublecast.engine import Engine

    from .conftest import make_config

    # One workspace per form: "1/2/24" and "01/02/24" for the same day can
    # shift to the same string, in which case the first form seen wins.
    for i, d in enumerate(["1/2/24", "01/02/24", "05/11/24", "12/11/2024", "2026-03-02"]):
        e = Engine(make_config(tmp_path, shift_dates=True, workspace=f"d{i}"))
        out = e.scramble(f"due {d}").text
        assert d not in out
        assert e.restore(out) == f"due {d}"
        assert e.scramble("release v1.2.2024").text == "release v1.2.2024"
        e.vault.close()


def test_small_quantities_stay_whole(tmp_path):
    from doublecast.engine import Engine

    from .conftest import make_config

    e = Engine(make_config(tmp_path, scale_quantities=True))
    out = e.scramble("ship 12 pallets and 3 cases").text
    assert "." not in out and "," not in out
    assert e.restore(out) == "ship 12 pallets and 3 cases"
    e.vault.close()
