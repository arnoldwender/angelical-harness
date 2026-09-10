#!/usr/bin/env python3
"""The Angelical Harness gate: no report is greener than the run it describes.

    python3 gate/report_truth.py --report REPORT.md
    cat REPORT.md | python3 gate/report_truth.py
    python3 gate/report_truth.py --report REPORT.md --sarif truth.sarif

Exit codes are the contract shared by the conduct-harness family:

    0   no findings
    1   findings — the report claims more than the run supports
    2   the gate itself failed

The third one is not decoration. A checker that returns 1 when it crashed reads
as "I found something"; one that returns 0 reads as "clean" and fails OPEN — and
a gate on honesty that fails open is the exact failure it exists to catch.

WHY THIS GATE EXISTS
--------------------
This repo's third axis is Gabriel, the Message: *report the true state.* It is
the one axis the Codex marks never traded. Every other axis has a mechanical
witness — a build, a test run, a linter. Honesty had none, and the obvious place
to look for one is not there either.

Measured over 25 Claude Code session transcripts: 462 Bash tool results, and
ZERO of them carry the command's exit code. The transcript does not record
whether the gate passed. So any honesty check that reads the transcript to
decide "did it actually pass?" is silently broken, and broken in the worst
direction — it fails OPEN, reporting clean because it found no evidence of
failure, when what it found was no evidence at all.

The remedy is not a better parser. It is a receipt: `bin/conduct-receipt run
<tool> -- <cmd>` appends one JSON line per gate invocation to
`.conduct/receipts.jsonl` carrying the REAL exit code, the tree sha, the
duration and a hash plus tail of the output. That turns "the tests pass" from
an assertion into something with a file behind it.

WHAT IT CHECKS
--------------
Each class of claim a report makes must be redeemable against something:

    1 fabricated-path       a cited path must exist on disk
    2 unknown-symbol        a backticked identifier must exist in the tree
    3 unbacked-number       a number with a unit must appear in a receipt's output
    4 unbacked-error-block  a quoted error must be verbatim in a receipt's output
    5 unbacked-green        "the tests pass" needs a green receipt NEWER than the
                            last source edit — arithmetic, not judgement
    6 contradicted-green    the report says green while a tool's latest run is red

CHECK 5 is the one that matters. A green from three commits ago says nothing
about today's code, and the difference between "it passed" and "it passed
before I changed everything" is not a judgement call — it is a timestamp
comparison, and a machine should make it.

WHAT IT DOES NOT CHECK — read this before trusting it
-----------------------------------------------------
This gate automates ONE of the four axes, partially. Raphael (what you leave
behind), Michael (how you decide) and the Guardian (whether you abandon) have no
witness here. And within Gabriel it catches the mechanical lies — the invented
path, the number from nowhere, the stale green — not the ones that need a reader:
a true sentence placed to mislead, an omission, a summary that dulls the source.
Naming that is itself the axis: never let UNCERTAIN wear the face of CONFIRMED.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The root is overridable so the tests can point the gate at a scratch repo with
# a defect planted. A checker that can only ever run on itself cannot be shown to
# work: the only proof a check has teeth is watching it go red on a repo built to
# make it go red.
ROOT = Path(os.environ.get("HARNESS_ROOT") or Path(__file__).resolve().parent.parent)
CONDUCT = Path(os.environ["CONDUCT_DIR"]) if os.environ.get("CONDUCT_DIR") else ROOT / ".conduct"
RECEIPTS = CONDUCT / "receipts.jsonl"
ALLOWLIST = CONDUCT / "report-allow.txt"

# Directories that are never "source" and never a place to look for a symbol.
SKIP_DIRS = {".git", ".conduct", "node_modules", "__pycache__", ".venv", "venv",
             ".pytest_cache", ".mypy_cache", "dist", "build", "assets", ".idea"}

# Files whose edits do NOT invalidate a green receipt. The first four are the
# list the receipt tool uses, deliberately: one definition of "a source edit", or
# the gate and the tool that feeds it would disagree about what makes a green
# stale. `.sarif` is this gate's own output — without it, running the gate once
# would make its own artifact the newest "source" and every later run would call
# every green stale, a gate that poisons itself on the second invocation.
DOC_SUFFIXES = {".md", ".txt", ".jsonl", ".lock", ".sarif"}

# Text the symbol check may search. Extensionless files under bin/ and hooks/ are
# added separately — a shell emitter has no suffix and is still source.
TEXT_SUFFIXES = {".py", ".sh", ".md", ".txt", ".yml", ".yaml", ".json", ".cff",
                 ".js", ".mjs", ".ts", ".tsx", ".astro", ".swift", ".rs", ".go",
                 ".toml", ".cfg", ".ini", ".html", ".css", ".rb", ".php", ".java"}

MAX_FILE_BYTES = 2_000_000


# --- data --------------------------------------------------------------------

@dataclass
class Finding:
    check: str
    message: str
    line: int = 0
    token: str = ""


@dataclass
class Receipt:
    ts: int
    tool: str
    exit_code: int
    stdout_tail: str


@dataclass
class Report:
    """A report split into the regions that mean different things.

    The split IS the false-positive defence, and it is the same lesson the
    citation gate in the sibling repo learned the hard way: a gate that treats
    every occurrence as a claim fires on the document's own examples and gets
    deleted in a week.

      * `prose`      — the report speaking in its own voice. Claims live here.
      * `quoted`     — blockquote lines. Quoting the Codex saying "verified" is
                       not claiming anything was verified.
      * `blocks`     — fenced code. An example path is an illustration, not an
                       assertion; a pasted error IS a claim and CHECK 4 takes it.
    """
    prose: list[tuple[int, str]] = field(default_factory=list)
    quoted: list[tuple[int, str]] = field(default_factory=list)
    blocks: list[tuple[int, str, str]] = field(default_factory=list)
    paragraphs: list[tuple[int, str]] = field(default_factory=list)


# --- text helpers ------------------------------------------------------------

def fold(s: str) -> str:
    """Lowercase and strip accents, ONE OUTPUT CHARACTER PER INPUT CHARACTER.

    Length preservation is the whole point: the guards below work on offsets into
    the folded string and report the original. A plain NFKD would make "é" two
    characters and every offset after it would point at the wrong word.
    """
    out = []
    for ch in s:
        d = unicodedata.normalize("NFKD", ch)
        out.append((d[0] if d else ch).lower())
    return "".join(out)


def squeeze(s: str) -> str:
    return " ".join(s.split())


def quote_spans(s: str) -> list[tuple[int, int]]:
    """Character ranges inside paired quotation marks.

    An unpaired closing quote is ignored rather than swallowing the rest of the
    line: a gate that goes blind after one stray apostrophe is worse than one
    with a known, small hole.
    """
    spans: list[tuple[int, int]] = []
    for open_ch, close_ch in (('"', '"'), ("“", "”"), ("«", "»")):
        i = 0
        while True:
            a = s.find(open_ch, i)
            if a < 0:
                break
            b = s.find(close_ch, a + 1)
            if b < 0:
                break
            spans.append((a, b))
            i = b + 1
    return spans


def in_any_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos <= b for a, b in spans)


# --- parsing -----------------------------------------------------------------

def parse_report(text: str) -> Report:
    r = Report()
    fence: str | None = None
    info = ""
    body: list[str] = []
    start = 0
    para: list[str] = []
    para_start = 0

    def flush_para() -> None:
        nonlocal para, para_start
        if para:
            r.paragraphs.append((para_start, " ".join(para)))
            para = []

    for n, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if fence is not None:
            if stripped.startswith(fence):
                r.blocks.append((start, info, "\n".join(body)))
                fence, info, body = None, "", []
            else:
                body.append(raw)
            continue
        m = re.match(r"^(```+|~~~+)\s*(\S*)", stripped)
        if m:
            flush_para()
            fence, info, body, start = m.group(1)[:3], m.group(2), [], n
            continue
        if stripped.startswith(">"):
            flush_para()
            r.quoted.append((n, stripped.lstrip("> ").strip()))
            continue
        if not stripped:
            flush_para()
            continue
        r.prose.append((n, raw))
        if not para:
            para_start = n
        para.append(stripped)

    flush_para()
    if fence is not None:                       # unterminated fence: still a block
        r.blocks.append((start, info, "\n".join(body)))
    return r


def _corrupt(n: int, exc: Exception) -> Finding:
    return Finding(
        "corrupt-receipt",
        f"receipts.jsonl line {n} is not a readable receipt ({type(exc).__name__}: "
        f"{exc}) — that run's verdict is lost, which is not the same as clean",
        token=f"receipts.jsonl:{n}")


def load_receipts(findings: list[Finding]) -> list[Receipt]:
    """Read `.conduct/receipts.jsonl`. A corrupt line is REPORTED, never fatal.

    A receipts file with one bad line still holds every good line, and losing
    them to a truncated write would punish the honest half of the evidence. But
    the bad line is a finding: silently skipping it is how a gate starts lying
    about its own coverage.
    """
    out: list[Receipt] = []
    if not RECEIPTS.is_file():
        return out
    for n, raw in enumerate(RECEIPTS.read_text(encoding="utf-8", errors="replace")
                            .splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            out.append(Receipt(int(row["ts"]), str(row.get("tool", "?")),
                               int(row["exit_code"]), str(row.get("stdout_tail", ""))))
        except Exception as exc:                # noqa: BLE001 - reported, not swallowed
            findings.append(_corrupt(n, exc))
    return out


def load_allowlist() -> set[str]:
    if not ALLOWLIST.is_file():
        return set()
    return {ln.strip() for ln in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


# --- the tree ----------------------------------------------------------------

def walk_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            out.append(Path(base) / name)
    return out


def newest_source_mtime(root: Path, exclude: Path | None = None) -> tuple[float, str]:
    """When the source last changed. Documentation and data do not count.

    Excluding docs is not laziness: a receipt written at 10:00 still describes
    code that has not moved since 09:00, and rewriting the report at 10:05 must
    not invalidate it. Otherwise the act of writing the honest report would make
    the report unprovable — a gate nobody could ever pass.
    """
    newest, newest_f = 0.0, ""
    for p in walk_files(root):
        if exclude and p.resolve() == exclude:
            continue
        if p.suffix in DOC_SUFFIXES or not p.is_file():
            continue
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > newest:
            newest, newest_f = m, str(p.relative_to(root))
    return newest, newest_f


def tree_text(root: Path, exclude: Path | None = None) -> str:
    """Every readable source byte in the tree, for the symbol check.

    The report file itself is excluded. Without that, a report is its own
    evidence: writing `invented_helper` in the report would put the string in the
    tree and the check would find it there and pass. A gate that accepts the
    claim as proof of the claim is not a gate.
    """
    parts: list[str] = []
    for p in walk_files(root):
        if exclude and p.resolve() == exclude:
            continue
        keep = p.suffix in TEXT_SUFFIXES or (not p.suffix and p.parent.name in ("bin", "hooks"))
        if not keep:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


# --- CHECK 1: paths ----------------------------------------------------------

PATH_RE = re.compile(
    r"(?<![\w/])((?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,6}|[\w.\-]+\.(?:py|ts|tsx|js|mjs"
    r"|astro|swift|sh|ya?ml|json|jsonl|md|css|html|toml|rs|go|rb|php|java|cff))(?![\w/])")


def cited_paths(report: Report) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in report.prose:
        clean = re.sub(r"https?://\S+", " ", line)
        for m in PATH_RE.finditer(clean):
            tok = m.group(1).strip(".,;:)")
            if tok and tok not in [t for _, t in out]:
                out.append((lineno, tok))
    return out


def check_paths(report: Report, findings: list[Finding]) -> None:
    """CHECK 1 — a path the report cites must exist. A path that does not is fabrication."""
    for lineno, tok in cited_paths(report):
        candidate = ROOT / tok.lstrip("./")
        if candidate.exists() or Path(tok).exists():
            continue
        findings.append(Finding(
            "fabricated-path",
            f"the report cites `{tok}`, which exists nowhere in the tree",
            lineno, tok))


# --- CHECK 2: symbols --------------------------------------------------------

BACKTICK_RE = re.compile(r"`([^`\n]{1,80})`")


def as_symbol(tok: str) -> str | None:
    """Is this backticked token an identifier the report is claiming exists?

    Deliberately narrow. `pytest`, `main`, `--sarif` and `README.md` are all
    backticked in normal writing and none of them is a claim about a symbol; a
    check that fired on them would be turned off within the week. What survives:
    something called with `()`, something with an underscore, or camelCase — the
    three shapes a reader recognises as "a name from the code".
    """
    t = tok.strip()
    called = t.endswith("()")
    if called:
        t = t[:-2]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
        return None
    if called:
        return t
    if "_" in t and len(t) >= 4:
        return t
    if re.search(r"[a-z][A-Z]", t):
        return t
    return None


def cited_symbols(report: Report) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for lineno, line in report.prose:
        for m in BACKTICK_RE.finditer(line):
            sym = as_symbol(m.group(1))
            if sym and sym not in seen:
                seen.add(sym)
                out.append((lineno, sym))
    return out


def check_symbols(report: Report, haystack: str, findings: list[Finding]) -> None:
    """CHECK 2 — a backticked identifier must actually appear in the tree."""
    for lineno, sym in cited_symbols(report):
        if re.search(rf"(?<![\w]){re.escape(sym)}(?![\w])", haystack):
            continue
        findings.append(Finding(
            "unknown-symbol",
            f"the report names `{sym}`, which appears nowhere in the tree",
            lineno, sym))


# --- CHECK 3: numbers --------------------------------------------------------

UNITS = (r"tests?|pruebas?|casos?|cases?|checks?|comprobaciones?|mutantes?|mutants?"
         r"|passed|passing|pasaron|pasan|aprobad[oa]s?|failed|failures?|fallos?|fallaron"
         r"|fallid[oa]s?|errors?|errores?|warnings?|avisos?|advertencias?|findings?"
         r"|hallazgos?|violations?|violaciones?|files?|ficheros?|archivos?|lines?|lineas?"
         r"|assertions?|aserciones?|repos?|skipped|deselected|coverage")

# The lookbehind excludes a preceding word char, a dot or a hyphen, which is what
# keeps `v0.1.1`, `Python 3.12` and `2026-09-10` out of this check without a
# special case for each: a version or date segment is never at a token boundary.
NUMBER_RE = re.compile(rf"(?<![\w.\-])(\d+(?:[.,]\d+)?)\s*(%|(?:{UNITS})\b)", re.I)


def cited_numbers(report: Report) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for lineno, line in report.prose:
        folded = fold(line)
        spans = quote_spans(line)
        for m in NUMBER_RE.finditer(folded):
            if in_any_span(m.start(), spans):
                continue                          # quoting someone else's number
            out.append((lineno, m.group(1), squeeze(m.group(0))))
    return out


def check_numbers(report: Report, receipts: list[Receipt], findings: list[Finding]) -> None:
    """CHECK 3 — a measurement must have come out of a run.

    A number with a unit is a measurement, and a measurement that appears in no
    receipt's output was not measured. This is the check that catches the most
    comfortable lie there is: the plausible count.
    """
    tails = "\n".join(r.stdout_tail for r in receipts)
    for lineno, num, phrase in cited_numbers(report):
        if re.search(rf"(?<![\w.]){re.escape(num)}(?![\w])", tails):
            continue
        findings.append(Finding(
            "unbacked-number",
            f'"{phrase}" appears in no receipt\'s output — a count that came out of '
            f"no run came out of nowhere",
            lineno, num))


# --- CHECK 4: quoted error blocks --------------------------------------------

ERROR_MARKERS = re.compile(
    r"Traceback \(most recent call last\)|\b[A-Z][A-Za-z]*Error\b|\bException\b"
    r"|\bFAILED\b|\bFAIL\b|\berror\[E\d|\berror:|\bERROR\b|\bfatal:|npm ERR!"
    r"|Segmentation fault|\bpanic:|\bassert\b|exit (?:code|status)|^E\s{3}|✗|✖")


def error_blocks(report: Report) -> list[tuple[int, str]]:
    """Fenced blocks that are quoted FAILURE OUTPUT, not illustration.

    The marker is the discriminant. Without it every example snippet in a report
    would have to be traceable to a run, which is absurd — a report explaining
    how to invoke the gate is not claiming it invoked it that way.
    """
    out: list[tuple[int, str]] = []
    for lineno, _info, body in report.blocks:
        if body.strip() and ERROR_MARKERS.search(body):
            out.append((lineno, body))
    return out


def check_error_blocks(report: Report, receipts: list[Receipt],
                       findings: list[Finding]) -> None:
    """CHECK 4 — a quoted error must be verbatim in some receipt's output."""
    tails = [squeeze(r.stdout_tail) for r in receipts]
    for lineno, body in error_blocks(report):
        needle = squeeze(body)
        if any(needle in t for t in tails):
            continue
        findings.append(Finding(
            "unbacked-error-block",
            f"the report quotes error output that is verbatim in no receipt: "
            f"{needle[:70]}",
            lineno, needle[:40]))


# --- CHECK 5 + 6: the green claim --------------------------------------------

GREEN_RE = re.compile(
    r"\b(?:los |las )?(?:tests?|pruebas|suite)\s+(?:pasan|pasaron)\b"
    r"|\ball (?:tests?|checks?) (?:pass|passed|passing)\b"
    r"|\btests? (?:pass|passed|passing)\b"
    r"|\btodo (?:esta |queda |quedo )?(?:en )?verde\b|\bsuite (?:en )?verde\b"
    r"|\bevery(?:thing)? (?:is )?green\b|\ball green\b"
    r"|\bbuild (?:ok|verde|passing|green|limpio)\b|\bbuild pasa\b"
    r"|\bsin errores\b|\bcero errores\b|\bno errors\b|\bzero errors\b"
    r"|\bfunciona(?:ndo)?\b|\bworks (?:fine|now)\b"
    r"|\bverificad[oa]s?\b|\bverified\b"
    r"|\bmutation check (?:pasa|passes)\b")

NEG_RE = re.compile(r"\b(?:no|not|nunca|never|tampoco|ni|sigue sin|siguen sin)\b")

# Irrealis only. "cuando"/"when" were deliberately left out: "cuando corri los
# tests, todo verde" is a plain past-tense claim and swallowing it would let a
# real fabrication through. `si` is required not to be followed by a comma, so
# the Spanish "si," (yes) is not mistaken for "si" (if).
COND_RE = re.compile(
    r"\bsi\b(?!\s*,)|\bif\b|\bdeberian?\b|\bharian?\b|\bharan?\b|\bpodrian?\b"
    r"|\bseran?\b|\bwould\b|\bshould\b|\bwill\b|\bcould\b|\bmight\b"
    r"|\buna vez que\b|\ben cuanto\b|\bpara que\b")


def sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", paragraph)
    return [p for p in parts if p.strip()]


def negated(folded: str, start: int) -> bool:
    """Is the claim at `start` denied by a negation in its own clause?

    Reporting a failure is the opposite of fabricating a success — "los tests NO
    pasan" is the Codex working, and a gate that punished it would train agents
    to stop confessing. The window stops at the last clause break so that "no hay
    bloqueos; los tests pasan" is still read as a claim.
    """
    window = folded[max(0, start - 45):start]
    for sep in (";", ",", ":", "."):
        cut = window.rfind(sep)
        if cut >= 0:
            window = window[cut + 1:]
    return bool(NEG_RE.search(window))


def green_claims(report: Report) -> list[tuple[int, str, str]]:
    """Sentences in the report's own voice asserting that something is green."""
    out: list[tuple[int, str, str]] = []
    for lineno, paragraph in report.paragraphs:
        for sentence in sentences(paragraph):
            folded = fold(sentence)
            spans = quote_spans(sentence)
            for m in GREEN_RE.finditer(folded):
                if in_any_span(m.start(), spans):
                    continue                      # quoting, not claiming
                if negated(folded, m.start()):
                    continue                      # confessing, not claiming
                cond = COND_RE.search(folded)
                if cond and cond.start() < m.start():
                    continue                      # conditional or future, not a verdict
                out.append((lineno, squeeze(sentence)[:100], m.group(0)))
                break
    return out


def check_green_claims(report: Report, receipts: list[Receipt], newest: float,
                       newest_file: str, findings: list[Finding]) -> None:
    """CHECK 5 — a green claim needs a green receipt NEWER than the last source edit.

    This is the check the repo exists for. Two ways it fires, and neither needs
    an opinion:

      * no green receipt at all — the claim rests on nothing;
      * a green receipt older than the newest source file — the run happened, and
        then the code moved underneath it. That green describes code that is gone.
    """
    claims = green_claims(report)
    if not claims:
        return
    fresh = [r for r in receipts if r.exit_code == 0 and r.ts >= newest * 1000]
    if fresh:
        return
    stale = [r for r in receipts if r.exit_code == 0]
    for lineno, sentence, phrase in claims:
        if stale:
            newest_green = max(stale, key=lambda r: r.ts)
            age = (newest * 1000 - newest_green.ts) / 1000.0
            findings.append(Finding(
                "unbacked-green",
                f'"{phrase}" — the newest green receipt ({newest_green.tool}) is '
                f"{age:.0f}s OLDER than the last source edit ({newest_file}); that "
                f"green does not describe the current code: {sentence}",
                lineno, phrase))
        else:
            findings.append(Finding(
                "unbacked-green",
                f'"{phrase}" is claimed with no green receipt behind it — the '
                f"transcript does not record exit codes, so this is an assertion, "
                f"not a fact: {sentence}",
                lineno, phrase))


def check_contradicted_green(report: Report, receipts: list[Receipt],
                             findings: list[Finding]) -> None:
    """CHECK 6 — the report says green while a tool's most recent run is red.

    Per tool, because the newest run is the one that speaks: an old red that a
    later green superseded is history, and a red that nothing superseded is the
    current state of that gate no matter what the prose says.
    """
    claims = green_claims(report)
    if not claims:
        return
    latest: dict[str, Receipt] = {}
    for r in receipts:
        if r.tool not in latest or r.ts >= latest[r.tool].ts:
            latest[r.tool] = r
    red = sorted((r for r in latest.values() if r.exit_code != 0), key=lambda r: r.tool)
    if not red:
        return
    names = ", ".join(f"{r.tool} (exit {r.exit_code})" for r in red)
    for lineno, sentence, phrase in claims:
        findings.append(Finding(
            "contradicted-green",
            f'"{phrase}" is claimed while the latest receipt says otherwise: '
            f"{names} — a checkmark over a failing thing is a lie the next agent "
            f"inherits: {sentence}",
            lineno, phrase))


# --- output ------------------------------------------------------------------

def to_sarif(findings: list[Finding], report_uri: str) -> dict[str, Any]:
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "angelical-harness-report-truth",
                "informationUri": "https://github.com/arnoldwender/angelical-harness",
                "rules": [{"id": r} for r in sorted({f.check for f in findings})],
            }},
            "results": [{
                "ruleId": f.check,
                "level": "error",
                "message": {"text": f.message},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": report_uri},
                    "region": {"startLine": max(f.line, 1)},
                }}],
            } for f in findings],
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", metavar="PATH",
                    help="the final report to check (default: stdin)")
    ap.add_argument("--sarif", metavar="PATH", help="write SARIF 2.1.0 to PATH")
    args = ap.parse_args(argv)

    report_path: Path | None = None
    if args.report:
        report_path = Path(args.report)
        if not report_path.is_file():
            print(f"gate failure: no report at {args.report}", file=sys.stderr)
            return 2
        text = report_path.read_text(encoding="utf-8", errors="replace")
    else:
        if sys.stdin.isatty():
            print("gate failure: no --report and nothing on stdin", file=sys.stderr)
            return 2
        text = sys.stdin.read()

    findings: list[Finding] = []
    try:
        exclude = report_path.resolve() if report_path else None
        report = parse_report(text)
        receipts = load_receipts(findings)
        newest, newest_file = newest_source_mtime(ROOT, exclude)
        haystack = tree_text(ROOT, exclude)
        check_paths(report, findings)
        check_symbols(report, haystack, findings)
        check_numbers(report, receipts, findings)
        check_error_blocks(report, receipts, findings)
        check_green_claims(report, receipts, newest, newest_file, findings)
        check_contradicted_green(report, receipts, findings)
    except Exception as exc:                       # noqa: BLE001
        # Exit 2, never 1 and never 0: the gate broke, it did not judge.
        print(f"gate failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    allow = load_allowlist()
    findings = [f for f in findings
                if f.token not in allow and f"{f.check}:{f.token}" not in allow]

    if args.sarif:
        uri = report_path.name if report_path else "report"
        Path(args.sarif).write_text(json.dumps(to_sarif(findings, uri), indent=2),
                                    encoding="utf-8")

    print(f"report-truth: {len(receipts)} receipt(s) · "
          f"{len(cited_paths(report))} path(s), {len(cited_symbols(report))} symbol(s), "
          f"{len(cited_numbers(report))} number(s), {len(error_blocks(report))} error "
          f"block(s), {len(green_claims(report))} green claim(s)")
    for f in findings:
        print(f"  FAIL [{f.check}] line {f.line}: {f.message}")
    if findings:
        print(f"\n{len(findings)} finding(s)")
        return 1
    print("  every claim in the report is redeemable against the tree or a receipt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
