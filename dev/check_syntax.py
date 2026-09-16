#!/usr/bin/env python3
"""Parse-check the integration on an interpreter older than Home Assistant's.

Home Assistant requires Python 3.13; this box only has 3.8. `from __future__
import annotations` already makes the modern annotation syntax parseable, so
the only construct the old parser chokes on is PEP 695 (`type X = ...`), which
is rewritten to a plain assignment before parsing. This checks syntax only --
hassfest in CI is still the real gate.
"""

from __future__ import annotations

import ast
import pathlib
import re

TYPE_ALIAS = re.compile(r"^type\s+(\w+)\s*=", re.MULTILINE)


def main() -> int:
    """Parse every integration module and report failures."""
    root = pathlib.Path("custom_components/techem")
    failed = False

    for path in sorted(root.rglob("*.py")):
        source = TYPE_ALIAS.sub(r"\1 =", path.read_text())
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as err:
            failed = True
            print(f"FAIL {path}:{err.lineno} {err.msg}")
        else:
            print(f"ok   {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
