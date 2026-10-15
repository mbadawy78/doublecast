---
name: doublecast
description: Protect sensitive business data before you read or send it. Use whenever the user asks you to work with company files, exports, emails, CRM/ERP/BI data, customer or employee lists, prices, contracts or anything they call confidential, and whenever they mention Doublecast, scrambling, anonymising or "keeping data private".
---

# Doublecast: work on the double, never the original

Doublecast runs on the user's machine. It swaps sensitive values (customers, suppliers,
people, products, sites, IDs, IBANs, VAT numbers, emails, phones, prices, secrets) for
realistic doubles, and puts the real values back afterwards. Money is multiplied by a
secret factor, so ratios, margins and growth rates you compute are correct, but absolute
amounts you see are not the real ones.

## Rules

1. **Never open a sensitive file directly.** Read it through Doublecast (below).
2. **Work with the doubles as if they were real.** Do not try to guess, reverse or ask for
   the real names or amounts.
3. **Write results through Doublecast** so the user gets real values back on their machine.
4. If Doublecast is not installed, tell the user and offer the install command before
   touching sensitive data. Do not fall back to reading the raw file.

## Check it is available

```bash
doublecast --version && doublecast doctor
```

Not installed? Ask the user to run:

```bash
pipx install "doublecast[all]"     # or: pip install "doublecast[all]"
doublecast init
```

## Reading data

Preferred, when the `doublecast` MCP server is connected: call `read_scrambled(path)`.

Otherwise, make a scrambled copy and read that copy only:

```bash
doublecast scramble path/to/file.xlsx        # -> path/to/file.doublecast.xlsx
```

Supported: .xlsx .xlsm .docx .csv .tsv .pdf (→ .md) and text files (.txt .md .json .eml ...).
For text the user pastes, ask them to run `doublecast clip scramble` first, or pipe it:
`echo "..." | doublecast scramble -`.

## Writing results

- With MCP: `write_restored(path, content)` (text formats). Real values are restored locally.
- Without MCP: write your output to a file, then

```bash
doublecast restore output.md                 # -> output.restored.md
doublecast restore answer.doublecast.xlsx    # spreadsheets and Word files too
```

Tell the user which file holds the real values.

## Whole sessions

If the user wants an entire coding/agent session protected, they can start it through the
proxy instead: `doublecast run -- claude` (Claude Code) or see `doublecast env codex`.
Everything you send and receive is then scrambled and restored automatically.

## Teaching it the company's data

Names are found automatically (email headers, greetings, titles, signatures, company legal
forms, capitalised names) and remembered. To protect everything in the company's systems up
front, the user can run discovery once (Power BI, Microsoft 365, Dynamics 365, SharePoint,
SQL, Excel folders):

```bash
doublecast discover path ~/Documents/masterdata   # quick: a folder of Excel/CSV files
doublecast discover                               # all sources in ~/.doublecast/config.yaml
doublecast discover status
```

## Limits to mention when relevant

- Context can still identify a company ("the largest producer in region X"). If the context
  itself is confidential, say so and suggest a local model.
- Images and scanned PDFs are not scrambled.
- A brand-new name at the start of a sentence with an uncommon first name can slip through
  unless discovery or a term list covers it; `doublecast scan FILE` shows what will change.
