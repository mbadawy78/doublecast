"""Connectors behind Doublecast: the wrapper, discovery through the connector, connect/undo, the leak alarm."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from doublecast.config import Term
from doublecast.connectors import StdioClient, connect, disconnect, registered
from doublecast.discover.profiler import classify_column
from doublecast.wrap import Scrambler

FAKE = str(Path(__file__).parent / "fixtures" / "fake_powerbi_server.py")
REAL = ("Brightvale", "BRIGHTVALE", "Quorvia", "QUORVIA")


def _rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    return json.loads(proc.stdout.readline())


def test_wrapped_connector_scrambles_results_and_restores_arguments(tmp_path):
    log = tmp_path / "args.log"
    env = {**os.environ, "DOUBLECAST_HOME": str(tmp_path / "home"), "FAKE_PBI_LOG": str(log)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "doublecast", "wrap", "--name", "powerbi", "--", sys.executable, FAKE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        q = {"workspace": "ws", "dataset": "sales", "dax_query": "EVALUATE Customers"}
        res = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "powerbi_run_dax", "arguments": {"params": q}},
            },
        )
        text = res["result"]["content"][0]["text"]
        for real in REAL:
            assert real not in text, real
        data = json.loads(json.loads(text)["result"])
        rows = data["rows"]
        assert rows[0]["[Orders]"] == 312 and rows[0]["[Margin %]"] == 0.214  # counts and % untouched
        assert rows[0]["[Sales]"] != 1250000.5  # money scaled
        assert abs(rows[0]["[Sales]"] / rows[1]["[Sales]"] - 1250000.5 / 880000.0) < 1e-6  # ratios kept
        double = rows[0]["Customers[Customer Name]"]
        q2 = {"workspace": "ws", "dataset": "sales", "dax_query": f'FILTER(Customers, [Customer Name] = "{double}")'}
        _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "powerbi_run_dax", "arguments": {"params": q2}},
            },
        )
        sent = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert "Brightvale Foods Ltd." in sent[-1]["params"]["dax_query"]  # the connector got the real name
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_discovery_reads_names_through_the_connector(tmp_path, engine_factory):
    from doublecast.discover.run import scan
    from doublecast.discover.sources.powerbi import McpPowerBISource

    client = StdioClient(sys.executable, [FAKE])
    src = McpPowerBISource("powerbi-connector", client)
    try:
        result = scan(src)
    finally:
        src.close()
    assert result.error is None, result.error
    assert "Brightvale Foods Ltd." in result.terms.get("ORG", [])


def test_connect_and_undo_edit_the_claude_config_with_a_backup(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    original = {"mcpServers": {"powerbi": {"command": "/usr/bin/python3", "args": ["/x/server.py"], "env": {"A": "1"}}}}
    cfg.write_text(json.dumps(original), encoding="utf-8")
    home = tmp_path / "home"
    connect(home, "powerbi", cfg)
    wrapped = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["powerbi"]
    assert "wrap" in wrapped["args"] and wrapped["args"][-2:] == ["/usr/bin/python3", "/x/server.py"]
    assert wrapped["env"] == {"A": "1"}
    assert registered(home)["powerbi"]["command"] == "/usr/bin/python3"
    assert list(tmp_path.glob("claude_desktop_config.json.before-doublecast-*"))
    assert "already" in connect(home, "powerbi", cfg)
    with pytest.raises(ValueError):
        connect(home, "nope", cfg)
    disconnect(home, "powerbi")
    assert json.loads(cfg.read_text(encoding="utf-8")) == original


def test_leak_alarm_reports_known_values_that_got_through(engine_factory):
    e = engine_factory(terms=[Term("ORG", "Brightvale Foods", ["Brightvale"])])
    assert e.leaks(e.scramble("Order from Brightvale Foods today").text) == []
    assert e.check_and_log_leaks("raw text naming Brightvale", "test/file.csv") == 1
    e.activity.flush()
    from doublecast import activity

    s = activity.summary(e.config.home / f"{e.config.workspace}.activity.json")
    assert s["leaks_today"] and "Brightvale" not in json.dumps(s)  # masked


def test_amounts_are_not_phone_numbers():
    assert classify_column("col12", ["7520035.25", "-45212.5", "157,000.75", "n/a"]).category is None
    assert classify_column("Mobile", ["+30 694 123 4567", "6944 123456"]).category == "PHONE"


def test_scrambler_keeps_schema_and_counts(engine):
    out = Scrambler(engine).text(
        json.dumps(
            {
                "columns": ["Customers[Customer Name]"],
                "row_count_returned": 2,
                "rows": [{"Customers[Customer Name]": "Nordia Hellas"}, {"Customers[Customer Name]": "Kallergis"}],
            }
        )
    )
    data = json.loads(out)
    assert data["columns"] == ["Customers[Customer Name]"] and data["row_count_returned"] == 2
    assert "Nordia" not in out and "Kallergis" not in out


def test_discover_run_uses_a_connected_powerbi_without_config(tmp_path, monkeypatch, capsys):
    from doublecast.cli import main

    home = tmp_path / "home"
    home.mkdir()
    (home / "connectors.json").write_text(
        json.dumps({"powerbi": {"command": sys.executable, "args": [FAKE], "env": {}}}), encoding="utf-8"
    )
    monkeypatch.setenv("DOUBLECAST_HOME", str(home))
    assert main(["discover", "run", "--yes", "--quiet"]) == 0
    assert "No sources configured" not in capsys.readouterr().out
    from doublecast.config import load_config
    from doublecast.engine import Engine

    e = Engine(load_config(None))
    assert "Brightvale" not in e.scramble("Order from Brightvale Foods Ltd. today").text


def test_show_answer_opens_the_real_values_and_returns_none_of_them(tmp_path):
    home = tmp_path / "home"
    env = {**os.environ, "DOUBLECAST_HOME": str(home), "PATH": "/nonexistent"}  # no browser in tests
    proc = subprocess.Popen(
        [sys.executable, "-m", "doublecast", "wrap", "--name", "powerbi", "--", sys.executable, FAKE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        init = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert "show_answer" in init["result"]["instructions"]
        tools = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert "show_answer" in [t["name"] for t in tools["result"]["tools"]]
        q = {"workspace": "ws", "dataset": "sales", "dax_query": "EVALUATE Customers"}
        res = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "powerbi_run_dax", "arguments": {"params": q}},
            },
        )
        rows = json.loads(json.loads(res["result"]["content"][0]["text"])["result"])["rows"]
        double, sales = rows[0]["Customers[Customer Name]"], rows[0]["[Sales]"]
        answer = f"## Top customers\n\n| Customer | Sales |\n|---|---:|\n| {double} | €{sales:,.2f} |\n"
        shown = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "show_answer", "arguments": {"title": "Top customers", "markdown": answer}},
            },
        )
        reply = json.dumps(shown)
        assert "Brightvale" not in reply and "1,250,000" not in reply
        page = next((home / "answers").glob("*.html")).read_text(encoding="utf-8")
        assert "Brightvale Foods Ltd." in page and "1,250,000.50" in page and 'charset="utf-8"' in page
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_status_notices_when_the_app_undid_the_connection(tmp_path):
    from doublecast.connectors import protected

    cfg = tmp_path / "claude_desktop_config.json"
    original = {"mcpServers": {"powerbi": {"command": "/x/run.sh", "args": []}}}
    cfg.write_text(json.dumps(original), encoding="utf-8")
    home = tmp_path / "home"
    connect(home, "powerbi", cfg)
    assert protected(home) == {"powerbi": True}
    cfg.write_text(json.dumps(original), encoding="utf-8")  # the app wrote its old copy back
    assert protected(home) == {"powerbi": False}


def test_structured_content_with_json_inside_is_scrambled_like_the_text(engine):
    inner = json.dumps({"rows": [{"[Customer]": "Nordia Hellas", "[Sales]": 1000.0, "[Orders]": 7}]}, indent=2)
    out = Scrambler(engine).result(
        {"content": [{"type": "text", "text": inner}], "structuredContent": {"result": inner}}, "test"
    )
    for part in (out["content"][0]["text"], out["structuredContent"]["result"]):
        row = json.loads(part)["rows"][0]
        assert "Nordia" not in part and row["[Sales]"] != 1000.0 and row["[Orders]"] == 7
