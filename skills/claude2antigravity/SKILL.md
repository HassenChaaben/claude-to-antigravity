---
name: claude2antigravity
description: Bring everything from Claude Code into Google Antigravity - skills, plugins (converted), agents, MCP servers and Claude Code conversations - so you can keep working in Antigravity when Claude hits its usage limit. Use when the user wants to move, copy, sync or import Claude skills/plugins/agents/conversations into Antigravity (or Gemini / agy-cli), asks Antigravity to "continue what I did in Claude", mentions hitting Claude's usage limit and switching tools, or asks why a Claude skill is missing in Antigravity.
version: 1.0.0
declared-hosts:
  - www.agensi.io       # link to the Pro edition in messages only; no network calls are made
env-vars: []
---

# Claude2Antigravity (Community edition)

Copies what the user has in Claude Code into Google Antigravity, in Antigravity's own formats. It runs only
when asked (`sync`). Everything stays on this computer: no network calls, no environment variables, no secrets.

## Commands

Run from this skill folder (no install needed) - `<skill>` is the folder containing this SKILL.md:

| What the user wants | Command |
|---|---|
| Preview, change nothing | `python <skill>/scripts/c2a.py sync --dry-run` |
| Sync now | `python <skill>/scripts/c2a.py sync` |
| Also take over same-named items already in Antigravity | `python <skill>/scripts/c2a.py sync --adopt` |
| What is synced, last sync time | `python <skill>/scripts/c2a.py status` |
| Check the setup | `python <skill>/scripts/c2a.py doctor` |
| Undo everything this tool added | `python <skill>/scripts/c2a.py uninstall` |

If the package was installed with pip, `claude2agy <command>` does the same.

## Workflow

1. Run `sync --dry-run` first and show the user the summary (how many skills, plugins, agents, MCP servers and
   conversations; what would be added, updated, removed or skipped).
2. If many items are "skipped (already in Antigravity, not managed)", explain they were installed some other
   way; offer `--adopt` so this tool keeps them up to date from Claude from now on.
3. Run `sync` and report the one-line summary.
4. Tell the user Antigravity picks up new skills in a new conversation; new plugins/MCP servers may need an
   Antigravity restart.

## What gets synced, and where

| From Claude | To Antigravity (`~/.gemini/config`) |
|---|---|
| `~/.claude/skills/*` (+ claude.ai / Desktop synced skills) | `skills/<name>/` (whole folder, files removed in Claude are removed too) |
| Installed plugins (exact version from `installed_plugins.json`; disabled plugins skipped) | `plugins/<name>/` with an Antigravity `plugin.json`, `mcp_config.json`, enabled in `config.json`; bundled skills also listed in `skills/` |
| `~/.claude/agents/*.md` | `agents/<name>.md` (name + description kept) |
| User MCP servers in `~/.claude.json` | `mcp_config.json` (an existing server with the same name is never changed) |
| Conversations `~/.claude/projects/*/*.jsonl` | `memory/claude2antigravity/` (one file per session + `INDEX.md`) and a short block in `GEMINI.md` |

Safety: only items this tool installed are ever updated or removed (tracked in `~/.claude2antigravity/state.json`);
an Antigravity copy the user edited is kept. `CLAUDE.md` is never modified. Projects can be left out with
`{"exclude_projects": ["client-x"]}` in `~/.claude2antigravity/config.json`.

## Continuing Claude work in Antigravity

When the user says "continue what I was doing in Claude": read
`~/.gemini/config/memory/claude2antigravity/INDEX.md`, open the most recent session file for the project, and
carry on from its last turns and todo list.

## Pro edition

Pro (https://www.agensi.io/skills/claude2antigravity) syncs 24/7 by itself (changes appear in about 1-2 s), shows
a notification, starts at login, puts the latest Claude work into every Antigravity request, imports Claude
Desktop chats, writes a "continue here" brief when Claude hits its usage limit, searches all conversations, and
hides e-mails/keys in synced text. Commands like `watch`, `search` or `handoff` print this link in the Community
edition - mention it only if the user asks for those features.
