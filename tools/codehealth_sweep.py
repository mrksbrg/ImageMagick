#!/usr/bin/env python3
"""Sweep every first-party source file through CodeScene Code Health.

Drives the CodeScene MCP server (cs-mcp) over stdio and records a Code Health
score per file, so campaign progress can be compared against a committed
baseline. See docs/refactoring/README.md.

    python3 tools/codehealth_sweep.py                        # every subsystem
    python3 tools/codehealth_sweep.py --only MagickCore/     # one subsystem
    python3 tools/codehealth_sweep.py -o docs/refactoring/codehealth-current.json

Adapted from the 3SX campaign's sweep, so the two record the same thing.

The server is asked for scores in small chunks. Sending all files in one
session makes the CodeScene CLI die with java.lang.OutOfMemoryError, because
the server answers requests concurrently and spawns a CLI process per request.

Requires CS_ACCESS_TOKEN in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ImageMagick's own code: the four subsystems plus the filter modules and the
# command-line entry points. Tests, fuzzers, demos, PerlMagick, API examples
# and the website are left out: none of them is part of the library.
SUBSYSTEMS = (
    "MagickCore/",
    "MagickWand/",
    "coders/",
    "Magick++/lib/",
    "filters/",
    "utilities/",
)
EXCLUDE_PREFIXES = ()

SCORE_RE = re.compile(r"Code Health score:\s*([0-9.]+)")
CHUNK_DEFAULT = 16
RETRY_CHUNK = 4


def find_binary() -> str:
    """Locate the cs-mcp binary, preferring an explicit override."""
    override = os.environ.get("CS_MCP_BINARY_PATH")
    if override:
        if not Path(override).is_file():
            sys.exit("CS_MCP_BINARY_PATH is set but does not exist: " + override)
        return override

    on_path = shutil.which("cs-mcp")
    if on_path:
        return on_path

    try:
        npm_root = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True, shell=(os.name == "nt")
        ).stdout.strip()
    except OSError:
        npm_root = ""

    if npm_root:
        pkg = Path(npm_root) / "@codescene" / "codehealth-mcp"
        cache = pkg / ".cache"
        if cache.is_dir():
            for version_dir in sorted(cache.iterdir(), reverse=True):
                for candidate in ("cs-mcp.exe", "cs-mcp"):
                    exe = version_dir / candidate
                    if exe.is_file():
                        return str(exe)

    sys.exit(
        "Could not find cs-mcp. Install it with:\n"
        "  npm install -g @codescene/codehealth-mcp\n"
        "then run it once, or set CS_MCP_BINARY_PATH."
    )


def candidates() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True
    ).stdout
    files = []
    for line in out.splitlines():
        path = line.strip()
        if not path.endswith((".c", ".cpp")):
            continue
        if not path.startswith(SUBSYSTEMS) or path.startswith(EXCLUDE_PREFIXES):
            continue
        files.append(path)
    return sorted(files)


def run_chunk(exe: str, paths: list[str], first_id: int) -> tuple[dict[int, str], dict[int, str]]:
    """Score one chunk. Returns ({request id: response text}, {request id: path})."""
    lines = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "codehealth-sweep", "version": "1.0.0"},
                },
            }
        ),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    ]
    ids = {}
    for offset, rel in enumerate(paths):
        rid = first_id + offset
        ids[rid] = rel
        lines.append(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "method": "tools/call",
                    "params": {
                        "name": "code_health_score",
                        # Forward slashes: backslashes get mangled through several layers.
                        "arguments": {"file_path": str(REPO).replace(os.sep, "/") + "/" + rel},
                    },
                }
            )
        )
    stdin = "\n".join(lines) + "\n"

    env = dict(os.environ, CS_DISABLE_VERSION_CHECK="1")
    proc = subprocess.run(
        [exe], input=stdin, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace"
    )
    if "OutOfMemoryError" in (proc.stderr or ""):
        sys.exit("CodeScene CLI ran out of memory. Retry with a smaller --chunk.")

    out = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = msg.get("id")
        if rid not in ids:
            continue
        result = msg.get("result", {})
        text = " ".join(c.get("text", "") for c in result.get("content", []))
        out[rid] = "" if (result.get("isError") or "error" in msg) else text
    return {rid: out.get(rid, "") for rid in ids}, ids


FAILURE_MARKERS = ("error", "Error", "ERROR", "exception", "Exception", "OutOfMemory",
                   "timed out", "timeout", "Unauthorized", "not authenticated")


def looks_like_failure(text: str | None) -> bool:
    """A response that is not a score and not silence: the server said something."""
    return bool(text) and any(m in text for m in FAILURE_MARKERS)


def check_the_sweep_is_whole(output: str, scores: dict, unscorable: list, failed: list) -> None:
    """Refuse to overwrite a good sweep with a broken one.

    A file the server never answered for is indistinguishable, here, from a data
    table with no functions in it: both arrive without a score line. That is
    fine when it is a handful of data tables and ruinous when the CLI has died
    part-way, because the result still looks like a sweep - it just quietly
    reports four fifths of the repository as unscorable, and whoever reads the
    band table next believes it.

    So: any response that carried an error is fatal, and a scored count that has
    collapsed against the file being replaced is fatal. Neither is a judgement
    about the code; both mean the run did not happen.
    """
    if failed:
        for rel, text in failed[:5]:
            print("  " + rel + ": " + text, file=sys.stderr)
        sys.exit("%d files came back with an error; refusing to write %s" % (len(failed), output))

    # A file the committed baseline scored has functions; silence from it is
    # a request the server dropped (seen with the largest files under load),
    # not a data table.
    baseline = REPO / "docs" / "refactoring" / "codehealth-baseline.json"
    if baseline.is_file() and Path(output).resolve() != baseline.resolve():
        known = {r["path"] for r in json.loads(baseline.read_text()).get("scores", [])}
        dropped = sorted(set(unscorable) & known)
        if dropped:
            sys.exit("%d files the baseline scored came back without a score (%s); "
                     "refusing to write %s. Run again when the machine is idle."
                     % (len(dropped), ", ".join(dropped[:5]), output))

    previous = Path(output)
    if not previous.is_file():
        return
    try:
        was = json.loads(previous.read_text())
    except ValueError:
        return
    before = was.get("scored", 0)
    if before and len(scores) < before * 0.9:
        sys.exit(
            "scored %d files against %d in the file being replaced, and %d came back without a "
            "score. That is a run that died, not a repository that changed; %s is left alone."
            % (len(scores), before, len(unscorable), output)
        )


def tool_version(argv: list[str]) -> str:
    """First line of a tool's version output, minus update notices."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    lines = [l for l in out.splitlines() if l.strip() and "New version" not in l
             and not l.startswith("Use `cs")]
    return lines[0].strip() if lines else "unknown"


def band(score: float) -> str:
    if score >= 10.0:
        return "optimal"
    if score >= 9.0:
        return "green"
    if score >= 4.0:
        return "yellow"
    return "red"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output",
                    default=str(REPO / "docs" / "refactoring" / "codehealth-current.json"))
    ap.add_argument("--only", help="only files under this path prefix, e.g. MagickCore/")
    ap.add_argument("--chunk", type=int, default=CHUNK_DEFAULT,
                    help="files per server invocation (default %(default)s)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.environ.get("CS_ACCESS_TOKEN"):
        print("warning: CS_ACCESS_TOKEN is not set; standalone analysis only", file=sys.stderr)

    exe = find_binary()
    files = [f for f in candidates() if not args.only or f.startswith(args.only)]
    if not args.quiet:
        print("cs-mcp:  " + exe)
        print("scoring: " + str(len(files)) + " files in chunks of " + str(args.chunk))

    scores, unscorable, failed = {}, [], []
    for start in range(0, len(files), args.chunk):
        chunk = files[start:start + args.chunk]
        responses, ids = run_chunk(exe, chunk, 100 + start)
        for rid, text in responses.items():
            rel = ids[rid]
            match = SCORE_RE.search(text or "")
            if match:
                scores[rel] = float(match.group(1))
            elif looks_like_failure(text):
                failed.append((rel, " ".join((text or "").split())[:120]))
            else:
                unscorable.append(rel)
        if not args.quiet:
            done = min(start + args.chunk, len(files))
            print("  " + str(done) + "/" + str(len(files)), end="\r", flush=True)

    if not args.quiet:
        print(" " * 40, end="\r")

    # A file that came back silent is usually a data table, but under load it is
    # sometimes a request the server dropped. Ask again, in small chunks, before
    # believing the silence. Two sweeps in a row lost a third of the repository
    # this way while eight agents were scoring concurrently.
    if unscorable:
        retry, unscorable = unscorable, []
        if not args.quiet:
            print("re-asking for " + str(len(retry)) + " silent files")
        for start in range(0, len(retry), RETRY_CHUNK):
            responses, ids = run_chunk(exe, retry[start:start + RETRY_CHUNK], 900000 + start)
            for rid, text in responses.items():
                rel = ids[rid]
                match = SCORE_RE.search(text or "")
                if match:
                    scores[rel] = float(match.group(1))
                elif looks_like_failure(text):
                    failed.append((rel, " ".join((text or "").split())[:120]))
                else:
                    unscorable.append(rel)

    check_the_sweep_is_whole(args.output, scores, unscorable, failed)

    # Counted here rather than before the retry: the retry adds scores, and a
    # band table taken ahead of it reports the file count it had at the time.
    counts = {"red": 0, "yellow": 0, "green": 0, "optimal": 0}
    for value in scores.values():
        counts[band(value)] += 1

    by_subsystem = {}
    for rel, value in scores.items():
        top = next((s for s in SUBSYSTEMS if rel.startswith(s)), "other")
        by_subsystem.setdefault(top, []).append(value)

    payload = {
        # Scores move between CodeScene versions, so a sweep says which it used.
        "date": time.strftime("%Y-%m-%d"),
        "cs_mcp_version": tool_version([exe, "--version"]),
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                                 capture_output=True, text=True).stdout.strip(),
        "only": args.only,
        "total_candidates": len(files),
        "scored": len(scores),
        "unscorable": len(unscorable),
        "bands": counts,
        "mean": round(sum(scores.values()) / max(len(scores), 1), 2),
        "subsystems": {
            name: {"files": len(v), "mean": round(sum(v) / len(v), 2),
                   "bands": {b: sum(1 for x in v if band(x) == b)
                             for b in ("red", "yellow", "green", "optimal")}}
            for name, v in sorted(by_subsystem.items())},
        "scores": [{"path": p, "score": s} for p, s in sorted(scores.items(), key=lambda kv: kv[1])],
        "unscorable_files": sorted(unscorable),
    }
    Path(args.output).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print("scored " + str(len(scores)) + " files (" + str(len(unscorable)) + " unscorable - data tables)")
    total = max(len(scores), 1)
    for name in ("red", "yellow", "green", "optimal"):
        n = counts[name]
        print("  " + name.ljust(8) + str(n).rjust(4) + "  " + format(100.0 * n / total, "5.1f") + "%")
    for name, info in payload["subsystems"].items():
        print("  %-14s %4d files  mean %5.2f  red %d yellow %d green %d optimal %d" % (
            name, info["files"], info["mean"], info["bands"]["red"], info["bands"]["yellow"],
            info["bands"]["green"], info["bands"]["optimal"]))
    print("wrote " + args.output)

    worst = payload["scores"][:5]
    if worst:
        print("worst files:")
        for row in worst:
            print("  " + format(row["score"], "5.2f") + "  " + row["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
