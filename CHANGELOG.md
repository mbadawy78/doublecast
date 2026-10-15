# Changelog

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
