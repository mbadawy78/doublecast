from __future__ import annotations

import pytest

from doublecast.config import Config, Term
from doublecast.engine import Engine

TERMS = [
    Term("ORG", "Nordia Hellas"),
    Term("ORG", "Kallergis", ["Καλλέργης"]),
    Term("ORG", "Καρανίκας Τρόφιμα"),
    Term("PERSON", "Eleni Papadopoulou"),
    Term("PERSON", "Georgios Andreou"),
    Term("SITE", "Larissa Plant"),
    Term("PRODUCT", "Golden Twist 80g"),
    Term("PROJECT", "Project Falcon"),
]


def make_config(tmp_path, **kw) -> Config:
    base = dict(workspace="test", home=tmp_path, terms=list(TERMS), allow=["Greece", "Athens"], ner_enabled="off")
    base.update(kw)
    return Config(**base)


@pytest.fixture
def engine(tmp_path):
    e = Engine(make_config(tmp_path))
    yield e
    e.vault.close()


@pytest.fixture
def engine_factory(tmp_path):
    made = []

    def make(**kw):
        e = Engine(make_config(tmp_path, **kw))
        made.append(e)
        return e

    yield make
    for e in made:
        e.vault.close()
