# Changelog

## 0.2.0 (2026-10-15)

No lists needed.

- **Auto mode:** finds names from the structure of business text (email headers, greetings, titles,
  sign-offs, company legal forms, capitalised names, first + last names at sentence starts) in six
  languages, keeps Greek grammatical case, and remembers every name it finds (encrypted rules).
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
