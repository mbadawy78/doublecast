"""A stand-in for a local Power BI connector (MCP over stdio), for tests. Real-looking data, all invented."""

import json
import os
import sys

ROWS = [
    {
        "Customers[Customer Name]": "Brightvale Foods Ltd.",
        "Customers[Short Name]": "BRIGHTVALE",
        "[Sales]": 1250000.5,
        "[Orders]": 312,
        "[Margin %]": 0.214,
    },
    {
        "Customers[Customer Name]": "Quorvia Distribution",
        "Customers[Short Name]": "QUORVIA",
        "[Sales]": 880000.0,
        "[Orders]": 118,
        "[Margin %]": 0.187,
    },
]
COLUMNS = [
    {"t": "Customers", "c": "Customer Name"},
    {"t": "Customers", "c": "Short Name"},
    {"t": "Customers", "c": "City"},
]


def reply(i, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, "result": result}) + "\n")
    sys.stdout.flush()


def text(obj):
    return {"content": [{"type": "text", "text": json.dumps({"result": json.dumps(obj, indent=2)})}], "isError": False}


for line in sys.stdin:
    msg = json.loads(line)
    method, i = msg.get("method"), msg.get("id")
    if method == "initialize":
        reply(i, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-pbi"}})
    elif method == "tools/list":
        reply(i, {"tools": [{"name": "powerbi_known_datasets"}, {"name": "powerbi_run_dax"}]})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments", {})
        if os.environ.get("FAKE_PBI_LOG"):
            with open(os.environ["FAKE_PBI_LOG"], "a", encoding="utf-8") as fh:
                fh.write(json.dumps(args) + "\n")
        if name == "powerbi_known_datasets":
            reply(i, text({"datasets": {"sales": {"id": "x", "workspace": "ws"}}}))
        else:
            dax = args["params"]["dax_query"]
            if "INFO.VIEW.COLUMNS" in dax:
                rows = [{"[t]": c["t"], "[c]": c["c"]} for c in COLUMNS]
            elif "TOPN" in dax and "DISTINCT" not in dax:
                rows = [
                    {
                        "Customers[Customer Name]": r["Customers[Customer Name]"],
                        "Customers[Short Name]": r["Customers[Short Name]"],
                        "Customers[City]": "Toronto",
                    }
                    for r in ROWS
                ]
            elif "DISTINCT" in dax:
                col = "Customer Name" if "Customer Name" in dax else ("Short Name" if "Short Name" in dax else "City")
                vals = [r.get(f"Customers[{col}]", "Toronto") for r in ROWS]
                rows = [{"[v]": v} for v in vals]
            else:
                rows = ROWS
            reply(
                i, text({"row_count_returned": len(rows), "truncated": False, "columns": list(rows[0]), "rows": rows})
            )
