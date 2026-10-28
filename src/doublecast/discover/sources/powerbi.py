"""Power BI semantic models (datasets), read with DAX through the REST API.

Requirements (set by a Power BI admin): the tenant setting "Dataset Execute
Queries REST API" (admin portal, Integration settings) must be on, and you
need Read + Build on the dataset. Limits: 100,000 rows or 1,000,000 values
per query, 120 queries per minute per user.

Finding the tables, tested on a real tenant (October 2026):
1. INFO.VIEW.COLUMNS() — cheap, works through Execute Queries (the older
   INFO.* functions and DMVs are refused).
2. COLUMNSTATISTICS() — works too, but computes statistics for every column
   and can exceed the per-query memory limit on large models.
3. Otherwise list the tables in the config (`tables: [Customers, Products]`).
"""

from __future__ import annotations

from collections.abc import Iterator

from ..microsoft import Api
from .base import Source, SourceError, Table

PBI = "https://api.powerbi.com/v1.0/myorg"


def _q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _col(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


class PowerBISource(Source):
    kind = "powerbi"

    def __init__(
        self,
        name: str,
        api: Api,
        workspaces: list[str] | None = None,
        datasets: list[str] | None = None,
        tables: list[str] | None = None,
        include_my_workspace: bool = True,
    ):
        super().__init__(name)
        self.api = api
        self.workspaces = [w.lower() for w in workspaces or []]
        self.dataset_filter = [d.lower() for d in datasets or []]
        self.fixed_tables = tables or []
        self.include_my_workspace = include_my_workspace
        self.skipped: list[str] = []
        self._where: dict[str, tuple[str, str]] = {}  # table key -> (query url, table name)

    def _datasets(self) -> Iterator[tuple[str, dict]]:
        if self.include_my_workspace and not self.workspaces:
            for d in self.api.get(f"{PBI}/datasets").get("value", []):
                yield f"{PBI}/datasets/{d['id']}", d
        for g in self.api.get(f"{PBI}/groups").get("value", []):
            if self.workspaces and g.get("name", "").lower() not in self.workspaces:
                continue
            for d in self.api.get(f"{PBI}/groups/{g['id']}/datasets").get("value", []):
                yield f"{PBI}/groups/{g['id']}/datasets/{d['id']}", {**d, "workspace": g.get("name")}

    def _query(self, base: str, dax: str) -> list[dict]:
        data = self.api.post(
            f"{base}/executeQueries", {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}
        )
        result = (data.get("results") or [{}])[0]
        if result.get("error"):
            raise SourceError(str(result["error"]))
        tables = result.get("tables") or [{}]
        if tables[0].get("error"):
            raise SourceError(str(tables[0]["error"]))
        return tables[0].get("rows") or []

    @staticmethod
    def _strip(row: dict) -> dict:
        # "Customers[Name]" -> "Name"
        out = {}
        for k, v in row.items():
            key = k.split("[", 1)[1].rstrip("]") if "[" in k else k
            out[key] = v
        return out

    def tables(self) -> Iterator[Table]:
        for base, ds in self._datasets():
            label = ds.get("name") or str(base).rsplit("/", 1)[-1]
            if self.dataset_filter and label.lower() not in self.dataset_filter:
                continue
            prefix = f"{ds.get('workspace') or 'My workspace'} / {label}"
            names: dict[str, list[str]] = {}
            if self.fixed_tables:
                names = {t: [] for t in self.fixed_tables}
            else:
                try:
                    names = self._list_columns(base)
                except SourceError as exc:
                    self.skipped.append(f"{prefix}: could not list tables ({exc}); add `tables:` to the config")
                    continue
            for t, cols in names.items():
                if t.startswith(("DateTableTemplate_", "LocalDateTable_")):
                    continue
                key = f"{prefix} / {t}"
                self._where[key] = (base, t)
                if not cols:
                    try:
                        first = self.sample(Table(key), 1)
                        cols = list(first[0].keys()) if first else []
                    except SourceError as exc:
                        self.skipped.append(f"{key}: {exc}")
                        continue
                yield Table(key, cols)

    _LISTERS = (
        # cheap model metadata; works through Execute Queries on current Power BI
        'EVALUATE SELECTCOLUMNS(FILTER(INFO.VIEW.COLUMNS(), [Type] <> "RowNumber"), "t", [Table], "c", [Name])',
        # older fallback: correct but heavy on big models (per-query memory limit)
        'EVALUATE SELECTCOLUMNS(COLUMNSTATISTICS(), "t", [Table Name], "c", [Column Name])',
    )

    def _list_columns(self, base: str) -> dict[str, list[str]]:
        errors = []
        for dax in self._LISTERS:
            try:
                rows = self._query(base, dax)
            except SourceError as exc:
                errors.append(str(exc)[:200])
                continue
            names: dict[str, list[str]] = {}
            for row in rows:
                r = {k.split("[")[-1].rstrip("]"): v for k, v in row.items()}
                t, c = r.get("t"), r.get("c")
                if t and c and not str(c).startswith("RowNumber-"):
                    names.setdefault(t, []).append(c)
            return names
        raise SourceError("; ".join(errors))

    def sample(self, table: Table, n: int) -> list[dict]:
        base, t = self._where[table.name]
        return [self._strip(r) for r in self._query(base, f"EVALUATE TOPN({int(n)}, {_q(t)})")]

    def values(self, table: Table, column: str, limit: int):
        base, t = self._where[table.name]
        dax = f'EVALUATE TOPN({int(limit)}, DISTINCT(SELECTCOLUMNS({_q(t)}, "v", {_q(t)}{_col(column)})))'
        for row in self._query(base, dax):
            yield next(iter(row.values()), None)

    def close(self) -> None:
        self.api.close()


class McpPowerBISource(PowerBISource):
    """Power BI through the local Power BI connector the Claude app already uses.

    No separate sign-in: the connector's own (see `doublecast connect powerbi`). Datasets are the
    ones the connector knows (`powerbi_known_datasets`); queries go through `powerbi_run_dax`.
    """

    def __init__(self, name: str, client, datasets: list[str] | None = None, tables: list[str] | None = None):
        Source.__init__(self, name)
        self.client = client
        self.workspaces: list[str] = []
        self.dataset_filter = [d.lower() for d in datasets or []]
        self.fixed_tables = tables or []
        self.include_my_workspace = False
        self.skipped: list[str] = []
        self._where: dict[str, tuple] = {}

    def _datasets(self):
        import json

        try:
            known = json.loads(self.client.call("powerbi_known_datasets", {}))
        except (ValueError, RuntimeError) as exc:
            raise SourceError(f"The Power BI connector did not list its datasets: {exc}") from exc
        for alias, d in (known.get("datasets") or {}).items():
            yield (d.get("workspace"), alias), {"name": alias, "workspace": d.get("workspace")}

    def _query(self, base, dax: str) -> list[dict]:
        import json

        workspace, dataset = base
        try:
            text = self.client.call(
                "powerbi_run_dax", {"params": {"workspace": workspace, "dataset": dataset, "dax_query": dax}}
            )
            data = json.loads(text)
        except (ValueError, RuntimeError, TimeoutError) as exc:
            raise SourceError(str(exc)[:300]) from exc
        if isinstance(data, dict) and data.get("error"):
            raise SourceError(str(data["error"])[:300])
        return (data.get("rows") if isinstance(data, dict) else data) or []

    def close(self) -> None:
        self.client.close()
