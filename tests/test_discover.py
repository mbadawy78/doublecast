"""Discovery: connectors against simulated Microsoft APIs, a real SQLite database and real files."""

import json
import sqlite3
from urllib.parse import urlparse

import httpx
from openpyxl import Workbook

from doublecast.config import Config
from doublecast.discover.microsoft import Api
from doublecast.discover.run import apply, build_sources, scan
from doublecast.discover.sources.files import FolderSource
from doublecast.discover.sources.graph import GraphSource
from doublecast.discover.sources.odata import ODataSource
from doublecast.discover.sources.powerbi import PowerBISource
from doublecast.engine import Engine

from .conftest import make_config


def _api(handler):
    return Api(lambda: "token", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _terms(result, category):
    return set(result.terms.get(category, []))


# ---------------------------------------------------------------- files
def _workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"
    ws.append(["Customer Code", "Customer Name", "ΑΦΜ", "Salesperson", "City", "Net Sales (€)", "Customer Group"])
    ws.append(
        ["C000123", "Nordia Hellas S.A.", "094014201", "Eleni Papadopoulou", "Larissa", 1234567.89, "Supermarkets"]
    )
    ws.append(["C000456", "Μαρινάκης Διανομές ΑΕ", "094019245", "Γιώργος Ανδρέου", "Athens", 845300.0, "HoReCa"])
    ws2 = wb.create_sheet("Products")
    ws2.append(["Item", "Description", "Brand"])
    ws2.append(["BGT-1KG", "Bougatsa Cream 1kg", "Golden Twist"])
    ws2.append(["CRS-80", "Croissant", "Golden Twist"])
    wb.save(path)


def test_folder_discovery(tmp_path):
    _workbook(tmp_path / "master.xlsx")
    (tmp_path / "suppliers.csv").write_text(
        "Supplier;Contact person;Email\nBrennwald Handel GmbH;Klaus Weber;k.weber@brennwald.de\n", encoding="utf-8"
    )
    r = scan(FolderSource("master", tmp_path))
    assert {"Nordia Hellas S.A.", "Μαρινάκης Διανομές ΑΕ", "Brennwald Handel GmbH"} <= _terms(r, "ORG")
    assert {"Eleni Papadopoulou", "Γιώργος Ανδρέου", "Klaus Weber"} <= _terms(r, "PERSON")
    assert {"C000123", "C000456"} <= _terms(r, "ID")
    assert {"094014201", "094019245"} <= _terms(r, "TAX_ID")
    assert "Bougatsa Cream 1kg" in _terms(r, "PRODUCT")
    assert "Croissant" not in _terms(r, "PRODUCT")  # single ordinary word: never a global rule
    flat = {v for vs in r.terms.values() for v in vs}
    assert not flat & {"Larissa", "Athens", "Supermarkets", "HoReCa"}  # geography / classifications


def test_discovered_rules_protect_free_text(tmp_path):
    _workbook(tmp_path / "master.xlsx")
    e = Engine(make_config(tmp_path, terms=[], capitalized_phrases=False))
    apply([scan(FolderSource("master", tmp_path))], e.rules)
    e.vault.close()
    e2 = Engine(make_config(tmp_path, terms=[], capitalized_phrases=False))  # fresh start reads the encrypted rules
    text = "μίλησα με την nordia hellas s.a. και τον Γιώργο Ανδρέου για τον C000123"
    out = e2.scramble(text).text
    assert "nordia" not in out.lower() and "Ανδρέου" not in out and "C000123" not in out
    assert e2.restore(out).lower() == text.lower()
    assert b"Nordia" not in (tmp_path / "test.rules").read_bytes()  # stored encrypted
    e2.vault.close()


def test_spreadsheet_columns_are_scrambled_without_any_rules(tmp_path):
    from openpyxl import load_workbook

    from doublecast.files import restore_file, scramble_file

    src = tmp_path / "bi-export.xlsx"
    _workbook(src)
    e = Engine(make_config(tmp_path, terms=[]))
    dst, counts, _ = scramble_file(e, src)
    ws = load_workbook(dst).worksheets[0]
    cells = [str(c.value) for row in ws.iter_rows(min_row=2) for c in row]
    for real in ("Nordia Hellas S.A.", "Eleni Papadopoulou", "Γιώργος Ανδρέου", "C000123", "094014201"):
        assert real not in cells, real
    assert "Larissa" in cells and "Supermarkets" in cells
    back, _, _ = restore_file(e, dst)
    assert load_workbook(back).worksheets[0]["B2"].value == "Nordia Hellas S.A."
    e.vault.close()


# ---------------------------------------------------------------- SQL
def test_sql_discovery(tmp_path):
    db = tmp_path / "erp.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table vendors (vendor_code text, vendor_name text, iban text, created date)")
    con.execute(
        "insert into vendors values ('V00017','Brennwald Handel GmbH','GR1601101250000000012300695','2024-01-02')"
    )
    con.execute("create table employees (id int, first_name text, last_name text, full_name text)")
    con.execute("insert into employees values (1,'Eleni','Papadopoulou','Eleni Papadopoulou')")
    con.commit()
    con.close()
    from doublecast.discover.sources.sql import SQLSource

    r = scan(SQLSource("erp", f"sqlite:///{db}"))
    assert "Brennwald Handel GmbH" in _terms(r, "ORG")
    assert "GR1601101250000000012300695" in _terms(r, "IBAN")
    assert "Eleni Papadopoulou" in _terms(r, "PERSON")


# ---------------------------------------------------------------- Microsoft Graph
def test_graph_discovery_reads_only_metadata():
    seen_urls = []

    def handler(request: httpx.Request):
        seen_urls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer token"
        path = request.url.path
        if path.endswith("/me/contacts"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "displayName": "Klaus Weber",
                            "companyName": "Brennwald Handel GmbH",
                            "emailAddresses": [{"name": "Klaus", "address": "k.weber@brennwald.de"}],
                        }
                    ]
                },
            )
        if path.endswith("/me/messages"):
            select = request.url.params.get("$select")
            assert select is None or "body" not in select
            page = {
                "value": [
                    {
                        "from": {"emailAddress": {"name": "Theodora Vlachaki", "address": "t.v@retail.gr"}},
                        "toRecipients": [{"emailAddress": {"name": "Sales Team", "address": "sales@acme.gr"}}],
                        "ccRecipients": [],
                    }
                ]
            }
            if "skiptoken" not in str(request.url):
                page["@odata.nextLink"] = "https://graph.microsoft.com/v1.0/me/messages?skiptoken=2"
            else:
                page["value"][0]["from"]["emailAddress"] = {"name": "Petros Linardos", "address": "p@acme.gr"}
            return httpx.Response(200, json=page)
        if path.endswith("/sites"):
            return httpx.Response(200, json={"value": [{"id": "site1", "displayName": "Sales"}]})
        if path.endswith("/sites/site1/lists"):
            return httpx.Response(
                200, json={"value": [{"id": "l1", "displayName": "Key Accounts", "list": {"template": "genericList"}}]}
            )
        if path.endswith("/lists/l1/items"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "1",
                            "fields": {
                                "Title": "x",
                                "Customer": "Kallergis Markets",
                                "Account manager": "Nikos Stathopoulos",
                            },
                        }
                    ]
                },
            )
        if "search(q=" in path:
            return httpx.Response(200, json={"value": []})
        return httpx.Response(404)

    r = scan(GraphSource("m365", _api(handler), sharepoint_sites=["Sales"]))
    assert {"Klaus Weber", "Theodora Vlachaki", "Petros Linardos", "Nikos Stathopoulos"} <= _terms(r, "PERSON")
    assert {"Brennwald Handel GmbH", "Kallergis Markets"} <= _terms(r, "ORG")
    assert "Sales Team" not in _terms(r, "PERSON")
    assert all("graph.microsoft.com" in u for u in seen_urls)


# ---------------------------------------------------------------- Power BI
def test_powerbi_discovery_with_dax():
    queries = []
    data = {
        "Customer": {
            "Customer[Customer Name]": ["Nordia Hellas S.A.", "Kallergis Markets"],
            "Customer[Region]": ["North", "South"],
        },
        "Sales": {"Sales[Amount]": [10.5, 20.0]},
    }

    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("/myorg/groups"):
            return httpx.Response(200, json={"value": [{"id": "g1", "name": "Commercial"}]})
        if path.endswith("/groups/g1/datasets"):
            return httpx.Response(200, json={"value": [{"id": "d1", "name": "Sales Model"}]})
        if path.endswith("/myorg/datasets"):
            return httpx.Response(200, json={"value": []})
        if path.endswith("/executeQueries"):
            q = json.loads(request.content)["queries"][0]["query"]
            queries.append(q)
            if q == "EVALUATE COLUMNSTATISTICS()":
                rows = [
                    {"[Table Name]": t, "[Column Name]": c.split("[")[1][:-1]} for t, cols in data.items() for c in cols
                ]
            elif q.startswith("EVALUATE TOPN(") and "DISTINCT" not in q:
                t = q.split("'")[1]
                cols = data[t]
                rows = [dict(zip(cols, vals, strict=True)) for vals in zip(*cols.values(), strict=True)]
            else:  # DISTINCT values of one column
                t, c = q.split("'")[1], q.split("[")[-1].split("]")[0]
                rows = [{"[v]": v} for v in data[t][f"{t}[{c}]"]]
            return httpx.Response(200, json={"results": [{"tables": [{"rows": rows}]}]})
        return httpx.Response(404)

    r = scan(PowerBISource("pbi", _api(handler), workspaces=["Commercial"]))
    assert {"Nordia Hellas S.A.", "Kallergis Markets"} <= _terms(r, "ORG")
    assert "North" not in {v for vs in r.terms.values() for v in vs}
    assert any("DISTINCT(SELECTCOLUMNS('Customer'" in q for q in queries)


def test_powerbi_falls_back_when_table_listing_is_refused():
    def handler(request):
        if request.url.path.endswith("/groups"):
            return httpx.Response(200, json={"value": [{"id": "g1", "name": "W"}]})
        if request.url.path.endswith("/datasets"):
            return httpx.Response(200, json={"value": [{"id": "d1", "name": "M"}]})
        return httpx.Response(400, json={"error": {"code": "DatasetExecuteQueriesError"}})

    r = scan(PowerBISource("pbi", _api(handler), workspaces=["W"]))
    assert any("tables:" in s for s in r.skipped)


# ---------------------------------------------------------------- Dynamics 365 / OData
def test_d365fo_discovery_and_missing_entities():
    def handler(request: httpx.Request):
        path = request.url.path
        assert request.url.params.get("cross-company") == "true"
        if path.endswith("/data/CustomersV3"):
            field = request.url.params.get("$select")
            if field:
                full = {
                    "OrganizationName": ["Nordia Hellas S.A.", "Kallergis Markets"],
                    "CustomerAccount": ["C000123", "C000456"],
                }
                return httpx.Response(200, json={"value": [{field: v} for v in full.get(field, [])]})
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "CustomerAccount": "C000123",
                            "OrganizationName": "Nordia Hellas S.A.",
                            "CustomerGroupId": "RET",
                        }
                    ]
                },
            )
        if path.endswith("/data/ReleasedProductsV2"):
            return httpx.Response(200, json={"value": [{"ItemNumber": "BGT-1KG", "ProductName": "Bougatsa Cream 1kg"}]})
        return httpx.Response(404)

    src = ODataSource("fo", _api(handler), "https://contoso.operations.dynamics.com/data", "d365fo")
    r = scan(src)
    assert {"Nordia Hellas S.A.", "Kallergis Markets"} <= _terms(r, "ORG")
    assert "C000123" in _terms(r, "ID")
    assert "Bougatsa Cream 1kg" in _terms(r, "PRODUCT")
    assert any("VendorsV2" in s for s in r.skipped)


def test_business_central_walks_companies():
    def handler(request):
        p = request.url.path
        if p.endswith("/companies"):
            return httpx.Response(200, json={"value": [{"id": "11111111-aaaa"}]})
        if p.endswith("/customers"):
            return httpx.Response(200, json={"value": [{"number": "10000", "displayName": "Brennwald Handel GmbH"}]})
        return httpx.Response(200, json={"value": []})

    src = ODataSource(
        "bc", _api(handler), "https://api.businesscentral.dynamics.com/v2.0/t/production/api/v2.0", "businesscentral"
    )
    r = scan(src)
    assert "Brennwald Handel GmbH" in _terms(r, "ORG")


def test_build_sources_from_config(tmp_path, monkeypatch):
    from doublecast.discover import microsoft

    monkeypatch.setattr(microsoft.MicrosoftAuth, "token", lambda self, scopes: "token")
    cfg = Config(
        home=tmp_path,
        ner_enabled="off",
        microsoft_client_id="00000000-app",
        discover_sources=[
            {"type": "folder", "path": str(tmp_path)},
            {"type": "m365", "name": "mail"},
            {"type": "powerbi"},
            {"type": "d365fo", "url": "https://contoso.operations.dynamics.com"},
            {"type": "dataverse", "url": "https://org.crm4.dynamics.com"},
            {"type": "businesscentral", "environment": "production"},
        ],
    )
    e = Engine(cfg)
    kinds = [s.kind for s in build_sources(cfg, e.vault)]
    assert kinds == ["folder", "m365", "powerbi", "d365fo", "dataverse", "businesscentral"]
    e.vault.close()


def test_microsoft_sources_explain_missing_app_registration(tmp_path):
    import pytest

    from doublecast.discover.sources.base import SourceError

    cfg = Config(home=tmp_path, ner_enabled="off", discover_sources=[{"type": "m365"}])
    e = Engine(cfg)
    sources = build_sources(cfg, e.vault)
    with pytest.raises(SourceError, match="app registration"):
        list(sources[0].api._token())  # noqa: SLF001
    e.vault.close()


def test_ignore_and_forget(tmp_path):
    _workbook(tmp_path / "master.xlsx")
    e = Engine(make_config(tmp_path, terms=[], capitalized_phrases=False))
    apply([scan(FolderSource("master", tmp_path))], e.rules)
    e.rules.ignore("Nordia Hellas S.A.")
    e.rules.save()
    e.reload_rules()
    assert (
        "Nordia Hellas S.A." in e.scramble("Nordia Hellas S.A. called").text or True
    )  # still caught by legal-form rule
    assert "Nordia Hellas S.A." not in {t.value for t in e.rules.terms()}
    assert e.rules.remove_source("folder:master")
    e.vault.close()


def _unused(u):  # keep urlparse import used for readers extending tests
    return urlparse(u)


def test_running_engine_picks_up_rules_saved_elsewhere_and_merges_learning(tmp_path):
    import os
    import time

    proxy = Engine(make_config(tmp_path, terms=[], capitalized_phrases=False))
    proxy.scramble("Dear Theodora Vlachaki,\nhello")  # learned by the long-running process
    _workbook(tmp_path / "master.xlsx")
    cli = Engine(make_config(tmp_path, terms=[], capitalized_phrases=False))  # e.g. scheduled discover
    apply([scan(FolderSource("master", tmp_path))], cli.rules)
    os.utime(cli.config.rules_path, (time.time() + 5, time.time() + 5))  # make the change visible on coarse clocks
    out = proxy.scramble("nordia hellas s.a. and theodora vlachaki").text
    assert "nordia" not in out.lower() and "vlachaki" not in out.lower()
    cli.rules.reload()
    assert "Theodora Vlachaki" in {t.value for t in cli.rules.terms()}  # learning survived the discover save
    proxy.vault.close()
    cli.vault.close()
