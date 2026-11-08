"""Small shared helpers: logging, atomic writes, tree signatures, frontmatter."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("claude2antigravity")

# Windows: start helper programs (wsl.exe, git, schtasks) without a console window. Without this flag a
# background process with no console makes Windows open one for a split second (a visible flash).
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def setup_logging(log_file: Path | None, verbose: bool = False) -> None:
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > 2_000_000:  # keep the log small
            log_file.replace(log_file.with_suffix(".old.txt"))
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_.-]+", "-", name.strip().lower()).strip("-.")
    return s or "unnamed"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return default


def write_text_if_changed(path: Path, text: str) -> bool:
    """Atomic write that is skipped when the content is identical (no needless disk writes)."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


def write_json_if_changed(path: Path, data: Any) -> bool:
    return write_text_if_changed(path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def tree_signature(root: Path) -> str:
    """Cheap signature of a whole folder: every file's relative path, size and mtime.

    Unlike hashing only SKILL.md, a change to any script or reference inside the folder is detected.
    """
    h = hashlib.sha1()
    if root.is_file():
        st = root.stat()
        h.update(f"{root.name}|{st.st_size}|{st.st_mtime_ns}".encode())
        return h.hexdigest()

    def walk(folder: str, rel: str) -> None:
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP_DIRS:
                        walk(e.path, f"{rel}/{e.name}")
                else:
                    st = e.stat(follow_symlinks=False)  # free: cached from the directory listing on Windows
                    h.update(f"{rel}/{e.name}|{st.st_size}|{st.st_mtime_ns};".encode())
            except OSError:
                continue

    walk(str(root), "")
    return h.hexdigest()


def shallow_signature(root: Path) -> str:
    """Very cheap signature: the item itself and its direct children (name, size, mtime).

    Catches added/removed/renamed files and edits to top-level files such as SKILL.md or plugin.json.
    Deeper edits are caught by tree_signature during a deep sync.
    """
    h = hashlib.sha1()
    try:
        st = root.stat()
        h.update(f"{st.st_size}|{st.st_mtime_ns}".encode())
        if root.is_dir():
            with os.scandir(root) as it:
                for e in sorted(it, key=lambda x: x.name):
                    s = e.stat()
                    h.update(f"{e.name}|{s.st_size}|{s.st_mtime_ns};".encode())
    except OSError:
        return ""
    return h.hexdigest()


def content_signature(root: Path) -> str:
    """Signature from file contents (used for the destination copy, whose mtimes are new after copying)."""
    h = hashlib.sha1()
    if root.is_file():
        h.update(root.read_bytes())
        return h.hexdigest()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            try:
                with open(p, "rb") as f:
                    h.update(f"{rel_dir}/{name}\n".encode())
                    h.update(hashlib.sha1(f.read()).digest())
            except OSError:
                continue
    return h.hexdigest()


def _on_rm_error(func, path, _exc):  # read-only files on Windows (e.g. git objects)
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=_on_rm_error)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _mirror_in_place(src: Path, dst: Path) -> None:
    """Update dst file by file (used when the folder cannot be swapped because a program holds it open)."""
    wanted: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        wanted.add(dst / rel)
        for name in filenames:
            s, d = Path(dirpath) / name, dst / rel / name
            wanted.add(d)
            if not d.exists() or d.stat().st_size != s.stat().st_size or d.read_bytes() != s.read_bytes():
                shutil.copy2(s, d)
    for p in sorted(dst.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p not in wanted:
            remove_path(p)


def replace_tree(src: Path, dst: Path) -> None:
    """Make dst an exact copy of src (files removed in src disappear from dst too).

    Normally a fresh copy is swapped in. On Windows a folder that another program (Antigravity, an antivirus)
    has open cannot be renamed, so after a few retries the files are updated in place instead.
    """
    tmp = dst.with_name(dst.name + ".c2a-tmp")
    if tmp.exists():
        remove_path(tmp)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(*SKIP_DIRS), symlinks=False)
    for attempt in range(4):
        try:
            if dst.exists() or dst.is_symlink():
                remove_path(dst)
            os.replace(tmp, dst)
            return
        except PermissionError:
            time.sleep(0.25 * (attempt + 1))
    log.debug("folder busy, updating in place: %s", dst)
    remove_path(tmp)
    _mirror_in_place(src, dst)


FRONTMATTER = re.compile(r"\A﻿?---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal YAML frontmatter reader for `key: value` lines (enough for SKILL.md / agent files)."""
    m = FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", line)
        if kv and not line.startswith((" ", "\t")):
            key = kv.group(1)
            meta[key] = kv.group(2).strip().strip("'\"")
        elif key and line.strip():  # folded continuation lines
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, text[m.end():]


def render_frontmatter(meta: dict[str, str], body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        v = str(v).replace("\n", " ")
        if re.search(r"[:#\[\]{}&*!|>'\"%@`]", v) or v != v.strip():
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.lstrip("\n")


def version_key(v: str) -> tuple:
    """Sort key for versions like 1.10.2, 6.4.2-8ca22d, or git hashes (unknown parts sort lowest)."""
    parts = re.findall(r"\d+", str(v).split("-")[0])
    return tuple(int(p) for p in parts[:4]) if parts else (-1,)
