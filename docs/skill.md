# Use Doublecast as a Claude skill

A skill teaches Claude *when* and *how* to use Doublecast, so you don't have to remind it:
before Claude opens a company file it makes a scrambled copy, works on the double, and writes
results back with the real values restored on your machine.

The skill is in [`integrations/claude-skill/doublecast/SKILL.md`](../integrations/claude-skill/doublecast/SKILL.md).

## Install

1. Install Doublecast on the machine where Claude works:

   ```bash
   pipx install "doublecast[all]"     # or: pip install "doublecast[all]"
   doublecast init
   ```

2. Add the skill:
   - **Claude Code:** copy the `doublecast` folder to `~/.claude/skills/` (all projects) or to
     `.claude/skills/` inside a project.
   - **Claude apps:** zip the `doublecast` folder and upload it as a custom skill in
     Settings → Capabilities (where available for your plan).

3. Optional but recommended, connect the MCP server so Claude can read and write through
   Doublecast directly:

   ```bash
   claude mcp add doublecast -- doublecast mcp
   codex  mcp add doublecast -- doublecast mcp
   ```

## Skill, MCP or proxy?

| | Skill | MCP server | Proxy |
|---|---|---|---|
| What it is | Instructions Claude follows | Tools Claude calls (`read_scrambled`, `write_restored`...) | A local gateway all traffic passes through |
| Protects | Files Claude is told to use | Files Claude reads with the tools | Everything sent to the model, automatically |
| Relies on | Claude following the instructions | Claude using the tools | Nothing: works even if Claude forgets |
| Best for | Everyday use in any Claude surface | Agents working with local files | Claude Code / Codex sessions on confidential work |

The proxy is the only option that does not depend on the model's cooperation. Use it when
the stakes are high: `doublecast run -- claude`.
