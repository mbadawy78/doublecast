"""The engine: detect, swap for doubles, and restore.

engine = Engine(load_config())
out = engine.scramble("Invoice for Nordia Hellas, €12.400,00, IBAN GR16 0110 ...")
send(out.text)                     # only stand-ins leave the machine
answer = engine.restore(ai_reply)  # real values come back
"""

from __future__ import annotations

import bisect
import logging
import re
from dataclasses import dataclass, field

from .config import Config, Term, load_config
from .data.names import RECOGNISED_FIRST_NAMES
from .detectors.base import Span, resolve_overlaps
from .detectors.dictionary import DictionaryDetector
from .detectors.heuristics import detect_structure, is_common_word, learnable
from .detectors.ner import NerDetector
from .detectors.patterns import CORE_PATTERNS, detect_ibans, detect_patterns, load_pack, load_pack_meta
from .detectors.secrets import detect_secrets
from .discover.rules import RulesStore
from .numbers import NumberTransformer, guess_decimal_char
from .restore import Restorer, StreamRestorer, apply
from .surrogates import SurrogateFactory, match_case, split_legal_form
from .textnorm import fold, greek_stem, inflect_words, is_greek, word_endings
from .vault import Vault

log = logging.getLogger("doublecast")

REDACTED_RE = re.compile(r"\[REDACTED:[a-z_]+\]")

# Capitalised multi-word names that were not swapped: a hint that a term may be missing.
_UNLISTED_RE = re.compile(r"(?<![\w.])(?:[A-ZΑ-ΩΆΈΉΊΌΎΏ][\w'’&.-]+(?:\s+(?:&\s+)?[A-ZΑ-ΩΆΈΉΊΌΎΏ][\w'’&.-]+){1,3})")
_COMMON_CAPS = {
    fold(w)
    for w in (
        "The",
        "This",
        "That",
        "These",
        "We",
        "I",
        "You",
        "Dear",
        "Hi",
        "Hello",
        "Best",
        "Regards",
        "Kind",
        "Thanks",
        "Thank",
        "Please",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "EU",
        "VAT",
        "CEO",
        "COO",
        "CFO",
        "OK",
        "Total",
        "Invoice",
        "No",
        "Price",
        "Key",
        "Team",
        "Account",
        "Ms",
        "Mr",
        "Mrs",
        "Dr",
        "Subject",
        "Re",
        "Fwd",
        "From",
        "To",
        "Cc",
        "Sent",
        "Date",
        "Note",
        "Summary",
        "Action",
        "Items",
        "Next",
        "Steps",
        "Αγαπητέ",
        "Αγαπητή",
        "Καλημέρα",
        "Καλησπέρα",
        "Ευχαριστώ",
        "Με",
        "Το",
        "Η",
        "Ο",
        "Οι",
        "Τα",
        "Στο",
        "Στη",
    )
}


_FIRST_NAME_KEYS = {fold(n) for n in RECOGNISED_FIRST_NAMES}
_CAP_RUN = re.compile(r"(?<![\w'’\-])[^\W\d_][\w'’\-]*(?:[ \t]+[^\W\d_][\w'’\-]*){0,3}")


def _latin_key(word: str) -> str:
    """How a name is spelled in an email address: Παπαδοπούλου -> papadopoulou, Müller -> muller."""
    from .data.realnames import strip_accents, translit

    w = translit(word) if is_greek(word) else strip_accents(word).lower()
    return re.sub(r"[^a-z0-9]", "", w)


def _word_root(folded_word: str) -> str:
    stem = greek_stem(folded_word)
    return stem or folded_word


class _Guard:
    """Fast "does this span touch any protected interval?" (intervals may overlap)."""

    def __init__(self, intervals: list[tuple[int, int]]):
        ordered = sorted(intervals)
        self.starts = [s for s, _ in ordered]
        self.max_end: list[int] = []
        running = -1
        for _, e in ordered:
            running = max(running, e)
            self.max_end.append(running)

    def hits(self, start: int, end: int) -> bool:
        i = bisect.bisect_left(self.starts, end)  # intervals that start before `end`
        return i > 0 and self.max_end[i - 1] > start


@dataclass
class ScrambleResult:
    text: str
    spans: list[Span] = field(default_factory=list)
    replacements: list[tuple[str, str, str]] = field(default_factory=list)  # (category, original, stand-in)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.spans)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.spans:
            counts[s.category] = counts.get(s.category, 0) + 1
        return counts


class Engine:
    def __init__(self, config: Config | None = None, vault: Vault | None = None):
        self.config = config or load_config()
        self.vault = vault or Vault(self.config.vault_path, self.config.key_path)
        self.factory = SurrogateFactory(self.vault.seed(), self.config.default_language, self.config.languages)
        self.rules = RulesStore(self.config.rules_path, self.vault)
        self._rules_dirty = False
        self._context: set[str] = set()
        self._recent_terms: list = []
        self._just_learned: list[tuple[str, str]] = []
        self._homonym_keys: dict[str, str] = {}
        self._email_people: dict[str, tuple[str, str]] = {}
        self._email_first: dict[str, str] = {}
        self._email_orgs: dict[str, str] = {}
        self._email_index_count = 0
        self._script_twins: dict[str, tuple[str, bool]] = {}
        self._used_twin = False
        self._homonym_count = 0
        self.recent_dictionary: DictionaryDetector | None = None
        self.terms = self._all_terms()
        self.dictionary = DictionaryDetector(self.terms, self.config.allow)
        self.pattern_specs = list(CORE_PATTERNS)
        self.money_headers: set[str] = set()
        self.quantity_headers: set[str] = set()
        for pack in self.config.packs:
            self.pattern_specs.extend(load_pack(pack))
            meta = load_pack_meta(pack)
            self.money_headers.update(fold(h) for h in meta.get("money_headers", []) or [])
            self.quantity_headers.update(fold(h) for h in meta.get("quantity_headers", []) or [])
        self.numbers = NumberTransformer(
            self.vault.factor("money"),
            self.vault.factor("quantity"),
            self.vault.date_offset_days(),
            scale_money=self.config.scale_money,
            scale_quantities=self.config.scale_quantities,
            shift_dates=self.config.shift_dates,
            locale=self.config.number_locale,
        )
        self.allow = {fold(a).strip() for a in self.config.allow}
        self._index_terms()
        self.ner: NerDetector | None = None
        if self.config.ner_enabled in ("auto", "on"):
            self.ner = NerDetector(self.config.ner_model, self.config.ner_labels, self.config.ner_threshold)
            if not self.ner.available:
                if self.config.ner_enabled == "on":
                    log.warning("NER requested but unavailable: %s", self.ner.error)
                self.ner = None
        self._cache: dict[str, str] = {}
        self.totals: dict[str, int] = {}
        self._known_words: set[str] = set()
        self._known_words_version = -1
        self._known_words_count = 0
        self._restorer: Restorer | None = None
        self._restorer_version = -1
        self._default_decimal = "."

    # ------------------------------------------------------------ terms: config + discovered + learned
    def _all_terms(self) -> list:
        seen = {fold(t.value) for t in self.config.terms}
        extra = [t for t in self.rules.terms() if fold(t.value) not in seen]
        return list(self.config.terms) + extra

    def _index_terms(self) -> None:
        self._term_roots = {
            _word_root(w) for t in self.terms for v in (t.value, *t.aliases) for w in fold(v).split() if len(w) >= 4
        }
        self._term_values = {fold(t.value) for t in self.terms} | {fold(a) for t in self.terms for a in t.aliases}

    def reload_rules(self) -> None:
        """Pick up newly discovered or learned terms (full rebuild)."""
        self.terms = self._all_terms()
        self.dictionary = DictionaryDetector(self.terms, self.config.allow)
        self._recent_terms = []
        self._just_learned = []
        self.recent_dictionary = None
        self._index_terms()
        self._cache.clear()
        self._rules_dirty = False

    def _add_learned_terms(self) -> None:
        """Names learned a moment ago go into a small second matcher, so a big rule set is not
        recompiled after every email (that took seconds with tens of thousands of terms)."""
        new = [Term(c, v) for c, v in self._just_learned if fold(v) not in self._term_values]
        self._just_learned = []
        self._rules_dirty = False
        if not new:
            return
        if len(self._recent_terms) + len(new) > 300:
            self.reload_rules()
            return
        self._recent_terms += new
        self.terms = self.terms + new
        self.recent_dictionary = DictionaryDetector(self._recent_terms, self.config.allow)
        for t in new:
            for v in (t.value, *t.aliases):
                self._term_values.add(fold(v))
                self._term_roots.update(_word_root(w) for w in fold(v).split() if len(w) >= 4)
        self._cache.clear()

    def _learn(self, spans: list[Span]) -> None:
        if not self.config.auto_learn:
            return
        changed = False
        for s in spans:
            if s.detector == "heuristic" and s.meta.get("strong") and s.category in ("PERSON", "ORG"):
                # only what cannot be ordinary language is remembered ("Dear Reader" teaches nothing)
                if s.kind == "legal_form":
                    core, _ = split_legal_form(s.text)
                    if not core or not learnable("ORG", core):
                        continue  # "Marketing Ltd", "Net Weight KG"
                    changed |= self._remember("ORG", s.text)
                    # also learn "Nordia Hellas" on its own, with the matching part of the double
                    full_double = self.vault.get(s.text)
                    if len(core) >= 4 and full_double and (len(core.split()) > 1 or not core.isupper()):
                        core_double, _ = split_legal_form(full_double)
                        self.vault.try_put("ORG", core, core_double)
                        changed |= self._remember("ORG", core)
                elif learnable(s.category, s.text, s.kind):
                    changed |= self._remember(s.category, s.text)
        if changed:
            self.rules.save()
            self._rules_dirty = True

    def _remember(self, category: str, value: str) -> bool:
        if self.rules.learn(category, value):
            self._just_learned.append((category, value.strip()))
            return True
        return False

    def learn_value(self, category: str, value: str) -> None:
        """Remember a value found through a spreadsheet column (saved by flush_learned)."""
        if not self.config.auto_learn:
            return
        from .discover.profiler import extract_terms

        terms, _ = extract_terms(category, [value])
        for t in terms:
            if category in ("PHONE", "TAX_ID", "IBAN", "ID") or learnable(category, t):
                self._pending_learn = True

    def flush_learned(self) -> None:
        if getattr(self, "_pending_learn", False):
            self.rules.save()
            self._rules_dirty = True
            self._pending_learn = False

    # ------------------------------------------------------------ restorer cache
    @property
    def restorer(self) -> Restorer:
        if self._restorer is None or self._restorer_version != self.vault.version:
            mappings = self.vault.mappings()
            if self._restorer is not None and self._restorer.can_extend(len(mappings)):
                self._restorer.extend(mappings[self._restorer.size :])
            else:
                self._restorer = Restorer(mappings, self._number_matches)
            self._restorer_version = self.vault.version
        return self._restorer

    def _number_matches(self, text: str):
        return self.numbers.restore_matches(text, self._default_decimal)

    # ------------------------------------------------------------ detection
    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        ibans = detect_ibans(text)
        secrets = detect_secrets(text)
        # digits inside an IBAN can pass the card checksum: the IBAN wins
        secrets = [s for s in secrets if not (s.kind == "payment_card" and any(s.overlaps(i) for i in ibans))]
        spans += secrets
        spans += ibans
        spans += detect_patterns(text, self.pattern_specs, self.config.languages)
        if self.rules.changed_on_disk():  # e.g. a scheduled discover ran while the proxy is up
            self.rules.reload()
            self.reload_rules()
        if self._rules_dirty:
            self._add_learned_terms()
        spans += self.dictionary.detect(text)
        if self.recent_dictionary is not None:
            spans += self.recent_dictionary.detect(text)
        if self.config.structure_detection:
            spans += detect_structure(text, self.config.capitalized_phrases)
        if self.ner:
            spans += self.ner.detect(text)
        spans += self.numbers.detect(text)
        keys = self.vault.surrogate_keys()
        spans = [s for s in spans if fold(s.text).strip() not in self.allow]
        # never re-scramble a stand-in (stand-ins can come back in chat history),
        # nor any shorter detection inside one
        # Structured values (emails, IBANs, IDs) that are already doubles are left alone, so text
        # that went through Doublecast once is not scrambled twice. Names are different: a real
        # person can share a name with a double used elsewhere, and leaking them is worse.
        protected = [
            (s.start, s.end)
            for s in spans
            if s.action == "replace" and s.detector in ("pattern", "pack", "secret") and fold(s.text).strip() in keys
        ]
        protected += [m.span() for m in REDACTED_RE.finditer(text)]
        spans += self._same_text_mentions(text, spans)
        spans += self._homonyms(text, spans)
        if protected:
            guard = _Guard(protected)
            spans = [s for s in spans if not guard.hits(s.start, s.end)]
        return resolve_overlaps(spans)

    def _same_text_mentions(self, text: str, spans: list[Span]) -> list[Span]:
        """ "Dear Mr Spyros Pappas, ... please call Pappas": once a strong clue names someone, every
        other mention in the same text is swapped too, not only from the next text on."""
        names: dict[str, str] = {}
        for s in spans:
            if s.detector != "heuristic" or not s.meta.get("strong") or s.category not in ("PERSON", "ORG"):
                continue
            names.setdefault(s.text, s.category)
            words = s.text.split()
            if s.category == "PERSON" and len(words) >= 2 and learnable("PERSON", words[-1], "title"):
                names.setdefault(words[-1], "PERSON")
            if s.kind == "legal_form":
                core, _ = split_legal_form(s.text)
                if core and learnable("ORG", core):
                    names.setdefault(core, "ORG")
        if not names:
            return []
        taken = [(s.start, s.end) for s in spans]
        out: list[Span] = []
        for name, cat in sorted(names.items(), key=lambda kv: -len(kv[0])):
            for m in re.finditer(rf"(?<![\w'’\-]){re.escape(name)}(?![\w\-])", text, re.IGNORECASE):
                if any(a < m.end() and m.start() < b for a, b in taken):
                    continue
                taken.append(m.span())
                out.append(
                    Span(
                        m.start(),
                        m.end(),
                        cat,
                        m.group(0),
                        "heuristic",
                        kind="same_text",
                        confidence=0.8,
                        meta={"strong": False, "canonical": name},
                    )
                )
        return out

    def _homonyms(self, text: str, spans: list[Span]) -> list[Span]:
        """A real person who shares a name with a double used earlier ("Dimitriou") gets a double
        of their own; otherwise restoring the answer would turn them into someone else."""
        if self._homonym_count != len(self.vault.mappings()):
            for m in self.vault.mappings()[self._homonym_count :]:
                if m.category in ("PERSON", "PERSON_PART", "ORG"):
                    key = fold(m.surrogate)
                    self._homonym_keys[key] = "ORG" if m.category == "ORG" else "PERSON"
            self._homonym_count = len(self.vault.mappings())
        if not self._homonym_keys:
            return []
        taken = [(s.start, s.end) for s in spans]
        out: list[Span] = []
        for m in _CAP_RUN.finditer(text):
            words = list(re.finditer(r"\S+", m.group(0)))
            # longest run of words first: "Daniel Kelgate" before "Kelgate"
            found = False
            for i in range(len(words)):
                for j in range(len(words), i, -1):
                    a, b = m.start() + words[i].start(), m.start() + words[j - 1].end()
                    cat = self._homonym_keys.get(fold(text[a:b])) if text[a].isupper() else None
                    if cat and not any(x < b and a < y for x, y in taken):
                        out.append(
                            Span(
                                a,
                                b,
                                cat,
                                text[a:b],
                                "heuristic",
                                kind="homonym",
                                confidence=0.7,
                                meta={"strong": False},
                            )
                        )
                        taken.append((a, b))
                        found = True
                        break
                if found:
                    break
        return out

    # ------------------------------------------------------------ stand-ins
    def stand_in(self, category: str, original: str) -> str:
        existing = self.vault.get(original)
        if existing:
            return existing
        twin = self._other_script_twin(category, original)
        for attempt in range(40):
            candidate = twin if (attempt == 0 and twin) else self.factory.make(category, original, attempt)
            self._used_twin = bool(twin) and attempt == 0
            key = fold(candidate)
            if key == fold(original) or key in self._term_values or self.vault.surrogate_taken(candidate):
                continue
            own_folded = fold(original).split()
            if category == "PERSON" and set(key.split()) & {w for w in own_folded if len(w) >= 3}:
                continue  # "Nikos Andreou" must not become "Nikos Athanasiou"
            own = {_word_root(w) for w in own_folded} | set(own_folded)  # shared words like "Project", "Plant" are fine
            if self._context and any(
                w not in own and (w in self._context or _word_root(w) in self._context)
                for w in key.split()
                if len(w) >= 3
            ):
                continue  # "Maria" must not stand in for Eleni in a text that also mentions a real Maria
            own_words = [w for w in fold(original).split() if len(w) >= 4]
            if any(ow in w and ow != w for ow in own_words for w in key.split()):
                continue  # "Falcon" must not become "Falconer"
            if any(
                (r := _word_root(w)) in self._term_roots and r not in own and w not in _FIRST_NAME_KEYS
                for w in key.split()
                if len(w) >= 4
            ):
                continue  # a double must never look like (an inflection of) another real listed name
            stored = self.vault.put(category, original, candidate)
            if stored != candidate:
                self._used_twin = False
            if category == "PERSON":
                self._register_surname(original, stored)
            return stored
        # extremely crowded vaults: fall back to a neutral, unique code
        n = len(self.vault.mappings()) + 1
        while True:
            fallback = f"{category.title()} {n:05d}"
            if not self.vault.surrogate_taken(fallback):
                return self.vault.put(category, original, fallback)
            n += 1

    # ------------------------------------------------------------ emails that match their person
    def _name_index(self) -> None:
        """Latin spelling of each real name word -> Latin spelling of its double, so
        e.papadopoulou@masoutis.gr can become f.theodoridou@doukas.gr."""
        maps = self.vault.mappings()
        if self._email_index_count == len(maps):
            return
        for m in maps[self._email_index_count :]:
            if m.category not in ("PERSON", "ORG", "PERSON_PART"):
                continue
            self._script_twins.setdefault(
                " ".join(_latin_key(w) for w in m.original.split()), (m.surrogate, is_greek(m.original))
            )
            ow = [_latin_key(w) for w in split_legal_form(m.original)[0].split()]
            dw = [_latin_key(w) for w in split_legal_form(m.surrogate)[0].split()]
            if not ow or not dw:
                continue
            if m.category == "PERSON_PART":
                continue
            if m.category == "PERSON":
                if len(ow) >= 2 and len(dw) >= 2:
                    self._email_people.setdefault(ow[-1], (dw[0], dw[-1]))
                    self._email_people.setdefault(ow[0], (dw[0], dw[-1]))
                    self._email_first.setdefault(ow[0], dw[0])
                elif len(ow) == 1:
                    self._email_people.setdefault(ow[0], ("", dw[-1]))
            else:
                self._email_orgs.setdefault("".join(ow), "".join(dw))
                self._email_orgs.setdefault(ow[0], dw[0])
        self._email_index_count = len(maps)

    def _email_stand_in(self, original: str) -> str:
        existing = self.vault.get(original)
        if existing:
            return existing
        self._name_index()
        local, _, domain = original.partition("@")
        tokens = re.split(r"([._\-])", local)
        words = [t for t in tokens if t and t not in "._-"]
        person = next((self._email_people[_latin_key(t)] for t in words if _latin_key(t) in self._email_people), None)
        if person:
            first, last = person
            out = []
            for t in tokens:
                k = _latin_key(t)
                if not t or t in "._-":
                    out.append(t)
                elif k in self._email_people and self._email_people[k] == person:
                    out.append(last if k not in self._email_first else (first or last))
                elif len(t) <= 2 and first:
                    out.append(first[: len(t)])
                else:
                    out.append(_latin_key(self.factory.make("PERSON", t)).split()[0] if t.isalpha() else t)
            new_local = "".join(out)
            labels = domain.split(".")
            stem = labels[-2] if len(labels) >= 2 else labels[0]
            if stem.lower() in self._email_orgs:
                labels[-2 if len(labels) >= 2 else 0] = self._email_orgs[stem.lower()]
                new_domain = ".".join(labels)
            else:
                new_domain = self.factory.make("EMAIL", original).partition("@")[2]
            candidate = f"{new_local}@{new_domain}"
            if candidate.lower() != original.lower() and not self.vault.surrogate_taken(candidate):
                return self.vault.put("EMAIL", original, candidate)
        return self.stand_in("EMAIL", original)

    def _other_script_twin(self, category: str, original: str) -> str | None:
        """Ελένη Παπαδοπούλου and Eleni Papadopoulou are one person: give them one double,
        in each one's own script (Πολυξένη Χριστοδούλου / Polyxeni Christodoulou)."""
        if category not in ("PERSON", "ORG"):
            return None
        from .data.realnames import GREEK_FROM_LATIN, translit_name

        self._name_index()
        key = " ".join(_latin_key(w) for w in original.split())
        hit = self._script_twins.get(key)
        if not hit:
            return None
        double, greek = hit
        if greek == is_greek(original):
            return None
        if not is_greek(original):
            return translit_name(double)
        words = [GREEK_FROM_LATIN.get(w) for w in double.split()]
        return " ".join(words) if all(words) else None

    def _register_surname(self, original: str, surrogate: str) -> None:
        o_words, s_words = original.split(), surrogate.split()
        if len(o_words) >= 2 and len(s_words) >= 2 and len(o_words[-1]) >= 4:
            if self.vault.get(o_words[-1]) is None and not self.vault.surrogate_taken(s_words[-1]):
                self.vault.put("PERSON_PART", o_words[-1], s_words[-1])

    # ------------------------------------------------------------ public API
    def plan(self, text: str) -> tuple[list[tuple[int, int, str]], list[Span], list[tuple[str, str, str]]]:
        """Work out every swap for `text` without applying it.

        Returns (replacements as (start, end, new_text), spans, log rows).
        """
        if not text:
            return [], [], []
        self._default_decimal = guess_decimal_char(text)
        spans = self.detect(text)
        words = set(re.findall(r"\w{3,}", fold(text)))
        self._context = words | {_word_root(w) for w in words if is_greek(w)}
        replacements: list[tuple[int, int, str]] = []
        log_rows: list[tuple[str, str, str]] = []
        kept: list[Span] = []
        # people and companies first, so an email can be built from their doubles
        for span in sorted(spans, key=lambda sp: sp.category == "EMAIL"):
            if span.action == "redact":
                new = f"[REDACTED:{span.kind or 'secret'}]"
            elif span.action in ("money", "quantity", "date"):
                new = self.numbers.forward(span, self._default_decimal)
                if new is None:
                    continue
                if span.action == "date":
                    # remember the exact written form, so "05/11/24" comes back padded
                    self.vault.try_put("DATE", span.text, new)
            else:
                canonical = span.meta.get("canonical", span.text)
                self._used_twin = False
                if span.category == "EMAIL":
                    new = self._email_stand_in(canonical)
                else:
                    self.factory.gender_hint = span.meta.get("gender")
                    try:
                        new = self.stand_in(span.category, canonical)
                    finally:
                        self.factory.gender_hint = None
                endings = None if self._used_twin else span.meta.get("endings")
                if not endings and not self._used_twin and span.detector == "heuristic" and is_greek(span.text):
                    endings = word_endings(fold(span.text))  # "κ. Σταματόπουλο" -> "κ. Ηλιόπουλο"
                if endings:
                    new = inflect_words(new, endings)  # keep Greek grammar: της Καρανίκα -> της Σολίκα
                new = match_case(span.text, new)  # "ΝΟΡΔΙΑ" in, "ΒΕΡΦΙΛΝΤ" out
            replacements.append((span.start, span.end, new))
            log_rows.append((span.category, span.text, new))
            kept.append(span)
        self._context = set()
        self._learn(kept)
        return replacements, kept, log_rows

    def scramble(self, text: str) -> ScrambleResult:
        if not text:
            return ScrambleResult(text)
        replacements, kept, log_rows = self.plan(text)
        out = apply(text, replacements)
        for span in kept:
            self.totals[span.category] = self.totals.get(span.category, 0) + 1
        return ScrambleResult(out, kept, log_rows, self._warnings(out))

    def scramble_cached(self, text: str) -> str:
        """Scramble with a memo. Chat clients resend the whole conversation on
        every turn; stand-ins are deterministic, so repeated text is reused."""
        hit = self._cache.get(text)
        if hit is not None:
            return hit
        out = self.scramble(text).text
        if len(self._cache) > 20000:
            self._cache.clear()
        self._cache[text] = out
        return out

    def restore_plan(self, text: str) -> list[tuple[int, int, str]]:
        if not text:
            return []
        self._default_decimal = guess_decimal_char(text)
        return self.restorer.matches(text)

    def restore(self, text: str) -> str:
        if not text:
            return text
        self._default_decimal = guess_decimal_char(text)
        return self.restorer.restore(text)

    def stream_restorer(self, escape_json: bool = False) -> StreamRestorer:
        return StreamRestorer(self.restorer, escape_json=escape_json)

    # ------------------------------------------------------------ hints
    def _warnings(self, scrambled: str, skip: list[Span] | None = None) -> list[str]:
        known = self.vault.surrogate_keys()
        if self._known_words_version != self.vault.version:
            mappings = self.vault.mappings()
            if len(mappings) < self._known_words_count:  # vault was wiped or edited
                self._known_words, self._known_words_count = set(), 0
            for m in mappings[self._known_words_count :]:
                for w in fold(m.surrogate).split():
                    w = w.strip(".,")
                    self._known_words.add(w)
                    if is_greek(w):
                        self._known_words.add(_word_root(w))
            self._known_words_count = len(mappings)
            self._known_words_version = self.vault.version
        known_words = self._known_words
        hints = []
        for m in _UNLISTED_RE.finditer(scrambled):
            if skip and any(m.start() < sp.end and sp.start < m.end() for sp in skip):
                continue
            phrase = m.group(0).strip(" .,'’")
            raw_words = phrase.split()
            if any(any(c.isdigit() for c in w) for w in raw_words):
                continue
            if all(w.isupper() for w in raw_words if len(w) > 1):
                continue
            key = fold(phrase)
            words = key.split()
            if key in known or key in self.allow:
                continue
            if all(w.strip(".,") in _COMMON_CAPS or w.strip(".,") in known_words for w in words):
                continue
            if any(_word_root(w.strip(".,")) in known_words for w in words if is_greek(w)):
                continue  # an inflected double ("Ηλιόπουλο") is ours
            if all(is_common_word(w) for w in raw_words):
                continue  # vocabulary, not a name
            hints.append(phrase)
        unique = sorted(set(hints))[:20]
        if unique:
            return ["Possible names not in your term lists (left unchanged): " + ", ".join(unique)]
        return []
