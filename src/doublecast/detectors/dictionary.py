"""Your own terms: customers, suppliers, people, sites, products, projects.

This is the most reliable layer: anything listed is always replaced, in
any capitalisation or accent form, and for Greek words also in their
inflected forms (Καλλέργης / Καλλέργη / Καλλέργες ...).
Large lists (thousands of customers) are compiled into a trie regex, so
matching stays fast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Term
from ..textnorm import (
    GREEK_ENDING_REGEX,
    STEM_MARK,
    fold,
    fold_with_map,
    has_stem,
    span_to_original,
    stem_key,
    word_endings,
)
from .base import Span

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", fold(s).strip())


def trie_regex(words: list[str]) -> str:
    """Compile a list of literal strings into one efficient regex.

    A space in a word matches any run of whitespace.
    """
    trie: dict = {}
    for w in words:
        node = trie
        for ch in w:
            node = node.setdefault(ch, {})
        node[""] = True

    def build(node: dict) -> str:
        end = "" in node
        branches = []
        for ch in sorted(k for k in node if k != ""):
            if ch == " ":
                piece = r"\s+"
            elif ch == STEM_MARK:
                piece = GREEK_ENDING_REGEX
            else:
                piece = re.escape(ch)
            branches.append(piece + build(node[ch]))
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        if end:
            return "(?:" + body + ")?"
        return body

    return build(trie)


@dataclass
class _Entry:
    category: str
    canonical: str  # the term as configured (what the vault maps)
    component: bool = False


class DictionaryDetector:
    def __init__(self, terms: list[Term], allow: list[str] | None = None):
        self.allow = {_norm(a) for a in (allow or [])}
        self.exact: dict[str, _Entry] = {}
        self.stems: dict[str, _Entry] = {}
        for term in terms:
            for variant in [term.value, *term.aliases]:
                self._add(variant, _Entry(term.category, term.value))
            if term.category == "PERSON":
                words = term.value.split()
                if len(words) >= 2 and len(words[-1]) >= 4:
                    surname = words[-1]
                    key = _norm(surname)
                    if key not in self.exact and key not in self.allow:
                        self._add(surname, _Entry("PERSON", surname, component=True))
        self._regex = self._compile()

    def _add(self, variant: str, entry: _Entry) -> None:
        key = _norm(variant)
        if not key or key in self.allow:
            return
        self.exact.setdefault(key, entry)
        if has_stem(key):
            self.stems.setdefault(stem_key(key), entry)

    def _compile(self) -> re.Pattern[str] | None:
        if not self.exact and not self.stems:
            return None
        parts = []
        if self.exact:
            parts.append(trie_regex(sorted(self.exact)))
        if self.stems:
            parts.append(trie_regex(sorted(self.stems)))
        body = "|".join(f"(?:{p})" for p in parts)
        return re.compile(rf"(?<![^\W_])(?:{body})(?![^\W_])")  # "Trio_D365" is two words

    @property
    def size(self) -> int:
        return len(self.exact)

    def _lookup(self, matched: str) -> _Entry | None:
        key = _WS.sub(" ", matched)
        if key in self.exact:
            return self.exact[key]
        return self.stems.get(stem_key(key))

    def detect(self, text: str) -> list[Span]:
        if self._regex is None:
            return []
        folded, index = fold_with_map(text)
        folded = folded.replace("_", " ")  # file names and identifiers: "Nordia_Hellas_D365"
        spans: list[Span] = []
        for m in self._regex.finditer(folded):
            if m.end() == m.start():
                continue
            entry = self._lookup(m.group(0))
            if entry is None:
                continue
            s, e = span_to_original(index, m.start(), m.end(), len(text))
            if entry.component and not text[s].isupper():
                continue  # a surname alone must look like a name ("Rose", not "rose")
            meta = {"canonical": entry.canonical}
            matched = _WS.sub(" ", m.group(0))
            if matched not in self.exact:
                endings = word_endings(matched)
                if any(endings):
                    meta["endings"] = endings
            spans.append(
                Span(
                    s,
                    e,
                    entry.category,
                    text[s:e],
                    "dictionary",
                    kind="component" if entry.component else "term",
                    meta=meta,
                )
            )
        return spans
