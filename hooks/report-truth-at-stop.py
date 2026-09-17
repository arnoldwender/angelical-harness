#!/usr/bin/env python3
"""The Angelical Harness — the hand-back, checked when the agent stops.

A Claude Code `Stop` hook. When the agent finishes its turn, this hands the
message it is about to leave the human — `last_assistant_message` in the Stop
payload — to the report-truth gate (`gate/report_truth.py`), with the working
directory as its root. If the report claims more than the tree and the receipts
support — a path that exists nowhere, a count no run produced, "the tests pass"
with no green receipt newer than the last edit — the finding goes back to the
agent so the report is corrected before anyone reads it. See hooks/README.md for
the wiring and the README for why.

    "hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python3 /abs/path/to/angelical-harness/hooks/report-truth-at-stop.py",
         "timeout": 30}]}]}

WHY AT STOP
-----------
Gabriel's rule is about the state you hand back, and the hand-back exists only
when the turn ends. In CI the gate reads a report file after the fact; here it
reads the very message the human is about to see, at the one moment the agent
that wrote it can still change it.

ONLY WHERE THE EVIDENCE LAYER EXISTS
------------------------------------
The hook judges only when `<cwd>/.conduct/receipts.jsonl` exists (or the file
under `CONDUCT_DIR`, as the gate reads it). Without receipts every green claim
is unbacked by construction — that is the gate's thesis, and it is right in CI —
but a Stop hook that sent the agent round on every "done" in every repository
that never adopted `bin/conduct-receipt` would be uninstalled by lunch, after
which it catches nothing. Where there are no receipts the hook records
`skipped` and says nothing. Adoption is one wrapper around your test command.

WHAT IT DOES
------------
1. Reads the Stop payload: `cwd`, `session_id`, `stop_hook_active`,
   `last_assistant_message`. No message: receipt `no-message`, silence.
2. No receipts file in the working directory: receipt `skipped`, silence.
3. Runs the gate as a subprocess with the message on stdin and `HARNESS_ROOT`
   = the working directory, so paths, symbols, receipts and
   `.conduct/report-allow.txt` are the working repository's. Exit 2 is
   recorded as `gate-failure` and stays silent — never "clean".
4. On findings, in the default `feedback` mode, prints
   `{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "…"}}`.
   Claude Code keeps the conversation going once with that text, labelled as
   hook feedback, so the agent can correct the report — or the claim.
5. Appends one receipt per run to `REPORT_TRUTH_RECEIPTS` (default
   `~/.local/state/angelical-harness/report-truth-receipts.jsonl`; `off`
   disables): `{ts, session, cwd, verdict, checks, findings, ms}`. Never the
   message, never a line of it.

THE BRAKES, BECAUSE A STOP HOOK CAN TALK FOREVER
------------------------------------------------
`stop_hook_active` — the runtime says a stop hook already sent the agent round
this turn: record, stay silent. The same finding signature is never fed back
twice: the second time the human is told (`systemMessage`) and the agent is not
sent round again. And the runtime caps consecutive continuations at eight,
whatever the hook says.

MODES
-----
`REPORT_TRUTH_HOOK_MODE=feedback` (default) — `additionalContext`: the agent is
told and continues once. `notify` — `systemMessage` only: the human sees it,
the agent is not steered. `block` — `decision: "block"` with the finding as the
reason. Any error of the hook's own is a receipt with `verdict: error` and exit
0; the hook is never the reason a session cannot end.

WHAT IT DOES NOT SEE
--------------------
What the gate does not: a true sentence placed to mislead, an omission, a
summary that dulls the source. And a message that is not a hand-back — a
question to the human mid-task — is judged like any other; the gate's checks are
shaped so that prose without claims passes in silence, and every claim it does
make is one the agent can redeem or withdraw.

Tests: tests/test_report_truth_hook.py · mutants: tests/mutation_check_report_truth_hook.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
GATE = pathlib.Path(os.environ.get("REPORT_TRUTH_GATE") or HERE.parent / "gate" / "report_truth.py")


def _default_receipts() -> str:
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "angelical-harness", "report-truth-receipts.jsonl")


RECEIPTS = os.environ.get("REPORT_TRUTH_RECEIPTS") or _default_receipts()
MODE = os.environ.get("REPORT_TRUTH_HOOK_MODE", "feedback")       # feedback | notify | block
RECEIPT_TAIL_BYTES = 262_144
MAX_SHOWN = 4
MAX_MESSAGE = 220                # per finding; the runtime caps hook output at 10,000


# --- receipts (the hook's own, not the gate's) --------------------------------

def receipt(**row: object) -> None:
    """One JSON line per run. Verdicts and counts only — never the message."""
    if RECEIPTS == "off":
        return
    try:
        pathlib.Path(RECEIPTS).parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}
        with open(RECEIPTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — a receipt never brings the hook down
        pass


def last_receipt(session: str, cwd: str) -> dict | None:
    """This session's last receipt for this directory, from the tail of the file."""
    if RECEIPTS == "off":
        return None
    try:
        with open(RECEIPTS, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - RECEIPT_TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for raw in reversed(tail.split("\n")):
        if session not in raw or cwd not in raw:
            continue
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if r.get("session") == session and r.get("cwd") == cwd and "signature" in r:
            return r
    return None


# --- the evidence layer --------------------------------------------------------

def evidence_file(cwd: str) -> pathlib.Path:
    """Where the gate will look for receipts: `CONDUCT_DIR` if set, else `<cwd>/.conduct`."""
    conduct = os.environ.get("CONDUCT_DIR")
    base = pathlib.Path(conduct) if conduct else pathlib.Path(cwd) / ".conduct"
    return base / "receipts.jsonl"
# mutation-anchor: evidence


# --- the gate ----------------------------------------------------------------

def judge(cwd: str, message: str) -> tuple[int, str, str]:
    """Run the gate over `message` as the report, rooted at `cwd`. Returns
    (exit code, stdout, stderr) — the gate's contract is the evidence."""
    env = {**os.environ, "HARNESS_ROOT": cwd}
    r = subprocess.run([sys.executable, str(GATE)], input=message, capture_output=True,
                       text=True, env=env, cwd=cwd, check=False, timeout=25)
    return r.returncode, r.stdout, r.stderr


def findings_of(stdout: str) -> list[str]:
    return [line.strip()[5:] for line in stdout.split("\n") if line.strip().startswith("FAIL ")]


def signature(findings: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(findings)).encode("utf-8")).hexdigest()[:16]


def message(findings: list[str]) -> str:
    shown = [f[:MAX_MESSAGE] for f in findings[:MAX_SHOWN]]
    more = f" (+{len(findings) - MAX_SHOWN} more)" if len(findings) > MAX_SHOWN else ""
    return ("report-truth: this hand-back claims more than the tree and the receipts support. "
            + " ".join(shown) + more
            + " Gabriel, the Message: the state you hand back is the true state. Name what you "
            "could not verify, never let UNCERTAIN wear the face of CONFIRMED — correct the claim "
            "or the report before it is read. A token that is genuinely fine goes in "
            ".conduct/report-allow.txt.")


# --- main --------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    payload = json.loads(sys.stdin.read() or "{}")
    if payload.get("hook_event_name") not in (None, "Stop", "SubagentStop"):
        return 0
    cwd = str(payload.get("cwd") or os.getcwd())
    session = str(payload.get("session_id") or "")[:8]
    common = {"session": session, "cwd": cwd, "mode": MODE}

    text = str(payload.get("last_assistant_message") or "")
    if not text.strip():
        receipt(verdict="no-message", **common)
        return 0
    if not evidence_file(cwd).is_file():
        receipt(verdict="skipped", why="no-receipts", **common)
        return 0
    code, out, err = judge(cwd, text)
    ms = int((time.time() - t0) * 1000)

    if code == 2:
        receipt(verdict="gate-failure", error=err.strip()[:200], ms=ms, **common)
        return 0
    findings = findings_of(out) if code == 1 else []
    if not findings:
        receipt(verdict="ok", ms=ms, **common)
        return 0

    sig = signature(findings)
    checks = sorted({f.split("]", 1)[0].lstrip("[") for f in findings if f.startswith("[")})
    already = bool(payload.get("stop_hook_active"))
    # mutation-anchor: stop_hook_active
    previous = last_receipt(session, cwd)
    repeated = bool(previous) and previous.get("signature") == sig
    # mutation-anchor: repeated
    mode = MODE
    if already:
        receipt(verdict="finding", nudged=False, why="stop_hook_active", checks=checks,
                findings=len(findings), signature=sig, ms=ms, **common)
        return 0
    if repeated and mode != "notify":
        mode = "notify"

    receipt(verdict="finding", nudged=mode != "notify", checks=checks, findings=len(findings),
            signature=sig, ms=ms, **common)
    body = message(findings)
    if mode == "block":
        print(json.dumps({"decision": "block", "reason": body}, ensure_ascii=False))
    elif mode == "notify":
        print(json.dumps({"systemMessage": body}, ensure_ascii=False))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop",
                                                 "additionalContext": body}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail open on purpose: the hook never keeps a session from ending
        receipt(verdict="error", error=f"{type(exc).__name__}: {exc}"[:200])
        sys.exit(0)
