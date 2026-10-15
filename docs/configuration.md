# Configuration reference

Doublecast reads `~/.doublecast/config.yaml`. Set `DOUBLECAST_HOME` to use another folder, or pass `-c path/to/config.yaml` to any command. `doublecast init` writes a commented starter file with permissions 600, because it will hold your customer and people lists.

```yaml
workspace: acme            # separate vault + secret factors; -w on the CLI overrides
mode: warn                 # warn | block
languages: [el, en, de, fr, it, es]
default_language: en       # language for person doubles when it can't be guessed
packs: [fmcg, finance, hr, legal_health]

terms:
  ORG:
    - Nordia Hellas
    - value: Kallergis
      aliases: [Καλλέργης, ΚΑΛΛΕΡΓΗΣ ΑΕΕ]
  PERSON: [Eleni Papadopoulou]
  SITE: [Larissa Plant]
  PRODUCT: [Golden Twist 80g]
  PROJECT: [Project Falcon]
  CUSTOM: [our internal codename]

term_files: [customers.csv, people.csv]   # relative to the config file
allow: [Greece, Athens]

numbers:
  scale_money: true
  scale_quantities: false
  locale: auto             # auto | eu | us

dates:
  shift: false

ner:
  enabled: auto            # auto | on | off
  model: urchade/gliner_multi_pii-v1
  threshold: 0.55
  labels: [person, organization, company, location, product]

proxy:
  host: 127.0.0.1
  port: 8787
  pin_claude_code_system: true   # forward Claude Code's attribution block unchanged
  upstreams:
    anthropic: https://api.anthropic.com
    openai: https://api.openai.com
    chatgpt: https://chatgpt.com/backend-api/codex
```

## Terms

Categories: `ORG`, `PERSON`, `SITE`, `PRODUCT`, `PROJECT`, `CUSTOM`, plus `EMAIL`, `PHONE`, `IBAN`, `TAX_ID`, `NATIONAL_ID`, `ID`, `URL`, `IP` if you want to list specific values.

- Matching ignores case and accents, and treats any whitespace as a space.
- Greek words of five letters or more also match their inflected forms (genitive, accusative, plural).
- For a `PERSON` with two or more words, the surname on its own is also protected, but only when capitalised, so "Rose" the person is swapped and "a rose" the flower is not.
- Restored values follow the case of the text the model wrote (a double in capitals restores to the real value in capitals).
- `aliases` map several spellings to one canonical value. All of them get the same double, and restoring returns the canonical value.

### CSV term files

```csv
category,value,aliases
ORG,Nordia Hellas,NORDIA|Νόρντια Ελλάς
PERSON,Eleni Papadopoulou,
SITE,Larissa Plant,Εργοστάσιο Λάρισας
```

Export customers and suppliers from your ERP, people from HR, and sites from your master data.

## Numbers

- **Money**: any number attached to a currency symbol or code (€, EUR, ευρώ, $, USD, £, CHF and others) is multiplied by the workspace's secret factor. In spreadsheets, numeric cells are scaled when the column header names money (Price, Τιμή, Umsatz, Montant...) or the cell format shows a currency.
- **Quantities** (off by default): kg, tonnes, units, cases, pallets in all six languages, with a separate factor.
- **Magnitude words are understood**: `€2.3m`, `$1.2bn`, `€12k`, `1,5 εκατ. ευρώ`, `12 χιλιάδες ευρώ`, `3 Mio. €`, `1.2 million euros`.
- **Percentages are never touched.**
- **Spreadsheets** keep up to 6 decimals exactly; values with more decimals are rounded to 6.
- `locale: auto` reads `1.234` and `1,234` (one separator, three digits) as one thousand two hundred thirty-four. Set `eu` or `us` if your documents use three-decimal amounts.

## Dates

With `dates.shift: true`, dates (ISO `2026-03-02`, and day/month/year with `/`, `.` or `-`) move by a secret whole number of weeks, so weekdays stay right. Each date comes back in the exact form it was written (`05/11/24` stays zero-padded). One rare exception: if both `1/2/24` and `01/02/24` appear in the same workspace, they can shift to the same text, and both then restore to the first form seen. Version-like strings (`v1.2.2024`) are left alone.

## Modes

| | `warn` (default) | `block` |
|---|---|---|
| Scrambling fails in the proxy | Logs a warning, sends the request **with secrets stripped** but no other swaps | Returns HTTP 422, sends nothing |
| Image/PDF attachment in a request | Passes through, logs a warning | Passes through, logs a warning |

## Workspaces

Each workspace has its own vault file, its own money factor and its own date offset. Use one per company or client. Doubles are consistent within a workspace and unrelated across workspaces.

## Files

| Path | Contains |
|---|---|
| `~/.doublecast/config.yaml` | Your settings and term lists (600) |
| `~/.doublecast/key` | The encryption key (600). Back it up; without it nothing can be restored |
| `~/.doublecast/<workspace>.vault` | Encrypted real values ↔ doubles, secret factors (600) |
