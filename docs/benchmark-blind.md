# Blind benchmark

The other benchmarks generate their own test emails, so a good score there partly measures how
well the project knows its own test. This one does not.

**How it was made.** A separate AI agent, which never saw Doublecast's code, wrote 130 realistic
business documents for an invented Greek frozen-pastry maker and its customers, suppliers and
hauliers: emails with headers and signatures, Teams-style chats in lower case and Greeklish,
meeting notes, memos and CSV exports, in Greek (45), English (35), German, French, Italian,
Spanish (10 each) and mixed Greek/English (10). It invented every person and company, used
uncommon names on purpose, and wrote the hard cases in: names at the start of a sentence,
surname-first order, Greek cases ("του κ. Μαυρίδη"), nicknames, lower-case names, companies with
and without legal forms, foreign tax numbers, IBANs with wrong check digits, addresses on several
lines. It marked 1,542 sensitive values and 686 ordinary phrases that must stay untouched
(products, cities, job titles, months).

Files: [`bench/blind/corpus.jsonl`](../bench/blind/corpus.jsonl). Run it yourself:

```bash
python bench/blind/score.py bench/blind/corpus.jsonl shared   # one vault for all documents
python bench/blind/score.py bench/blind/corpus.jsonl fresh    # a new vault per document
python bench/blind/score_with_discovery.py                    # with a master-data export
```

## Results (October 2026, no lists, no AI model)

"Leaked" means the exact value still appears in what would be sent to the AI.

| Value | Doublecast, one vault | Doublecast, new vault each time | Microsoft Presidio (default) |
|---|---:|---:|---:|
| Email addresses | **0%** | 0% | 0% |
| IBANs | **0%** | 0% | 50% |
| Phone numbers | **0%** | 0% | 12% |
| Tax numbers | **13%** | 13% | 35% |
| Addresses | **21%** | 21% | 29% |
| Companies | **17%** | 21% | 39% |
| People | **21%** | 26% | 28% |
| Amounts (scaled, not removed) | **2%** | 2% | 89% (not a Presidio goal) |
| Product codes, site codes | 87% | 87% | 77% |
| **Everything except amounts and codes** | **16%** | 20% | 28% |
| Ordinary phrases changed by mistake | **2.8%** | 2.8% | 45% |
| Text restored exactly | **130 / 130** | 130 / 130 | n/a (one-way) |

Presidio was run with its default recognisers and spaCy's large English and Greek models
(`score_presidio.py`), as a newcomer would install it; no custom recognisers, no German, French,
Italian or Spanish models. A tuned Presidio would do better. It is here as a reference point,
not a rival: it removes, Doublecast swaps and restores.

**With discovery.** Giving Doublecast the 78 people and companies from the CSV exports (what
`doublecast discover` would read from a customer and contact list) and testing on the other 117
documents: **0 of 94** mentions of those names leaked.

## What this says, plainly

- Structured values (emails, IBANs, phones) are handled. Tax numbers and addresses mostly.
- **About one name in five gets through when Doublecast knows nothing in advance.** Mostly lone
  first names at the start of a line, nicknames, lower-case surnames in chats, and one-word
  company names in running text. Remembering helps (one vault: 21% vs 26%), and lists or
  discovery close the gap for every name they contain.
- Internal product and site codes (`KRB-070-12`, `Plant KZ-2`) are not treated as secrets by
  default. If yours are, list them.
- Over-protection is low: the AI reads the text it expects.

The first run of this benchmark, before the fixes it prompted, was worse: 40% of values leaked
and 14 of 130 documents did not come back exactly. The fixes are in the changelog (0.2.2).
