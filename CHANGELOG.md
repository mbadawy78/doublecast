# Changelog

## 0.2.2 (2026-10-21)

Tested blind, and fixed what the test found.

- **Blind benchmark** (`bench/blind`): 130 documents written by an agent that never saw the code,
  scored against Microsoft Presidio. Leaks fell from 40% to 16% of sensitive values (amounts and
  internal codes aside); exact restore from 116/130 to 130/130 documents.
- Restore fixes: amounts below one ("€0,568"), a lower-case real name equal to an earlier double,
  surnames in any case, names written with and without accents, an exact match now beats an
  inflected one, Greek doubles never share a stem with another double.
- New clues: pasted CSV and Markdown tables (the header names each column), chat speakers
  ("callum:", "[09:12] Τάκης:"), "P. Kremastioti", "Vyron M.", surname-first lists, one-word
  company names ("it's with Crestway"), "Crestway Logistics", lower-case names in chats, known
  first names anywhere, more legal forms (plc, BV, NV, e.K., AB, OÜ...).
- Structured data: Greek phone numbers in every common grouping, French/Spanish/Italian/UK and
  any +country numbers, tax numbers after a label whatever their checksum, GB/SE/ES-CIF VAT,
  IBANs with a wrong check digit, street addresses (Greek and Latin).
- Doubles that are ordinary words ("Orchard", "Winter", "Farina", "Ψαράς") are gone from the
  name lists, and such words are never restored in lower case.
- Power BI: tables are listed with INFO.VIEW.COLUMNS(), checked on a real tenant; COLUMNSTATISTICS()
  ran out of memory on a large model and is now only the fallback.
- Microsoft API details checked against Microsoft Learn: Retry-After dates, Business Central
  `.default` scope, F&O URL case, contacts page size.
- Windows clipboard keeps Greek (UTF-8 both ways).

## 0.2.1 (2026-10-21)

Doubles that read like real people and companies.

- Large pools of real first names and surnames in Greek, English, German, French, Italian and
  Spanish; no more syllable-made names ("Λορούλης", "Quorory Rivory").
- Gender is kept (from the first name or the title: Ms, κα, Frau...), Greek women get feminine
  surnames, and the language of the name is kept (a German stays German).
- The same person written in Greek and in Latin letters gets one double in both scripts.
- Email addresses follow the person and the company (e.papadopoulou@masoutis.gr ->
  a.angelopoulou@apostolidis.gr).
- Companies keep their generic words and legal form ("Lidl Hellas EPE" -> "Thornfield Hellas EPE");
  Greek companies get Greek surname-style names that decline like the original.
- Products in Greek ("στο Κρουασάν Βουτύρου") are no longer mistaken for people.
- A double never reuses the original's first name.

## 0.2.0 (2026-10-15)

No lists needed.

- **Auto mode:** finds names from the structure of business text (email headers, greetings, titles,
  sign-offs, company legal forms, capitalised names, first + last names at sentence starts) in six
  languages, keeps Greek grammatical case, and remembers names found from strong clues (encrypted
  rules). Learning is strict: ordinary words, job titles, departments, lone first names and short
  codes are never remembered.
- **Column understanding:** spreadsheet columns headed Customer / Πελάτης / Salesperson / Είδος /
  Αποθήκη / ΑΦΜ... are swapped cell by cell; codes and IDs too.
- **Discovery:** `doublecast discover` learns what is sensitive from Excel/CSV folders, SQL databases,
  Microsoft 365 (Outlook contacts, mail correspondents, SharePoint lists and files), Power BI,
  Dynamics 365 F&O, Dataverse and Business Central. Read-only, local, encrypted, reviewable,
  schedulable.
- **Claude skill** in `integrations/claude-skill/doublecast`.
- Unlimited realistic surnames for doubles; vocabulary-aware broad net (offline word frequencies).
- Names that look like doubles are no longer skipped (a real person can share a double's name).
- New benchmark: `doublecast bench --auto`.
- Hardened after an independent review: a double never equals another word in the same text;
  code blocks and shell lines are left alone; Markdown tables, CSV rows, Greek article + name,
  κύριο/κο, possessives, inflected Greek first names and initials in company names are caught;
  `forget learned` is no longer undone by a running proxy; learning stays fast with tens of
  thousands of rules; discovery retries throttling and outages, renews tokens during long scans,
  never blocks a scheduled run on a sign-in, and no longer protects GL accounts, address
  cities, store formats or invoice-line descriptions.
- Hyphenated names, stacked titles ("Herr Dr. Schmidt"), leading initials and repeat mentions
  in the same text are caught; a real person who shares an earlier double's name gets their own.

## 0.1.0 (2026-10-15)

First public release.

- Engine: dictionary (case/accent-insensitive, Greek inflection), pattern and checksum detectors, secrets, optional local NER (GLiNER).
- Realistic, deterministic doubles; Greek doubles keep the declension class so cases round-trip exactly.
- Secret money scaling (and optional quantity scaling, date shifting), exact restore.
- Encrypted per-workspace vault.
- Proxy for Anthropic (Claude Code), OpenAI Chat Completions and Responses (Codex, beta), including the ChatGPT-login Codex backend; streaming-safe restore, tool-call arguments, signed reasoning left untouched.
- Files: xlsx (formulas kept, money columns scaled), docx (run formatting kept), csv, text, pdf → Markdown.
- Clipboard mode for web chats, MCP server, `doublecast run` wrapper.
- Packs: fmcg, finance, hr, legal_health. Languages: el, en, de, fr, it, es.
- Leak benchmark (`doublecast bench`).
- Hardened before release after an independent adversarial review: streamed amounts with a leading currency sign, non-JSON request bodies, other clients' system prompts, common-word surnames, credential shapes (`DB_PASSWORD=`, `Bearer`, AWS secret keys), money with magnitude words (`€2.3m`), ID columns in spreadsheets, Greek multi-word case endings, and date formats.
