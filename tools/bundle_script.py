"""Fold a set of Python modules into ONE self-contained script (for Agensi, where each script runs alone).

    python tools/bundle_script.py --out c2a_sync.py --entry entry.py mod1.py mod2.py ...

How it works (plain text, no exec/eval, so reviewers can read the result):
- every module's code is copied in order, with its relative/sibling imports removed;
- `from __future__` lines are moved to the top;
- for every bundled module that the code uses as `module.name`, a small namespace object with that
  module's top-level names is created at the end, so `memory.write_all(...)` keeps working;
- the build fails if two modules define the same top-level name (that would silently break the script).
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REL_IMPORT = re.compile(r"^\s*from\s+\.+[\w.]*\s+import\s+")


def top_level_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(n.name)
        elif isinstance(n, ast.Assign):
            names += [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.append(n.target.id)
    return names


def strip_imports(src: str, local: set[str]) -> tuple[str, list[str]]:
    """Remove relative imports and `import X`/`from X import` of bundled sibling modules."""
    out: list[str] = []
    future: list[str] = []
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        sibling = re.match(r"^\s*(from\s+(\w+)\s+import|import\s+(\w+)\s*$)", line)
        is_sibling = bool(sibling and (sibling.group(2) in local or sibling.group(3) in local))
        if s.startswith("from __future__"):
            future.append(s)
        elif REL_IMPORT.match(line) or is_sibling:
            indent = line[: len(line) - len(line.lstrip())]
            block = line
            while "(" in block and ")" not in block and i + 1 < len(lines):  # multi-line import
                i += 1
                block += lines[i]
            if out and out[-1].rstrip().endswith(":"):
                out.append(indent + "pass  # (bundled import removed)")
        else:
            out.append(line)
        i += 1
    return "\n".join(out), future


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--entry", required=True, type=Path, help="code that runs the script (has main())")
    ap.add_argument("--title", default="", help="first docstring line of the bundled script")
    ap.add_argument("modules", nargs="+", type=Path)
    a = ap.parse_args()

    local = {m.stem for m in a.modules}
    owner: dict[str, str] = {}
    parts: list[str] = []
    futures: set[str] = set()
    namespaces: dict[str, list[str]] = {}
    for m in a.modules:
        src = m.read_text(encoding="utf-8")
        names = top_level_names(ast.parse(src))
        for n in names:
            if n in owner and not n.startswith("__"):
                print(f"name clash: {n} is defined in {owner[n]} and {m.stem}")
                return 1
            owner[n] = m.stem
        code, fut = strip_imports(src, local)
        futures |= set(fut)
        parts.append(f"# {'=' * 20} {m.name} {'=' * 20}\n{code.strip()}\n")
        namespaces[m.stem] = [n for n in names if not n.startswith("__")]

    entry_src = a.entry.read_text(encoding="utf-8")
    entry_code, fut = strip_imports(entry_src, local)
    futures |= set(fut)
    body = "\n\n".join(parts) + "\n" + entry_code
    used = {m for m in namespaces if re.search(rf"(?<![\w.]){m}\.\w", body) and m not in owner}
    ns_lines = [f"{m} = _Namespace(" + ", ".join(f"{n}={n}" for n in namespaces[m]) + ")" for m in sorted(used)]

    header = [f'"""{a.title or a.out.stem} - self-contained script (built from the Claude2Antigravity modules)."""',
              *sorted(futures), "", "import types as _types", "",
              "_Namespace = _types.SimpleNamespace", ""]
    entry_main = entry_code.find('if __name__ == "__main__":')
    if entry_main == -1:
        print("entry file needs an `if __name__ == \"__main__\":` block")
        return 1
    final = ("\n".join(header) + "\n" + "\n\n".join(parts) + "\n"
             + entry_code[:entry_main] + "\n# module namespaces used as `module.name`\n" + "\n".join(ns_lines)
             + "\n\n\n" + entry_code[entry_main:])
    a.out.write_text(final.rstrip() + "\n", encoding="utf-8", newline="\n")
    compile(final, str(a.out), "exec")  # syntax check only (nothing is executed)
    print(f"wrote {a.out} ({len(final.encode()) // 1024} KB, {len(a.modules)} modules, namespaces: {sorted(used)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
