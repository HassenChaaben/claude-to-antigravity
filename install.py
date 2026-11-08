"""Install Claude2Antigravity (Community edition).

    python install.py                 # skill for Claude Code + Antigravity, then a first sync preview
    python install.py --target claude # or: antigravity, both (default)
    python install.py --pip           # also install the `claude2agy` command with pip (user site)
    python install.py --sync          # run the first sync right away

Nothing is downloaded; the skill folder is copied from this repository.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL = ROOT / "skills" / "claude2antigravity"


def copy_skill(dest_root: Path) -> Path:
    dst = dest_root / "claude2antigravity"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SKILL, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["claude", "antigravity", "both"], default="both")
    ap.add_argument("--pip", action="store_true", help="pip install --user . (adds the claude2agy command)")
    ap.add_argument("--sync", action="store_true", help="run the first sync now (otherwise only a preview)")
    a = ap.parse_args()
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is needed.")
        return 1
    home = Path.home()
    installed = []
    if a.target in ("claude", "both"):
        installed.append(copy_skill(home / ".claude" / "skills"))
    if a.target in ("antigravity", "both"):
        installed.append(copy_skill(home / ".gemini" / "config" / "skills"))
    for p in installed:
        print(f"  installed skill: {p}")
    if a.pip:
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", str(ROOT)], check=False)
    runner = installed[0] / "scripts" / "c2a.py"
    print("\nPreview of the first sync (nothing is changed yet):")
    subprocess.run([sys.executable, str(runner), "sync", "--dry-run"], check=False)
    if a.sync:
        subprocess.run([sys.executable, str(runner), "sync"], check=False)
    else:
        print(f"\nRun the sync with:\n  python \"{runner}\" sync")
        print("Or ask your agent: \"sync my Claude skills to Antigravity\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
