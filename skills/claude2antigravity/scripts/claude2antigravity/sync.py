"""The sync engine: plan what changed in Claude, then apply it to Antigravity.

Safety rules
- Only items Claude2Antigravity installed itself (recorded in state.json) are ever updated or removed.
- An Antigravity item with the same name that we did not install is left alone (use --adopt to take it over).
- If the user edited our copy inside Antigravity, it is not deleted when the Claude original disappears.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import conversations, convert, memory
from .paths import Homes
from .sources import Item, find_agents, find_mcp_servers, find_plugins, find_skills
from .util import (content_signature, log, read_json, remove_path, replace_tree, shallow_signature, tree_signature,
                   write_json_if_changed)

STATE_VERSION = 1
MAX_VISIBLE_SESSIONS = 200


@dataclass
class Action:
    op: str          # add | update | remove | skip
    kind: str        # skill | plugin | agent | mcp
    name: str
    reason: str = ""
    item: Item | None = None


@dataclass
class Report:
    actions: list[Action] = field(default_factory=list)
    sessions: int = 0
    memory_files_changed: int = 0
    seconds: float = 0.0
    dry_run: bool = False

    def changes(self) -> list[Action]:
        return [a for a in self.actions if a.op in ("add", "update", "remove")]

    def summary(self) -> str:
        c = self.changes()
        count = {op: sum(a.op == op for a in c) for op in ("add", "update", "remove")}
        skipped = sum(a.op == "skip" for a in self.actions)
        verb = "would change" if self.dry_run else "changed"
        return (f"{verb}: {count['add']} added, {count['update']} updated, {count['remove']} removed, {skipped} skipped"
                f" · {self.sessions} conversations · {self.seconds:.2f}s")


class State:
    def __init__(self, path: Path):
        self.path = path
        data = read_json(path, {}) or {}
        self.items: dict[str, dict] = data.get("items", {}) if data.get("version") == STATE_VERSION else {}
        self.mcp: dict[str, dict] = data.get("mcp", {})

    def save(self) -> None:
        write_json_if_changed(self.path, {"version": STATE_VERSION, "items": self.items, "mcp": self.mcp})


def destination(homes: Homes, item: Item) -> Path:
    if item.kind == "skill":
        return homes.agy_skills / item.name
    if item.kind == "plugin":
        return homes.agy_plugins / item.name
    return homes.agy_agents / f"{item.name}.md"


def all_items(homes: Homes) -> list[Item]:
    skills = find_skills(homes)
    plugins = find_plugins(homes)
    names = {s.name for s in skills}
    # Skills bundled inside plugins also become top-level skills (Antigravity lists them at once),
    # unless the user already has a standalone skill with that name - the user's skill wins.
    for p in plugins:
        for md in sorted((p.src / "skills").glob("*/SKILL.md")):
            name = md.parent.name.lower()
            if name not in names and name != "claude2antigravity":
                names.add(name)
                skills.append(Item("skill", name, md.parent, f"plugin {p.name}", p.version, md.stat().st_mtime))
    return skills + plugins + find_agents(homes)


def plan(homes: Homes, state: State, adopt: bool = False, deep: bool = True) -> list[Action]:
    """deep=False (live watcher): items whose shallow signature is unchanged are not walked at all."""
    actions: list[Action] = []
    current: set[str] = set()
    for item in all_items(homes):
        current.add(item.key)
        dst = destination(homes, item)
        rec = state.items.get(item.key)
        shallow = shallow_signature(item.src)
        item.meta["shallow"] = shallow
        if (not deep and rec is not None and rec.get("shallow") == shallow and rec.get("src") == str(item.src)
                and dst.exists()):
            continue
        sig = tree_signature(item.src)
        item.meta["src_sig"] = sig
        if rec is None:
            if dst.exists() and not adopt:
                actions.append(Action("skip", item.kind, item.name, "already in Antigravity, not managed (use --adopt)"))
            else:
                actions.append(Action("update" if dst.exists() else "add", item.kind, item.name, item.origin, item))
        elif rec.get("src_sig") != sig or not dst.exists():
            actions.append(Action("update", item.kind, item.name, item.origin, item))
        elif rec.get("shallow") != shallow:
            rec["shallow"] = shallow  # touched but identical: remember, so the fast path skips it next time
    for key, rec in state.items.items():
        if key not in current:
            kind, name = key.split(":", 1)
            actions.append(Action("remove", kind, name, "no longer in Claude"))
    return actions


def apply_item(homes: Homes, state: State, a: Action, post_plugin=None) -> None:
    item = a.item
    assert item is not None
    dst = destination(homes, item)
    if item.kind == "agent":
        convert.convert_agent(item.src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        replace_tree(item.src, dst)
        if item.kind == "plugin":
            convert.convert_plugin(dst, item.name, item.version, item.meta.get("description", ""))
            if post_plugin:
                post_plugin(dst, item)
            convert.set_plugin_enabled(homes.agy / "config.json", item.name, True)
    state.items[item.key] = {"dst": str(dst), "src": str(item.src), "origin": item.origin,
                             "src_sig": item.meta["src_sig"], "shallow": item.meta.get("shallow", ""),
                             "dst_sig": content_signature(dst),
                             "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def apply_remove(homes: Homes, state: State, a: Action) -> None:
    key = f"{a.kind}:{a.name}"
    rec = state.items.pop(key, {})
    dst = Path(rec.get("dst", ""))
    if not rec.get("dst") or not dst.exists():
        return
    if content_signature(dst) != rec.get("dst_sig"):
        log.warning("kept %s: it was changed inside Antigravity after syncing", dst)
        a.op, a.reason = "skip", "edited in Antigravity, kept"
        return
    remove_path(dst)
    if a.kind == "plugin":
        convert.set_plugin_enabled(homes.agy / "config.json", a.name, None)


def sync_mcp(homes: Homes, state: State, dry_run: bool) -> list[Action]:
    """Add Claude's user-level MCP servers. A same-named server already in Antigravity is never overwritten,
    even with --adopt, because Antigravity entries are often tuned by hand (timeouts, full paths)."""
    cfg_path = homes.agy / "mcp_config.json"
    cfg = read_json(cfg_path, {}) or {}
    servers = cfg.setdefault("mcpServers", {}) if isinstance(cfg, dict) else {}
    actions: list[Action] = []
    wanted = {name: convert.mcp_server(c) for name, c in find_mcp_servers(homes).items()}
    for name, conv in wanted.items():
        if conv is None:
            continue
        sig = json.dumps(conv, sort_keys=True)
        ours = name in state.mcp
        if name in servers and not ours:
            actions.append(Action("skip", "mcp", name, "already in Antigravity (kept as is)"))
            continue
        if ours and state.mcp[name].get("sig") == sig and name in servers:
            continue
        actions.append(Action("update" if name in servers else "add", "mcp", name, "~/.claude.json"))
        if not dry_run:
            servers[name] = conv
            state.mcp[name] = {"sig": sig}
    for name in list(state.mcp):
        if name not in wanted:
            actions.append(Action("remove", "mcp", name, "no longer in Claude"))
            if not dry_run:
                servers.pop(name, None)
                state.mcp.pop(name)
    if not dry_run and any(a.op != "skip" for a in actions):
        write_json_if_changed(cfg_path, cfg)
    return actions


def _pro():
    try:
        from . import pro  # noqa: PLC0415 - optional Pro edition
        return pro
    except ImportError:
        return None


def run(homes: Homes, dry_run: bool = False, adopt: bool = False, conversations_on: bool = True,
        only_conversations: bool = False, deep: bool = True) -> Report:
    t0 = time.perf_counter()
    report = Report(dry_run=dry_run)
    homes.app.mkdir(parents=True, exist_ok=True)
    state = State(homes.app / "state.json")
    pro = _pro()
    post_plugin = pro.post_plugin if pro else None

    if not only_conversations:
        actions = plan(homes, state, adopt, deep)
        if not dry_run:
            homes.agy.mkdir(parents=True, exist_ok=True)
            for a in actions:
                try:
                    if a.op in ("add", "update"):
                        apply_item(homes, state, a, post_plugin)
                    elif a.op == "remove":
                        apply_remove(homes, state, a)
                except FileNotFoundError:  # removed in Claude while we were copying: the next sync cleans up
                    log.debug("%s %s disappeared during the sync", a.kind, a.name)
                    a.op, a.reason = "skip", "removed while syncing"
                except OSError as exc:  # one broken item must not stop the whole sync
                    log.error("could not %s %s %s: %s", a.op, a.kind, a.name, exc)
                    a.op, a.reason = "skip", f"error: {exc}"
        report.actions += actions
        report.actions += sync_mcp(homes, state, dry_run)
        if not dry_run:
            state.save()

    if conversations_on:
        cache_path = homes.app / "conversations.json"
        cache = read_json(cache_path, {}) or {}
        new_cache, visible, changed = conversations.collect(homes, cache)
        extra_sessions, extra_block, redact = (pro.conversation_extras(homes, visible, new_cache)
                                               if pro else ([], "", None))
        visible = sorted(visible + extra_sessions, key=lambda s: s.get("last_ts", ""), reverse=True)
        visible = visible[:MAX_VISIBLE_SESSIONS]
        report.sessions = len(visible)
        extra_changed = {s["file"] for s in extra_sessions if s.get("changed", True)}
        if not dry_run and (changed or extra_changed or not (homes.agy_memory / "INDEX.md").exists()):
            only = None
            if isinstance(changed, set) and (homes.agy_memory / "INDEX.md").exists():
                only = changed | extra_changed
            report.memory_files_changed = memory.write_all(homes, visible, redact, extra_block, only)
            shown = {id(s) for s in visible}
            for old in new_cache.values():  # keep the cache small: only visible sessions keep their turns
                if id(old) not in shown:
                    old["turns"] = []
            cache_path.write_text(json.dumps(new_cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    report.seconds = time.perf_counter() - t0
    if not dry_run and (report.changes() or report.memory_files_changed or not only_conversations):
        write_json_if_changed(homes.app / "last_sync.json",
                              {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "summary": report.summary()})
    return report


def uninstall(homes: Homes) -> int:
    """Remove everything Claude2Antigravity installed (unchanged copies only) and our GEMINI.md block."""
    state = State(homes.app / "state.json")
    removed = 0
    for key in list(state.items):
        kind, name = key.split(":", 1)
        a = Action("remove", kind, name)
        apply_remove(homes, state, a)
        removed += a.op == "remove"
    cfg_path = homes.agy / "mcp_config.json"
    cfg = read_json(cfg_path, {}) or {}
    for name in list(state.mcp):
        cfg.get("mcpServers", {}).pop(name, None)
        state.mcp.pop(name)
        removed += 1
    if cfg:
        write_json_if_changed(cfg_path, cfg)
    memory.remove_block(homes.gemini_md)
    if homes.agy_memory.exists():
        remove_path(homes.agy_memory)
    state.save()
    return removed
