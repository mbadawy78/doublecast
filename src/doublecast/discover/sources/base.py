"""What every discovery source provides.

A source is anything with tables of rows: a folder of spreadsheets, a SQL
database, a Power BI dataset, Dynamics 365 entities, SharePoint lists,
Outlook contacts. Each source answers three questions:

* which tables do you have?            tables()
* show me a sample of a table          sample(table, n)
* give me every value of one column    values(table, column, limit)

Everything stays on this machine: sources are read, never written to.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class Table:
    name: str
    columns: list[str] = field(default_factory=list)
    note: str = ""


class SourceError(RuntimeError):
    """A source could not be read (missing permission, wrong URL...)."""


class Source:
    kind = "base"

    def __init__(self, name: str):
        self.name = name

    def tables(self) -> Iterator[Table]:
        raise NotImplementedError

    def sample(self, table: Table, n: int) -> list[dict]:
        raise NotImplementedError

    def values(self, table: Table, column: str, limit: int) -> Iterator[object]:
        """Default: read rows and pick the column. Sources override with something cheaper."""
        for row in self.sample(table, limit):
            yield row.get(column)

    def close(self) -> None:  # pragma: no cover - optional
        pass
