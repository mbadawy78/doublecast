from __future__ import annotations

import bisect
from dataclasses import dataclass, field

# Higher wins when two detections overlap.
PRIORITY = {
    "secret": 100,
    "pattern": 80,
    "dictionary": 70,
    "pack": 65,
    "column": 62,
    "heuristic": 60,
    "ner": 50,
    "money": 40,
    "quantity": 35,
    "date": 30,
}


@dataclass
class Span:
    start: int
    end: int
    category: str
    text: str
    detector: str  # secret | pattern | dictionary | pack | ner | money | quantity | date
    action: str = "replace"  # replace | redact | money | quantity | date
    confidence: float = 1.0
    kind: str = ""  # sub-type, e.g. "aws_key", "greek_vat"
    meta: dict = field(default_factory=dict)

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.detector, 0)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


class IntervalSet:
    """Non-overlapping [start, end) intervals with O(log n) overlap checks."""

    def __init__(self):
        self.starts: list[int] = []
        self.ends: list[int] = []

    def overlaps(self, start: int, end: int) -> bool:
        i = bisect.bisect_left(self.starts, start)
        if i < len(self.starts) and self.starts[i] < end:
            return True
        return i > 0 and self.ends[i - 1] > start

    def add(self, start: int, end: int) -> None:
        i = bisect.bisect_left(self.starts, start)
        self.starts.insert(i, start)
        self.ends.insert(i, end)


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Keep the strongest detection wherever spans overlap.

    Strength = priority, then length, then confidence.
    """
    ordered = sorted(spans, key=lambda s: (-s.priority, -(s.end - s.start), -s.confidence, s.start))
    taken = IntervalSet()
    kept: list[Span] = []
    for span in ordered:
        if span.end <= span.start or taken.overlaps(span.start, span.end):
            continue
        taken.add(span.start, span.end)
        kept.append(span)
    return sorted(kept, key=lambda s: s.start)
