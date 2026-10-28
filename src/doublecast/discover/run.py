"""Run discovery: connect, read structure, classify columns, collect terms."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import Config
from .microsoft import GRAPH_SCOPES, POWERBI_SCOPES, Api, MicrosoftAuth
from .profiler import TERM_CATEGORIES, classify_column, extract_terms
from .sources.base import Source, SourceError

log = logging.getLogger("doublecast.discover")


@dataclass
class ColumnResult:
    table: str
    column: str
    category: str | None
    confidence: float
    reason: str
    values: int = 0
    skipped: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class SourceResult:
    name: str
    kind: str
    columns: list[ColumnResult] = field(default_factory=list)
    terms: dict[str, list[str]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    error: str | None = None

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.terms.items() if v}


def build_sources(cfg: Config, vault, prompt: Callable[[str], None] | None = None, client=None) -> list[Source]:
    """Turn `discover.sources` from the config into source objects."""
    from .sources.files import FolderSource

    sources: list[Source] = []
    auth: MicrosoftAuth | None = None

    def ms() -> MicrosoftAuth:
        nonlocal auth
        if auth is None:
            auth = MicrosoftAuth(
                cfg.microsoft_tenant, cfg.microsoft_client_id, vault, cfg.home / "microsoft.tokens", prompt
            )
        return auth

    def api(scopes: list[str], headers: dict | None = None) -> Api:
        cache: dict[str, tuple[str, float]] = {}

        def token(fresh: bool = False) -> str:
            # MSAL refreshes silently; ask it again every 20 minutes so long scans never use an expired token
            hit = cache.get("t")
            if fresh or hit is None or time.monotonic() - hit[1] > 1200:
                cache["t"] = (ms().token(scopes), time.monotonic())
            return cache["t"][0]

        return Api(token, client=client, headers=headers)

    for i, spec in enumerate(cfg.discover_sources):
        kind = str(spec.get("type", "")).lower()
        name = str(spec.get("name") or f"{kind}-{i + 1}")
        if kind == "folder":
            sources.append(FolderSource(name, spec["path"], recursive=bool(spec.get("recursive", True))))
        elif kind == "sql":
            from .sources.sql import SQLSource

            sources.append(SQLSource(name, spec["url"], spec.get("schema"), spec.get("tables")))
        elif kind in ("m365", "graph", "outlook", "sharepoint"):
            from .sources.graph import GraphSource

            sources.append(
                GraphSource(
                    name,
                    api(GRAPH_SCOPES),
                    contacts=bool(spec.get("contacts", True)),
                    mail_messages=int(spec.get("mail_messages", 500)),
                    sharepoint_sites=list(spec.get("sharepoint_sites", []) or []),
                    sharepoint_files=int(spec.get("sharepoint_files", 50)),
                )
            )
        elif kind == "powerbi":
            from .sources.powerbi import PowerBISource

            sources.append(
                PowerBISource(
                    name, api(POWERBI_SCOPES), spec.get("workspaces"), spec.get("datasets"), spec.get("tables")
                )
            )
        elif kind in ("d365fo", "dataverse", "businesscentral"):
            from .sources.odata import ODataSource

            url = str(spec.get("url", "")).strip().rstrip("/").lower()  # token audience must match exactly
            if kind in ("d365fo", "dataverse") and not url:
                raise ValueError(f"Source '{name}' ({kind}) needs a url")
            if kind == "d365fo":
                base, scopes, headers = f"{url}/data", [f"{url}/.default"], None
            elif kind == "dataverse":
                base, scopes = f"{url}/api/data/v9.2", [f"{url}/user_impersonation"]
                headers = {"OData-MaxVersion": "4.0", "OData-Version": "4.0"}
            else:
                env = spec.get("environment", "production")
                tenant = spec.get("tenant_id", cfg.microsoft_tenant)
                base = f"https://api.businesscentral.dynamics.com/v2.0/{tenant}/{env}/api/v2.0"
                scopes, headers = ["https://api.businesscentral.dynamics.com/.default"], None
            sources.append(ODataSource(name, api(scopes, headers), base, kind, spec.get("entities")))
        elif kind in ("connector", "powerbi-connector"):
            from ..connectors import StdioClient
            from .sources.powerbi import McpPowerBISource

            sources.append(
                McpPowerBISource(
                    name,
                    StdioClient.for_connector(cfg.home, spec.get("connector", "powerbi")),
                    spec.get("datasets"),
                    spec.get("tables"),
                )
            )
        else:
            raise ValueError(
                f"Unknown discovery source type '{kind}'. Use folder, sql, m365, powerbi, powerbi-connector, d365fo, "
                "dataverse or businesscentral."
            )
    # a Power BI connector put behind Doublecast (`doublecast connect powerbi`) is read too, with no setup
    from ..connectors import registered

    named = {s.name for s in sources}
    if (
        "powerbi" in registered(cfg.home)
        and "powerbi-connector" not in named
        and not any(
            str(spec.get("type", "")).lower() in ("connector", "powerbi-connector") for spec in cfg.discover_sources
        )
    ):
        from ..connectors import StdioClient
        from .sources.powerbi import McpPowerBISource

        sources.append(McpPowerBISource("powerbi-connector", StdioClient.for_connector(cfg.home, "powerbi")))
    return sources


def scan(
    source: Source, sample_rows: int = 200, max_values: int = 50000, progress: Callable[[str], None] | None = None
) -> SourceResult:
    result = SourceResult(source.name, source.kind)
    say = progress or (lambda _m: None)
    try:
        for table in source.tables():
            say(f"  {table.name}")
            try:
                rows = source.sample(table, sample_rows)
            except SourceError as exc:
                result.skipped.append(f"{table.name}: {exc}")
                continue
            columns = table.columns or sorted({k for r in rows for k in r})
            for col in columns:
                verdict = classify_column(col, (r.get(col) for r in rows), table.name)
                cr = ColumnResult(table.name, col, verdict.category, verdict.confidence, verdict.reason)
                result.columns.append(cr)
                if verdict.category not in TERM_CATEGORIES:
                    continue
                try:
                    terms, skipped = extract_terms(verdict.category, source.values(table, col, max_values), max_values)
                except SourceError as exc:
                    result.skipped.append(f"{table.name}.{col}: {exc}")
                    continue
                cr.values, cr.skipped, cr.examples = len(terms), skipped, terms[:3]
                result.terms.setdefault(verdict.category, []).extend(terms)
    except SourceError as exc:
        result.error = str(exc)
    finally:
        result.skipped.extend(getattr(source, "skipped", []))
        source.close()
    for cat in list(result.terms):
        result.terms[cat] = sorted(set(result.terms[cat]))
    return result


def apply(results: list[SourceResult], rules) -> None:
    for r in results:
        if r.error and not r.terms:
            continue
        columns = [
            {
                "table": c.table,
                "column": c.column,
                "category": c.category,
                "confidence": c.confidence,
                "reason": c.reason,
                "values": c.values,
            }
            for c in r.columns
            if c.category
        ]
        rules.set_source(f"{r.kind}:{r.name}", columns, r.terms)
    rules.save()
