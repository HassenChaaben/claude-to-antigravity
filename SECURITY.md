# Security policy

Claude2Antigravity reads Claude's local folders and writes to Antigravity's local folders. It makes **no network
calls**, reads **no environment variables**, and stores **no secrets**.

| Reads | Writes | Starts |
|---|---|---|
| `~/.claude/` (skills, plugins, agents, `projects/*.jsonl`), `~/.claude.json` (user MCP servers), Claude Desktop app data (Pro) | `~/.gemini/config/` (skills, plugins, agents, `mcp_config.json`, `config.json` plugin list, a marked block in `GEMINI.md`), `~/.claude2antigravity/` (state, logs) | `wsl.exe -l --running -q` (find Claude inside running WSL). Pro also starts Task Scheduler / launchctl / systemctl at setup, `git status` for handoff briefs, and the notification window. Always with argument lists, never a shell. |

MCP server entries copied from `~/.claude.json` may contain your own API keys in their `env` block; they are
copied to Antigravity's `mcp_config.json` on the same computer, exactly as they are, so the servers keep working.

## Reporting a vulnerability

Please open a private security advisory on GitHub
(https://github.com/HassenChaaben/claude-to-antigravity/security/advisories/new) instead of a public issue.
