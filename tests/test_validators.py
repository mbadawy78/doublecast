import random

from doublecast.validators import (
    afm_complete,
    afm_valid,
    amka_valid,
    dni_letter,
    dni_valid,
    ean13_complete,
    ean13_valid,
    iban_valid,
    iban_with_check,
    luhn_valid,
    shape_preserving,
)


def test_iban_examples():
    assert iban_valid("GR16 0110 1250 0000 0001 2300 695")
    assert iban_valid("DE89370400440532013000")
    assert not iban_valid("DE89370400440532013001")


def test_iban_generation_is_valid():
    rng = random.Random(1)
    for _ in range(50):
        bban = "".join(rng.choice("0123456789") for _ in range(23))
        assert iban_valid(iban_with_check("GR", bban))


def test_afm():
    assert afm_valid("094014201")
    assert not afm_valid("094014202")
    assert afm_valid(afm_complete("12345678"))


def test_luhn_and_amka():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert not amka_valid("99999999999")


def test_ean_and_dni():
    assert ean13_valid(ean13_complete("520123456789"))
    assert dni_valid("12345678" + dni_letter("12345678"))


def test_shape_preserving_keeps_shape():
    out = shape_preserving("INV-2024/0187", random.Random(3), keep_prefix=4)
    assert out.startswith("INV-")
    assert len(out) == len("INV-2024/0187")
    assert out[8] == "/"
