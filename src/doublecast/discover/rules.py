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
        self._stamp: tuple = ()
        # what this process changed since it last read the file; on save these are replayed
        # onto the newest copy on disk, so another process's "forget" is not undone
        self._learned_delta: list[tuple[str, str]] = []
        self._ignored_delta: list[str] = []
        self._sources_set: dict = {}
        self._sources_removed: set[str] = set()
        self._learned_cleared = False
        if self.path.exists():
            self.data = self._read()
        self.version = 0

    def _file_stamp(self) -> tuple:
        st = self.path.stat()
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def _read(self) -> dict:
        self._stamp = self._file_stamp()
        data = json.loads(self.vault.decrypt(self.path.read_bytes()).decode("utf-8"))
        data.setdefault("sources", {})
        data.setdefault("learned", {})
        data.setdefault("ignored", [])
        return data

    def changed_on_disk(self) -> bool:
        """True when another process (a scheduled discover, the CLI) saved newer rules."""
        try:
            return self._file_stamp() != self._stamp
        except FileNotFoundError:
            return False

    def reload(self) -> None:
        """Take the newest copy on disk, keeping this process's unsaved changes."""
        if not self.path.exists():
            return
        if self._learned_delta or self._ignored_delta or self._sources_set or self._sources_removed:
            self.save()  # replays the changes onto the disk copy
        else:
            self.data = self._read()

    # ------------------------------------------------------------ persistence
    def save(self, replace_sources: bool = False) -> None:
        """Write the rules. Changes other processes saved meanwhile are kept: this process's own
        changes are replayed onto the newest copy on disk (a "forget" elsewhere stays forgotten)."""
        if self.changed_on_disk():
            disk = self._read()
            if self._learned_cleared:
                disk["learned"] = {}
            for cat, v in self._learned_delta:
                bucket = disk["learned"].setdefault(cat, [])
                if v not in bucket:
                    bucket.append(v)
            for v in self._ignored_delta:
                if v not in disk["ignored"]:
                    disk["ignored"].append(v)
            if replace_sources:
                disk["sources"] = dict(self.data["sources"])
            else:
                for name in self._sources_removed:
                    disk["sources"].pop(name, None)
                disk["sources"].update(self._sources_set)
            self.data = disk
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = self.vault.encrypt(json.dumps(self.data, ensure_ascii=False).encode("utf-8"))
        tmp = self.path.with_suffix(f".tmp{os.getpid()}")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, self.path)
        self._stamp = self._file_stamp()
        self._learned_delta, self._ignored_delta = [], []
        self._sources_set, self._sources_removed, self._learned_cleared = {}, set(), False
        self.version += 1

    # ------------------------------------------------------------ sources
    def set_source(self, name: str, columns: list[dict], terms: dict[str, list[str]]) -> None:
        self.data["sources"][name] = self._sources_set[name] = {
            "refreshed": dt.datetime.now().replace(microsecond=0).isoformat(),
            "columns": columns,
            "terms": {cat: sorted(set(vals)) for cat, vals in terms.items() if vals},
        }

    def remove_source(self, name: str) -> bool:
        self._sources_removed.add(name)
        self._sources_set.pop(name, None)
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
        self._learned_delta.append((category, value))
        return True

    def clear_learned(self) -> None:
        self.data["learned"] = {}
        self._learned_delta = []
        self._learned_cleared = True

    def ignore(self, value: str) -> None:
        if fold(value) not in self._ignored():
            self.data["ignored"].append(value)
            self._ignored_delta.append(value)

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
