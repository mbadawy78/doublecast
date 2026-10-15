# Security policy

## Reporting

If you find a way for real values to reach the AI provider when they should not, a way to read the vault without the key, or a flaw in the proxy, **please report it privately** using GitHub's *Report a vulnerability* button (Security tab), rather than opening a public issue.

Please include:
- what you did (config, command, input shape; use invented data),
- what left the machine that shouldn't have,
- the Doublecast version (`doublecast --version`) and OS.

You should get a reply within 7 days. Fixes for confirmed leaks are prioritised over everything else.

## Scope

In scope: detection gaps for values the docs say are covered, restore bugs that write wrong real values, vault cryptography, proxy behaviour (headers, streaming, failure modes), MCP tools returning real values.

Out of scope: re-identification from context, and names nobody listed when the optional AI detector is off. Both are documented limits (see [docs/security.md](docs/security.md)), though test cases that improve them are welcome as normal issues.
