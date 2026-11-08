"""Run Claude2Antigravity straight from the skill folder (no pip install needed).

    python scripts/c2a.py sync
    python scripts/c2a.py status
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude2antigravity.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
