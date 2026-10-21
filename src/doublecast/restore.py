"""Putting the real values back.

Restoring is tolerant on purpose. Models rewrite things: they change case
("NORDMART"), drop accents, add possessives ("Nordmart's") and, in Greek,
inflect names ("της Νορμάρκετ"). Matching runs on folded text and accepts
Greek endings; when a single Greek word comes back inflected, the same
ending is put on the real value so the sentence stays grammatical.

The streaming restorer holds back the tail of the text it has seen, so a
stand-in split across two network chunks ("Nord" | "mart") is still caught.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from .detectors.dictionary import trie_regex
from .surrogates import match_case
from .textnorm import fold, fold_with_map, has_stem, inflect_words, span_to_original, stem_key, word_endings
from .vault import Mapping

Replacement = tuple[int, int, str]
_WS = re.compile(r"\s+")


class _Index:
    """One compiled regex over a batch of stand-ins."""

    def __init__(self, mappings: list[Mapping]):
        self.exact: dict[str, str] = {}
        self.stems: dict[str, str] = {}
        self.parts: set[str] = set()  # surname-only stand-ins: need a capital letter
        ambiguous: set[str] = set()
        for mp in mappings:
            key = _WS.sub(" ", fold(mp.surrogate).strip())
            if not key:
                continue
            if mp.category == "PERSON_PART":
                self.parts.add(key)
            if key in self.exact and self.exact[key] != mp.original:
                ambiguous.add(key)
            self.exact[key] = mp.original
            if has_stem(key):
                self.stems.setdefault(stem_key(key), mp.original)
        for key in ambiguous:
            self.exact.pop(key, None)
        keys = sorted(set(self.exact) | set(self.stems))
        self.regex = re.compile(r"(?<![^\W_])(?:" + trie_regex(keys) + r")(?![^\W_])") if keys else None
        self.max_len = max((len(k) for k in self.exact), default=0)

    def lookup(self, matched: str) -> tuple[str, str] | None:
        """Return (original, folded ending or '') for a matched folded stand-in."""
        key = _WS.sub(" ", matched)
        if key in self.exact:
            return self.exact[key], []
        original = self.stems.get(stem_key(key))
        if original is None:
            return None
        return original, word_endings(key)


def _is_vocabulary(folded: str) -> bool:
    """Doubles that are also ordinary words (from vaults made before such words left the name
    lists) are restored only when written like a name: "the orchard" stays a fruit garden."""
    from .data.realnames import WORDLIKE_FOLDED

    return folded in WORDLIKE_FOLDED


class Restorer:
    def __init__(
        self,
        mappings: list[Mapping],
        number_matches: Callable[[str], list[Replacement]] | None = None,
    ):
        self.number_matches = number_matches
        self.size = len(mappings)
        self._indexes: list[_Index] = [_Index(mappings)] if mappings else []

    # ------------------------------------------------------------ growth
    def can_extend(self, new_total: int) -> bool:
        return new_total >= self.size and len(self._indexes) < 12

    def extend(self, new_mappings: list[Mapping]) -> None:
        if new_mappings:
            self._indexes.append(_Index(new_mappings))
            self.size += len(new_mappings)

    @property
    def max_len(self) -> int:
        return max((ix.max_len for ix in self._indexes), default=0)

    @property
    def by_key(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for ix in self._indexes:
            merged.update(ix.exact)
        return merged

    # ------------------------------------------------------------ matching
    def _surrogate_matches(self, text: str) -> list[Replacement]:
        if not self._indexes:
            return []
        folded, index = fold_with_map(text)
        folded = folded.replace("_", " ")
        candidates: list[tuple[int, int, str, bool]] = []
        for ix in self._indexes:
            if ix.regex is None:
                continue
            for m in ix.regex.finditer(folded):
                if m.end() == m.start():
                    continue
                hit = ix.lookup(m.group(0))
                if hit is None:
                    continue
                original, endings = hit
                if endings and any(endings):
                    original = inflect_words(original, endings)
                s, e = span_to_original(index, m.start(), m.end(), len(text))
                original = match_case(text[s:e], original)
                word = text[s:e]
                if "_" in word and not any(c.isspace() for c in word):
                    original = re.sub(r"\s+", "_", original)
                if word.islower() and _is_vocabulary(_WS.sub(" ", m.group(0))):
                    continue  # "the orchard" is a fruit garden, not the double "Orchard"
                # (a surname alone is restored in any case: doubles never are ordinary words, and a chat
                # writes "διαμαντης", a heading "ΔΙΑΜΑΝΤΗΣ")
                exact = _WS.sub(" ", m.group(0)) in ix.exact
                candidates.append((s, e, original, exact))
        # longest match wins where batches overlap; an exact match beats an inflected one
        candidates.sort(key=lambda r: (r[0], -(r[1] - r[0]), not r[3]))
        out: list[Replacement] = []
        last_end = -1
        for s, e, r, _exact in candidates:
            if s >= last_end:
                out.append((s, e, r))
                last_end = e
        return out

    def surrogate_spans(self, text: str) -> list[tuple[int, int]]:
        return [(s, e) for s, e, _ in self._surrogate_matches(text)]

    def matches(self, text: str) -> list[Replacement]:
        found = self._surrogate_matches(text)
        if self.number_matches:
            taken = [(s, e) for s, e, _ in found]
            for s, e, r in self.number_matches(text):
                if not any(s < te and ts < e for ts, te in taken):
                    found.append((s, e, r))
        found.sort(key=lambda x: x[0])
        return found

    def restore(self, text: str) -> str:
        return apply(text, self.matches(text))


def apply(text: str, replacements: list[Replacement], escape_json: bool = False) -> str:
    if not replacements:
        return text
    out, pos = [], 0
    for s, e, r in sorted(replacements, key=lambda x: x[0]):
        if s < pos:
            continue
        out.append(text[pos:s])
        out.append(json.dumps(r, ensure_ascii=False)[1:-1] if escape_json else r)
        pos = e
    out.append(text[pos:])
    return "".join(out)


class StreamRestorer:
    """Restore text that arrives in pieces.

    Emits everything that can no longer be part of an unfinished stand-in or
    amount, and holds back the rest until more text (or the end) arrives.
    """

    def __init__(self, restorer: Restorer, escape_json: bool = False, holdback: int | None = None):
        self.restorer = restorer
        self.escape_json = escape_json
        self.holdback = holdback if holdback is not None else max(restorer.max_len + 8, 40)
        self.buffer = ""

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        if len(self.buffer) <= self.holdback:
            return ""
        cut = len(self.buffer) - self.holdback
        reps = self.restorer.matches(self.buffer)
        for s, e, _ in reps:
            if s < cut <= e:
                cut = s
        # never cut inside a word: a stand-in could continue into the held part
        while 0 < cut < len(self.buffer) and self.buffer[cut - 1].isalnum() and self.buffer[cut].isalnum():
            cut -= 1
        if cut <= 0:
            return ""
        emit_reps = [r for r in reps if r[1] <= cut]
        out = apply(self.buffer[:cut], emit_reps, self.escape_json)
        self.buffer = self.buffer[cut:]
        return out

    def flush(self) -> str:
        out = apply(self.buffer, self.restorer.matches(self.buffer), self.escape_json)
        self.buffer = ""
        return out
