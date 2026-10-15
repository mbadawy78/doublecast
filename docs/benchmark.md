# Doublecast leak benchmark

Synthetic corpus: 1800 short business documents, 300 per language (el, en, de, fr, it, es), seed 7.
Listed = in the term lists or caught by a pattern detector. Unlisted = a person name nobody listed (AI detector off).

| Category | Values | Leaked | Leak rate |
|---|---:|---:|---:|
| EMAIL | 551 | 0 | 0.0% |
| IBAN | 543 | 0 | 0.0% |
| ID | 551 | 0 | 0.0% |
| NATIONAL_ID | 62 | 0 | 0.0% |
| ORG | 1257 | 0 | 0.0% |
| PERSON | 1110 | 0 | 0.0% |
| PHONE | 559 | 0 | 0.0% |
| SECRET | 147 | 0 | 0.0% |
| SITE | 543 | 0 | 0.0% |
| TAX_ID | 543 | 0 | 0.0% |
| UNLISTED_PERSON | 543 | 0 | 0.0% |

- **Round-trip exact restore:** 1653/1653 (100.0%)
- **Restore after model mangling** (upper-case, possessive, Greek genitive): 3275/3275 (100.0%)
- **Ratio drift from money scaling** (rounding to cents): max 1.15e-05, mean 1.38e-07
- **Scramble speed:** 83 KB/s on this machine, starting from an empty vault (13.2s for the whole benchmark)

Unlisted names leak by design when no AI detector is installed: list your people and partners,
or install the optional detector (`pip install 'doublecast[ner]'`) as a safety net.