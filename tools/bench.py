"""Benchmark Claude2Antigravity on a large synthetic setup (never touches your real folders).

    python tools/bench.py                 # Community parts
    python tools/bench.py --pro <scripts> # also the live watcher (path to a Pro 'scripts' folder)

Builds 200 skills, 50 plugins (with bundled skills and MCP servers), 30 agents and 1,000 conversations in a
temporary folder, then measures sync times, live latency, idle CPU/RAM and idle disk writes.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMUNITY_SCRIPTS = ROOT / "skills" / "claude2antigravity" / "scripts"


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def line(kind: str, text: str, ts: str) -> str:
    msg = ({"role": "user", "content": text} if kind == "user"
           else {"role": "assistant", "content": [{"type": "text", "text": text}]})
    return json.dumps({"type": kind, "timestamp": ts, "cwd": "C:/work/demo", "message": msg}) + "\n"


def build(home: Path, skills=200, plugins=50, agents=30, transcripts=1000) -> None:
    rnd = random.Random(7)
    claude = home / ".claude"
    for i in range(skills):
        d = claude / "skills" / f"skill-{i:03d}"
        write(d / "SKILL.md", f"---\nname: skill-{i:03d}\ndescription: test skill {i}\n---\n" + "Step.\n" * 40)
        for j in range(4):
            write(d / "scripts" / f"tool{j}.py", "print('x')\n" * 50)
        write(d / "references" / "guide.md", "Reference text.\n" * 200)
    installed = {}
    for i in range(plugins):
        d = claude / "plugins" / "cache" / "mkt" / f"plugin-{i:02d}" / "1.0.0"
        write(d / ".claude-plugin" / "plugin.json", json.dumps({"name": f"plugin-{i:02d}", "version": "1.0.0"}))
        write(d / ".mcp.json", json.dumps({"mcpServers": {f"srv{i}": {"type": "stdio", "command": "npx", "args": ["x"]}}}))
        for j in range(3):
            write(d / "skills" / f"p{i:02d}-s{j}" / "SKILL.md", f"---\nname: p{i:02d}-s{j}\ndescription: d\n---\nx\n")
        installed[f"plugin-{i:02d}@mkt"] = [{"scope": "user", "installPath": str(d), "version": "1.0.0"}]
    write(claude / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": installed}))
    for i in range(agents):
        write(claude / "agents" / f"agent-{i:02d}.md", f"---\nname: agent-{i:02d}\ndescription: d\ntools: Read\n---\nBe.\n")
    for i in range(transcripts):
        turns = "".join(line("user" if k % 2 == 0 else "assistant", f"turn {k} " + "words " * rnd.randint(5, 80),
                             f"2026-10-{1 + i % 28:02d}T{k % 24:02d}:00:00Z") for k in range(rnd.randint(4, 40)))
        f = claude / "projects" / f"proj-{i % 25:02d}" / f"session-{i:04d}.jsonl"
        write(f, turns)
        old = time.time() - 2 * 86400 - i  # past sessions: written days ago, like a real history
        os.utime(f, (old, old))
    (home / ".gemini" / "config").mkdir(parents=True, exist_ok=True)


def timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return time.perf_counter() - t0, out


def proc_stats(pid: int) -> tuple[float, float]:
    """(CPU seconds, working set MB) of a process - Windows PowerShell, else ps."""
    if sys.platform == "win32":
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              f"$p=Get-Process -Id {pid}; \"$($p.CPU) $($p.WorkingSet64)\""],
                             capture_output=True, text=True, timeout=20).stdout.split()
        return float(out[0].replace(",", ".")), int(out[1]) / 1e6
    out = subprocess.run(["ps", "-o", "cputime=,rss=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
    h, m, s = (int(x) for x in out[0].split(":"))
    return h * 3600 + m * 60 + s, int(out[1]) / 1e3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pro", type=Path, help="Pro 'scripts' folder (Community + Pro merged)")
    ap.add_argument("--json", type=Path, help="write results here")
    a = ap.parse_args()
    scripts = a.pro or COMMUNITY_SCRIPTS
    sys.path.insert(0, str(scripts))
    from claude2antigravity import is_pro, sync  # noqa: PLC0415
    from claude2antigravity.paths import discover  # noqa: PLC0415

    results: dict[str, object] = {}
    tmp = Path(tempfile.mkdtemp(prefix="c2a-bench-"))
    try:
        home = tmp / "home"
        t, _ = timed(build, home)
        print(f"built synthetic setup in {t:.1f}s")
        app = home / ".claude2antigravity"
        write(app / "config.json", json.dumps({"notifications": False}))
        homes = discover(claude_home=home / ".claude", agy_home=home / ".gemini" / "config", app_home=app,
                         include_wsl=False)
        t, r = timed(sync.run, homes, deep=True)
        results["first_full_sync_s"] = round(t, 2)
        results["items_synced"] = len(r.changes())
        results["conversations"] = r.sessions
        results["idle_deep_sync_s"] = round(timed(sync.run, homes, deep=True)[0], 3)
        results["idle_fast_sync_s"] = round(timed(sync.run, homes, deep=False)[0], 3)
        results["idle_config_only_fast_s"] = round(timed(sync.run, homes, deep=False, conversations_on=False)[0], 3)
        if is_pro():
            from claude2antigravity.pro import watch  # noqa: PLC0415
            n = 50
            cw = watch.ConversationWatch(homes)
            t0 = time.perf_counter()
            for _ in range(n):  # exactly what the watcher does every second
                watch.config_fingerprint(homes)
                cw.quick()
            results["idle_check_ms"] = round((time.perf_counter() - t0) / n * 1000, 2)
            t0 = time.perf_counter()
            for _ in range(10):  # what it does every 5 seconds
                watch.skillmd_fingerprint(homes)
                cw.full_changed()
            results["five_second_check_ms"] = round((time.perf_counter() - t0) / 10 * 1000, 1)
            gui = Path(sys.executable).with_name("pythonw.exe")
            py = str(gui if gui.exists() else sys.executable)
            proc = subprocess.Popen([py, str(scripts / "c2a.py"), "watch", "--claude-home", str(home / ".claude"),
                                     "--antigravity-home", str(home / ".gemini" / "config"), "--app-home", str(app),
                                     "--no-wsl"])
            for _ in range(200):
                if watch.is_running(homes):
                    break
                time.sleep(0.1)
            time.sleep(3)
            agy = home / ".gemini" / "config"
            snap = {p: p.stat().st_mtime_ns for p in list(agy.rglob("*")) + list(app.rglob("*")) if p.is_file()}
            cpu0, _ = proc_stats(proc.pid)
            time.sleep(30)
            cpu1, mem = proc_stats(proc.pid)
            after = {p: p.stat().st_mtime_ns for p in list(agy.rglob("*")) + list(app.rglob("*")) if p.is_file()}
            results["idle_cpu_percent"] = round((cpu1 - cpu0) / 30 * 100, 2)
            results["idle_ram_mb"] = round(mem, 1)
            results["idle_files_written_30s"] = sum(1 for p, m in after.items() if snap.get(p) != m)
            lat = []
            for i in range(10):
                start = time.perf_counter()
                write(home / ".claude" / "skills" / f"new-{i}" / "SKILL.md", f"---\nname: new-{i}\ndescription: d\n---\n")
                while not (agy / "skills" / f"new-{i}" / "SKILL.md").exists():
                    time.sleep(0.02)
                    if time.perf_counter() - start > 15:
                        break
                lat.append(time.perf_counter() - start)
                time.sleep(1.5)
            lat.sort()
            results["live_latency_median_s"] = round(statistics.median(lat), 2)
            results["live_latency_p95_s"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2)
            results["live_latency_max_s"] = round(lat[-1], 2)
            start = time.perf_counter()
            with open(home / ".claude" / "projects" / "proj-00" / "session-0000.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line("user", "brand new prompt for the bench", "2026-11-08T09:00:00Z"))
            target = agy / "memory" / "claude2antigravity" / "INDEX.md"
            while "brand new prompt" not in target.read_text(encoding="utf-8"):
                time.sleep(0.02)
                if time.perf_counter() - start > 15:
                    break
            results["conversation_latency_s"] = round(time.perf_counter() - start, 2)
            watch.stop(homes)
            proc.wait(10)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    width = max(len(k) for k in results)
    for k, v in results.items():
        print(f"{k:<{width}}  {v}")
    if a.json:
        a.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
