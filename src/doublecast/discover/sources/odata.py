"""OData sources: Dynamics 365 Finance & Operations, Dataverse (Dynamics 365
Sales/Customer Service, Power Apps), and Business Central.

Each flavour has a preset list of the entities that hold master data. Names
that do not exist in a given environment are skipped and reported, so the
same preset works across versions. Add your own with `entities: [...]`.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..microsoft import Api
from .base import Source, SourceError, Table

PRESETS = {
    # D365 F&O public entity sets. CustomersV3 and ReleasedProductsV2 are documented; the others are
    # common names that vary by version and are checked at run time.
    "d365fo": [
        "CustomersV3",
        "VendorsV2",
        "ReleasedProductsV2",
        "ContactPersons",
        "Workers",
        "Warehouses",
        "OperationalSites",
        "PartyContactsV3",
    ],
    "dataverse": ["accounts", "contacts", "systemusers", "products", "leads", "competitors"],
    "businesscentral": ["customers", "vendors", "items", "employees", "contacts"],
}


class ODataSource(Source):
    def __init__(
        self,
        name: str,
        api: Api,
        base_url: str,
        flavour: str,
        entities: list[str] | None = None,
        cross_company: bool = True,
    ):
        super().__init__(name)
        self.kind = flavour
        self.api = api
        self.base = base_url.rstrip("/")
        self.flavour = flavour
        self.entities = entities or PRESETS[flavour]
        self.cross_company = cross_company and flavour == "d365fo"
        self.skipped: list[str] = []
        self._companies: list[str] | None = None

    def _extra(self) -> dict:
        return {"cross-company": "true"} if self.cross_company else {}

    def _collections(self) -> list[tuple[str, str]]:
        """(display name, url) for every entity collection to scan."""
        if self.flavour != "businesscentral":
            return [(e, f"{self.base}/{e}") for e in self.entities]
        if self._companies is None:
            self._companies = [c["id"] for c in self.api.pages(f"{self.base}/companies", limit=100)]
        return [
            (f"{e}@{cid[:8]}", f"{self.base}/companies({cid})/{e}") for cid in self._companies for e in self.entities
        ]

    def tables(self) -> Iterator[Table]:
        self._urls: dict[str, str] = {}
        self._rows: dict[str, list[dict]] = {}
        for display, url in self._collections():
            try:
                rows = list(self.api.pages(url, {"$top": "200", **self._extra()}, limit=200))
            except SourceError as exc:
                self.skipped.append(f"{display}: {exc}")
                continue
            cols = sorted({k for r in rows for k in r if not k.startswith("@") and not isinstance(r[k], (dict, list))})
            self._urls[display] = url
            self._rows[display] = rows
            yield Table(display, cols)

    def sample(self, table: Table, n: int) -> list[dict]:
        return self._rows.get(table.name, [])[:n]

    def values(self, table: Table, column: str, limit: int):
        url = self._urls[table.name]
        params = {"$select": column, **self._extra()}
        if self.flavour == "d365fo":
            params["$top"] = "10000"
        for row in self.api.pages(url, params, limit=limit):
            yield row.get(column)
