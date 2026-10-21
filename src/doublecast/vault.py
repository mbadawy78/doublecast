"""The vault: the only place where real values and their stand-ins meet.

* SQLite file per workspace (``~/.doublecast/<workspace>.vault``).
* Real values are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
* Lookups use a keyed hash, so the database never holds a plain real value.
* Stand-ins are stored in clear: they are fake by construction.
* The key lives in ``~/.doublecast/key`` (permissions 600). Lose it and the
  vault can no longer restore anything; that is the point.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from .textnorm import fold


@dataclass(frozen=True)
class Mapping:
    category: str
    original: str
    surrogate: str


def _marks(text: str) -> int:
    """How much spelling information a form carries: accents and capitals."""
    import unicodedata

    return sum(1 for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) == "Mn") + sum(
        1 for c in text if c.isupper()
    )


def _load_or_create_key(key_path: Path) -> bytes:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(key_path.parent, 0o700)
    except OSError:
        pass
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class Vault:
    def __init__(self, path: Path, key_path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key = _load_or_create_key(Path(key_path))
        self._fernet = Fernet(key)
        self._hkey = hashlib.sha256(key + b"doublecast-lookup").digest()
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mappings (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                lookup TEXT NOT NULL UNIQUE,
                original BLOB NOT NULL,
                surrogate TEXT NOT NULL,
                surrogate_folded TEXT NOT NULL UNIQUE,
                created TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v BLOB NOT NULL);
            """
        )
        self._db.commit()
        self._cache: list[Mapping] | None = None
        self._keys: set[str] | None = None
        self.version = 0
        self.rewrites = 0  # originals refined in place: restore indexes must be rebuilt

    # ---------------------------------------------------------------- lookups
    def _lookup_key(self, folded_original: str) -> str:
        return hmac.new(self._hkey, folded_original.encode("utf-8"), hashlib.sha256).hexdigest()

    def get(self, original: str) -> str | None:
        key = self._lookup_key(fold(original))
        with self._lock:
            row = self._db.execute("SELECT surrogate FROM mappings WHERE lookup=?", (key,)).fetchone()
        return row[0] if row else None

    def refine_original(self, original: str) -> None:
        """Keep the most complete spelling of a value as its original: seen first as "παντελης" in a
        chat and later as "Παντελής", the accented form is what comes back (stripped again where the
        text has no accents)."""
        key = self._lookup_key(fold(original))
        with self._lock:
            row = self._db.execute("SELECT id, original FROM mappings WHERE lookup=?", (key,)).fetchone()
            if not row:
                return
            current = self._fernet.decrypt(row[1]).decode("utf-8")
            if current == original or _marks(original) <= _marks(current):
                return
            self._db.execute(
                "UPDATE mappings SET original=? WHERE id=?", (self._fernet.encrypt(original.encode("utf-8")), row[0])
            )
            self._db.commit()
            self._cache = None
            self.version += 1
            self.rewrites += 1

    def surrogate_taken(self, surrogate: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM mappings WHERE surrogate_folded=?", (fold(surrogate),)).fetchone()
        return row is not None

    def is_surrogate(self, text: str) -> bool:
        return self.surrogate_taken(text)

    def put(self, category: str, original: str, surrogate: str) -> str:
        """Store a mapping; returns the surrogate actually stored (first writer wins)."""
        key = self._lookup_key(fold(original))
        with self._lock:
            existing = self._db.execute("SELECT surrogate FROM mappings WHERE lookup=?", (key,)).fetchone()
            if existing:
                return existing[0]
            self._db.execute(
                "INSERT INTO mappings(category, lookup, original, surrogate, surrogate_folded) VALUES (?,?,?,?,?)",
                (category, key, self._fernet.encrypt(original.encode("utf-8")), surrogate, fold(surrogate)),
            )
            self._db.commit()
            if self._cache is not None:
                self._cache.append(Mapping(category, original, surrogate))
            if self._keys is not None:
                self._keys.add(fold(surrogate))
            self.version += 1
        return surrogate

    def try_put(self, category: str, original: str, surrogate: str) -> bool:
        """Store a mapping only if neither side is already used. Returns True if stored."""
        with self._lock:
            if self.get(original) is not None or self.surrogate_taken(surrogate):
                return False
            self.put(category, original, surrogate)
            return True

    def surrogate_keys(self) -> set[str]:
        """Folded stand-ins, without decrypting anything (fast membership checks)."""
        with self._lock:
            if self._keys is None:
                rows = self._db.execute("SELECT surrogate_folded FROM mappings").fetchall()
                self._keys = {r[0] for r in rows}
            return self._keys

    def mappings(self) -> list[Mapping]:
        with self._lock:
            if self._cache is None:
                rows = self._db.execute("SELECT category, original, surrogate FROM mappings ORDER BY id").fetchall()
                self._cache = [Mapping(cat, self._fernet.decrypt(orig).decode("utf-8"), sur) for cat, orig, sur in rows]
            return list(self._cache)

    def forget(self, original: str) -> bool:
        key = self._lookup_key(fold(original))
        with self._lock:
            cur = self._db.execute("DELETE FROM mappings WHERE lookup=?", (key,))
            self._db.commit()
            self._cache = None
            self._keys = None
            self.version += 1
            return cur.rowcount > 0

    def wipe(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM mappings")
            self._db.execute("DELETE FROM meta")
            self._db.commit()
            self._cache = None
            self._keys = None
            self.version += 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT category, COUNT(*) FROM mappings GROUP BY category").fetchall()
        return {cat: n for cat, n in rows}

    # ---------------------------------------------------------------- encryption for other local files
    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        return self._fernet.decrypt(token)

    # ---------------------------------------------------------------- secrets
    def _meta(self, name: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT v FROM meta WHERE k=?", (name,)).fetchone()
        return self._fernet.decrypt(row[0]).decode("utf-8") if row else None

    def _set_meta(self, name: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)",
                (name, self._fernet.encrypt(value.encode("utf-8"))),
            )
            self._db.commit()

    def factor(self, name: str) -> float:
        """A secret multiplier > 1.15.

        It must be above 1: rounding a scaled amount then dividing it back
        is only guaranteed to return the original when the factor is > 1.
        """
        value = self._meta(f"factor:{name}")
        if value is None:
            rng = random.SystemRandom()
            f = round(rng.uniform(1.17, 3.4), 6)
            self._set_meta(f"factor:{name}", repr(f))
            return f
        return float(value)

    def date_offset_days(self) -> int:
        value = self._meta("date_offset")
        if value is None:
            rng = random.SystemRandom()
            weeks = rng.choice([w for w in range(-60, 61) if abs(w) >= 6])
            self._set_meta("date_offset", str(weeks * 7))
            return weeks * 7
        return int(value)

    def seed(self) -> bytes:
        value = self._meta("seed")
        if value is None:
            value = os.urandom(16).hex()
            self._set_meta("seed", value)
        return bytes.fromhex(value)

    def close(self) -> None:
        with self._lock:
            self._db.close()
