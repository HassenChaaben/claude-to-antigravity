import json
import os
import sys
import time

from conftest import skill, transcript_line, write

from claude2antigravity import cli, sync


def run(env, **kw):
    return sync.run(env.homes(kw.pop("settings", None)), **kw)


def ops(report):
    return {(a.op, a.kind, a.name) for a in report.actions}


# ------------------------------------------------------------------ skills
def test_skill_is_copied_with_all_files(env):
    skill(env.claude / "skills", "pdf-tools", extra={"scripts/run.py": "print(1)\n"})
    r = run(env)
    assert ("add", "skill", "pdf-tools") in ops(r)
    assert (env.agy / "skills" / "pdf-tools" / "scripts" / "run.py").read_text() == "print(1)\n"


def test_change_in_a_script_not_only_skill_md_is_synced(env):
    d = skill(env.claude / "skills", "pdf-tools", extra={"scripts/run.py": "print(1)\n"})
    run(env)
    time.sleep(0.02)
    (d / "scripts" / "run.py").write_text("print(2)\n")
    r = run(env)
    assert ("update", "skill", "pdf-tools") in ops(r)
    assert (env.agy / "skills" / "pdf-tools" / "scripts" / "run.py").read_text() == "print(2)\n"


def test_file_deleted_in_claude_disappears_in_antigravity(env):
    d = skill(env.claude / "skills", "s1", extra={"old.md": "x"})
    run(env)
    (d / "old.md").unlink()
    run(env)
    assert not (env.agy / "skills" / "s1" / "old.md").exists()


def test_uninstalled_skill_is_removed_only_if_we_installed_it(env):
    d = skill(env.claude / "skills", "temp")
    skill(env.agy / "skills", "users-own")
    run(env)
    import shutil
    shutil.rmtree(d)
    r = run(env)
    assert ("remove", "skill", "temp") in ops(r)
    assert not (env.agy / "skills" / "temp").exists()
    assert (env.agy / "skills" / "users-own" / "SKILL.md").exists()


def test_copy_edited_in_antigravity_is_kept_when_original_is_deleted(env):
    d = skill(env.claude / "skills", "temp")
    run(env)
    (env.agy / "skills" / "temp" / "SKILL.md").write_text("my edits")
    import shutil
    shutil.rmtree(d)
    run(env)
    assert (env.agy / "skills" / "temp" / "SKILL.md").read_text() == "my edits"


def test_existing_unmanaged_item_is_skipped_unless_adopt(env):
    skill(env.claude / "skills", "shared", body="claude version")
    skill(env.agy / "skills", "shared", body="antigravity version")
    r = run(env)
    assert ("skip", "skill", "shared") in ops(r)
    assert "antigravity version" in (env.agy / "skills" / "shared" / "SKILL.md").read_text()
    r = run(env, adopt=True)
    assert ("update", "skill", "shared") in ops(r)
    assert "claude version" in (env.agy / "skills" / "shared" / "SKILL.md").read_text()


def test_own_skill_is_never_synced(env):
    skill(env.claude / "skills", "claude2antigravity")
    run(env)
    assert not (env.agy / "skills" / "claude2antigravity").exists()


def test_dry_run_writes_nothing(env):
    skill(env.claude / "skills", "a")
    write(env.claude / "projects" / "p" / "s.jsonl", transcript_line("user", "hello", "2026-11-07T10:00:00Z"))
    before = sorted(p.relative_to(env.home) for p in env.home.rglob("*"))
    r = run(env, dry_run=True)
    assert ("add", "skill", "a") in ops(r)
    after = sorted(p.relative_to(env.home) for p in env.home.rglob("*") if env.app not in p.parents and p != env.app)
    assert [p for p in after] == [p for p in before]


def test_second_run_with_no_changes_writes_no_files(env):
    skill(env.claude / "skills", "a")
    p = env.plugin("tools", "1.0.0")
    env.register_plugins({"tools@mkt": p})
    write(env.claude / "projects" / "p" / "s.jsonl", transcript_line("user", "hello", "2026-11-07T10:00:00Z"))
    run(env)
    snap = {f: f.stat().st_mtime_ns for f in env.agy.rglob("*") if f.is_file()}
    time.sleep(0.05)
    r = run(env)
    assert not r.changes()
    assert {f: f.stat().st_mtime_ns for f in env.agy.rglob("*") if f.is_file()} == snap


# ------------------------------------------------------------------ plugins
def test_plugin_conversion_and_enable(env):
    p = env.plugin("devkit", "2.1.0", skills=("lint",), agents=("reviewer",),
                   mcp={"docs": {"type": "http", "url": "https://example.com/mcp"},
                        "local": {"type": "stdio", "command": "npx", "args": ["-y", "pkg", "${CLAUDE_PLUGIN_ROOT}/x"]}})
    env.register_plugins({"devkit@mkt": p})
    run(env)
    dst = env.agy / "plugins" / "devkit"
    manifest = json.loads((dst / "plugin.json").read_text())
    assert manifest == {"name": "devkit", "displayName": "Devkit", "version": "2.1.0", "description": "devkit plugin"}
    mcp = json.loads((dst / "mcp_config.json").read_text())["mcpServers"]
    assert mcp["docs"]["serverUrl"] == "https://example.com/mcp" and "type" not in mcp["docs"]
    assert mcp["local"]["command"] == ("npx.cmd" if sys.platform == "win32" else "npx")
    assert str(dst) in mcp["local"]["args"][2]
    assert json.loads((env.agy / "config.json").read_text())["plugins"]["devkit"] == {"enabled": True}
    assert (env.agy / "skills" / "lint" / "SKILL.md").exists()  # bundled skill is listed at top level
    assert (dst / "agents" / "reviewer.md").exists()


def test_plugin_uses_installed_version_not_an_old_cache_copy(env):
    env.plugin("devkit", "1.0.0")
    new = env.plugin("devkit", "1.2.0")
    env.register_plugins({"devkit@mkt": new})
    run(env)
    assert json.loads((env.agy / "plugins" / "devkit" / "plugin.json").read_text())["version"] == "1.2.0"


def test_disabled_plugin_is_not_synced(env):
    p = env.plugin("off", "1.0.0")
    env.register_plugins({"off@mkt": p}, enabled={"off@mkt": False})
    run(env)
    assert not (env.agy / "plugins" / "off").exists()


def test_users_standalone_skill_wins_over_plugin_skill_with_same_name(env):
    skill(env.claude / "skills", "helper", body="standalone")
    p = env.plugin("kit", "1.0.0", skills=("helper",))
    env.register_plugins({"kit@mkt": p})
    run(env)
    assert "standalone" in (env.agy / "skills" / "helper" / "SKILL.md").read_text()


def test_existing_config_json_settings_are_kept(env):
    write(env.agy / "config.json", json.dumps({"userSettings": {"theme": "dark"}, "plugins": {"mine": {"enabled": False}}}))
    p = env.plugin("kit", "1.0.0")
    env.register_plugins({"kit@mkt": p})
    run(env)
    cfg = json.loads((env.agy / "config.json").read_text())
    assert cfg["userSettings"] == {"theme": "dark"} and cfg["plugins"]["mine"] == {"enabled": False}


def test_removed_plugin_is_unregistered(env):
    p = env.plugin("kit", "1.0.0")
    env.register_plugins({"kit@mkt": p})
    run(env)
    env.register_plugins({})
    run(env)
    assert "kit" not in json.loads((env.agy / "config.json").read_text())["plugins"]
    assert not (env.agy / "plugins" / "kit").exists()


# ------------------------------------------------------------------ agents & MCP
def test_agent_frontmatter_is_converted(env):
    write(env.claude / "agents" / "reviewer.md",
          "---\nname: reviewer\ndescription: Reviews code\ntools: Read, Grep\nmodel: opus\ncolor: red\n---\nReview it.\n")
    run(env)
    text = (env.agy / "agents" / "reviewer.md").read_text()
    assert text.startswith("---\nname: reviewer\ndescription: Reviews code\n---\n")
    assert "model:" not in text and "Review it." in text and "Read, Grep" in text


def test_user_mcp_servers_are_added_without_touching_existing_ones(env):
    write(env.home / ".claude.json", json.dumps({"mcpServers": {
        "flow": {"type": "stdio", "command": "node", "args": ["index.js"]},
        "mine": {"type": "stdio", "command": "node", "args": ["claude.js"]}}}))
    write(env.agy / "mcp_config.json", json.dumps({"mcpServers": {"mine": {"command": "python", "args": ["agy.py"]}}}))
    r = run(env)
    servers = json.loads((env.agy / "mcp_config.json").read_text())["mcpServers"]
    assert servers["flow"]["command"] == "node" and servers["mine"]["args"] == ["agy.py"]
    assert ("skip", "mcp", "mine") in ops(r)


# ------------------------------------------------------------------ conversations
def test_conversations_become_readable_files_and_gemini_block(env):
    f = write(env.claude / "projects" / "C--work-demo" / "abcdef1234.jsonl",
              transcript_line("user", "Add login to the app", "2026-11-07T10:00:00Z")
              + transcript_line("assistant", "I added the login page and tests.", "2026-11-07T10:01:00Z"))
    write(env.agy / "GEMINI.md", "# My rules\nAlways be kind.\n")
    write(env.claude / "CLAUDE.md", "my claude rules\n")
    run(env)
    session = env.agy / "memory" / "claude2antigravity" / "sessions" / "c--work-demo" / "abcdef12.md"
    assert "Add login to the app" in session.read_text() and "I added the login page" in session.read_text()
    assert "Add login to the app" in (env.agy / "memory" / "claude2antigravity" / "INDEX.md").read_text()
    gem = (env.agy / "GEMINI.md").read_text()
    assert gem.startswith("# My rules\nAlways be kind.") and "CLAUDE2ANTIGRAVITY:START" in gem
    assert (env.claude / "CLAUDE.md").read_text() == "my claude rules\n"   # never touched
    # incremental: only new lines are read
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(transcript_line("user", "Now add logout", "2026-11-07T10:05:00Z"))
    run(env)
    assert "Now add logout" in session.read_text()
    cache = json.loads((env.app / "conversations.json").read_text())
    assert cache[str(f)]["offset"] == f.stat().st_size


def test_gemini_block_is_replaced_not_duplicated(env):
    write(env.claude / "projects" / "p" / "s.jsonl", transcript_line("user", "first", "2026-11-07T10:00:00Z"))
    run(env)
    with open(env.claude / "projects" / "p" / "s.jsonl", "a", encoding="utf-8") as fh:
        fh.write(transcript_line("user", "second", "2026-11-07T11:00:00Z"))
    run(env)
    assert (env.agy / "GEMINI.md").read_text().count("CLAUDE2ANTIGRAVITY:START") == 1


def test_excluded_projects_are_not_written(env):
    write(env.claude / "projects" / "secret" / "s.jsonl",
          transcript_line("user", "confidential plan", "2026-11-07T10:00:00Z", cwd="C:/work/secret-client"))
    run(env, settings={"exclude_projects": ["secret-client"]})
    assert "confidential" not in "".join(p.read_text() for p in env.agy.rglob("*.md"))


def test_command_noise_is_not_recorded(env):
    write(env.claude / "projects" / "p" / "s.jsonl",
          transcript_line("user", "<command-name>/clear</command-name>", "2026-11-07T10:00:00Z")
          + transcript_line("user", "real question", "2026-11-07T10:01:00Z"))
    run(env)
    text = (env.agy / "memory" / "claude2antigravity" / "INDEX.md").read_text()
    assert "real question" in text and "/clear" not in text


# ------------------------------------------------------------------ uninstall & CLI
def test_uninstall_removes_only_our_items(env):
    skill(env.claude / "skills", "a")
    skill(env.agy / "skills", "mine")
    write(env.claude / "projects" / "p" / "s.jsonl", transcript_line("user", "hi", "2026-11-07T10:00:00Z"))
    write(env.agy / "GEMINI.md", "# rules\n")
    run(env)
    sync.uninstall(env.homes())
    assert not (env.agy / "skills" / "a").exists() and (env.agy / "skills" / "mine").exists()
    assert (env.agy / "GEMINI.md").read_text() == "# rules\n"


def test_cli_sync_and_pro_stub(env, capsys):
    skill(env.claude / "skills", "a")
    args = ["--claude-home", str(env.claude), "--antigravity-home", str(env.agy), "--app-home", str(env.app), "--no-wsl"]
    assert cli.main(["sync", *args]) == 0
    assert (env.agy / "skills" / "a").exists()
    if not __import__("claude2antigravity").is_pro():
        assert cli.main(["watch"]) == 3
        assert "agensi.io" in capsys.readouterr().out


def test_missing_claude_home_is_reported(tmp_path):
    args = ["--claude-home", str(tmp_path / "nope"), "--antigravity-home", str(tmp_path / "agy"),
            "--app-home", str(tmp_path / "app")]
    assert cli.main(["sync", *args]) in (0, 2)
    assert os.path.isdir(tmp_path / "app")


def test_busy_folder_is_updated_in_place(env, monkeypatch):
    """Windows cannot rename a folder another program holds open; the sync must still update it."""
    d = skill(env.claude / "skills", "busy", extra={"a.py": "1", "old.py": "x"})
    run(env)
    (d / "a.py").write_text("2")
    (d / "old.py").unlink()
    import claude2antigravity.util as u

    real_replace = u.os.replace

    def locked(src, dst, *a, **k):  # only the skill folder is "held open by another program"
        if str(dst).endswith("busy"):
            raise PermissionError("in use")
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(u.os, "replace", locked)
    monkeypatch.setattr(u.time, "sleep", lambda s: None)
    run(env)
    dst = env.agy / "skills" / "busy"
    assert (dst / "a.py").read_text() == "2" and not (dst / "old.py").exists()
    assert not (env.agy / "skills" / "busy.c2a-tmp").exists()


def test_wsl_homes_are_rechecked(env, monkeypatch):
    from claude2antigravity import paths
    homes = env.homes()
    homes.auto_wsl = True
    fake = env.home / "wsl" / ".claude"
    fake.mkdir(parents=True)
    monkeypatch.setattr(paths, "running_wsl_homes", lambda: [fake])
    assert homes.refresh_wsl() and homes.claude == [env.claude, fake]
    assert not homes.refresh_wsl()  # no change the second time
    monkeypatch.setattr(paths, "running_wsl_homes", lambda: [])
    assert homes.refresh_wsl() and homes.claude == [env.claude]


def test_helper_programs_never_open_a_window():
    """Every program the tool starts must pass the no-window flag on Windows (no console flash)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "skills" / "claude2antigravity" / "scripts" / "claude2antigravity"
    for f in root.rglob("*.py"):
        for m in re.finditer(r"subprocess\.run\((.*?)\)\n", f.read_text(encoding="utf-8"), re.S):
            assert "NO_WINDOW" in m.group(1), f"{f.name}: subprocess.run without NO_WINDOW"


def test_empty_antigravity_config_files_are_handled_quietly(env, caplog):
    """A fresh Antigravity install can have 0-byte mcp_config.json / config.json: treat them as empty."""
    write(env.agy / "mcp_config.json", "")
    write(env.agy / "config.json", "")
    write(env.home / ".claude.json", json.dumps({"mcpServers": {"flow": {"type": "stdio", "command": "node"}}}))
    p = env.plugin("kit", "1.0.0")
    env.register_plugins({"kit@mkt": p})
    run(env)
    assert json.loads((env.agy / "mcp_config.json").read_text())["mcpServers"]["flow"]["command"] == "node"
    assert json.loads((env.agy / "config.json").read_text())["plugins"]["kit"] == {"enabled": True}
    assert "Expecting value" not in caplog.text


def test_broken_antigravity_config_is_never_overwritten(env):
    bad = '{"mcpServers": {"mine": {"command": "x"}},  // my notes\n}'
    write(env.agy / "mcp_config.json", bad)
    write(env.agy / "config.json", bad)
    write(env.home / ".claude.json", json.dumps({"mcpServers": {"flow": {"type": "stdio", "command": "node"}}}))
    p = env.plugin("kit", "1.0.0")
    env.register_plugins({"kit@mkt": p})
    run(env)
    assert (env.agy / "mcp_config.json").read_text() == bad
    assert (env.agy / "config.json").read_text() == bad
