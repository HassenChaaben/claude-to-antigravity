import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "claude2antigravity" / "scripts"))

from claude2antigravity.paths import discover  # noqa: E402


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def skill(root: Path, name: str, body: str = "Do the thing.", extra: dict | None = None) -> Path:
    d = root / name
    write(d / "SKILL.md", f"---\nname: {name}\ndescription: {name} skill\n---\n\n{body}\n")
    for rel, text in (extra or {}).items():
        write(d / rel, text)
    return d


def transcript_line(kind: str, text: str, ts: str, cwd: str = "C:/work/demo", **extra) -> str:
    if kind == "user":
        msg = {"role": "user", "content": text}
    else:
        msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    obj = {"type": kind, "timestamp": ts, "cwd": cwd, "gitBranch": "main", "message": msg}
    obj.update(extra)
    return json.dumps(obj) + "\n"


class Env:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.claude = self.home / ".claude"
        self.agy = self.home / ".gemini" / "config"
        self.app = self.home / ".claude2antigravity"
        self.claude.mkdir(parents=True)
        self.agy.mkdir(parents=True)

    def homes(self, settings: dict | None = None):
        if settings is not None:
            write(self.app / "config.json", json.dumps(settings))
        return discover(claude_home=self.claude, agy_home=self.agy, app_home=self.app, include_wsl=False)

    def plugin(self, name: str, version: str, mkt: str = "mkt", skills=("helper",), mcp: dict | None = None,
               agents=(), hooks: dict | None = None) -> Path:
        d = self.claude / "plugins" / "cache" / mkt / name / version
        write(d / ".claude-plugin" / "plugin.json",
              json.dumps({"name": name, "version": version, "description": f"{name} plugin"}))
        for s in skills:
            skill(d / "skills", s)
        for a in agents:
            write(d / "agents" / f"{a}.md", f"---\nname: {a}\ndescription: agent {a}\n---\nBe {a}.\n")
        if mcp:
            write(d / ".mcp.json", json.dumps({"mcpServers": mcp}))
        if hooks:
            write(d / "hooks" / "hooks.json", json.dumps(hooks))
        return d

    def register_plugins(self, entries: dict[str, Path], enabled: dict[str, bool] | None = None) -> None:
        data = {"version": 2, "plugins": {k: [{"scope": "user", "installPath": str(v), "version": v.name}]
                                          for k, v in entries.items()}}
        write(self.claude / "plugins" / "installed_plugins.json", json.dumps(data))
        if enabled is not None:
            write(self.claude / "settings.json", json.dumps({"enabledPlugins": enabled}))


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)
