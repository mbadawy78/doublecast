"""Activity log, `doublecast status` and the tray's menu text."""

import json

from doublecast import activity
from doublecast.cli import main
from doublecast.engine import Engine

from .conftest import make_config


def test_activity_holds_counts_and_masked_samples_only(tmp_path):
    e = Engine(make_config(tmp_path, terms=[]))
    e.scramble("Dear Ms Vlachaki,\nLidl Hellas EPE owes €1.250,00. Write to eleni.p@masoutis.gr")
    e.activity.flush()
    raw = (tmp_path / "test.activity.json").read_text(encoding="utf-8")
    for real in ("Vlachaki", "Lidl", "eleni.p@masoutis.gr", "1.250"):
        assert real not in raw
    s = activity.summary(tmp_path / "test.activity.json")
    assert s["today_total"] >= 3 and s["today"]["PERSON"] >= 1
    assert all("•••" in row["from"] for row in s["last"])
    e.vault.close()


def test_two_processes_add_up(tmp_path):
    path = tmp_path / "w.activity.json"
    a, b = activity.Activity(path, "proxy"), activity.Activity(path, "clipboard")
    a.record([("PERSON", "Eleni", "Fani")])
    a.flush()
    b.record([("ORG", "Lidl", "Marlow"), ("PERSON", "Nikos", "Kostas")])
    b.flush()
    s = activity.summary(path)
    assert s["today"] == {"PERSON": 2, "ORG": 1} and s["total_all"] == 3


def test_status_command_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOUBLECAST_HOME", str(tmp_path))
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"proxy", "today", "today_total", "total_all", "last", "version"} <= set(data)
    assert data["proxy"]["running"] in (True, False)


def test_tray_menu_text(tmp_path):
    from doublecast.tray import Model

    m = Model.__new__(Model)
    m.cfg = make_config(tmp_path)
    m._engine = None
    m._proxy = None
    m.data = {
        "today_total": 4,
        "today": {"PERSON": 2, "ORG": 1, "MONEY": 1},
        "total_all": 10,
        "last": [],
        "proxy": {"running": True, "address": "http://127.0.0.1:8787"},
    }
    assert m.title == "🛡 4"
    assert m.proxy_line.startswith("●")
    assert "2 people" in m.today_line and "1 company" in m.today_line
    assert m.last_lines == ["Nothing swapped yet"]
