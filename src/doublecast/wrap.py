"""`doublecast wrap -- <connector command>`: a local connector (MCP server), seen through Doublecast.

The Claude app talks to this process; this process talks to the real connector.

    AI ──call──▶ wrap: put real values back in the arguments ──▶ connector ──▶ your data
    AI ◀─doubles─ wrap: scramble the result, check for leaks ◀── connector ◀──┘

Results that are tables (Power BI rows, query results, lists of records) are scrambled column by
column: the column name says what the values are, so a "Customer" column is swapped whole and a
"Sales" measure is scaled by the secret factor, while counts, percentages and dates stay as they
are. Anything else is scrambled as text.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

from .files.tabular import column_kind, factor_for, prelearn, row_kind, scale_value, scramble_cell


def _split_key(key: str) -> tuple[str, str]:
    """'Customers[Customer Name]' -> ('Customers', 'Customer Name'); '[Sales]' -> ('', 'Sales')."""
    if "[" in key and key.endswith("]"):
        table, _, col = key.partition("[")
        return table.strip().strip("'"), col[:-1]
    return "", key


def _money(engine, header: str) -> bool:
    if not engine.config.scale_money or row_kind(header) == "keep":
        return False
    return column_kind(engine, header) == "money" or row_kind(header) == "money"


class Scrambler:
    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.Lock()

    # ------------------------------------------------------------ results going to the AI
    def result(self, result: dict, where: str) -> dict:
        with self.lock:
            self.engine.from_disk = True  # connector data is real, never earlier doubles
            try:
                out = dict(result)
                content = []
                for item in result.get("content", []) or []:
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        item = {**item, "text": self.text(item["text"])}
                    elif item.get("type") in ("image", "audio", "resource", "resource_link"):
                        item = {
                            "type": "text",
                            "text": "[Doublecast: a non-text result was withheld; it cannot be scrambled]",
                        }
                    content.append(item)
                if "content" in result:
                    out["content"] = content
                if isinstance(result.get("structuredContent"), (dict, list)):
                    out["structuredContent"] = self.value(result["structuredContent"])
                leaked = sum(
                    self.engine.check_and_log_leaks(c.get("text", ""), where)
                    for c in content
                    if c.get("type") == "text"
                )
                if leaked:
                    print(
                        f"doublecast: {leaked} known value(s) still visible in a result from {where}", file=sys.stderr
                    )
                self.engine.activity.flush()
                return out
            finally:
                self.engine.from_disk = False

    def text(self, text: str) -> str:
        try:
            data = json.loads(text)
        except ValueError:
            return self.engine.scramble(text).text
        if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
            return json.dumps({"result": self.text(data["result"])}, ensure_ascii=False)
        pretty = "\n" in text
        return json.dumps(self.value(data), ensure_ascii=False, indent=2 if pretty else None)

    def value(self, obj, header: str = "", table: str = ""):
        if isinstance(obj, dict):
            rows = obj.get("rows")
            out = {}
            for k, v in obj.items():
                if k == "rows" and isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
                    out[k] = self.rows(rows)
                elif k in ("columns", "column_names") and isinstance(v, list):
                    out[k] = v  # the schema names columns, it holds no data
                else:
                    out[k] = self.value(v, k, table)
            return out
        if isinstance(obj, list):
            if obj and all(isinstance(r, dict) for r in obj) and len(obj) > 1:
                return self.rows(obj)
            return [self.value(v, header, table) for v in obj]
        if isinstance(obj, str):
            if header:
                t, h = _split_key(header)
                return scramble_cell(self.engine, h, obj, t or table)[0]
            return self.engine.scramble(obj).text
        if isinstance(obj, (int, float)) and not isinstance(obj, bool) and header:
            _, h = _split_key(header)
            if _money(self.engine, h):
                return scale_value(obj, factor_for(self.engine, "money"), "scramble")
        return obj

    def rows(self, rows: list[dict]) -> list[dict]:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        by_table: dict[str, list[str]] = {}
        for k in keys:
            t, h = _split_key(k)
            by_table.setdefault(t, []).append(k)
        for t, ks in by_table.items():  # learn every name in the result first, short forms included
            prelearn(self.engine, [_split_key(k)[1] for k in ks], ([r.get(k) for k in ks] for r in rows), t)
        out = []
        for r in rows:
            new = {}
            for k, v in r.items():
                t, h = _split_key(k)
                if isinstance(v, (dict, list)):
                    new[k] = self.value(v, k, t)
                else:
                    new[k] = self.value(v, k, t)
            out.append(new)
        return out

    # ------------------------------------------------------------ arguments coming from the AI
    def arguments(self, args):
        with self.lock:
            return self._restore(args)

    def _restore(self, obj):
        if isinstance(obj, dict):
            return {k: self._restore(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._restore(v) for v in obj]
        if isinstance(obj, str):
            return self.engine.restore(obj)
        return obj


def run_wrap(engine, command: list[str], name: str = "connector") -> int:
    if not command:
        print("Usage: doublecast wrap -- <connector command> [args...]", file=sys.stderr)
        return 2
    engine.activity.source = name
    scr = Scrambler(engine)
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # the connector's own log goes where ours goes
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    from .answers import CONFIRMATION, TOOL, show_answer

    calls: dict[object, str] = {}
    lists: set = set()
    inits: set = set()
    out_lock = threading.Lock()

    def emit(msg: dict) -> None:
        with out_lock:
            sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def to_connector():
        assert child.stdin is not None
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                child.stdin.write(line)
                child.stdin.flush()
                continue
            if isinstance(msg, dict) and msg.get("method") == "tools/list" and "id" in msg:
                lists.add(msg["id"])
            if isinstance(msg, dict) and msg.get("method") == "initialize" and "id" in msg:
                inits.add(msg["id"])
            if isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg:
                params = msg.get("params") or {}
                if params.get("name") == TOOL["name"]:  # ours: answered here, never sent to the connector
                    args = params.get("arguments") or {}
                    with scr.lock:
                        show_answer(engine, str(args.get("markdown", "")), str(args.get("title", "")))
                    emit(
                        {
                            "jsonrpc": "2.0",
                            "id": msg["id"],
                            "result": {"content": [{"type": "text", "text": CONFIRMATION}]},
                        }
                    )
                    continue
                calls[msg["id"]] = str(params.get("name", "tool"))
                if "arguments" in params:
                    params["arguments"] = scr.arguments(params["arguments"])
                msg["params"] = params
                line = json.dumps(msg, ensure_ascii=False) + "\n"
            child.stdin.write(line)
            child.stdin.flush()
        try:
            child.stdin.close()
        except OSError:
            pass

    threading.Thread(target=to_connector, daemon=True).start()
    assert child.stdout is not None
    for line in child.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue  # stray output from the connector must never reach the AI unscrambled
        if isinstance(msg, dict) and msg.get("id") in inits and isinstance(msg.get("result"), dict):
            inits.discard(msg["id"])
            note = (
                "This connector runs through Doublecast: names in results are stand-ins and money is scaled "
                "by a secret factor (ratios, rankings and % are true). Use the stand-ins as they are. After "
                "answering from this data, call show_answer with your answer so the user sees the real values."
            )
            msg["result"]["instructions"] = ((msg["result"].get("instructions") or "") + "\n\n" + note).strip()
        elif isinstance(msg, dict) and msg.get("id") in lists and isinstance(msg.get("result"), dict):
            lists.discard(msg["id"])
            tools = msg["result"].get("tools")
            if isinstance(tools, list) and not any(t.get("name") == TOOL["name"] for t in tools):
                msg["result"]["tools"] = [*tools, TOOL]
        elif isinstance(msg, dict) and msg.get("id") in calls and isinstance(msg.get("result"), dict):
            tool = calls.pop(msg["id"])
            msg["result"] = scr.result(msg["result"], f"{name}/{tool}")
        elif isinstance(msg, dict) and msg.get("id") in calls and "error" in msg:
            calls.pop(msg["id"], None)
            err = msg["error"]
            if isinstance(err, dict) and isinstance(err.get("message"), str):
                err["message"] = scr.text(err["message"])
        emit(msg)
    engine.activity.flush()
    return child.wait()
