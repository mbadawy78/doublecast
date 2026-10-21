# Contributing

Thanks for helping. The most valuable contributions, in order:

1. **Leaks.** Real-world text shapes where something sensitive survives scrambling. Turn it into a failing test (with invented data) and open an issue or PR.
2. **Country patterns** with checksum validators (VAT, national ID, phone formats) and tests for a true positive and a near-miss.
3. **Industry packs** (see [docs/packs.md](docs/packs.md)): construction, pharma, logistics, retail, public sector...
4. **Languages:** name lists for doubles, money words, inflection rules.

## Setup

```bash
git clone https://github.com/mbadawy78/doublecast && cd doublecast
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
doublecast bench -n 100
```

## Rules

- **Never commit real data**, not even in tests. Invent names, use checksum-valid generated IDs (`doublecast.validators` has generators).
- Every detector change needs a test, and `doublecast bench` must not get worse. Include its before/after summary in your PR.
- Keep the core dependency-light. Heavy, optional things (AI detectors, OCR) go behind extras.
- Precision matters as much as recall: a pattern that swaps ordinary numbers or words breaks the AI's answers. Prefer keyword anchors and checksums.
- Style: `ruff check .` and `ruff format .`, line length 120.

## Commit messages

Short imperative subject ("Add Portuguese NIF validator"), a body that says why.
