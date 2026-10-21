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
- **Restore after model mangling** (upper-case, possessive, Greek genitive): 3316/3316 (100.0%)
- **Ratio drift from money scaling** (rounding to cents): max 9.21e-06, mean 9.90e-08
- **Scramble speed:** 60 KB/s on this machine, starting from an empty vault (16.4s for the whole benchmark)

UNLISTED_PERSON uses only a dozen distinct names that are not in any list. Auto mode catches each
the first time it appears in a greeting, header or after a title, and remembers it, so this row
mostly measures *remembering*. How well brand-new names are found is measured separately, with
names that never repeat: see [benchmark-auto.md](benchmark-auto.md).