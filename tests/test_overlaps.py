import random

from doublecast.detectors.base import Span, resolve_overlaps
from doublecast.engine import _Guard


def _brute_resolve(spans):
    ordered = sorted(spans, key=lambda s: (-s.priority, -(s.end - s.start), -s.confidence, s.start))
    kept = []
    for s in ordered:
        if s.end > s.start and not any(s.overlaps(k) for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)


def test_resolve_overlaps_matches_brute_force():
    rng = random.Random(0)
    detectors = ["secret", "pattern", "dictionary", "money"]
    for _ in range(300):
        spans = []
        for _ in range(rng.randint(0, 30)):
            a = rng.randint(0, 200)
            spans.append(Span(a, a + rng.randint(1, 25), "ID", "x", rng.choice(detectors)))
        fast = [(s.start, s.end, s.detector) for s in resolve_overlaps(spans)]
        slow = [(s.start, s.end, s.detector) for s in _brute_resolve(spans)]
        assert fast == slow


def test_guard_matches_brute_force():
    rng = random.Random(1)
    for _ in range(300):
        intervals = [(a, a + rng.randint(1, 30)) for a in (rng.randint(0, 300) for _ in range(rng.randint(1, 20)))]
        guard = _Guard(intervals)
        for _ in range(30):
            s = rng.randint(0, 320)
            e = s + rng.randint(1, 20)
            assert guard.hits(s, e) == any(s < pe and ps < e for ps, pe in intervals)
