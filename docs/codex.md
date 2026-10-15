# OpenAI Codex (beta)

Codex speaks OpenAI's Responses API (`/responses`) over streaming events. Doublecast restores those streams, including function-call arguments. Support is **beta**: it is covered by tests against a simulated Responses stream, not yet by long real-world use. Please report anything odd.

Start the proxy first:

```bash
doublecast proxy
```

Then choose the section that matches how you sign in to Codex. `doublecast env codex` prints both for your port.

## If you use an OpenAI API key

Add one line to the **user-level** `~/.codex/config.toml` (Codex ignores this key in project-level config files):

```toml
openai_base_url = "http://127.0.0.1:8787/openai/v1"
```

The older `OPENAI_BASE_URL` environment variable is deprecated in Codex in favour of this config key, so prefer the config file.

## If you sign in with ChatGPT

ChatGPT-login traffic goes to a different backend (`chatgpt.com/backend-api/codex`), not to `api.openai.com`. Doublecast has a matching route. Add a custom provider:

```toml
model_provider = "doublecast"

[model_providers.doublecast]
name = "OpenAI via Doublecast"
base_url = "http://127.0.0.1:8787/backend-api/codex"
requires_openai_auth = true
```

`requires_openai_auth = true` keeps your ChatGPT sign-in. The proxy forwards `Authorization` and `ChatGPT-Account-ID` unchanged.

## MCP

```bash
codex mcp add doublecast -- doublecast mcp
```

Sources: the Codex configuration reference, advanced configuration, authentication and MCP pages (learn.chatgpt.com/docs). These settings change between Codex releases; check the current docs if something stops working.
