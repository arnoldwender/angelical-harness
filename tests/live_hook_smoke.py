#!/usr/bin/env python3
"""Run the live hook once against a planted hand-back, the way the runtime would.

    python3 tests/live_hook_smoke.py

Builds a scratch tree with one source file and one fresh green receipt, pipes a
`Stop` payload whose `last_assistant_message` cites a file that does not exist
to hooks/report-truth-at-stop.py exactly as Claude Code would, and requires two
things: exit 0, and a `hookSpecificOutput.additionalContext` that names
`fabricated-path`. Exit 0 when both hold, 1 otherwise, printing what came back.

Kept as a versioned file rather than an inline shell heredoc so the assertion
is re-runnable and readable on its own.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "report-truth-at-stop.py"


def main() -> int:
    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        (root / "src").mkdir()
        (root / "src" / "svc.py").write_text("def sum_items(items):\n    return sum(items)\n",
                                             encoding="utf-8")
        (root / ".conduct").mkdir()
        (root / ".conduct" / "receipts.jsonl").write_text(json.dumps({
            "ts": int((time.time() + 5) * 1000), "tool": "pytest", "exit_code": 0,
            "stdout_tail": "12 passed"}) + "\n", encoding="utf-8")
        payload = {"session_id": "smoke", "cwd": scratch, "hook_event_name": "Stop",
                   "stop_hook_active": False,
                   "last_assistant_message": "Rewrote src/zzz_missing.py; nothing else moved."}
        env = {**os.environ, "REPORT_TRUTH_RECEIPTS": "off"}
        env.pop("REPORT_TRUTH_HOOK_MODE", None)
        env.pop("CONDUCT_DIR", None)
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, cwd=scratch,
                           check=False, timeout=60)
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    context = (out.get("hookSpecificOutput") or {}).get("additionalContext") or ""
    if r.returncode != 0:
        print(f"exit {r.returncode}, expected 0: {r.stderr.strip()[:300]}")
        return 1
    if "[fabricated-path]" not in context:
        print(f"the planted invented path was not handed back: {out!r}")
        return 1
    print("planted [fabricated-path] was handed back to the agent at Stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
