"""Turn real command output (a text file) into a terminal-style SVG for the README proofs.

    python tools/terminal_svg.py output.txt docs/assets/proof-x.svg --title "claude2agy doctor"

The text is the unedited output of the command; only colours are added (OK/PASS green, WARN/FAIL red).
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

COLORS = [("FAIL", "#F87171"), ("WARN", "#FBBF24"), ("OK", "#4ADE80"), ("PASS", "#4ADE80"), ("passed", "#4ADE80"),
          ("All good", "#4ADE80"), ("Clean", "#4ADE80"), ("$ ", "#A78BFA")]


def color_for(line: str) -> str:
    for word, col in COLORS:
        if word in line:
            return col
    return "#D1D5DB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--title", default="terminal")
    a = ap.parse_args()
    lines = a.src.read_text(encoding="utf-8").rstrip().splitlines()
    width = max(640, min(1200, 8.2 * max((len(x) for x in lines), default=40) + 48))
    height = 56 + 20 * len(lines) + 20
    rows = []
    for i, line in enumerate(lines):
        rows.append(f'<text x="24" y="{66 + i * 20}" fill="{color_for(line)}" xml:space="preserve">'
                    f'{html.escape(line)}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height}" viewBox="0 0 {width:.0f} {height}">
<rect width="100%" height="100%" rx="12" fill="#0D1117"/>
<rect width="100%" height="34" rx="12" fill="#161B22"/><rect y="22" width="100%" height="12" fill="#161B22"/>
<circle cx="20" cy="17" r="6" fill="#FF5F57"/><circle cx="40" cy="17" r="6" fill="#FEBC2E"/><circle cx="60" cy="17" r="6" fill="#28C840"/>
<text x="{width / 2:.0f}" y="22" text-anchor="middle" fill="#8B949E" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">{html.escape(a.title)}</text>
<g font-family="Cascadia Mono, Consolas, Menlo, monospace" font-size="13.5">
{chr(10).join(rows)}
</g></svg>
'''
    a.out.write_text(svg, encoding="utf-8")
    print(f"wrote {a.out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
