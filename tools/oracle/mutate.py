#!/usr/bin/env python3
"""Mutation testing of the differential oracle with Mull.

    tools/oracle/build.sh mull 'MagickCore/resize\\.c$'
    tools/oracle/casemap.py
    tools/oracle/mutate.py --file 'MagickCore/resize\\.c$' [--function NAME] [--limit N]

A sweep over several files shares one build and samples each file equally:

    tools/oracle/build.sh mull 'MagickCore/(draw|fx|pixel)\\.c$' top3
    tools/oracle/mutate.py --file 'MagickCore/(draw|fx|pixel)\\.c$' --name top3 --per-file 100

A Mull build compiles every mutant of the selected files into one `magick`,
each behind a switch: the environment variable named by the mutant's id
(`cxx_add_to_sub:/abs/path/file.c:LINE:COL:LINE:COL`). With no switch set the
binary behaves like the original, so that same binary is the baseline and no
compiler or flag difference can masquerade as a kill.

For each mutant the driver runs only the cases that execute the mutant's
function (from casemap.json), cheapest first, and stops at the first
divergence:

  killed       some case diverged (a different output, a crash or a timeout)
  survived     every case that reaches the function gave identical results
  no-coverage  no case executes the function; the oracle cannot see it at all
  error        the driver itself failed on this mutant (kept, not guessed)

Each result is appended to build-oracle/work/mutation-<name>.partial.jsonl as
it arrives, and a rerun with the same arguments skips mutants already there,
so a crash or reboot costs only the mutants in flight.

A function that most cases execute (ReadBlob, AcquireImage, ...) would make
every survivor there cost a full oracle run, so at most --max-cases cases are
tried per mutant. Cases that killed mutants in earlier runs (any
build-oracle/work/mutation-*.json) go first, most kills first: in the 25-file
sweep, a few dozen cases did most of the killing, and they were often
expensive ones that cheapest-first reached too late. The rest follow as the
cheapest of each case family in turn, so every family gets a chance to kill it. A kill is exact either way; a survivor that hit the
cap is flagged `capped`, meaning the remaining cases never ran on it.

A survivor is either an equivalent mutant or a gap in the catalogue, and only
reading it tells which. The report lists survivors with their source line,
and splits them by whether the oracle executes that line at all (from
build-oracle/oracle.lcov, the coverage run described in ORACLE.md).
"""

import argparse
import concurrent.futures
import glob
import hashlib
import json
import shutil
import os
import random
import resource
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casemap  # noqa: E402
import oracle   # noqa: E402

MUTANT_ID = re.compile(r"^([a-z_]+):(/[^:]+):(\d+):(\d+):(\d+):(\d+)$")
LLVM_COV = "/Library/Developer/CommandLineTools/usr/bin/llvm-cov"
# A mutant that loops forever should cost seconds, not minutes, but a case that
# is merely slow must not time out and pass for a kill. Mull builds run every
# case several times slower than a normal build (one case takes 9.4 s), so a
# fixed 10 s limit once produced hundreds of false kills. A mutant gets
# MUTANT_TIMEOUT_FACTOR times the case's own baseline time, within these bounds.
MUTANT_TIMEOUT = 10
MUTANT_TIMEOUT_FACTOR = 4
MUTANT_TIMEOUT_MAX = 60
# Even so, `-sketch` on 8 busy cores once ran past 4x its baseline and gave six
# false kills; a timeout is therefore rerun once with this limit before it
# counts. A mutant that really loops forever costs this much, once.
MUTANT_TIMEOUT_CONFIRM = 120
LCOV = os.path.join(oracle.OUT, "oracle.lcov")


def list_mutants(binary, file_regex):
    out = subprocess.run(["strings", "-a", binary], stdout=subprocess.PIPE, check=True)
    rx, seen = re.compile(file_regex), set()
    mutants = []
    for line in out.stdout.decode(errors="replace").splitlines():
        m = MUTANT_ID.match(line.strip())
        if m and rx.search(m.group(2)) and line not in seen:
            seen.add(line)
            mutants.append({"id": line.strip(), "mutator": m.group(1), "file": m.group(2),
                            "line": int(m.group(3)), "col": int(m.group(4))})
    return sorted(mutants, key=lambda m: (m["file"], m["line"], m["col"], m["mutator"]))


def function_ranges(file_regex):
    """(name, file, first line, last line) for every function in the matching
    files, from the coverage build's mapping."""
    cov_bin = os.path.join(oracle.OUT, "cov", "utilities", "magick")
    prof = os.path.join(oracle.OUT, "oracle.profdata")
    out = subprocess.run([LLVM_COV, "export", "-skip-expansions", cov_bin,
                          "-instr-profile=" + prof], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, check=True).stdout
    rx, ranges = re.compile(file_regex), []
    for fn in json.loads(out)["data"][0]["functions"]:
        if not fn["filenames"] or not rx.search(fn["filenames"][0]):
            continue
        regions = [r for r in fn["regions"] if r[5] == 0]  # file id 0: the function's own file
        if regions:
            ranges.append((fn["name"], fn["filenames"][0], min(r[0] for r in regions),
                           max(r[2] for r in regions)))
    return ranges


def executed_lines():
    """{absolute source path: set of lines the oracle executes}, or None
    without a coverage run."""
    if not os.path.exists(LCOV):
        return None
    lines, current = {}, None
    with open(LCOV) as f:
        for row in f:
            if row.startswith("SF:"):
                current = lines.setdefault(row[3:].strip(), set())
            elif row.startswith("DA:"):
                n, hits = row[3:].split(",")[:2]
                if int(hits) > 0:
                    current.add(int(n))
    return lines


def enclosing(mutant, ranges):
    best = None
    for name, f, lo, hi in ranges:
        if os.path.basename(f) == os.path.basename(mutant["file"]) and lo <= mutant["line"] <= hi:
            if best is None or hi - lo < best[1]:
                best = (name, hi - lo)
    return best[0] if best else None


def plain(name):
    """`resize.c:Triangle` or `file.c;Triangle` -> `Triangle`."""
    return re.split(r"[;:]", name)[-1]


def sandbox(binary):
    """A sandbox-exec prefix that lets a mutant run magick and write under
    build-oracle/, and nothing else.

    delegate.c runs the commands in delegates.xml: lpr, `open -a Preview`,
    curl, gimp, `... ; /bin/rm`. The case catalogue never asks for those, but
    a mutant can skip the check that stops them (policy.c is mutated too), and
    it would then print, open windows or use the network on the real machine.
    The operating system enforces this profile, so no mutant can switch it off.
    """
    out = os.path.realpath(oracle.OUT)
    profile = ("(version 1)(allow default)"
               "(deny process-exec)(allow process-exec (literal \"%s\"))"
               "(deny network*)"
               "(deny file-write*)(allow file-write* (subpath \"%s\")"
               " (literal \"/dev/null\") (literal \"/dev/tty\") (literal \"/dev/dtracehelper\"))"
               % (os.path.realpath(binary), out))
    return ["/usr/bin/sandbox-exec", "-p", profile]


def kill_counts(exclude):
    """{case id: mutants it killed} over earlier mutation reports."""
    counts = {}
    for path in glob.glob(os.path.join(oracle.WORK, "mutation-*.json")):
        if os.path.basename(path) == exclude:
            continue
        with open(path) as f:
            for r in json.load(f):
                # A timeout says the mutant was slower, not which case sees
                # its behaviour; ranking by those would favour slow cases.
                if r["status"] == "killed" and "timeout" not in r.get("why", ""):
                    counts[r["killer"]] = counts.get(r["killer"], 0) + 1
    return counts


def spread(ids, n):
    """n of the cost-sorted ids, taking the cheapest remaining case of each
    family (`morphology/...`) in turn."""
    queues = {}
    for i in ids:
        queues.setdefault(i.split("/")[0], []).append(i)
    queues, picked = list(queues.values()), []
    while len(picked) < min(n, len(ids)):
        for q in queues:
            if q and len(picked) < n:
                picked.append(q.pop(0))
    return picked


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", required=True, help="regex selecting the mutated source file(s)")
    p.add_argument("--bin", help="Mull build (default: from --name or --file, as build.sh names it)")
    p.add_argument("--name", help="the name given to build.sh mull; also names the report")
    p.add_argument("--function", help="only mutants inside this function")
    p.add_argument("--limit", type=int, help="random sample of this many mutants")
    p.add_argument("--ids", help="file listing mutant ids to run, one per line (e.g. to recheck survivors)")
    p.add_argument("--per-file", type=int, help="random sample of this many mutants per file")
    p.add_argument("--cases", help="only cases whose id matches this regex, e.g. '^infra/' to "
                   "ask whether new cases kill what the old ones missed")
    p.add_argument("--max-cases", type=int, default=300,
                   help="cases tried per mutant, spread over case families (0: all)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    args = p.parse_args()

    slug = args.name or re.sub(r"[^A-Za-z0-9]", "_", args.file)
    binary = os.path.abspath(args.bin or os.path.join(oracle.OUT, "mull-" + slug,
                                                      "utilities", "magick"))
    base_bin = oracle.build("base", "origin/main")  # only for the corpus and option lists
    oracle.WRAPPER = sandbox(binary)  # baseline and mutants alike
    # No child may write a file over 2 GB (it gets SIGXFSZ instead): a
    # runaway mutant must not fill the disk. Children inherit the limit.
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 << 30, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))
    manifest, cases = oracle.load_cases(base_bin)
    by_id = {c["id"]: c for c in cases}
    fmap = casemap.load_map(cases)
    ranges = function_ranges(args.file)

    mutants = list_mutants(binary, args.file)
    for m in mutants:
        m["function"] = enclosing(m, ranges)
    if args.function:
        mutants = [m for m in mutants if m["function"] and plain(m["function"]) == args.function]
    if args.ids:
        with open(args.ids) as f:
            wanted = {line.strip() for line in f if line.strip()}
        mutants = [m for m in mutants if m["id"] in wanted]
    if args.per_file:
        rng, by_file = random.Random(args.seed), {}
        for m in mutants:
            by_file.setdefault(m["file"], []).append(m)
        mutants = [m for f in sorted(by_file) for m in
                   (rng.sample(by_file[f], args.per_file)
                    if len(by_file[f]) > args.per_file else by_file[f])]
    if args.limit and len(mutants) > args.limit:
        mutants = random.Random(args.seed).sample(mutants, args.limit)
    mutants.sort(key=lambda m: (m["file"], m["line"], m["col"], m["mutator"]))
    # casemap.json and llvm-cov spell names the same way (`resize.c:Triangle`
    # for statics), so an exact lookup cannot confuse two files' statics.
    relevant = {m["function"]: fmap.get(m["function"], []) for m in mutants if m["function"]}
    if args.cases:
        keep = re.compile(args.cases)
        relevant = {f: [i for i in ids if keep.search(i)] for f, ids in relevant.items()}
    print("mutate: %d mutants in %s, %d functions" % (len(mutants), args.file, len(relevant)))

    # Baseline: the same binary with no mutant switched on.
    # Kept per binary, catalogue and way of running (the wrapper), so a
    # resumed run does not spend minutes recomputing it. The wrapper is in the
    # key because adding the sandbox changed two cases' stderr, and a cache
    # from before it turned those into 28 false kills.
    needed = sorted({cid for ids in relevant.values() for cid in ids})
    start = time.time()
    wrap = hashlib.sha1(json.dumps(oracle.WRAPPER).encode()).hexdigest()[:8]
    cache_file = oracle.cache_path(binary, manifest).replace(".json", "") + "-mull-%s.json" % wrap
    base = {}
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            base = {i: r for i, r in json.load(f).items() if "timeout" not in r["rc"]}
    todo = [by_id[i] for i in needed if i not in base]
    if todo:
        base.update(oracle.parallel(lambda c: oracle.run_case(binary, "mbase-" + slug, c, manifest),
                                    todo, args.jobs, "baseline"))
        with open(cache_file, "w") as f:
            json.dump(base, f)
    base = {i: base[i] for i in needed}
    unstable = sorted(i for i in needed if "timeout" in base[i]["rc"])
    for i in unstable:  # a case that times out unmutated can kill nothing honestly
        base.pop(i)
    shutil.rmtree(os.path.join(oracle.WORK, "runs", "mbase-" + slug), ignore_errors=True)
    print("mutate: baseline over %d cases in %.0fs" % (len(needed), time.time() - start))

    kills = kill_counts("mutation-%s.json" % slug)

    def test(m):
        ids = [i for i in relevant.get(m["function"], []) if i in base]
        if not ids:
            return dict(m, status="no-coverage", cases=0)
        ids.sort(key=lambda i: base[i]["secs"])  # cheap cases first: most kills are early
        capped = bool(args.max_cases) and len(ids) > args.max_cases
        if capped:
            proven = sorted((i for i in ids if kills.get(i)), key=lambda i: -kills[i])
            proven = proven[:args.max_cases]
            chosen = set(proven)
            ids = proven + spread([i for i in ids if i not in chosen],
                                  args.max_cases - len(proven))
        side = "mut-" + hashlib.sha1(m["id"].encode()).hexdigest()[:10]  # one dir per mutant
        try:
            for n, i in enumerate(ids, 1):
                limit = min(MUTANT_TIMEOUT_MAX,
                            max(MUTANT_TIMEOUT, MUTANT_TIMEOUT_FACTOR * base[i]["secs"]))
                r = oracle.run_case(binary, side, by_id[i], manifest, {m["id"]: "1"}, limit)
                if "timeout" in r["rc"]:
                    # Under a full load a slow case can overrun even a scaled
                    # limit; only a mutant that still hangs is a kill.
                    r = oracle.run_case(binary, side, by_id[i], manifest, {m["id"]: "1"},
                                        MUTANT_TIMEOUT_CONFIRM)
                if not oracle.same(base[i], r):
                    return dict(m, status="killed", cases=n, killer=i,
                                why="; ".join(oracle.explain(base[i], r))[:200])
            return dict(m, status="survived", cases=len(ids), capped=capped)
        finally:
            shutil.rmtree(os.path.join(oracle.WORK, "runs", side), ignore_errors=True)

    started_log = os.path.join(oracle.WORK, "mutation-%s.started" % slug)

    def guarded(m):
        # A mutant that started but never finished is the one to suspect if
        # the driver itself dies.
        with open(started_log, "a") as f:
            f.write(m["id"] + "\n")
        try:
            return test(m)
        except Exception as e:  # one bad mutant must not lose hours of results
            return dict(m, status="error", why=repr(e)[:200])

    partial = os.path.join(oracle.WORK, "mutation-%s.partial.jsonl" % slug)
    results = []
    if os.path.exists(partial):
        wanted = {m["id"] for m in mutants}
        with open(partial) as f:
            results = [r for r in map(json.loads, f) if r["id"] in wanted]
        done_ids = {r["id"] for r in results}
        mutants = [m for m in mutants if m["id"] not in done_ids]
        print("mutate: resuming, %d mutants already done" % len(results))
    start, done = time.time(), len(results)
    total = done + len(mutants)
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool, open(partial, "a") as log:
        # As each finishes, not in submission order: one slow mutant once held
        # back 50 finished results for most of an hour, unsaved.
        futures = [pool.submit(guarded, m) for m in mutants]
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            log.flush()
            done += 1
            if done % 25 == 0 or done == total:
                sys.stderr.write("  mutants: %d/%d (%.0fs)\n" % (done, total, time.time() - start))
    results.sort(key=lambda m: (m["file"], m["line"], m["col"], m["mutator"]))
    report(results, args, slug, time.time() - start)


def report(results, args, slug, elapsed):
    executed = executed_lines()
    for r in results:
        if r["status"] == "survived" and executed is not None:
            r["line_executed"] = r["line"] in executed.get(r["file"], ())
    count = lambda s: sum(1 for r in results if r["status"] == s)
    killed, survived, nocov = count("killed"), count("survived"), count("no-coverage")
    reached = killed + survived
    print("\nmutate: %d mutants, %.0fs" % (len(results), elapsed))
    print("  killed %d, survived %d (%d capped), no coverage %d, errors %d" % (
        killed, survived, sum(1 for r in results if r.get("capped")), nocov, count("error")))
    if reached:
        print("  mutation score on reached code: %.1f%%   overall: %.1f%%"
              % (100.0 * killed / reached, 100.0 * killed / len(results)))
    files = sorted({r["file"] for r in results})
    if len(files) > 1:
        print("\n  %-18s %5s %6s %8s %6s %7s %8s %8s" % (
            "file", "total", "killed", "survived", "no-cov", "exec'd", "reached", "overall"))
        for f in sorted(files, key=lambda f: file_score(results, f)):
            rs = [r for r in results if r["file"] == f]
            c = lambda s: sum(1 for r in rs if r["status"] == s)
            k, sv = c("killed"), c("survived")
            print("  %-18s %5d %6d %8d %6d %7d %7.1f%% %7.1f%%" % (
                os.path.basename(f), len(rs), k, sv, c("no-coverage"),
                sum(1 for r in rs if r.get("line_executed")),
                100.0 * k / (k + sv) if k + sv else 0, 100.0 * k / len(rs)))
        print("  (exec'd: survivors on lines the oracle executes; the rest sit on lines it never reaches)")
    per_fn = {}
    for r in results:
        per_fn.setdefault(plain(r["function"] or "?"), []).append(r)
    print("\n  %-34s %5s %6s %8s %6s" % ("function", "total", "killed", "survived", "no-cov"))
    for fn, rs in sorted(per_fn.items(), key=lambda x: -len(x[1])):
        c = lambda s: sum(1 for r in rs if r["status"] == s)
        print("  %-34s %5d %6d %8d %6d" % (fn[:34], len(rs), c("killed"), c("survived"),
                                           c("no-coverage")))
    lines = {}
    surv = [r for r in results if r["status"] == "survived"]
    if surv:
        print("\n  survivors (equivalent, or a gap in the catalogue):")
    for r in surv:
        if r["file"] not in lines:
            with open(r["file"], errors="replace") as f:
                lines[r["file"]] = f.read().split("\n")  # not splitlines(): sources hold form feeds
        src = lines[r["file"]][r["line"] - 1].strip()
        mark = {True: "x", False: " "}.get(r.get("line_executed"), "?")
        mark += "c" if r.get("capped") else " "
        print("    %s %s:%d:%d %-26s %s" % (mark, os.path.basename(r["file"]), r["line"],
                                           r["col"], r["mutator"], src[:90]))
    if surv:
        print("  (x: the oracle executes this line; c: capped, not every reaching case ran)")
    path = os.path.join(oracle.WORK, "mutation-%s.json" % slug)
    with open(path, "w") as f:
        json.dump(results, f, indent=1)
    print("\n  full results: %s" % os.path.relpath(path, oracle.ROOT))


def file_score(results, f):
    rs = [r for r in results if r["file"] == f]
    return sum(1 for r in rs if r["status"] == "killed") / float(len(rs))


if __name__ == "__main__":
    sys.exit(main())
