"""Build the Agensi Pro zip: the Community skill folder + the private Pro files, then a security pre-scan.

    python tools/build_pro_zip.py --pro ../claude-to-antigravity-pro --out ~/Downloads/claude-to-antigravity-pro.zip

The private folder (never committed) holds SKILL.md (Pro version) and scripts/claude2antigravity/pro/*.py.
The zip has SKILL.md at its root, LF line endings, no caches. It is written only if the pre-scan
(agensi-review skill: agensi_scan.py) reports zero findings.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "claude2antigravity"
TEXT_EXT = {".md", ".py", ".json", ".txt", ".toml", ".yml", ".yaml"}
DEFAULT_SCANNER = Path.home() / ".claude" / "skills" / "agensi-review" / "scripts" / "agensi_scan.py"


def collect(base: Path) -> dict[str, Path]:
    out = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base).as_posix()
        if p.is_file() and "__pycache__" not in rel and ".egg-info" not in rel \
                and not any(x.startswith(".") for x in rel.split("/")) and not rel.startswith("tests/"):
            out[rel] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pro", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scanner", type=Path, default=DEFAULT_SCANNER)
    a = ap.parse_args()
    files = collect(SKILL)
    pro = collect(a.pro)
    stray = [r for r in pro if r not in files and not r.startswith("scripts/claude2antigravity/pro/")]
    if stray:
        print("Pro files outside SKILL.md / scripts/claude2antigravity/pro/:", *stray, sep="\n  ")
        return 1
    files.update(pro)
    if not a.scanner.exists():
        print(f"security scanner not found: {a.scanner}")
        return 1
    spec = importlib.util.spec_from_file_location("agensi_scan", a.scanner)
    scanner = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["agensi_scan"] = scanner
    spec.loader.exec_module(scanner)  # type: ignore[union-attr]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_zip = Path(tmp) / "pro.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, src in files.items():
                data = src.read_bytes()
                if src.suffix.lower() in TEXT_EXT:
                    data = data.replace(b"\r\n", b"\n")
                z.writestr(rel, data)
        findings = scanner.scan(tmp_zip)
        points, status = scanner.score(findings)
        for f in findings:
            print(f"{f.severity.upper()} [{f.check}] {f.file}:{f.line} {f.why}\n    > {f.snippet}")
        print(f"pre-scan: {points}/100 ({status}), {len(findings)} finding(s)")
        if findings:
            print("zip NOT written")
            return 1
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(tmp_zip.read_bytes())
    print(f"wrote {a.out} ({len(files)} files, {len(pro)} from Pro)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
