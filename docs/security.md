# Security model

Doublecast reduces how much of your sensitive data reaches an AI provider. It is a strong layer, not a guarantee. This page states plainly what it protects against and what it does not.

## What it protects

| Threat | Protection |
|---|---|
| Provider logs, retention, training, or a breach exposing your prompts | Listed and pattern-detectable values never leave your machine; only doubles do |
| Credentials pasted or read into a prompt | Removed (`[REDACTED:kind]`) and never restored, in every mode |
| Someone stealing the vault file | Real values are encrypted (Fernet: AES-128-CBC + HMAC-SHA256); lookups use a keyed hash. Useless without `~/.doublecast/key` |
| Inferring real revenue or prices from doubles | Money is scaled by a secret per-workspace factor between 1.17 and 3.4 |
| Linking two clients' data | Separate workspaces have unrelated doubles and factors |

## What it does not protect

1. **Context re-identification.** Doubles hide names, not facts. "The largest olive-oil exporter on Crete, with 30 export markets" identifies a company with no name in it. A [2026 study](https://www.alphaxiv.org/abs/2605.30848) found web-search agents re-identified roughly half to three-quarters of Presidio-redacted transcripts from context. If the context itself is the secret, don't send it, or use a local model.
2. **Values nobody listed.** Without the optional local AI detector, names of people and companies that are not in your terms and have no recognisable shape pass through unchanged. `doublecast scan` and the proxy log flag capitalised names that were left alone. Treat those warnings as a to-do list.
3. **Ratios are real.** Scaling hides absolute amounts but keeps every ratio exact; that is what makes the answers useful. Margins, growth rates and mix percentages are visible. A determined analyst holding one real figure from elsewhere can derive the factor, and with it every amount in that workspace. Rotate by starting a new workspace when that matters.
4. **Binary attachments.** Images and PDFs embedded in API requests (base64) cannot be rewritten and pass through with a warning. Scramble documents with `doublecast scramble` before attaching them.
5. **Traffic outside the proxy.** Tools send telemetry, update checks and other requests directly to their vendors. For Claude Code, set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`; see [claude-code.md](claude-code.md).
6. **Your own machine.** Anyone who can read `~/.doublecast/` can read the vault. Doublecast assumes your computer is trusted. `doublecast vault list` deliberately prints real values next to their doubles in your terminal; it is the one command that does.
7. **Model-invented amounts.** Amounts the AI introduces from general knowledge are divided by the factor on the way back, so they can come back wrong. Amounts derived from your figures restore to within a cent.

## Design choices that matter for security

- **Fail behaviour is explicit.** `mode: block` refuses to send when scrambling fails or when a request body is not JSON (so it can't be rewritten). `mode: warn` (default) still strips secrets before sending in both cases.
- **Claude Code's attribution block** (the first system block, only for requests whose user-agent identifies Claude Code) is forwarded unchanged; see [claude-code.md](claude-code.md). If you put sensitive text in a custom system prompt, it goes in later blocks, which are scrambled.
- **No real values to the model from MCP.** The MCP server reads files *for* the model (scrambled) and writes files *from* the model (restored locally). There is no tool that returns real text to the model.
- **Signed reasoning blocks are never modified** and never restored, so they can't leak real values back upstream.
- **The proxy listens on 127.0.0.1 only** by default. Don't bind it to a network interface without putting authentication in front of it.
- **Deterministic doubles** are derived with HMAC-SHA256 from a per-vault random seed, so they reveal nothing about the original.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
