"""Turn Claude formats into Antigravity formats."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .util import BrokenConfig, log, read_config, parse_frontmatter, read_json, render_frontmatter, write_json_if_changed

PLUGIN_ROOT_TOKENS = ("${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT")


def display_name(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").title()


def mcp_server(cfg: dict, plugin_root: Path | None = None) -> dict | None:
    """Claude MCP server entry -> Antigravity mcp_config.json entry."""
    out = {k: v for k, v in cfg.items() if k not in ("type",)}
    kind = cfg.get("type")
    url = cfg.get("url") or cfg.get("serverUrl")
    if url is not None:
        if not str(url).strip():
            return None
        out["serverUrl"] = url  # Antigravity reads serverUrl for remote servers
        out["url"] = url
    elif "command" in cfg:
        cmd = str(cfg["command"])
        if sys.platform == "win32" and cmd in ("npx", "npm", "pnpm", "yarn"):
            out["command"] = cmd + ".cmd"  # Antigravity starts processes without a shell on Windows
    else:
        return None
    if kind == "sse":
        out["transport"] = "sse"
    if plugin_root is not None:
        out = json.loads(_replace_root(json.dumps(out), plugin_root))
    return out


def _replace_root(text: str, root: Path) -> str:
    esc = json.dumps(str(root))[1:-1]
    for tok in PLUGIN_ROOT_TOKENS:
        text = text.replace(tok, esc)
    return text


def convert_plugin(dst: Path, name: str, version: str, description: str) -> list[str]:
    """Rewrite a copied Claude plugin folder in place so Antigravity can load it. Returns bundled skill names."""
    manifest = {"name": name, "displayName": display_name(name), "version": version or "1.0.0",
                "description": description or f"{display_name(name)} (from Claude)"}
    write_json_if_changed(dst / "plugin.json", manifest)

    claude_mcp = read_json(dst / ".mcp.json", {}) or {}
    servers = claude_mcp.get("mcpServers", claude_mcp) if isinstance(claude_mcp, dict) else {}
    converted = {}
    for sid, cfg in (servers or {}).items():
        if isinstance(cfg, dict) and (c := mcp_server(cfg, dst)) is not None:
            converted[sid] = c
    if converted:
        write_json_if_changed(dst / "mcp_config.json", {"mcpServers": converted})
    return sorted(p.parent.name for p in (dst / "skills").glob("*/SKILL.md"))


def convert_agent(src: Path, dst: Path) -> None:
    """Claude agent (.md with name/description/tools/model) -> Antigravity agent (.md with name/description)."""
    meta, body = parse_frontmatter(src.read_text(encoding="utf-8", errors="replace"))
    out = {"name": meta.get("name") or src.stem, "description": meta.get("description", "")}
    if meta.get("tools"):
        body = f"<!-- Claude tools for this agent: {meta['tools']} -->\n\n" + body.lstrip("\n")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(render_frontmatter(out, body), encoding="utf-8", newline="\n")
    os.replace(tmp, dst)


def set_plugin_enabled(config_json: Path, name: str, enabled: bool | None) -> None:
    """enabled=True/False sets the flag; None removes our entry. Every other setting is kept as is."""
    try:
        data = read_config(config_json)
    except BrokenConfig as exc:
        log.warning("plugin %s not enabled: %s", name, exc)
        return
    plugins = data.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        return
    if enabled is None:
        if name not in plugins:
            return
        plugins.pop(name)
    else:
        entry = plugins.get(name)
        if isinstance(entry, dict) and entry.get("enabled") is enabled:
            return
        if isinstance(entry, dict):
            entry["enabled"] = enabled
        else:
            plugins[name] = {"enabled": enabled}
    write_json_if_changed(config_json, data)
