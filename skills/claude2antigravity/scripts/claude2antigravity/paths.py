"""Where Claude and Antigravity keep their files, found automatically for the current user.

Nothing personal is hard-coded and no environment variables are read: everything starts from Path.home().
WSL (Windows only): Claude Code homes inside *running* WSL distros are included, so the WSL VM is never woken up.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .util import NO_WINDOW, log

APP_DIR_NAME = ".claude2antigravity"


@dataclass
class Homes:
    claude: list[Path]                 # one or more ~/.claude folders (Windows/macOS/Linux + WSL)
    claude_json: list[Path]            # ~/.claude.json files (user-level MCP servers)
    desktop: Path | None               # Claude Desktop app data folder
    agy: Path                          # Antigravity config: ~/.gemini/config
    app: Path                          # our own state, logs and index: ~/.claude2antigravity
    settings: dict = field(default_factory=dict)
    auto_wsl: bool = False             # True when WSL homes should be looked up again (live sync)
    wsl_homes: list[Path] = field(default_factory=list)  # the part of `claude` that lives inside WSL

    def refresh_wsl(self) -> bool:
        """Re-check which WSL distros are running (e.g. WSL started after login). Returns True if changed."""
        if not self.auto_wsl:
            return False
        found = running_wsl_homes()
        if found == self.wsl_homes:
            return False
        self.claude = [p for p in self.claude if p not in self.wsl_homes] + found
        self.wsl_homes = found
        claude = self.claude
        self.claude_json = [p for p in [c.parent / ".claude.json" for c in claude] if p.exists()]
        return True

    @property
    def agy_skills(self) -> Path:
        return self.agy / "skills"

    @property
    def agy_plugins(self) -> Path:
        return self.agy / "plugins"

    @property
    def agy_agents(self) -> Path:
        return self.agy / "agents"

    @property
    def agy_memory(self) -> Path:
        return self.agy / "memory" / "claude2antigravity"

    @property
    def gemini_md(self) -> Path:
        return self.agy / "GEMINI.md"


def desktop_dir(home: Path) -> Path | None:
    if sys.platform == "win32":
        p = home / "AppData" / "Roaming" / "Claude"
    elif sys.platform == "darwin":
        p = home / "Library" / "Application Support" / "Claude"
    else:
        p = home / ".config" / "Claude"
    return p if p.exists() else None


def running_wsl_homes() -> list[Path]:
    """~/.claude folders inside WSL distros that are already running (Windows only)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["wsl.exe", "-l", "--running", "-q"], capture_output=True, timeout=3, check=False,
                             **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = out.stdout.decode("utf-16-le", errors="ignore").replace("\x00", "")
    homes: list[Path] = []
    for distro in (d.strip() for d in text.splitlines()):
        if not distro or "docker" in distro.lower():
            continue
        base = Path(rf"\\wsl.localhost\{distro}\home")
        try:
            homes += [h / ".claude" for h in base.iterdir() if (h / ".claude").is_dir()]
        except OSError:
            continue
    return homes


def load_settings(app: Path) -> dict:
    """User settings in ~/.claude2antigravity/config.json (all optional)."""
    try:
        data = json.loads((app / "config.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("ignoring invalid config.json: %s", exc)
        return {}


def discover(claude_home: Path | None = None, agy_home: Path | None = None, app_home: Path | None = None,
             include_wsl: bool | None = None) -> Homes:
    home = Path.home()
    app = app_home or home / APP_DIR_NAME
    settings = load_settings(app)
    auto_wsl = False
    wsl_homes: list[Path] = []
    if claude_home is not None:  # explicit override (tests, custom setups)
        claude = [claude_home]
        claude_json = [claude_home.parent / ".claude.json"]
        desktop = None
    else:
        claude = [home / ".claude"] if (home / ".claude").exists() else []
        claude_json = [home / ".claude.json"]
        desktop = desktop_dir(home)
        use_wsl = settings.get("wsl", True) if include_wsl is None else include_wsl
        auto_wsl = bool(use_wsl)
        if use_wsl:
            wsl_homes = running_wsl_homes()
            for wsl_home in wsl_homes:
                claude.append(wsl_home)
                claude_json.append(wsl_home.parent / ".claude.json")
    agy = agy_home or home / ".gemini" / "config"
    return Homes(claude=claude, claude_json=[p for p in claude_json if p.exists()], desktop=desktop, agy=agy,
                 app=app, settings=settings, auto_wsl=auto_wsl, wsl_homes=wsl_homes)
