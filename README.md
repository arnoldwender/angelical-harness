# The Angelical Harness

**A conduct codex for AI coding agents — four disciplines, kept under the watch of the
angels. Every run opens with a blessing and closes with one.**

Modern coding agents are capable but undisciplined: they declare work "done" before
it passes, they take the shortcut that looks fast and costs later, they paper over a
red test to reach green, they report success over failure. A *harness* — the loop and
tooling around the model — can fix the plumbing. It cannot, by itself, fix the
**conduct.**

The Angelical Harness adds the missing layer: a small, memorable **codex of conduct**
that rides inside every agent's context and governs *how it behaves until the work is
truly done.*

## Two layers, cleanly split

| Layer | Named by | What it is |
| --- | --- | --- |
| **Conduct** | **angels** | The [Codex](CODEX.md) — four always-active axes of discipline. Evocative, so it's remembered under pressure. |
| **Function** | **engineering** | The agents, skills, and commands the harness runs. Named technically, by what they do. |

The split is the whole idea: **angels name the discipline; engineering names the
machinery.** A rule you invoke fifty times a day should read as poetry you never
forget; a tool you invoke fifty times a day should read as exactly what it does.

## The Codex, in one breath

Four orthogonal axes, each under an angel chosen for what the angel *does*:

- **Raphael — the Healing** · what you touch, you leave better.
- **Michael — the Discernment** · how you decide under pressure: minimum force, no shining shortcut.
- **Gabriel — the Message** · how you report: the real state, no green makeup.
- **The Guardian — the Vigil** · do you abandon the task: never-say-die against obstacles, nothing half-done.

With one hard limit: the Vigil's persistence stops at **legitimate gates** — approval
markers, evidence checkpoints, hard rules are boundaries the angels *keep,* not walls
to break. Precedence: **Michael › Guardian › Raphael**, and Gabriel's honesty is never
traded away. Full text: **[CODEX.md](CODEX.md)**.

## Why angels

They're the project's guardians — the work is placed under their watch, and that's the
honest reason, not a metaphor picked for style. It also happens to be the best mnemonic
there is: each axis is named for the angel whose work it mirrors — Raphael heals, Michael
discerns, Gabriel carries the message, the Guardian keeps the vigil. One word holds a whole
discipline, and holds it even when the clock is burning.

And the harness opens with the Blessing of Saint Benedict and closes with a benediction —
because work begun under blessing is work you hold yourself to.

## How to use it

1. Drop [CODEX.md](CODEX.md) (or a trimmed version) into your agent's system prompt,
   `AGENTS.md`, or `CLAUDE.md`. That alone installs the conduct layer — the codex is
   prose, not code, and is harness-agnostic (Claude, or any agent SDK).
2. Keep your functional layer — agents, skills, commands — named technically.
3. Let the axes stay *always active*: no trigger phrase, every session, every
   sub-agent. Intensity scales to the task (a hotfix heals the minimum; an audit only
   reports).

## Repository

- **[BLESSING.md](BLESSING.md)** · **[`bin/blessing`](bin/blessing)** — the harness's
  first utterance: the Blessing of Saint Benedict (*Vade Retro Satana*), fixed, followed
  by a rotating line of Church Latin from [`verba.txt`](verba.txt). Opening: protection.
- **[CODEX.md](CODEX.md)** — the canonical core (v1.0): four axes, ~4 rules each, a
  **falsifier** per rule, and a paste-ready block for `AGENTS.md`. Closing: the Benediction.
- **[REFERENCE.md](REFERENCE.md)** — the full expansion (~12 rules per axis) for depth
  and citation.
- **[codex-block.md](codex-block.md)** — the paste-ready conduct block (the single source
  the hook and your `AGENTS.md` share).
- **[hooks/](hooks/)** — `session-start.sh`: opens every session blessed and keeps the
  axes in context. Harness-agnostic; wiring for Claude Code included.
- **[agents/](agents/)** — a starter agent set (`reviewer`, `implementer`) that works
  under the Codex.
- **[EXAMPLE.md](EXAMPLE.md)** — a worked before/after: same model, same task, opposite
  outcome — the axis firing.

## Status

Early, but real. The Codex core (v1.0) is stable, and the reference wiring ships with it: a
session-start hook that opens every run blessed and keeps the axes present
([hooks/](hooks/)), a starter agent set ([agents/](agents/)), and a worked before/after
example ([EXAMPLE.md](EXAMPLE.md)) — the example is what turns a codex from manifesto into
instrument. Battle-tested refinements and real before/afters are welcome.

## License

**MIT** — see [LICENSE](LICENSE), dedicated *Soli Deo gloria*. A `CITATION.cff` (CC-BY-4.0)
gives the citable form. MIT keeps the one thing that actually protects users — the
liability disclaimer — while letting the codex be pasted anywhere without attribution
friction.
