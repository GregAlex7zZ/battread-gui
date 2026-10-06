# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Require explanatory entry points for every maintained Python construct.

Run from any directory. Presence checks supplement review of documentation
quality, usage and constraints as required by CONTRIBUTING.md.
"""

import ast
from pathlib import Path


def main() -> int:
    """Check all modules, classes and functions; return one for missing docstrings."""
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    count = 0
    for directory in ("src", "tests", "tools", "packaging"):
        for path in sorted((root / directory).rglob("*.py")):
            count += 1
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ) and not ast.get_docstring(node):
                    failures.append(
                        f"{path.relative_to(root)}:{getattr(node, 'lineno', 1)}: "
                        f"missing documentation for {getattr(node, 'name', '<module>')}"
                    )
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Documentation present in all {count} maintained Python files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
