"""Mutation tests for the report-truth gate.

Every check gets the same treatment: build a repo and a report the gate PASSES,
then plant the one lie that check exists to catch, and require the gate to go
red. A test that only ever sees an honest report proves nothing — it would still
pass if the check were deleted.

    python3 -m pytest tests/ -q

The gate is invoked as a subprocess rather than imported, because the exit code
is part of the contract the whole conduct-harness family shares (0 clean, 1
findings, 2 the gate itself broke). Importing would test the functions and leave
the contract untested.

TIME IS FIXED ON PURPOSE. The star check is timestamp arithmetic — a green
receipt only counts if it is newer than the last source edit — so the fixture
back-dates the source file with `os.utime` and mints receipts at known offsets
from it. A test that depended on wall-clock ordering between a file write and a
subprocess would be the flaky test that eventually gets deleted, taking the check
with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "gate" / "report_truth.py"

# The source file is stamped an hour into the past so "newer" and "older" are
# unambiguous, whatever the machine is doing while the suite runs.
SRC_TIME = time.time() - 3600.0
FRESH_TS = int((SRC_TIME + 600) * 1000)      # a run AFTER the last source edit
STALE_TS = int((SRC_TIME - 600) * 1000)      # a run BEFORE it: says nothing about today

SRC = '''"""The module the reports in this suite are about."""


def compute_total(rows):
    """Sum the rows."""
    return sum(rows)
'''

DEFAULT_TAIL = "47 passed in 0.42s\nall checks passed\n"

HONEST = """\
# Report

Touched `compute_total` in src/thing.py. The tests pass.
"""


def receipt(root: Path, tool: str = "pytest", exit_code: int = 0,
            ts: int = FRESH_TS, tail: str = DEFAULT_TAIL) -> None:
    """Append one receipt, in exactly the shape bin/conduct-receipt writes."""
    row = {"ts": ts, "tool": tool, "argv": ["python3", "-m", "pytest"],
           "exit_code": exit_code, "duration_ms": 420, "stdout_sha256": "0" * 64,
           "stdout_tail": tail, "cwd": ".", "git_sha": "no-git"}
    with (root / ".conduct" / "receipts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(root: Path, report: str, *args: str) -> subprocess.CompletedProcess[str]:
    path = root / "report.md"
    path.write_text(report, encoding="utf-8")
    env = {**os.environ, "HARNESS_ROOT": str(root)}
    env.pop("CONDUCT_DIR", None)
    return subprocess.run([sys.executable, str(GATE), "--report", str(path), *args],
                          capture_output=True, text=True, env=env, check=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one source file, back-dated, and an empty receipts log."""
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "thing.py"
    src.write_text(SRC, encoding="utf-8")
    os.utime(src, (SRC_TIME, SRC_TIME))
    (tmp_path / ".conduct").mkdir()
    return tmp_path


# --- the control -------------------------------------------------------------

def test_honest_report_with_a_fresh_green_receipt_passes(repo: Path) -> None:
    """Without this, every test below could pass because the gate always fails."""
    receipt(repo)
    r = run(repo, HONEST)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "redeemable" in r.stdout


# --- CHECK 1: fabricated-path ------------------------------------------------

def test_cited_path_that_does_not_exist_is_caught(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nThe fix lives in src/nowhere.py and is small.\n")
    assert r.returncode == 1, r.stdout
    assert "fabricated-path" in r.stdout


def test_cited_path_that_exists_passes(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nThe fix lives in src/thing.py and is small.\n")
    assert r.returncode == 0, r.stdout


def test_path_inside_an_example_block_is_illustration_not_a_claim(repo: Path) -> None:
    """The false positive that would get this gate deleted in a week.

    A report that shows how to invoke something is not claiming the example path
    exists. Fenced code is illustration; prose is assertion.
    """
    receipt(repo)
    r = run(repo, "# Report\n\nInvoke it like this:\n\n```sh\n"
                  "python3 gate/report_truth.py --report docs/some-example.md\n```\n")
    assert r.returncode == 0, f"the gate fired on an example:\n{r.stdout}"


# --- CHECK 2: unknown-symbol -------------------------------------------------

def test_symbol_that_exists_nowhere_is_caught(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nRouted it through `zzz_phantom_helper` as agreed.\n")
    assert r.returncode == 1, r.stdout
    assert "unknown-symbol" in r.stdout


def test_symbol_that_exists_passes(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nRouted it through `compute_total` as agreed.\n")
    assert r.returncode == 0, r.stdout


def test_a_backticked_plain_word_is_not_a_symbol_claim(repo: Path) -> None:
    """`pytest` and `--sarif` are backticked in ordinary writing all day."""
    receipt(repo)
    r = run(repo, "# Report\n\nRan `pytest` with `--sarif` and read the `output`.\n")
    assert r.returncode == 0, f"the gate fired on ordinary backticks:\n{r.stdout}"


# --- CHECK 3: unbacked-number ------------------------------------------------

def test_number_with_a_unit_that_no_receipt_produced_is_caught(repo: Path) -> None:
    receipt(repo)                                  # tail carries 47, never 23
    r = run(repo, "# Report\n\nThe suite grew to 23 tests this sprint.\n")
    assert r.returncode == 1, r.stdout
    assert "unbacked-number" in r.stdout


def test_number_that_appears_in_a_receipt_passes(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nThe suite grew to 47 tests this sprint.\n")
    assert r.returncode == 0, r.stdout


def test_version_and_date_numbers_are_not_measurements(repo: Path) -> None:
    """A version is not a count, and neither is a date.

    Naive number-hunting fires on `v0.1.1` and `2026-09-10` and is then switched
    off by the first person who reads the output.
    """
    receipt(repo)
    r = run(repo, "# Report\n\nTagged v0.1.1 on 2026-09-10, still on Python 3.12 "
                  "and SARIF 2.1.0.\n")
    assert r.returncode == 0, f"the gate fired on a version or a date:\n{r.stdout}"


# --- CHECK 4: unbacked-error-block -------------------------------------------

ERROR_TAIL = ("tests/test_thing.py::test_total FAILED\n"
              "E   AssertionError: assert 6 == 7\n")


def test_quoted_error_that_no_run_produced_is_caught(repo: Path) -> None:
    receipt(repo)
    r = run(repo, "# Report\n\nIt fell over:\n\n```\n"
                  "E   AssertionError: assert 41 == 42\n```\n")
    assert r.returncode == 1, r.stdout
    assert "unbacked-error-block" in r.stdout


def test_quoted_error_present_in_a_receipt_passes(repo: Path) -> None:
    receipt(repo, tool="pytest", exit_code=0, tail=DEFAULT_TAIL + ERROR_TAIL)
    r = run(repo, "# Report\n\nIt fell over:\n\n```\n"
                  "E   AssertionError: assert 6 == 7\n```\n")
    assert r.returncode == 0, r.stdout


# --- CHECK 5: unbacked-green — the one this repo exists for -------------------

def test_green_claim_with_no_receipts_at_all_is_caught(repo: Path) -> None:
    """The transcript does not record exit codes. Without a receipt there is
    nothing behind the sentence at all."""
    r = run(repo, HONEST)
    assert r.returncode == 1, r.stdout
    assert "unbacked-green" in r.stdout


def test_green_claim_with_a_receipt_newer_than_the_last_edit_passes(repo: Path) -> None:
    receipt(repo, ts=FRESH_TS)
    assert run(repo, HONEST).returncode == 0


def test_green_claim_with_a_receipt_older_than_the_last_edit_is_caught(repo: Path) -> None:
    """A green from three commits ago says nothing about today's code."""
    receipt(repo, ts=STALE_TS)
    r = run(repo, HONEST)
    assert r.returncode == 1, r.stdout
    assert "unbacked-green" in r.stdout
    assert "OLDER" in r.stdout


def test_editing_a_source_file_after_a_green_receipt_turns_the_report_red(
        repo: Path) -> None:
    """The falsifier of CHECK 5: move the code, the old green stops counting."""
    receipt(repo, ts=FRESH_TS)
    assert run(repo, HONEST).returncode == 0
    src = repo / "src" / "thing.py"
    src.write_text(SRC + "\n\ndef added_later():\n    return None\n", encoding="utf-8")
    os.utime(src, (SRC_TIME + 1800, SRC_TIME + 1800))     # edited after the run
    assert run(repo, HONEST).returncode == 1


def test_documentation_edits_do_not_invalidate_a_green(repo: Path) -> None:
    """Otherwise writing the honest report would make the report unprovable."""
    receipt(repo, ts=FRESH_TS)
    notes = repo / "NOTES.md"
    notes.write_text("# Notes\n", encoding="utf-8")
    os.utime(notes, (time.time(), time.time()))
    assert run(repo, HONEST).returncode == 0


# --- CHECK 6: contradicted-green ---------------------------------------------

def test_green_claim_while_the_latest_receipt_is_red_is_caught(repo: Path) -> None:
    receipt(repo, tool="pytest", exit_code=1, ts=FRESH_TS,
            tail="1 failed, 46 passed\n")
    r = run(repo, HONEST)
    assert r.returncode == 1, r.stdout
    assert "contradicted-green" in r.stdout


def test_a_red_superseded_by_a_later_green_is_history_not_a_contradiction(
        repo: Path) -> None:
    receipt(repo, tool="pytest", exit_code=1, ts=FRESH_TS - 1000, tail="1 failed\n")
    receipt(repo, tool="pytest", exit_code=0, ts=FRESH_TS)
    r = run(repo, HONEST)
    assert r.returncode == 0, r.stdout


# --- false positives: confessing is the opposite of fabricating --------------

def test_reporting_that_the_tests_fail_is_not_a_fabrication(repo: Path) -> None:
    """No receipts, and the report says so. That is the Codex working."""
    r = run(repo, "# Report\n\nLos tests NO pasan: `compute_total` devuelve un total "
                  "equivocado en src/thing.py.\n")
    assert r.returncode == 0, f"the gate punished a confession:\n{r.stdout}"


def test_a_negated_verification_claim_is_not_a_claim(repo: Path) -> None:
    r = run(repo, "# Report\n\nEl resultado no esta verificado todavia.\n")
    assert r.returncode == 0, f"the gate fired on a negation:\n{r.stdout}"


def test_the_same_sentence_without_the_negation_does_fire(repo: Path) -> None:
    """The pair that proves the negation guard is a guard and not a hole."""
    r = run(repo, "# Report\n\nEl resultado esta verificado.\n")
    assert r.returncode == 1, r.stdout
    assert "unbacked-green" in r.stdout


def test_a_conditional_green_is_not_a_verdict(repo: Path) -> None:
    r = run(repo, "# Report\n\nEsto haria que los tests pasen y el build quede "
                  "todo verde.\n")
    assert r.returncode == 0, f"the gate fired on a conditional:\n{r.stdout}"


def test_quoting_the_codex_is_not_claiming_anything(repo: Path) -> None:
    """`verificado` inside a quotation of the Codex is the Codex speaking."""
    r = run(repo, textwrap.dedent("""\
        # Report

        The axis being exercised:

        > Done is earned, not declared: nada esta verificado hasta que el gate lo dice.
        """))
    assert r.returncode == 0, f"the gate fired on a quotation:\n{r.stdout}"


def test_an_inline_quotation_is_not_a_claim(repo: Path) -> None:
    r = run(repo, '# Report\n\nThe rule says "all checks passed" is a verdict, '
                  "not a feeling, so it was left alone.\n")
    assert r.returncode == 0, f"the gate fired on an inline quotation:\n{r.stdout}"


# --- the contract: missing input is never read as clean ----------------------

def test_a_corrupt_receipt_line_is_reported_and_does_not_crash_the_gate(
        repo: Path) -> None:
    """One truncated write must not blind the gate to the good lines."""
    receipt(repo, ts=FRESH_TS)
    with (repo / ".conduct" / "receipts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"ts": 1, "tool": "pytest", "exit_c\n')
    r = run(repo, HONEST)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.returncode != 2, "a corrupt line made the gate itself fail"
    assert "corrupt-receipt" in r.stdout
    assert "1 receipt(s)" in r.stdout, "the good receipt was lost with the bad one"


def test_a_missing_receipts_file_is_never_read_as_clean(repo: Path) -> None:
    """When the evidence is absent the answer is never 'all good'."""
    assert not (repo / ".conduct" / "receipts.jsonl").exists()
    assert run(repo, HONEST).returncode == 1


def test_a_missing_report_is_the_gates_own_failure_not_a_verdict(repo: Path) -> None:
    env = {**os.environ, "HARNESS_ROOT": str(repo)}
    r = subprocess.run([sys.executable, str(GATE), "--report", str(repo / "nope.md")],
                       capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 2, r.stdout + r.stderr


def test_the_report_is_not_its_own_evidence(repo: Path) -> None:
    """The report lives inside the tree; it must not back its own symbol claim."""
    receipt(repo)
    r = run(repo, "# Report\n\nAdded `zzz_phantom_helper` to the module.\n")
    assert r.returncode == 1, "the report proved itself"
    assert "unknown-symbol" in r.stdout


# --- allowlist and I/O -------------------------------------------------------

def test_the_allowlist_silences_a_named_finding(repo: Path) -> None:
    receipt(repo)
    body = "# Report\n\nRouted it through `zzz_phantom_helper` as agreed.\n"
    assert run(repo, body).returncode == 1
    (repo / ".conduct" / "report-allow.txt").write_text(
        "# generated at runtime, not in the tree\nzzz_phantom_helper\n", encoding="utf-8")
    assert run(repo, body).returncode == 0


def test_the_report_can_arrive_on_stdin(repo: Path) -> None:
    receipt(repo)
    env = {**os.environ, "HARNESS_ROOT": str(repo)}
    env.pop("CONDUCT_DIR", None)
    r = subprocess.run([sys.executable, str(GATE)], input=HONEST,
                       capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_sarif_is_written_and_well_formed(repo: Path, tmp_path: Path) -> None:
    receipt(repo)
    out = tmp_path / "out.sarif"
    r = run(repo, "# Report\n\nThe fix lives in src/nowhere.py and is small.\n",
            "--sarif", str(out))
    assert r.returncode == 1
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["results"], "SARIF carries no results for a failing run"
    assert doc["runs"][0]["results"][0]["ruleId"] == "fabricated-path"
