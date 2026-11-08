"""Read Claude Code conversations (~/.claude/projects/*/*.jsonl) incrementally.

Each transcript is read from the byte offset where the previous run stopped, so an active 10 MB session costs only
the few new lines, not a full re-read.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .paths import Homes
from .util import log

MAX_TURNS = 60          # turns kept per session
MAX_TEXT = 2000         # characters kept per turn
LIMIT_RE = re.compile(r"usage limit reached|hit your (usage |session |weekly )?limit|limit reached[^\n]{0,40}reset"
                      r"|out of (extra )?usage", re.I)
NOISE = ("<command-name>", "<local-command", "<task-notification>", "<system-reminder>")


def clean(text: str) -> str:
    text = re.sub(r"<pasted_content[^>]*>", "[pasted] ", text)
    text = re.sub(r"</?(pasted_content|USER_REQUEST)[^>]*>", "", text)
    text = re.sub(r"<(system-reminder|ADDITIONAL_METADATA|CONTEXT_SUMMARY)>.*?</\1>", "", text, flags=re.S)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _ts(value) -> str:
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).isoformat()[:19]
    return str(value or "")[:19]


def new_session(path: Path) -> dict:
    return {"session_id": path.stem, "file": str(path), "project": path.parent.name, "cwd": "", "branch": "",
            "first_ts": "", "last_ts": "", "user_turns": 0, "turns": [], "tools": [], "todos": [],
            "limit_hit": "", "offset": 0, "size": 0, "mtime": 0}


def parse_lines(sess: dict, lines: list[str], max_turns: int | None = MAX_TURNS) -> None:
    """Add the turns found in `lines` to `sess`. max_turns=None keeps every turn (search index)."""
    tools = set(sess["tools"])
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        ts = _ts(obj.get("timestamp"))
        if ts:
            sess["first_ts"] = sess["first_ts"] or ts
            sess["last_ts"] = ts
        if obj.get("cwd") and not sess["cwd"]:
            sess["cwd"] = obj["cwd"]
        if obj.get("gitBranch") and obj["gitBranch"] != "HEAD":
            sess["branch"] = obj["gitBranch"]
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if obj.get("type") == "user" and msg.get("role") == "user" and not obj.get("isMeta"):
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
            text = str(content or "")
            if not text or any(n in text for n in NOISE):
                continue
            if (t := clean(text)):
                sess["turns"].append({"role": "user", "ts": ts, "text": t[:MAX_TEXT]})
                sess["user_turns"] += 1
        elif obj.get("type") == "assistant" and isinstance(content, list):
            texts = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    tools.add(str(c.get("name", "")))
                    if c.get("name") == "TodoWrite" and isinstance(c.get("input"), dict):
                        sess["todos"] = [{"content": t.get("content", ""), "status": t.get("status", "")}
                                         for t in c["input"].get("todos", []) if isinstance(t, dict)][:30]
                elif c.get("type") == "text" and c.get("text"):
                    texts.append(c["text"])
            text = clean("\n".join(texts))
            if text:
                sess["turns"].append({"role": "assistant", "ts": ts, "text": text[:MAX_TEXT]})
                if LIMIT_RE.search(text[:400]) and (obj.get("isApiErrorMessage") or len(text) < 400):
                    sess["limit_hit"] = ts or "yes"
    if max_turns:
        sess["turns"] = sess["turns"][-max_turns:]
    sess["tools"] = sorted(t for t in tools if t)


def update_session(path: Path, cached: dict | None, st=None) -> tuple[dict, bool]:
    """Return (session, changed). Reads only bytes appended since the cached offset."""
    try:
        st = st or path.stat()
    except OSError:
        return cached or new_session(path), False
    sess = cached if cached and cached.get("file") == str(path) else new_session(path)
    if sess["size"] == st.st_size and sess["mtime"] == st.st_mtime_ns:
        return sess, False
    if st.st_size < sess["offset"]:  # file was rewritten/truncated: start over
        sess = new_session(path)
    try:
        with open(path, "rb") as f:
            f.seek(sess["offset"])
            chunk = f.read()
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        return sess, False
    end = chunk.rfind(b"\n")
    if end == -1:  # no complete line yet
        return sess, False
    complete = chunk[: end + 1]
    parse_lines(sess, complete.decode("utf-8", errors="replace").splitlines())
    sess["offset"] += len(complete)
    sess["size"], sess["mtime"] = st.st_size, st.st_mtime_ns
    return sess, True


def transcript_entries(homes: Homes) -> list[tuple[Path, os.stat_result]]:
    """Every top-level transcript with its stat (subagent logs in sub-folders are skipped).

    os.scandir gives sizes and times straight from the directory listing, much faster than stat() per file.
    """
    out: list[tuple[Path, os.stat_result]] = []
    for ch in homes.claude:
        try:
            with os.scandir(ch / "projects") as projects:
                dirs = [d.path for d in projects if d.is_dir()]
        except OSError:
            continue
        for d in dirs:
            try:
                with os.scandir(d) as it:
                    out += [(Path(e.path), e.stat()) for e in it if e.name.endswith(".jsonl") and e.is_file()]
            except OSError:
                continue
    return out


def transcript_files(homes: Homes) -> list[Path]:
    return [p for p, _ in transcript_entries(homes)]


def excluded(sess: dict, patterns: list[str]) -> bool:
    hay = (sess.get("cwd", "") + " " + sess.get("project", "")).lower()
    return any(p and p.lower() in hay for p in patterns)


def collect(homes: Homes, cache: dict) -> tuple[dict[str, dict], list[dict], set[str] | bool]:
    """Update the session cache from all transcripts.

    Returns (new cache keyed by file, visible sessions newest first, changed). `changed` is the set of transcript
    files that changed, or True when a transcript was deleted (then everything is rewritten). Excluded and empty
    sessions stay in the cache (so they are not re-read) but are not visible.
    """
    patterns = [str(p) for p in homes.settings.get("exclude_projects", [])]
    new_cache: dict[str, dict] = {}
    changed_files: set[str] = set()
    for f, st in transcript_entries(homes):
        sess, ch = update_session(f, cache.get(str(f)), st)
        if ch:
            changed_files.add(str(f))
        new_cache[str(f)] = sess
    changed: set[str] | bool = changed_files
    if set(cache) - set(new_cache):
        changed = True  # a transcript was deleted
    visible = [s for s in new_cache.values() if s.get("user_turns") and not excluded(s, patterns)]
    visible.sort(key=lambda s: s.get("last_ts", ""), reverse=True)
    return new_cache, visible, changed
