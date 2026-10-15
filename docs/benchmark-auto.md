# Doublecast auto-mode benchmark (no lists)

100 synthetic emails per language (el, en, de, fr, it, es), seed 11. No term lists, no AI model:
only email structure, company legal forms, the capitalised-name net and self-learning.

| Situation | Values | Leaked | Leak rate |
|---|---:|---:|---:|
| email header names | 600 | 0 | 0.0% |
| greeting first names | 600 | 0 | 0.0% |
| company with legal form | 600 | 0 | 0.0% |
| title + surname | 600 | 0 | 0.0% |
| seen before, mentioned later without structure | 600 | 0 | 0.0% |
| new name mid-sentence (broad net) | 600 | 0 | 0.0% |
| new name at sentence start, common first name | 600 | 0 | 0.0% |
| new name at sentence start, uncommon first name (known gap) | 600 | 599 | 99.8% |

**Over-protection** (held-out phrases): 1 of 10 ordinary capitalised business phrases were swapped too (Purchase Requisition). No privacy cost, but the AI reads an invented name where an ordinary phrase was, which can confuse its answer. Set `auto.capitalized_phrases: false` to trade some recall for cleaner text.

A name that appears for the first time at the start of a sentence is caught when its first name
is a common one; otherwise it is the remaining gap without lists or an AI model.
`doublecast discover` closes it for every name that exists in your systems.