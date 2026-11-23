#!/usr/bin/env python3
"""Public-edition guard for the crossroads corpus.

validate_cards.py is the depth gate (section size, generated ledger, edges,
evidence vocabulary). This guard covers the classes that gate does not:

  1. LEAK  -- no internal hostnames, package trees, workspace paths, or
     confidentiality footers anywhere in shipped text.
  2. ROT   -- every relative markdown link resolves on disk.
  3. REPRODUCIBILITY -- every test named in a card's Verification section
     exists in that card's tests/ source, so every [executed] claim maps to
     something a reader can actually run. With --run-tests, runs them.

Exit 0 if clean, 1 otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

LEAK = re.compile(
    r"code\.amazon|@amzn|\bmwinit\b|\bmidway\b|corp\.amazon|amazon\.dev"
    r"|[a-z0-9-]+-kb/|\bASCB/|Amazon Confidential|\bSIM-T\b|git\.amazon",
    re.IGNORECASE,
)
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")
TEST_NAME = re.compile(r"`(test_[a-z0-9_]+)`")


def main() -> int:
    run_tests = "--run-tests" in sys.argv
    problems: list[str] = []

    shipped = [p for p in HERE.rglob("*")
               if p.is_file() and p.suffix in {".md", ".json", ".py"}
               and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]

    for f in shipped:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if LEAK.search(line) and f.name != "check_public_edition.py":
                problems.append(f"LEAK {f.relative_to(HERE)}:{n}: {line.strip()[:100]}")

    for f in HERE.rglob("*.md"):
        if "__pycache__" in f.parts:
            continue
        for target in LINK.findall(f.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "private:")):
                continue
            if not (f.parent / target).resolve().exists():
                problems.append(f"ROT  {f.relative_to(HERE)}: broken link -> {target}")

    for card_dir in sorted(HERE.glob("cards/PC-*/")):
        card = card_dir / "CARD.md"
        tests_src = "".join(
            p.read_text(encoding="utf-8") for p in (card_dir / "tests").glob("*.py")
        )
        for name in set(TEST_NAME.findall(card.read_text(encoding="utf-8"))):
            if name not in tests_src:
                problems.append(
                    f"REPRO {card_dir.name}: card names `{name}` but no such test ships"
                )
        if run_tests:
            r = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                cwd=card_dir, capture_output=True, text=True,
            )
            print(f"tests {'pass' if r.returncode == 0 else 'FAIL'}: {card_dir.name}")
            if r.returncode != 0:
                problems.append(f"REPRO {card_dir.name}: test suite fails")

    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        checked = "leak, links, executed->test mapping" + (" + suites" if run_tests else "")
        print(f"OK   {len(shipped)} shipped files clean ({checked})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
