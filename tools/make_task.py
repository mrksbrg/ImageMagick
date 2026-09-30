#!/usr/bin/env python3
"""Write a campaign task file for one source file.

    python3 tools/make_task.py M01 MagickCore/resize.c
    python3 tools/make_task.py M02 MagickCore/compare.c --wave 4

The task file (docs/refactoring/tasks/<ID>-<name>.md) follows the 3SX format -
baseline, smells, target functions in waves, steps with their recipes - and adds
what the ImageMagick campaign knows per function and 3SX did not:

  - how many oracle cases execute the function (casemap.json), so a function
    the oracle cannot see is marked before anyone touches it;
  - what mutation testing found there, from every report in build-oracle/work;
  - whether the function is public (Recipe A is then forbidden) and whether it
    contains OpenMP regions (the playbook's extraction rule then applies).

Everything is measured at the time of writing, so the task file records the
baseline score and a stale task file is detectable: if the score an agent
measures differs, the file changed since.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "oracle"))
import casemap  # noqa: E402
import classify  # noqa: E402
import mutate   # noqa: E402
import oracle   # noqa: E402

DETAIL = {  # CodeScene detail strings -> the number in them
    "cc": re.compile(r"cc = (\d+)"),
    "bumps": re.compile(r"bumps = (\d+)"),
    "nesting": re.compile(r"Nesting depth = (\d+)"),
    "args": re.compile(r"Arguments = (\d+)"),
}


def review(rel):
    out = subprocess.run([sys.executable, os.path.join(REPO, "tools", "ch.py"), "--json", rel],
                         capture_output=True, text=True, check=True).stdout
    start = out.index("{")
    return json.loads(out[start:])[rel]


def add_details(info, details):
    """Keep the largest cc/bumps/nesting/args number seen for one function."""
    for key, rx in DETAIL.items():
        m = rx.search(details or "")
        if m:
            info[key] = max(info.get(key, 0), int(m.group(1)))


def per_function_smells(data):
    """{function title: {"line", "categories", "cc", "bumps", ...}}"""
    funcs = {}
    for cat in data.get("review", []):
        for f in cat.get("functions") or []:
            name = f["title"].split(":")[0]
            info = funcs.setdefault(name, {"line": f.get("start-line"), "categories": set()})
            info["categories"].add(cat["category"])
            add_details(info, f.get("details"))
    return funcs


def report_results(path, rel):
    """The results in one mutation report that belong to this file."""
    with open(path) as f:
        return [r for r in json.load(f) if r["file"].endswith("/" + rel)]


def mutation_results(rel):
    """Every mutation result for this file, newest report winning per mutant."""
    results = {}
    paths = sorted(glob.glob(os.path.join(oracle.WORK, "mutation-*.json")), key=os.path.getmtime)
    for path in paths:
        if path.endswith("partial.jsonl"):
            continue
        for r in report_results(path, rel):
            results[r["id"]] = r
    return list(results.values())


def structure_recipes(info):
    """Guard clauses, extraction and predicates: what nesting and branching call for."""
    steps = []
    if info.get("nesting", 0) >= 4:
        steps.append("**Recipe G (guard clauses)** - nesting is %d, target is under 4." % info["nesting"])
    if info.get("bumps"):
        steps.append("**Recipe E (extract function)** - %d nested blocks; each bump is a "
                     "missing function." % info["bumps"])
    if "Complex Conditional" in info["categories"] or "Complex Method" in info["categories"]:
        steps.append("**Recipe P (named predicate)** - move compound conditions into named "
                     "`MagickBooleanType` helpers.")
    return steps


def recipes_for(info, public):
    steps = structure_recipes(info)
    if "Large Method" in info["categories"] and not info.get("bumps"):
        steps.append("**Recipe E (extract function)** - a large method; extract its "
                     "self-contained blocks.")
    if info.get("args", 0) > 4:
        steps.append("Recipe A does not apply: this function is public, and its signature is "
                     "the API." if public else
                     "**Recipe A (parameter object)** - %d arguments; the function is `static`, "
                     "so check that its address is never taken." % info["args"])
    if "Code Duplication" in info["categories"]:
        steps.append("**Recipe D or C** - duplication: D only if the blocks differ in one value, "
                     "C for an identical contiguous run.")
    return steps


class Evidence(NamedTuple):
    """What is measured about the file before a row is built for any function."""
    base_src: list
    ranges: dict
    fmap: dict
    muts: list
    executed: dict


def base_source(rel):
    """The file at the base ref, split into lines."""
    # Function ranges, mutation results and survivor lines all come from the
    # base build, so they are read against the base source; once a file has
    # been refactored, its working-tree line numbers no longer match them.
    base_ref = oracle.BASE_REF if hasattr(oracle, "BASE_REF") else "origin/main"
    return subprocess.run(["git", "show", "%s:%s" % (base_ref, rel)], cwd=REPO,
                          capture_output=True, text=True, errors="replace").stdout.split("\n")


def gather_evidence(rel, base_src):
    ranges = {mutate.plain(n): (n, lo, hi) for n, f, lo, hi in
              mutate.function_ranges(re.escape(rel) + "$")}
    base_bin = oracle.build("base", "origin/main")
    _, cases = oracle.load_cases(base_bin)
    fmap = casemap.load_map(cases)
    muts = mutation_results(rel)
    verdicts = classify.verdict_kinds(muts, lambda m: base_src[m["line"] - 1])
    for m in muts:
        m["verdict"] = verdicts.get(m["id"])
    executed = mutate.executed_lines() or {}
    return Evidence(base_src, ranges, fmap, muts, executed)


def signature_line(name, lo, base_src):
    # CodeScene's start line often includes the comment block above the
    # function; the coverage mapping starts at the brace. The signature
    # is the nearest line above the brace that names the function.
    return next((n for n in range(lo, max(lo - 8, 1), -1)
                 if re.search(r"\b%s\(" % re.escape(name), base_src[n - 1])), lo)


def mutants_in(lo, hi, ev):
    """The sampled mutants in lines lo..hi, how many were killed, and the survivors
    on lines the oracle executes."""
    mine = [m for m in ev.muts if lo <= m["line"] <= hi]
    killed = sum(1 for m in mine if m["status"] == "killed")
    survived = [m for m in mine if m["status"] == "survived"
                and m["line"] in ev.executed.get(m["file"], ())]
    return mine, killed, survived


def function_row(name, info, ev):
    compiled = name in ev.ranges
    full, lo, hi = ev.ranges.get(name, (name, info["line"] or 0, info["line"] or 0))
    public = ":" not in full and ";" not in full
    if compiled:
        info["line"] = signature_line(name, lo, ev.base_src)
    omp = sum(1 for line in ev.base_src[lo - 1:hi] if "#pragma omp" in line)
    reach = len(casemap.cases_for(name, ev.fmap))
    mine, killed, survived = mutants_in(lo, hi, ev)
    weight = info.get("cc", 0) + 5 * info.get("bumps", 0) + 5 * info.get("nesting", 0)
    return dict(name=name, line=info["line"], info=info, public=public, omp=omp,
                compiled=compiled,
                reach=reach, killed=killed, survived=survived, sampled=len(mine),
                weight=weight, lo=lo, hi=hi)


def measured_with():
    return "| Measured with | `cs-mcp` %s, `cs` %s |" % (
        subprocess.run(["cs-mcp", "--version"], capture_output=True, text=True).stdout.strip(),
        subprocess.run(["cs", "version"], capture_output=True, text=True).stdout.split("\n")[0]
        .replace("cs version ", "").split(" ")[0])


def intro(args, data, file_lines, functions):
    """Title, the baseline table and sections 1-3."""
    rel = args.file
    out = []
    w = out.append
    w("# %s - refactor `%s`\n" % (args.task_id, rel))
    w("| Field | Value |\n| --- | --- |")
    w("| Baseline Code Health | **%.2f** / 10 |" % data["score"])
    w("| Exit target | **plateau** - no legal recipe raises the score further; record it |")
    w("| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |")
    w("| File size | %d lines |" % file_lines)
    w("| Functions with findings | %d |" % functions)
    w(measured_with())
    w("")
    w("## 1. Read these first\n")
    w("- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification "
      "sequence.")
    w("- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the "
      "rules for OpenMP regions and public functions.")
    w("- [`../README.md`](../README.md) - campaign rules and the definition of done.\n")
    w("## 2. Record the baseline before touching anything\n")
    w("```bash\npython3 tools/ch.py --review %s\n```\n" % rel)
    w("The score must read %.2f. If it does not, this file changed after the task was "
      "written: stop and report that instead of proceeding.\n" % data["score"])
    w("## 3. What CodeScene flags here\n")
    w("| Smell | Functions |\n| --- | ---: |")
    for cat in data.get("review", []):
        w("| %s | %s |" % (cat["category"], len(cat.get("functions") or []) or "file"))
    w("")
    return out


def killed_cell(r):
    tried = r["killed"] + len(r["survived"])
    return "%d of %d" % (r["killed"], tried) if tried else "-"


def linkage_cell(r):
    if not r["compiled"]:
        return "not compiled"
    return "public" if r["public"] else "static"


def target_table(targets):
    """Section 4."""
    out = []
    w = out.append
    w("## 4. Target functions, highest leverage first\n")
    w("| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | "
      "Mutants killed |")
    w("| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |")
    for i, r in enumerate(targets, 1):
        info = r["info"]
        w("| %d | `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            i, r["name"], r["line"], info.get("cc", "-"), info.get("nesting", "-"),
            info.get("bumps", "-"), linkage_cell(r),
            r["omp"] or "-", r["reach"] if r["compiled"] else "-", killed_cell(r)))
    w("")
    w("Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is "
      "how many oracle cases execute the function; **Mutants killed** counts the sampled "
      "mutants on lines the oracle executes. A function with no cases cannot be checked and "
      "is listed last: skip it and report it.\n")
    return out


def unchecked_note(r):
    """Why a step must not be taken at all, or None when the oracle can check it."""
    if not r["compiled"]:
        return ("- **This function is not compiled in this build** (it sits in a "
                "preprocessor branch for a platform or a library that is not present). "
                "Nothing can check it here. Do not change it.\n")
    if r["reach"] == 0:
        return ("- **No oracle case executes this function. Do not change it.** Report it so "
                "cases can be added.\n")
    return None


def caution_lines(r):
    """OpenMP, public linkage and thin coverage."""
    out = []
    if r["omp"]:
        out.append("- Contains %d OpenMP pragma(s): only blocks inside a loop body that write no "
                   "variable declared outside it may be extracted. Never move or edit a pragma."
                   % r["omp"])
    if r["public"]:
        out.append("- Public function: its name and signature must not change.")
    if r["reach"] < 10:
        out.append("- Only %d oracle case(s) execute this function, so the oracle sees little of "
                   "it. Consider adding cases before a structural change." % r["reach"])
    return out


def survivor_kinds(survived, base_src):
    """{classify kind: [surviving mutants]}"""
    kinds = {}
    for m in survived:
        after = " ".join(base_src[m["line"]:m["line"] + 2])
        kinds.setdefault(classify.kind_of(dict(m, line_executed=True),
                                          base_src[m["line"] - 1].strip(), after,
                                          m.get("verdict")), []).append(m)
    return kinds


def gap_lines(gaps, name, base_src):
    out = ["- The oracle missed %d sampled mutant(s) here that are not of a known "
           "harmless kind. Take extra care on these lines, and consider closing the gap "
           "first:" % len(gaps)]
    for m in gaps[:6]:
        code = base_src[m["line"] - 1].strip()[:80]
        out.append("  - base line %d, `%s`: `%s`" % (m["line"], m["mutator"][4:], code))
    if len(gaps) > 6:
        out.append("  - and %d more (`tools/oracle/mutate.py --function %s`)" % (
            len(gaps) - 6, name))
    return out


def survivor_lines(r, base_src):
    """What the surviving mutants say about the function."""
    kinds = survivor_kinds(r["survived"], base_src)
    open_kinds = ("unmatched", "gap", "unresolved")
    harmless = sum(len(v) for k, v in kinds.items() if k not in open_kinds)
    gaps = sorted((m for k in open_kinds for m in kinds.get(k, [])), key=lambda m: m["line"])
    out = gap_lines(gaps, r["name"], base_src) if gaps else []
    if harmless:
        out.append("- %d further survivor(s) are of kinds the oracle cannot see by design "
                   "(logging, loop bounds over padding, allocation sizes, or read by hand and "
                   "found equivalent; see `tools/oracle/classify.py`)." % harmless)
    return out


def step_lines(r, step, base_src, rel):
    out = ["#### Step %d: `%s` (line %s)\n" % (step, r["name"], r["line"])]
    note = unchecked_note(r)
    if note:
        return out + [note]
    out += ["- " + s for s in recipes_for(r["info"], r["public"])]
    out += caution_lines(r)
    out += survivor_lines(r, base_src)
    out.append("\nCommit message: `refactor(%s): simplify %s`\n" % (rel, r["name"]))
    return out


def steps_section(targets, per_wave, base_src, rel):
    """Section 5: the targets in waves of `per_wave`."""
    out = ["## 5. Steps\n",
           "Work **one function at a time, in the order above**, and run the verification in "
           "section 6 after each commit. Re-run the review at the start of each wave: line "
           "numbers shift as earlier waves land.\n"]
    step = 0
    for wave in range(0, len(targets), per_wave):
        out.append("### Wave %d%s\n" % (wave // per_wave + 1, " - start here" if wave == 0 else ""))
        for r in targets[wave:wave + per_wave]:
            step += 1
            out += step_lines(r, step, base_src, rel)
    return out


def closing(rel):
    """Sections 6 and 7."""
    out = []
    w = out.append
    w("## 6. Verification after every commit\n")
    w("```bash\ntools/oracle/build.sh cand\npython3 tools/refactor_guard.py %s   # --calls "
      "after E, C, X\npython3 tools/oracle/oracle.py run --function <Function>\npython3 "
      "tools/ch.py --review %s\n```\n" % (rel, rel))
    w("Name the function you refactored in the oracle run, not a helper you extracted from "
      "it. If the guard fails or the oracle diverges, `git checkout -- %s` and stop.\n" % rel)
    w("Before the branch is pushed: `python3 tools/oracle/oracle.py run`.\n")
    w("## 7. Report\n")
    w("For each function: the recipes applied, the score before and after, and the review "
      "lines that changed. For the file: where it plateaued, and which smells are left.")
    return out


def write_task(task_id, rel, out):
    os.makedirs(os.path.join(REPO, "docs", "refactoring", "tasks"), exist_ok=True)
    name = os.path.splitext(os.path.basename(rel))[0]
    path = os.path.join(REPO, "docs", "refactoring", "tasks", "%s-%s.md" % (task_id, name))
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", os.path.relpath(path, REPO))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_id")
    ap.add_argument("file", help="path relative to the repository, e.g. MagickCore/resize.c")
    ap.add_argument("--wave", type=int, default=4, help="functions per wave")
    ap.add_argument("--targets", type=int, default=12, help="functions to list")
    args = ap.parse_args()
    rel = args.file
    src = open(os.path.join(REPO, rel), errors="replace").read().split("\n")
    base_src = base_source(rel)

    data = review(rel)
    smells = per_function_smells(data)
    ev = gather_evidence(rel, base_src)
    rows = [function_row(name, info, ev) for name, info in smells.items()]
    # Highest leverage first; the oracle must be able to see a function to work on it.
    rows.sort(key=lambda r: (not r["compiled"], r["reach"] == 0, -r["weight"]))
    targets = rows[:args.targets]

    out = intro(args, data, len(src), len(rows))
    out += target_table(targets)
    out += steps_section(targets, args.wave, base_src, rel)
    out += closing(rel)
    write_task(args.task_id, rel, out)


if __name__ == "__main__":
    sys.exit(main())
