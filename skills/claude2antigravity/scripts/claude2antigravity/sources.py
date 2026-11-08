"""Find everything installed in Claude: skills, plugins, agents and MCP servers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Homes
from .util import log, parse_frontmatter, read_json, slug, version_key

SELF_NAMES = {"claude2antigravity"}  # never sync ourselves (no self-overwrite loop)


@dataclass
class Item:
    kind: str            # skill | plugin | agent
    name: str            # destination name in Antigravity
    src: Path            # folder (skill/plugin) or file (agent)
    origin: str          # human-readable source label
    version: str = ""
    mtime: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _pick(found: dict[str, Item], item: Item, priority: int, prio: dict[str, int]) -> None:
    """Keep one item per name: higher priority source first, then higher version, then newer files."""
    old = found.get(item.key)
    if old is None:
        found[item.key], prio[item.key] = item, priority
        return
    better = (priority, version_key(item.version), item.mtime) > (prio[item.key], version_key(old.version), old.mtime)
    if better:
        found[item.key], prio[item.key] = item, priority


# ---------------------------------------------------------------- skills
_META_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}


def read_meta(md: Path) -> dict | None:
    """Frontmatter of a .md file, cached by size+mtime (the live watcher calls this on every sync)."""
    try:
        st = md.stat()
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    hit = _META_CACHE.get(str(md))
    if hit and hit[0] == key:
        return hit[1]
    try:
        meta, _ = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    _META_CACHE[str(md)] = (key, meta)
    return meta


def _skill_item(skill_md: Path, origin: str) -> Item | None:
    meta = read_meta(skill_md)
    if meta is None:
        return None
    name = slug(meta.get("name") or skill_md.parent.name)
    if name in SELF_NAMES:
        return None
    return Item("skill", name, skill_md.parent, origin, meta.get("version", ""), _mtime(skill_md),
                {"description": meta.get("description", "")})


def find_skills(homes: Homes) -> list[Item]:
    found: dict[str, Item] = {}
    prio: dict[str, int] = {}
    for ch in homes.claude:
        root = ch / "skills"
        for md in sorted(root.glob("*/SKILL.md")):
            if (it := _skill_item(md, f"Claude Code ({root})")):
                _pick(found, it, 3, prio)
        for md in sorted(root.glob("synced/*/*/SKILL.md")):  # skills synced from claude.ai / Desktop
            if (it := _skill_item(md, "Claude (synced)")):
                _pick(found, it, 2, prio)
    if homes.desktop:
        for md in sorted(homes.desktop.glob("local-agent-mode-sessions/skills-plugin/*/*/skills/*/SKILL.md")):
            if (it := _skill_item(md, "Claude Desktop")):
                _pick(found, it, 1, prio)
    return sorted(found.values(), key=lambda i: i.name)


# ---------------------------------------------------------------- plugins
def _plugin_json(plugin_dir: Path) -> dict:
    for p in (plugin_dir / ".claude-plugin" / "plugin.json", plugin_dir / "plugin.json"):
        data = read_json(p)
        if isinstance(data, dict):
            return data
    return {}


def _enabled_map(ch: Path) -> dict[str, bool]:
    data = read_json(ch / "settings.json", {}) or {}
    raw = data.get("enabledPlugins") if isinstance(data, dict) else None
    return {k.split("@")[0]: bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def find_plugins(homes: Homes) -> list[Item]:
    found: dict[str, Item] = {}
    prio: dict[str, int] = {}

    def add(plugin_dir: Path, origin: str, priority: int, version_hint: str = "") -> None:
        meta = _plugin_json(plugin_dir)
        if not meta and not (plugin_dir / "skills").is_dir():
            return
        name = slug(meta.get("name") or plugin_dir.name)
        if name in SELF_NAMES:
            return
        version = str(meta.get("version") or version_hint or "")
        _pick(found, Item("plugin", name, plugin_dir, origin, version, _mtime(plugin_dir),
                          {"description": meta.get("description", ""), "displayName": meta.get("displayName", "")}),
              priority, prio)

    for ch in homes.claude:
        enabled = _enabled_map(ch)
        installed = read_json(ch / "plugins" / "installed_plugins.json", {}) or {}
        for key, entries in (installed.get("plugins") or {}).items():
            short = key.split("@")[0]
            if enabled.get(short) is False:
                log.debug("skip disabled plugin %s", key)
                continue
            if isinstance(entries, dict):
                entries = [entries]
            for e in entries if isinstance(entries, list) else []:
                raw_path = str(e.get("installPath", ""))
                path = Path(raw_path)
                if raw_path.startswith("/") and not path.is_dir():
                    # Linux path written by Claude inside WSL: /home/<user>/.claude/... -> <wsl home>/.claude/...
                    rel = Path(*Path(raw_path).parts[3:]) if len(Path(raw_path).parts) > 3 else Path()
                    path = ch.parent / rel
                if path.is_dir():
                    add(path, f"Claude Code plugin ({key})", 3, str(e.get("version", "")))
        for pj in sorted((ch / "plugins" / "synced").glob("*/*/.claude-plugin/plugin.json")):
            add(pj.parent.parent, "Claude (synced plugin)", 2)
    if homes.desktop:
        rpm = homes.desktop / "rpm"
        for pj in sorted(list(rpm.glob("*/*/*/.claude-plugin/plugin.json")) + list(rpm.glob("*/*/*/plugin.json"))):
            d = pj.parent.parent if pj.parent.name == ".claude-plugin" else pj.parent
            add(d, "Claude Desktop plugin", 1)
    return sorted(found.values(), key=lambda i: i.name)


# ---------------------------------------------------------------- agents
def find_agents(homes: Homes) -> list[Item]:
    found: dict[str, Item] = {}
    prio: dict[str, int] = {}
    for ch in homes.claude:
        for md in sorted((ch / "agents").glob("*.md")):
            meta = read_meta(md)
            if meta is None:
                continue
            name = slug(meta.get("name") or md.stem)
            _pick(found, Item("agent", name, md, f"Claude Code agent ({md.parent})", "", _mtime(md)), 1, prio)
    return sorted(found.values(), key=lambda i: i.name)


# ---------------------------------------------------------------- MCP servers
def find_mcp_servers(homes: Homes) -> dict[str, dict]:
    """User-level MCP servers from ~/.claude.json (project-level servers stay project-specific)."""
    servers: dict[str, dict] = {}
    for cj in homes.claude_json:
        try:
            data = json.loads(cj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, cfg in (data.get("mcpServers") or {}).items():
            if isinstance(cfg, dict) and name not in servers:
                servers[name] = cfg
    return servers
