"""Text normalisation that keeps a map back to the original string.

Matching is done on a folded copy of the text (case-folded, accents removed,
Greek final sigma unified) so that "Καλλέργης", "ΚΑΛΛΕΡΓΗΣ" and
"καλλεργης" all match the same dictionary term. The index map lets us
replace the exact original span afterwards.
"""

from __future__ import annotations

import functools
import unicodedata

_GREEK_RANGE = (0x0370, 0x03FF)
_GREEK_EXT_RANGE = (0x1F00, 0x1FFF)


@functools.lru_cache(maxsize=8192)
def fold_char(ch: str) -> str:
    decomposed = unicodedata.normalize("NFD", ch)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    folded = stripped.casefold()
    return folded.replace("ς", "σ")


def fold(text: str) -> str:
    return "".join(fold_char(c) for c in text)


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """Return the folded text and, for every folded char, its index in `text`."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        f = fold_char(ch)
        for c in f:
            out.append(c)
            index.append(i)
    return "".join(out), index


def span_to_original(index: list[int], start: int, end: int, original_len: int) -> tuple[int, int]:
    """Map a [start, end) span in folded text back to the original text."""
    if start >= len(index):
        return original_len, original_len
    o_start = index[start]
    o_end = index[end - 1] + 1 if end - 1 < len(index) else original_len
    return o_start, o_end


def is_greek(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if _GREEK_RANGE[0] <= cp <= _GREEK_RANGE[1] or _GREEK_EXT_RANGE[0] <= cp <= _GREEK_EXT_RANGE[1]:
            return True
    return False


GREEK_ENDINGS = (
    "ους",
    "ων",
    "ου",
    "ης",
    "ες",
    "ας",
    "ος",
    "οι",
    "ις",
    "η",
    "α",
    "ο",
    "ε",
    "ι",
)


def greek_stem(folded_term: str) -> str | None:
    """Return a stem for an inflected Greek word, or None if not applicable.

    Works on folded text (no accents, final sigma unified to σ). The stem
    must keep at least three letters, so "νικοσ" and its inflection "νικο"
    share the stem "νικ".
    """
    if len(folded_term) < 4 or not is_greek(folded_term):
        return None
    for ending in sorted(GREEK_ENDINGS, key=len, reverse=True):
        e = ending.replace("ς", "σ")
        if folded_term.endswith(e) and len(folded_term) - len(e) >= 3:
            return folded_term[: -len(e)]
    return None


GREEK_ENDING_REGEX = (
    "(?:" + "|".join(sorted({e.replace("ς", "σ") for e in GREEK_ENDINGS}, key=len, reverse=True)) + ")?"
)


STEM_MARK = "\x00"  # placeholder for "any Greek ending" inside trie keys


def stem_key(folded_phrase: str) -> str:
    """Key for inflection-tolerant matching: every stemmable Greek word becomes stem + marker."""
    words = folded_phrase.split(" ")
    out = []
    for w in words:
        st = greek_stem(w)
        out.append(st + STEM_MARK if st else w)
    return " ".join(out)


def has_stem(folded_phrase: str) -> bool:
    return STEM_MARK in stem_key(folded_phrase)


def split_ending(word: str) -> tuple[str, str]:
    """Split one (unfolded) Greek word into (stem in original form, folded ending)."""
    fw = fold(word)
    st = greek_stem(fw)
    if not st or len(fw) != len(word):
        return word, ""
    return word[: len(st)], fw[len(st) :]


def inflect(word: str, ending: str) -> str:
    """Put a folded Greek ending onto a word (or the first word of a phrase)."""
    if not ending:
        return word
    if " " in word.strip():
        first, rest = word.strip().split(" ", 1)
        return inflect(first, ending) + " " + rest
    stem, own = split_ending(word)
    if stem == word or own == ending:
        return word  # already in that form: keep it untouched (accents included)
    if ending.endswith("σ"):
        ending = ending[:-1] + "ς"  # final sigma
    letters = [c for c in word if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return stem + ending.upper()
    return stem + ending


def first_word_ending(folded_phrase: str) -> str:
    first = folded_phrase.split(" ", 1)[0]
    st = greek_stem(first)
    return first[len(st) :] if st else ""


def word_endings(folded_phrase: str) -> list[str]:
    """Greek ending of every word ("" where a word has none)."""
    out = []
    for w in folded_phrase.split(" "):
        st = greek_stem(w)
        out.append(w[len(st) :] if st else "")
    return out


def inflect_words(phrase: str, endings: list[str]) -> str:
    """Give each word of `phrase` the matching ending, when word counts agree."""
    if not any(endings):
        return phrase
    words = phrase.split(" ")
    if len(words) != len(endings):
        return inflect(phrase, endings[0])
    return " ".join(inflect(w, e) if e else w for w, e in zip(words, endings, strict=True))
