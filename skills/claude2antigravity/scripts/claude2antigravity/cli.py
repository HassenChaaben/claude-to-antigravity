"""Command line: claude2agy sync | status | doctor | uninstall (+ Pro commands)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import EDITION, PRO_URL, __version__, is_pro
from . import sync as sync_mod
from .paths import Homes, discover
from .util import log, read_json, setup_logging

PRO_COMMANDS = {
    "watch": "24/7 live sync (changes appear in Antigravity in under 2 seconds)",
    "autostart": "start the live sync automatically when you log in",
    "search": "full-text search across all your Claude conversations",
    "handoff": "'continue in Antigravity' brief when Claude hits its usage limit",
    "context": "inject your latest Claude work into every Antigravity request",
    "setup": "one-step Pro setup: install, auto-start, Antigravity hooks",
}


def homes_from(args) -> Homes:
    return discover(
        claude_home=Path(args.claude_home) if args.claude_home else None,
        agy_home=Path(args.antigravity_home) if args.antigravity_home else None,
        app_home=Path(args.app_home) if args.app_home else None,
        include_wsl=False if args.no_wsl else None,
    )


def cmd_sync(args) -> int:
    homes = homes_from(args)
    if not homes.claude:
        log.error("No Claude Code folder (~/.claude) found. Install Claude Code first, or pass --claude-home.")
        return 2
    report = sync_mod.run(homes, dry_run=args.dry_run, adopt=args.adopt,
                          conversations_on=not args.no_conversations)
    for a in report.actions:
        if a.op != "skip" or args.verbose:
            mark = {"add": "+", "update": "~", "remove": "-", "skip": "·"}[a.op]
            log.info("  %s %-6s %-34s %s", mark, a.kind, a.name, a.reason)
    skipped = [a for a in report.actions if a.op == "skip"]
    if skipped and not args.verbose:
        log.info("  · %d item(s) skipped (already in Antigravity and not managed by us). Show them with -v; "
                 "take them over with --adopt.", len(skipped))
    log.info("%s %s", "Dry run:" if args.dry_run else "Done:", report.summary())
    if not args.dry_run:
        if not is_pro():
            log.info("Tip: Pro keeps this in sync 24/7 automatically - %s", PRO_URL)
    return 0


def cmd_status(args) -> int:
    homes = homes_from(args)
    state = sync_mod.State(homes.app / "state.json")
    last = read_json(homes.app / "last_sync.json", {}) or {}
    kinds: dict[str, int] = {}
    for key in state.items:
        kinds[key.split(":")[0]] = kinds.get(key.split(":")[0], 0) + 1
    print(f"Claude2Antigravity {__version__} ({EDITION} edition)")
    print(f"  Claude homes      : {', '.join(map(str, homes.claude)) or 'none found'}")
    print(f"  Antigravity       : {homes.agy}")
    print(f"  Managed items     : {kinds.get('skill', 0)} skills, {kinds.get('plugin', 0)} plugins, "
          f"{kinds.get('agent', 0)} agents, {len(state.mcp)} MCP servers")
    print(f"  Last sync         : {last.get('at', 'never')}  {last.get('summary', '')}")
    if is_pro():
        from .pro import watch  # noqa: PLC0415
        print(f"  Live sync         : {watch.status_line(homes)}")
    return 0


def cmd_doctor(args) -> int:
    homes = homes_from(args)
    checks: list[tuple[bool, str]] = []
    checks.append((sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (3.10+ needed)"))
    checks.append((bool(homes.claude), f"Claude Code folder: {', '.join(map(str, homes.claude)) or 'not found'}"))
    checks.append((homes.desktop is not None, f"Claude Desktop data: {homes.desktop or 'not found (optional)'}"))
    checks.append((homes.agy.exists(), f"Antigravity config: {homes.agy}"))
    try:
        homes.app.mkdir(parents=True, exist_ok=True)
        probe = homes.app / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append((True, f"State folder writable: {homes.app}"))
    except OSError as exc:
        checks.append((False, f"State folder not writable: {exc}"))
    gem = homes.gemini_md.read_text(encoding="utf-8") if homes.gemini_md.exists() else ""
    checks.append(("CLAUDE2ANTIGRAVITY:START" in gem, "GEMINI.md has the Claude context block (run sync if not)"))
    if "OMNISCIENT_SYNC_START" in gem:
        checks.append((False, "GEMINI.md also has an old OMNISCIENT_SYNC block from a previous tool"))
    checks.append((True, f"Edition: {EDITION}"))
    if is_pro():
        from .pro import doctor_checks  # noqa: PLC0415
        checks += doctor_checks(homes)
    ok = True
    for good, text in checks:
        print(f"  {'OK  ' if good else 'WARN'} {text}")
        ok &= good
    print("All good." if ok else "Some checks need attention (WARN lines above).")
    return 0 if ok else 1


def cmd_uninstall(args) -> int:
    homes = homes_from(args)
    if not args.yes:
        answer = input("Remove everything Claude2Antigravity added to Antigravity? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 1
    if is_pro():
        from .pro import teardown  # noqa: PLC0415
        teardown(homes)
    n = sync_mod.uninstall(homes)
    print(f"Removed {n} item(s) and the GEMINI.md block. Your own Antigravity items were not touched.")
    return 0


def cmd_pro_only(args) -> int:
    print(f"'{args.command}' is a Pro feature: {PRO_COMMANDS[args.command]}.")
    print(f"Get Claude2Antigravity Pro on Agensi: {PRO_URL}")
    return 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claude2agy", description="Bring Claude skills, plugins, agents, MCP servers and "
                                "conversations into Google Antigravity.")
    p.add_argument("--version", action="version", version=f"claude2antigravity {__version__} ({EDITION})")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--claude-home", help="use this Claude folder instead of ~/.claude")
    common.add_argument("--antigravity-home", help="use this folder instead of ~/.gemini/config")
    common.add_argument("--app-home", help="state folder (default ~/.claude2antigravity)")
    common.add_argument("--no-wsl", action="store_true", help="ignore Claude installs inside WSL")
    common.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("sync", parents=[common], help="copy everything from Claude into Antigravity now")
    s.add_argument("--dry-run", action="store_true", help="only show what would change")
    s.add_argument("--adopt", action="store_true", help="also take over same-named items already in Antigravity")
    s.add_argument("--no-conversations", action="store_true", help="skip conversation history")
    s.set_defaults(func=cmd_sync)
    sub.add_parser("status", parents=[common], help="what is synced").set_defaults(func=cmd_status)
    sub.add_parser("doctor", parents=[common], help="check the setup").set_defaults(func=cmd_doctor)
    u = sub.add_parser("uninstall", parents=[common], help="remove everything this tool added")
    u.add_argument("--yes", action="store_true")
    u.set_defaults(func=cmd_uninstall)
    if is_pro():
        from .pro import add_commands  # noqa: PLC0415
        add_commands(sub, common)
    else:
        for name, desc in PRO_COMMANDS.items():
            sp = sub.add_parser(name, help=f"[Pro] {desc}")
            sp.add_argument("rest", nargs="*")
            sp.set_defaults(func=cmd_pro_only)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    app = Path(args.app_home) if getattr(args, "app_home", None) else Path.home() / ".claude2antigravity"
    setup_logging(app / "log.txt", verbose=getattr(args, "verbose", False))
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
