"""Any SQL database SQLAlchemy can reach (SQL Server, PostgreSQL, MySQL, Oracle,
SQLite, Azure SQL, Synapse, D365 BYOD export databases...).

    pip install "doublecast[sql]"   # plus the database's own driver, e.g. pyodbc
"""

from __future__ import annotations

from collections.abc import Iterator

from .base import Source, SourceError, Table


class SQLSource(Source):
    kind = "sql"

    def __init__(self, name: str, url: str, schema: str | None = None, include: list[str] | None = None):
        super().__init__(name)
        try:
            import sqlalchemy as sa
        except ImportError as exc:  # pragma: no cover
            raise SourceError("SQL sources need SQLAlchemy: pip install 'doublecast[sql]'") from exc
        self.sa = sa
        self.engine = sa.create_engine(url)
        self.schema = schema
        self.include = [i.lower() for i in include or []]

    def tables(self) -> Iterator[Table]:
        insp = self.sa.inspect(self.engine)
        names = insp.get_table_names(schema=self.schema) + insp.get_view_names(schema=self.schema)
        for t in names:
            if self.include and t.lower() not in self.include:
                continue
            cols = [c["name"] for c in insp.get_columns(t, schema=self.schema)]
            yield Table(t, cols)

    def _table(self, table: Table):
        return self.sa.Table(table.name, self.sa.MetaData(), schema=self.schema, autoload_with=self.engine)

    def sample(self, table: Table, n: int) -> list[dict]:
        t = self._table(table)
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(self.sa.select(t).limit(n))]

    def values(self, table: Table, column: str, limit: int):
        t = self._table(table)
        with self.engine.connect() as conn:
            for (v,) in conn.execute(self.sa.select(t.c[column]).distinct().limit(limit)):
                yield v

    def close(self) -> None:
        self.engine.dispose()
