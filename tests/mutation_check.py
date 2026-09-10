#!/usr/bin/env python3
"""Prove the report-truth gate's tests actually defend it.

    python3 tests/mutation_check.py

For each check in gate/report_truth.py — and for the two guards that keep it from
punishing an honest confession — delete it, run the suite, and require the suite
to go RED. A test that still passes with the mechanism removed is not testing the
mechanism; it is decoration that reports green forever, which is the precise
failure this whole repo is about.

Exit 0 when every mutant was killed; 1 when any survived; 2 when this script
itself could not run (same contract as the gate).

The file is restored from an IN-MEMORY copy in a `finally`, never with
`git checkout`: this repo may hold uncommitted work, and a checkout to undo a
mutation would take that work with it. The restore is then verified — a mutation
runner that leaves the file mutated has done more harm than the bug it hunted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "gate" / "report_truth.py"

# (name, the exact source to neuter, what to put in its place)
#
# The guards are mutated too, and on purpose. Deleting CHECK 5 lets a lie
# through; deleting the negation guard makes the gate fire on "los tests NO
# pasan" — an agent that gets punished for confessing learns to stop confessing,
# so a hole in the guard is as dangerous as a hole in the check.
MUTANTS = [
    ("CHECK 1 fabricated-path", "check_paths(report, findings)", ""),
    ("CHECK 2 unknown-symbol", "check_symbols(report, haystack, findings)", ""),
    ("CHECK 3 unbacked-number", "check_numbers(report, receipts, findings)", ""),
    ("CHECK 4 unbacked-error-block", "check_error_blocks(report, receipts, findings)", ""),
    ("CHECK 5 unbacked-green",
     "check_green_claims(report, receipts, newest, newest_file, findings)", ""),
    ("CHECK 6 contradicted-green",
     "check_contradicted_green(report, receipts, findings)", ""),
    ("corrupt-receipt reporting", "findings.append(_corrupt(n, exc))", ""),
    ("guard: negation (confessing is not fabricating)",
     "if negated(folded, m.start()):", "if False:"),
    ("guard: conditional (a plan is not a verdict)",
     "if cond and cond.start() < m.start():", "if False:"),
    ("guard: the report is not its own evidence",
     "def tree_text(root: Path, exclude: Path | None = None) -> str:",
     "def tree_text(root: Path, exclude: Path | None = None) -> str:\n    exclude = None"),
]


def run_suite() -> bool:
    """True when the suite is green."""
    r = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
                        "-x", "--no-header"],
                       capture_output=True, text=True, cwd=ROOT, check=False)
    return r.returncode == 0


def main() -> int:
    original = GATE.read_text(encoding="utf-8")

    if not run_suite():
        print("the suite is RED before any mutation — fix that first", file=sys.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, call, replacement in MUTANTS:
            if original.count(call) != 1:
                print(f"  ?? {name}: {original.count(call)} occurrence(s) of the "
                      f"target — the mutation list is stale")
                survivors.append(f"{name} (stale)")
                continue
            GATE.write_text(original.replace(call, replacement or "pass", 1),
                            encoding="utf-8")
            if run_suite():
                print(f"  SURVIVED  {name} — removed it and the suite stayed green")
                survivors.append(name)
            else:
                print(f"  killed    {name}")
    finally:
        GATE.write_text(original, encoding="utf-8")

    if GATE.read_text(encoding="utf-8") != original:
        print("gate file was NOT restored cleanly", file=sys.stderr)
        return 2

    if survivors:
        print(f"\n{len(survivors)} mutant(s) survived: {', '.join(survivors)}")
        return 1
    print(f"\nall {len(MUTANTS)} mutants killed; gate restored and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
