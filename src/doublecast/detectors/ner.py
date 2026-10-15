"""Optional local AI detector for names you did not list.

Uses GLiNER (zero-shot named-entity recognition) when it is installed:

    pip install "doublecast[ner]"

The model runs on your machine; nothing is sent anywhere. It is a safety
net, not the main protection: your term lists and the pattern detectors
are deterministic, this is probabilistic. Quality on Greek has not been
benchmarked by its authors, so treat Greek results with care.
"""

from __future__ import annotations

import logging

from .base import Span

log = logging.getLogger("doublecast.ner")

LABEL_TO_CATEGORY = {
    "person": "PERSON",
    "organization": "ORG",
    "company": "ORG",
    "location": "SITE",
    "product": "PRODUCT",
}


class NerDetector:
    def __init__(self, model_name: str, labels: list[str], threshold: float):
        self.model_name = model_name
        self.labels = labels
        self.threshold = threshold
        self._model = None
        self.available = False
        self.error: str | None = None
        try:
            from gliner import GLiNER  # type: ignore[import-not-found]
        except ImportError:
            self.error = "GLiNER is not installed (pip install 'doublecast[ner]')"
            return
        try:
            self._model = GLiNER.from_pretrained(model_name)
            self.available = True
        except Exception as exc:  # network, missing weights, etc.
            self.error = f"Could not load NER model '{model_name}': {exc}"
            log.warning(self.error)

    def detect(self, text: str) -> list[Span]:
        if not self.available or not text.strip():
            return []
        spans: list[Span] = []
        # GLiNER works on bounded windows; chunk long text on paragraph boundaries.
        offset = 0
        for chunk in _chunks(text, 1500):
            try:
                ents = self._model.predict_entities(chunk, self.labels, threshold=self.threshold)
            except Exception as exc:  # pragma: no cover - model runtime errors
                log.warning("NER failed on a chunk: %s", exc)
                ents = []
            for ent in ents:
                category = LABEL_TO_CATEGORY.get(str(ent.get("label", "")).lower())
                if not category:
                    continue
                s, e = offset + int(ent["start"]), offset + int(ent["end"])
                spans.append(
                    Span(s, e, category, text[s:e], "ner", confidence=float(ent.get("score", 0.0)), kind="ner")
                )
            offset += len(chunk)
        return spans


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut + 1
        out.append(text[start:end])
        start = end
    return out
