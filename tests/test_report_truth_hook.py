"""Tests for the live hook, hooks/report-truth-at-stop.py.

A hand-back that claims more than the tree and the receipts support must be
handed back to the agent at Stop; one whose every claim is redeemable must end
the turn in silence; and where no receipts exist at all the hook must stay out
of the way. The hook is run as a Stop subprocess with the payload on stdin,
rooted at a small scratch tree; the exit code, the stdout JSON and the receipt
are what is asserted.

    python3 -m pytest tests/test_report_truth_hook.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# The mutation runner points this at a mutated COPY; the real hook is never rewritten.
HOOK = Path(os.environ.get("REPORT_TRUTH_HOOK_UNDER_TEST")
            or Path(__file__).resolve().parent.parent / "hooks" / "report-truth-at-stop.py")

CLEAN_HANDBACK = "Changed `sum_items` in src/svc.py and re-ran the suite: 12 tests passed."
GREEN_HANDBACK = "Tidied src/svc.py. The tests pass."
INVENTED_PATH = "Rewrote src/zzz_missing.py; nothing else moved."


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small source tree with one receipt file present. The receipt itself is what
    each test decides: fresh, stale, red, or absent."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "svc.py").write_text("def sum_items(items):\n    return sum(items)\n",
                                         encoding="utf-8")
    (root / ".conduct").mkdir()
    return root


def add_receipt(root: Path, exit_code: int = 0, tool: str = "pytest", tail: str = "12 passed",
                age_s: float = -5.0) -> None:
    """Append one gate receipt. A negative age is a receipt from the near future, which is
    what a run that happened AFTER the last source edit looks like to the gate."""
    row = {"ts": int((time.time() - age_s) * 1000), "tool": tool, "exit_code": exit_code,
           "stdout_tail": tail}
    with open(root / ".conduct" / "receipts.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def stop(root: Path, receipts: Path, text: str | None, active: bool = False,
         env: dict[str, str] | None = None, session: str = "test-session"
         ) -> tuple[int, dict | None, str, dict | None]:
    payload = {"session_id": session, "cwd": str(root), "hook_event_name": "Stop",
               "stop_hook_active": active}
    if text is not None:
        payload["last_assistant_message"] = text
    run_env = {**os.environ, "REPORT_TRUTH_RECEIPTS": str(receipts)}
    run_env.pop("REPORT_TRUTH_HOOK_MODE", None)
    run_env.pop("CONDUCT_DIR", None)
    run_env.update(env or {})
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=run_env, cwd=str(root),
                       check=False, timeout=90)
    out = json.loads(r.stdout) if r.stdout.strip() else None
    rec = None
    if receipts.is_file():
        rec = json.loads(receipts.read_text(encoding="utf-8").strip().split("\n")[-1])
    return r.returncode, out, r.stderr, rec


def feedback(out: dict | None) -> str:
    return ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""


# --- the control -------------------------------------------------------------

def test_a_hand_back_whose_claims_are_redeemable_ends_in_silence(tree: Path, tmp_path: Path) -> None:
    """Without this, every test below could pass because the hook always speaks."""
    add_receipt(tree)
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", CLEAN_HANDBACK)
    assert rc == 0 and out is None, (rc, out)
    assert rec["verdict"] == "ok"


# --- only where the evidence layer exists ------------------------------------

def test_without_receipts_the_hook_stays_out_of_the_way(tree: Path, tmp_path: Path) -> None:
    """No receipts.jsonl: even an invented path goes unjudged, on purpose, with a receipt
    that says so. A hook that nagged every repository that never adopted the receipt tool
    would be uninstalled by lunch."""
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH)
    assert rc == 0 and out is None
    assert rec["verdict"] == "skipped" and rec["why"] == "no-receipts"


def test_conduct_dir_is_honoured_as_the_gate_honours_it(tree: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "receipts.jsonl").write_text(
        json.dumps({"ts": int((time.time() + 5) * 1000), "tool": "pytest", "exit_code": 0,
                    "stdout_tail": "12 passed"}) + "\n", encoding="utf-8")
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"CONDUCT_DIR": str(elsewhere)})
    assert "[fabricated-path]" in feedback(out) and rec["verdict"] == "finding"


# --- the findings, handed back ----------------------------------------------

def test_an_invented_path_is_handed_back(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH)
    assert rc == 0
    assert "[fabricated-path]" in feedback(out) and "src/zzz_missing.py" in feedback(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert rec["verdict"] == "finding" and rec["nudged"] is True and rec["checks"] == ["fabricated-path"]


def test_a_green_claim_with_only_a_red_receipt_is_handed_back(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree, exit_code=1, tail="1 failed, 11 passed")
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", GREEN_HANDBACK)
    assert "[unbacked-green]" in feedback(out) and "[contradicted-green]" in feedback(out)
    assert rec["checks"] == ["contradicted-green", "unbacked-green"]


def test_a_green_claim_with_a_receipt_older_than_the_last_edit_is_handed_back(tree: Path, tmp_path: Path) -> None:
    """The check the gate exists for: a run that happened, and then the code moved."""
    add_receipt(tree, age_s=3600.0)
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", GREEN_HANDBACK)
    assert "[unbacked-green]" in feedback(out) and "OLDER" in feedback(out)
    assert rec["checks"] == ["unbacked-green"]


def test_a_green_claim_with_a_fresh_green_receipt_is_silent(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", GREEN_HANDBACK)
    assert out is None, feedback(out)
    assert rec["verdict"] == "ok"


def test_a_count_no_run_produced_is_handed_back(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree, tail="7 passed")
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", "Ran the suite: 12 tests passed.")
    assert "[unbacked-number]" in feedback(out) and rec["checks"] == ["unbacked-number"]


def test_a_negated_claim_is_a_confession_not_a_finding(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree, exit_code=1, tail="1 failed")
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", "The tests do not pass yet; one is red.")
    assert out is None, feedback(out)
    assert rec["verdict"] == "ok"


def test_the_working_repository_s_allowlist_applies(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    (tree / ".conduct" / "report-allow.txt").write_text("src/zzz_missing.py\n", encoding="utf-8")
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH)
    assert out is None, feedback(out)
    assert rec["verdict"] == "ok"


# --- the brakes --------------------------------------------------------------

def test_a_continuation_caused_by_a_stop_hook_is_not_nudged_again(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, active=True)
    assert rc == 0 and out is None
    assert rec["verdict"] == "finding" and rec["nudged"] is False and rec["why"] == "stop_hook_active"


def test_the_same_finding_is_not_fed_back_twice(tree: Path, tmp_path: Path) -> None:
    receipts = tmp_path / "r.jsonl"
    add_receipt(tree)
    _, out1, _, rec1 = stop(tree, receipts, INVENTED_PATH)
    assert feedback(out1) and rec1["nudged"] is True
    _, out2, _, rec2 = stop(tree, receipts, INVENTED_PATH)
    assert not feedback(out2) and "systemMessage" in out2 and rec2["nudged"] is False


def test_a_different_finding_in_the_same_session_is_fed_back(tree: Path, tmp_path: Path) -> None:
    receipts = tmp_path / "r.jsonl"
    add_receipt(tree)
    stop(tree, receipts, INVENTED_PATH)
    _, out, _, rec = stop(tree, receipts, "Rewrote src/other_missing.py.")
    assert feedback(out) and rec["nudged"] is True


# --- modes -------------------------------------------------------------------

def test_notify_mode_tells_the_human_and_does_not_steer(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"REPORT_TRUTH_HOOK_MODE": "notify"})
    assert "systemMessage" in out and "hookSpecificOutput" not in out and rec["nudged"] is False


def test_block_mode_uses_the_runtime_s_block_decision(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    _, out, _, _ = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"REPORT_TRUTH_HOOK_MODE": "block"})
    assert out["decision"] == "block" and "[fabricated-path]" in out["reason"]


# --- fail-open ---------------------------------------------------------------

def test_no_message_is_a_receipt_and_silence(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", None)
    assert rc == 0 and out is None and rec["verdict"] == "no-message"


def test_a_gate_that_could_not_judge_is_a_gate_failure_not_a_pass(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    broken = tmp_path / "broken_gate.py"
    broken.write_text("import sys\nsys.stderr.write('gate failure: planted\\n')\nsys.exit(2)\n",
                      encoding="utf-8")
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"REPORT_TRUTH_GATE": str(broken)})
    assert rc == 0 and out is None
    assert rec["verdict"] == "gate-failure" and "planted" in rec["error"]


def test_a_missing_gate_fails_open_with_a_receipt(tree: Path, tmp_path: Path) -> None:
    """The interpreter exits 2 on a file it cannot open, which the hook reads as the gate's
    own failure - the right word for it. Either way: silence, a receipt, exit 0."""
    add_receipt(tree)
    rc, out, _, rec = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"REPORT_TRUTH_GATE": str(tmp_path / "none.py")})
    assert rc == 0 and out is None and rec["verdict"] in ("error", "gate-failure")


def test_receipts_can_be_switched_off(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    rc, out, _, _ = stop(tree, tmp_path / "r.jsonl", INVENTED_PATH, env={"REPORT_TRUTH_RECEIPTS": "off"})
    assert rc == 0 and "[fabricated-path]" in feedback(out)
    assert not (tmp_path / "r.jsonl").exists()


def test_other_events_are_ignored(tree: Path, tmp_path: Path) -> None:
    receipts = tmp_path / "r.jsonl"
    payload = {"session_id": "s", "cwd": str(tree), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "last_assistant_message": INVENTED_PATH}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                       text=True, env={**os.environ, "REPORT_TRUTH_RECEIPTS": str(receipts)}, check=False)
    assert r.returncode == 0 and not r.stdout.strip() and not receipts.exists()


# --- the text and the receipt ------------------------------------------------

def test_the_feedback_is_capped_and_stays_far_below_the_runtime_cap(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    many = " ".join(f"Rewrote src/gone_{i}.py." for i in range(12))
    _, out, _, rec = stop(tree, tmp_path / "r.jsonl", many)
    assert "(+8 more)" in feedback(out) and rec["findings"] == 12
    assert 0 < len(feedback(out)) < 3000


def test_the_receipt_never_carries_the_message(tree: Path, tmp_path: Path) -> None:
    add_receipt(tree)
    _, _, _, rec = stop(tree, tmp_path / "r.jsonl", "Rewrote src/secret_marker_zz.py.")
    for key in ("ts", "session", "cwd", "verdict", "checks", "findings", "signature", "ms"):
        assert key in rec, (key, rec)
    assert "secret_marker_zz" not in json.dumps(rec)
