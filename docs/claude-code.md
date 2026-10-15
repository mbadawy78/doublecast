# Claude Code

Doublecast runs a local proxy between Claude Code and the Anthropic API. Claude Code sends requests to the proxy; the proxy scrambles them, forwards them to Anthropic with your credentials untouched, and restores the streamed answer before Claude Code sees it.

## Quickest: one protected session

```bash
doublecast run -- claude
```

This starts a temporary proxy on a free local port, sets `ANTHROPIC_BASE_URL` for that one `claude` process, and stops the proxy when you exit.

## Always on

```bash
doublecast proxy          # leave running (or set it up as a login item)
```

Then add this to `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"
  }
}
```

Run `/status` inside Claude Code and check the **Anthropic base URL** line. `doublecast env claude` prints all of this for your configured port.

## Your login keeps working

Per Claude Code's gateway documentation, setting only `ANTHROPIC_BASE_URL` keeps your claude.ai (Pro/Max) login as the active credential, provided the proxy forwards the `Authorization`, `anthropic-beta` and `anthropic-version` headers unchanged. Doublecast forwards authentication and `anthropic-*` headers unchanged and never stores credentials. It only adjusts transport headers (it asks the upstream for uncompressed responses so it can rewrite them, and drops hop-by-hop headers). API-key users (`ANTHROPIC_API_KEY`) work the same way.

## What the proxy does with Claude Code traffic

| Traffic | Treatment |
|---|---|
| `POST /v1/messages` (prompts, files Claude reads, tool results, your messages) | Scrambled on the way out; answer restored on the way in, including streamed text and tool-call arguments |
| First `system` block, when the request comes from Claude Code (user-agent `claude-cli/...`) | Forwarded byte-for-byte: it's Claude Code's attribution block, which Anthropic checks. Other clients' system prompts are scrambled. Disable with `proxy.pin_claude_code_system: false` |
| Thinking blocks | Forwarded byte-for-byte both ways (signed); they only ever contain doubles |
| `POST /v1/messages/count_tokens` | Scrambled, so counts match what is actually sent |
| `HEAD /api/hello` (connection warm-up) | Answered locally |
| Error responses | Passed through unmodified |

### Edits to your files keep working

When Claude reads a file containing "Nordia Hellas", it sees the double. When it edits that file, its `old_string`/`new_string` arguments contain the double, and the proxy restores them before Claude Code applies the edit, so the edit matches your real file. The exceptions are secrets: Claude sees `[REDACTED:openai_key]`, so an edit that tries to match a line containing a real key fails safely rather than writing the placeholder.

## Traffic that does not go through the proxy

Claude Code sends some traffic directly to Anthropic and third parties regardless of `ANTHROPIC_BASE_URL`: telemetry, error reports, update checks, a fast-mode availability check, and the WebFetch domain-safety check (hostname only). Prompts and files go through the proxy; this other traffic does not. To switch off the non-essential part:

```bash
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
```

Source: Claude Code docs, *LLM gateway* and *Data usage* pages. Verify against the current version, since this behaviour can change.

## Tips

- **Keep the proxy and your terms in sync.** New customers? Add them to `config.yaml` and restart the proxy.
- **One workspace per client** if you consult for several companies: `doublecast -w acme proxy`.
- Behind a custom base URL, Claude Code turns off MCP tool search by default. Set `ENABLE_TOOL_SEARCH=true` if you rely on it.
