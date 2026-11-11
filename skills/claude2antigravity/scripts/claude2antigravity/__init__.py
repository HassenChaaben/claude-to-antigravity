"""Claude2Antigravity - bring your Claude Code skills, plugins, agents, MCP servers and conversations into
Google Antigravity, so you can keep working when Claude hits its usage limit.

Community edition (MIT): manual `claude2agy sync`. Pro edition (Agensi): 24/7 live sync and extras.
"""
from __future__ import annotations

import importlib.util

__version__ = "1.0.2"
PRO_URL = "https://www.agensi.io/skills/claude2antigravity"


def is_pro() -> bool:
    """True when the Pro modules are installed next to this package."""
    try:
        return importlib.util.find_spec("claude2antigravity.pro") is not None
    except (ImportError, ValueError):
        return False


EDITION = "Pro" if is_pro() else "Community"
