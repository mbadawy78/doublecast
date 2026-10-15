"""Encrypted store for discovered and learned protection rules.

One file per workspace: ``~/.doublecast/<workspace>.rules``, encrypted with
the vault key (the lists themselves are sensitive: they are your customer
and staff master data).

Layout (before encryption):

    {
      "sources": {
        "powerbi:Sales": {
          "refreshed": "2026-10-15T20:41:00",
          "columns": [{"table": "...", "column": "...", "category": "ORG",
                        "confidence": 0.9, "reason": "...", "values": 1234}],
          "terms": {"ORG": ["...", ...], "PERSON": [...]}
        }
      },
      "learned": {"ORG": [...], "PERSON": [...]},
      "ignored": ["value never to protect", ...]
    }
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from ..config import Term
from ..textnorm import fold


class RulesStore:
    def __init__(self, path: Path, vault):
        self.path = Path(path)
        self.vault = vault
        self.data: dict = {"sources": {}, "learned": {}, "ignored": []}
        self._mtime = 0.0
        if self.path.exists():
            self.data = self._read()
        self.version = 0

    def _read(self) -> dict:
        self._mtime = self.path.stat().st_mtime
        data = json.loads(self.vault.decrypt(self.path.read_bytes()).decode("utf-8"))
        data.setdefault("sources", {})
        data.setdefault("learned", {})
        data.setdefault("ignored", [])
        return data

    def changed_on_disk(self) -> bool:
        """True when another process (a scheduled discover, the CLI) saved newer rules."""
        try:
            return self.path.stat().st_mtime != self._mtime
        except FileNotFoundError:
            return False

    def reload(self) -> None:
        if self.path.exists():
            self.data = self._read()

    # ------------------------------------------------------------ persistence
    def save(self, replace_sources: bool = False) -> None:
        """Write the rules. Names learned by other processes meanwhile are kept (merged)."""
        if self.changed_on_disk():
            disk = self._read()
            for cat, values in disk.get("learned", {}).items():
                mine = self.data["learned"].setdefault(cat, [])
                mine.extend(v for v in values if v not in mine)
            for v in disk.get("ignored", []):
                if v not in self.data["ignored"]:
                    self.data["ignored"].append(v)
            if not replace_sources:
                for name, info in disk.get("sources", {}).items():
                    self.data["sources"].setdefault(name, info)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = self.vault.encrypt(json.dumps(self.data, ensure_ascii=False).encode("utf-8"))
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime
        self.version += 1

    # ------------------------------------------------------------ sources
    def set_source(self, name: str, columns: list[dict], terms: dict[str, list[str]]) -> None:
        self.data["sources"][name] = {
            "refreshed": dt.datetime.now().replace(microsecond=0).isoformat(),
            "columns": columns,
            "terms": {cat: sorted(set(vals)) for cat, vals in terms.items() if vals},
        }

    def remove_source(self, name: str) -> bool:
        return self.data["sources"].pop(name, None) is not None

    def sources(self) -> dict:
        return self.data["sources"]

    # ------------------------------------------------------------ learned on the fly
    def learn(self, category: str, value: str) -> bool:
        value = value.strip()
        if not value or fold(value) in self._ignored():
            return False
        bucket = self.data["learned"].setdefault(category, [])
        if value in bucket:
            return False
        bucket.append(value)
        return True

    def ignore(self, value: str) -> None:
        if fold(value) not in self._ignored():
            self.data["ignored"].append(value)

    def _ignored(self) -> set[str]:
        return {fold(v) for v in self.data.get("ignored", [])}

    # ------------------------------------------------------------ output
    def terms(self) -> list[Term]:
        ignored = self._ignored()
        out: list[Term] = []
        seen: set[str] = set()
        groups = [s.get("terms", {}) for s in self.data["sources"].values()] + [self.data["learned"]]
        for group in groups:
            for category, values in group.items():
                for v in values:
                    key = fold(v)
                    if key in seen or key in ignored:
                        continue
                    seen.add(key)
                    out.append(Term(category, v))
        return out

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.terms():
            counts[t.category] = counts.get(t.category, 0) + 1
        return counts
