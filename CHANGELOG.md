# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-08

### Added
- **One-command sync** (`claude2agy sync`): Claude Code skills, plugins, agents, user MCP servers and conversations into Google Antigravity.
- **Plugin conversion**: Antigravity `plugin.json`, `.mcp.json` → `mcp_config.json` (`serverUrl`, `npx.cmd` on Windows, `${CLAUDE_PLUGIN_ROOT}` resolved), enabled in `config.json`; exact installed version from `installed_plugins.json`; disabled plugins skipped.
- **Agent conversion**: `~/.claude/agents/*.md` → `~/.gemini/config/agents/`.
- **Conversation memory**: one readable file per Claude Code session, an `INDEX.md`, and a short block in `GEMINI.md`. Incremental reading (only new lines). `CLAUDE.md` is never modified.
- **Safe by design**: only items this tool installed are updated or removed; edited copies are kept; `--dry-run`, `--adopt`, `status`, `doctor`, `uninstall`.
- **WSL support**: Claude Code inside running WSL distros is included without waking WSL.
- **Benchmark** (`tools/bench.py`) and 24 tests.
