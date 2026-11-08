"""Write Claude conversations where Antigravity can read them.

- memory/claude2antigravity/INDEX.md            every session, newest first
- memory/claude2antigravity/sessions/<p>/<id>.md the last turns of each session
- a marked block in ~/.gemini/config/GEMINI.md   the latest sessions, always in Antigravity's context

CLAUDE.md is never touched. Files are rewritten only when their content changes.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from .paths import Homes
from .util import log, remove_path, slug, write_text_if_changed

START = "<!-- CLAUDE2ANTIGRAVITY:START -->"
END = "<!-- CLAUDE2ANTIGRAVITY:END -->"
BLOCK_LIMIT = 6000           # characters of GEMINI.md we are allowed to use
SESSION_TURNS = 40

Redactor = Callable[[str], str]


def _identity(text: str) -> str:
    return text


def session_path(homes: Homes, sess: dict) -> Path:
    return homes.agy_memory / "sessions" / slug(sess["project"])[:80] / f"{sess['session_id'][:8]}.md"


def first_prompt(sess: dict) -> str:
    for t in sess["turns"]:
        if t["role"] == "user":
            return t["text"].splitlines()[0][:110]
    return ""


def render_session(sess: dict, redact: Redactor) -> str:
    lines = [f"# Claude session {sess['session_id'][:8]} - {sess['project']}", "",
             f"- Folder: `{sess.get('cwd') or '?'}`",
             f"- Branch: `{sess.get('branch') or '-'}`",
             f"- From {sess.get('first_ts', '')} to {sess.get('last_ts', '')} UTC, {sess.get('user_turns', 0)} prompts",
             f"- Tools used: {', '.join(sess.get('tools', [])[:20]) or '-'}"]
    if sess.get("todos"):
        lines += ["", "## Last todo list"]
        lines += [f"- [{'x' if t['status'] == 'completed' else ' '}] {t['content']}" for t in sess["todos"]]
    lines += ["", f"## Last {min(SESSION_TURNS, len(sess['turns']))} turns", ""]
    for t in sess["turns"][-SESSION_TURNS:]:
        who = "**You**" if t["role"] == "user" else "**Claude**"
        lines += [f"{who} ({t['ts']}):", "", redact(t["text"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def render_index(homes: Homes, sessions: list[dict], redact: Redactor) -> str:
    lines = ["# Claude Code conversations (synced by Claude2Antigravity)", "",
             "Newest first. Open a session file to continue that work in Antigravity.", "",
             "| Last activity (UTC) | Project folder | First prompt | File |", "|---|---|---|---|"]
    for s in sessions:
        rel = session_path(homes, s).relative_to(homes.agy_memory).as_posix()
        prompt = redact(first_prompt(s)).replace("|", "\\|")
        lines.append(f"| {s['last_ts'][:16]} | `{s.get('cwd') or s['project']}` | {prompt} | [{rel}]({rel}) |")
    return "\n".join(lines) + "\n"


def render_block(homes: Homes, sessions: list[dict], redact: Redactor, extra: str = "") -> str:
    index = (homes.agy_memory / "INDEX.md").as_posix()
    parts = [START, "## Recent Claude Code work (synced by Claude2Antigravity)",
             f"The user also works in Claude Code. Full history: `{index}`. When the user says \"continue\" or "
             "mentions a project below, read that session file first.", ""]
    if extra:
        parts += [extra, ""]
    budget = BLOCK_LIMIT - sum(len(p) + 1 for p in parts) - len(END) - 50
    for s in sessions[:5]:
        users = [t for t in s["turns"] if t["role"] == "user"][-2:]
        last_ai = next((t for t in reversed(s["turns"]) if t["role"] == "assistant"), None)
        chunk = [f"### {s['last_ts'][:16]} · `{s.get('cwd') or s['project']}`"
                 + (f" · branch `{s['branch']}`" if s.get("branch") else ""),
                 f"File: `{session_path(homes, s).as_posix()}`"]
        chunk += [f"- You: {redact(t['text'])[:240]}" for t in users]
        if last_ai:
            chunk.append(f"- Claude: {redact(last_ai['text'])[:300]}")
        text = "\n".join(chunk) + "\n"
        if len(text) > budget:
            break
        parts.append(text)
        budget -= len(text)
    parts.append(END)
    return "\n".join(parts)


def put_block(path: Path, block: str) -> bool:
    """Insert or replace our marked block. The rest of the file is never changed."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    new = pattern.sub(lambda _m: block, text) if pattern.search(text) else (text.rstrip() + "\n\n" + block + "\n").lstrip()
    return write_text_if_changed(path, new)


def remove_block(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    new = re.sub(r"\n*" + re.escape(START) + r".*?" + re.escape(END) + r"\n?", "\n", text, flags=re.S)
    return write_text_if_changed(path, new.rstrip() + "\n") if new != text else False


def write_all(homes: Homes, sessions: list[dict], redact: Redactor | None = None, extra_block: str = "",
              only: set[str] | None = None) -> int:
    """Write session files, the index and the GEMINI.md block. Returns how many files changed.

    only: transcript files that changed - other session files are left alone (fast path for the live watcher).
    """
    redact = redact or _identity
    changed = 0
    wanted: set[Path] = set()
    for s in sessions:
        p = session_path(homes, s)
        wanted.add(p)
        if only is None or s["file"] in only or not p.exists():
            changed += write_text_if_changed(p, render_session(s, redact))
    sessions_dir = homes.agy_memory / "sessions"
    if only is None and sessions_dir.exists():  # drop files of sessions that were deleted or excluded
        for p in sessions_dir.glob("*/*.md"):
            if p not in wanted:
                remove_path(p)
                changed += 1
    changed += write_text_if_changed(homes.agy_memory / "INDEX.md", render_index(homes, sessions, redact))
    block = render_block(homes, sessions, redact, extra_block)
    if len(block) > BLOCK_LIMIT + 500:
        log.warning("GEMINI.md block is %d characters (limit %d); it was shortened", len(block), BLOCK_LIMIT)
    changed += put_block(homes.gemini_md, block)
    return changed
