# Hooks — keeping the axes present

The Codex only works if it's *in context* when the agent acts. A one-time paste into
`AGENTS.md` works; a hook makes it automatic, every session, and opens each run under
blessing.

## `session-start.sh`

Emits, to stdout:

1. The **Blessing of Saint Benedict** + the rotating verbum of the day (`bin/blessing`).
2. The **conduct block** — the four axes, precedence, and the gate limit (`codex-block.md`).

It's harness-agnostic: any harness that can run a command at session start can use it, and
its stdout is plain readable text.

## Wiring it into Claude Code

Claude Code injects a `SessionStart` hook's stdout into the session context. Add to your
`settings.json` (use the **absolute** path to the script, and check your Claude Code
version's hook docs — the schema evolves):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "/abs/path/to/angelical-harness/hooks/session-start.sh" }
        ]
      }
    ]
  }
}
```

## Wiring it into any other harness

Run `hooks/session-start.sh` as the first step of your session bootstrap and prepend its
output to the system prompt (or your context-priming step). That's all — the blessing goes
first, the axes stay present.

## `report-truth-at-stop.py` — the hand-back, checked when the agent stops

A Claude Code `Stop` hook. When the agent finishes its turn, it hands the message it is about
to leave the human — `last_assistant_message` in the Stop payload — to
[`gate/report_truth.py`](../gate/report_truth.py), rooted at the working directory, and if the
report claims more than the tree and the receipts support, hands the finding back to the agent
so the report is corrected before anyone reads it:

> report-truth: this hand-back claims more than the tree and the receipts support.
> [fabricated-path] line 1: the report cites `src/zzz_missing.py`, which exists nowhere in the
> tree [unbacked-number] line 1: "987654 tests" appears in no receipt's output — a count that
> came out of no run came out of nowhere Gabriel, the Message: the state you hand back is the
> true state. Name what you could not verify, never let UNCERTAIN wear the face of CONFIRMED —
> correct the claim or the report before it is read. A token that is genuinely fine goes in
> .conduct/report-allow.txt.

Why at Stop: Gabriel's rule is about the state you hand back, and the hand-back exists only when
the turn ends. In CI the gate reads a report file after the fact; here it reads the very message
the human is about to see, at the one moment the agent that wrote it can still change it.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command",
            "command": "python3 /abs/path/to/angelical-harness/hooks/report-truth-at-stop.py",
            "timeout": 30 }
        ]
      }
    ]
  }
}
```

**Only where the evidence layer exists.** The hook judges only when `.conduct/receipts.jsonl`
is present in the working directory (or under `CONDUCT_DIR`, as the gate reads it). Without
receipts every green claim is unbacked by construction — that is the gate's thesis, and it is
right in CI — but a Stop hook that sent the agent round on every "done" in every repository that
never adopted [`bin/conduct-receipt`](../bin/conduct-receipt) would be uninstalled by lunch,
after which it catches nothing. Where there are no receipts the hook records `skipped` and says
nothing. Adoption is one wrapper around your test command.

A Stop hook that keeps the conversation going has to know when to stop itself. Three brakes:
`stop_hook_active` (the runtime says a stop hook already sent the agent round — this one then
records and stays silent, one nudge per turn); the same finding is never fed back twice (the
human is told instead); and the runtime's own cap of eight continuations. Modes:
`REPORT_TRUTH_HOOK_MODE=feedback` (default — `additionalContext`, the agent continues once),
`notify` (`systemMessage`, the human sees it, the agent is not steered), `block` (the runtime's
`decision: "block"`). The gate's exit 2 is a `gate-failure` receipt and silence, never "clean".
Receipts of the hook's own in `~/.local/state/angelical-harness/report-truth-receipts.jsonl`
(`REPORT_TRUTH_RECEIPTS=…` to move, `off` to disable) — verdict, checks, counts, never the
message. Any error of its own is a receipt and exit 0 — the hook is never the reason a session
cannot end.

Tests: [`tests/test_report_truth_hook.py`](../tests/test_report_truth_hook.py) ·
mutants: [`tests/mutation_check_report_truth_hook.py`](../tests/mutation_check_report_truth_hook.py) ·
once, the runtime's own payload shape: [`tests/live_hook_smoke.py`](../tests/live_hook_smoke.py).

## Just want to see it?

```sh
./hooks/session-start.sh
```
