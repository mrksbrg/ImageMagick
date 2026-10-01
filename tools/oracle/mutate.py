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
LLVM_COV = oracle.llvm_tool("llvm-cov")
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


def _source_order(m):
    """Mutants and results sort by file, line, column, then mutator."""
    return (m["file"], m["line"], m["col"], m["mutator"])


def _mutant_record(line, rx):
    """The mutant a `strings` line names, or None if it names none in the
    selected files."""
    m = MUTANT_ID.match(line.strip())
    if not (m and rx.search(m.group(2))):
        return None
    return {"id": line.strip(), "mutator": m.group(1), "file": m.group(2),
            "line": int(m.group(3)), "col": int(m.group(4))}


def list_mutants(binary, file_regex):
    out = subprocess.run(["strings", "-a", binary], stdout=subprocess.PIPE, check=True)
    rx, seen = re.compile(file_regex), set()
    mutants = []
    for line in out.stdout.decode(errors="replace").splitlines():
        mutant = _mutant_record(line, rx)
        if mutant and line not in seen:
            seen.add(line)
            mutants.append(mutant)
    return sorted(mutants, key=_source_order)


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


def _add_hit(lines, row):
    """Add the line of an lcov `DA:line,hits` row to lines if it ran."""
    n, hits = row[3:].split(",")[:2]
    if int(hits) > 0:
        lines.add(int(n))


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
                _add_hit(current, row)
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
    """A prefix that lets a mutant run magick and write under build-oracle/,
    and nothing else: sandbox-exec on macOS, bubblewrap on Linux.

    delegate.c runs the commands in delegates.xml: lpr, `open -a Preview`,
    curl, gimp, `... ; /bin/rm`. The case catalogue never asks for those, but
    a mutant can skip the check that stops them (policy.c is mutated too), and
    it would then print, open windows or use the network on the real machine.
    The operating system enforces this, so no mutant can switch it off.
    """
    out = os.path.realpath(oracle.OUT)
    if not oracle.MACOS:
        return bwrap_sandbox(out)
    profile = ("(version 1)(allow default)"
               "(deny process-exec)(allow process-exec (literal \"%s\"))"
               "(deny network*)"
               "(deny file-write*)(allow file-write* (subpath \"%s\")"
               " (literal \"/dev/null\") (literal \"/dev/tty\") (literal \"/dev/dtracehelper\"))"
               % (os.path.realpath(binary), out))
    return ["/usr/bin/sandbox-exec", "-p", profile]


def bwrap_sandbox(out):
    """bubblewrap has no rule that allows exec of one binary only, so the
    sandbox holds no other program to run: /usr/lib, /usr/share and /etc for
    magick's libraries, fonts and configuration, but no /usr/bin, /bin or
    /sbin, hence no shell for a delegate command to start. No network, and
    the only writable paths are build-oracle/ and a private /tmp."""
    root = os.path.realpath(oracle.ROOT)
    args = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr/lib", "/usr/lib", "--symlink", "usr/lib", "/lib"]
    if os.path.isdir("/usr/lib64"):
        args += ["--ro-bind", "/usr/lib64", "/usr/lib64", "--symlink", "usr/lib64", "/lib64"]
    args += ["--ro-bind", "/usr/share", "/usr/share", "--ro-bind", "/etc", "/etc"]
    if os.path.isdir("/var/cache/fontconfig"):  # without it every case rebuilds the font cache
        args += ["--ro-bind", "/var/cache/fontconfig", "/var/cache/fontconfig"]
    return args + ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                   "--ro-bind", root, root, "--bind", out, out, "--"]


def _is_case_kill(r):
    # A timeout says the mutant was slower, not which case sees its
    # behaviour; ranking by those would favour slow cases.
    return r["status"] == "killed" and "timeout" not in r.get("why", "")


def _add_kills(path, counts):
    """Count the kills in one mutation report into counts."""
    with open(path) as f:
        for r in filter(_is_case_kill, json.load(f)):
            counts[r["killer"]] = counts.get(r["killer"], 0) + 1


def kill_counts(exclude):
    """{case id: mutants it killed} over earlier mutation reports."""
    counts = {}
    for path in glob.glob(os.path.join(oracle.WORK, "mutation-*.json")):
        if os.path.basename(path) != exclude:
            _add_kills(path, counts)
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


def _parse_args():
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
    p.add_argument("-j", "--jobs", type=int, default=oracle.default_jobs())
    return p.parse_args()


def _limit_file_size():
    # No child may write a file over 2 GB (it gets SIGXFSZ instead): a
    # runaway mutant must not fill the disk. Children inherit the limit.
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 << 30, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))


def _in_function(m, function):
    return m["function"] and plain(m["function"]) == function


def _wanted_ids(path):
    with open(path) as f:
        return {line.strip() for line in f if line.strip()}


def _sample_per_file(mutants, per_file, seed):
    rng, by_file = random.Random(seed), {}
    for m in mutants:
        by_file.setdefault(m["file"], []).append(m)
    return [m for f in sorted(by_file) for m in
            (rng.sample(by_file[f], per_file)
             if len(by_file[f]) > per_file else by_file[f])]


def _filter(mutants, args):
    """The mutants that --function and --ids select."""
    if args.function:
        mutants = [m for m in mutants if _in_function(m, args.function)]
    if args.ids:
        wanted = _wanted_ids(args.ids)
        mutants = [m for m in mutants if m["id"] in wanted]
    return mutants


def _sample(mutants, args):
    """The random sample that --per-file and --limit ask for."""
    if args.per_file:
        mutants = _sample_per_file(mutants, args.per_file, args.seed)
    if args.limit and len(mutants) > args.limit:
        mutants = random.Random(args.seed).sample(mutants, args.limit)
    return mutants


def _select_mutants(args, binary, ranges):
    """The mutants to run, in source order, each with its function."""
    mutants = list_mutants(binary, args.file)
    for m in mutants:
        m["function"] = enclosing(m, ranges)
    mutants = _sample(_filter(mutants, args), args)
    mutants.sort(key=_source_order)
    return mutants


def _relevant_cases(mutants, fmap, cases_regex):
    """{function: ids of the cases that execute it} for the mutants' functions."""
    # casemap.json and llvm-cov spell names the same way (`resize.c:Triangle`
    # for statics), so an exact lookup cannot confuse two files' statics.
    relevant = {m["function"]: fmap.get(m["function"], []) for m in mutants if m["function"]}
    if cases_regex:
        keep = re.compile(cases_regex)
        relevant = {f: [i for i in ids if keep.search(i)] for f, ids in relevant.items()}
    return relevant


def _cached_baseline(cache_file):
    if not os.path.exists(cache_file):
        return {}
    with open(cache_file) as f:
        return {i: r for i, r in json.load(f).items() if "timeout" not in r["rc"]}


class _Run:
    """What testing the mutants needs: the binary, the catalogue, the cases
    that reach each function, the baseline and the earlier kills. main()
    fills in the rest as it computes them."""

    def __init__(self, binary, slug, manifest, by_id):
        self.binary, self.slug, self.manifest, self.by_id = binary, slug, manifest, by_id
        self.relevant, self.base, self.kills = {}, {}, {}
        self.max_cases, self.jobs = 0, 1
        self.started_log = os.path.join(oracle.WORK, "mutation-%s.started" % slug)

    def baseline(self, needed):
        """{case id: result} of the unmutated binary on the needed case ids,
        less the cases that time out even unmutated.

        Kept per binary, catalogue and way of running (the wrapper), so a
        resumed run does not spend minutes recomputing it. The wrapper is in
        the key because adding the sandbox changed two cases' stderr, and a
        cache from before it turned those into 28 false kills."""
        wrap = hashlib.sha1(json.dumps(oracle.WRAPPER).encode()).hexdigest()[:8]
        cache_file = (oracle.cache_path(self.binary, self.manifest).replace(".json", "")
                      + "-mull-%s.json" % wrap)
        base = _cached_baseline(cache_file)
        todo = [self.by_id[i] for i in needed if i not in base]
        if todo:
            side = "mbase-" + self.slug
            base.update(oracle.parallel(
                lambda c: oracle.run_case(self.binary, side, c, self.manifest),
                todo, self.jobs, "baseline"))
            with open(cache_file, "w") as f:
                json.dump(base, f)
        base = {i: base[i] for i in needed}
        unstable = sorted(i for i in needed if "timeout" in base[i]["rc"])
        for i in unstable:  # a case that times out unmutated can kill nothing honestly
            base.pop(i)
        if unstable:
            # Say so: a dropped case tests nothing, and a mutant it was meant
            # for then survives or shows no coverage with no sign of why.
            # Subimage search on a full-size image was one, on a Mull build.
            print("mutate: %d case(s) time out unmutated and are left out: %s"
                  % (len(unstable), " ".join(unstable[:10])), flush=True)
        shutil.rmtree(os.path.join(oracle.WORK, "runs", "mbase-" + self.slug), ignore_errors=True)
        return base

    def order(self, ids):
        """ids in the order to try them, and whether --max-cases cut them."""
        ids.sort(key=lambda i: self.base[i]["secs"])  # cheap cases first: most kills are early
        capped = bool(self.max_cases) and len(ids) > self.max_cases
        if capped:
            proven = sorted((i for i in ids if self.kills.get(i)), key=lambda i: -self.kills[i])
            proven = proven[:self.max_cases]
            chosen = set(proven)
            ids = proven + spread([i for i in ids if i not in chosen],
                                  self.max_cases - len(proven))
        return ids, capped

    def run_mutant(self, m, i, side):
        limit = min(MUTANT_TIMEOUT_MAX,
                    max(MUTANT_TIMEOUT, MUTANT_TIMEOUT_FACTOR * self.base[i]["secs"]))
        r = oracle.run_case(self.binary, side, self.by_id[i], self.manifest, {m["id"]: "1"}, limit)
        if "timeout" in r["rc"]:
            # Under a full load a slow case can overrun even a scaled
            # limit; only a mutant that still hangs is a kill.
            r = oracle.run_case(self.binary, side, self.by_id[i], self.manifest, {m["id"]: "1"},
                                MUTANT_TIMEOUT_CONFIRM)
        return r

    def first_kill(self, m, ids, side):
        """The killed result from the first case that diverges, or None."""
        for n, i in enumerate(ids, 1):
            r = self.run_mutant(m, i, side)
            if not oracle.same(self.base[i], r):
                return dict(m, status="killed", cases=n, killer=i,
                            why="; ".join(oracle.explain(self.base[i], r))[:200])
        return None

    def test(self, m):
        ids = [i for i in self.relevant.get(m["function"], []) if i in self.base]
        if not ids:
            return dict(m, status="no-coverage", cases=0)
        ids, capped = self.order(ids)
        side = "mut-" + hashlib.sha1(m["id"].encode()).hexdigest()[:10]  # one dir per mutant
        try:
            killed = self.first_kill(m, ids, side)
        finally:
            shutil.rmtree(os.path.join(oracle.WORK, "runs", side), ignore_errors=True)
        return killed or dict(m, status="survived", cases=len(ids), capped=capped)

    def guarded(self, m):
        # A mutant that started but never finished is the one to suspect if
        # the driver itself dies.
        with open(self.started_log, "a") as f:
            f.write(m["id"] + "\n")
        try:
            return self.test(m)
        except Exception as e:  # one bad mutant must not lose hours of results
            return dict(m, status="error", why=repr(e)[:200])


def _resume(partial, mutants):
    """(results already in the partial log, mutants still to run)."""
    if not os.path.exists(partial):
        return [], mutants
    wanted = {m["id"] for m in mutants}
    with open(partial) as f:
        results = [r for r in map(json.loads, f) if r["id"] in wanted]
    done_ids = {r["id"] for r in results}
    print("mutate: resuming, %d mutants already done" % len(results))
    return results, [m for m in mutants if m["id"] not in done_ids]


def _progress(done, total, start):
    if done % 25 == 0 or done == total:
        sys.stderr.write("  mutants: %d/%d (%.0fs)\n" % (done, total, time.time() - start))


def _run_all(run, mutants, results, partial):
    """Test the mutants, appending each result to results and to the partial
    log as it arrives; returns the start time."""
    start, done = time.time(), len(results)
    total = done + len(mutants)
    with concurrent.futures.ThreadPoolExecutor(run.jobs) as pool, open(partial, "a") as log:
        # As each finishes, not in submission order: one slow mutant once held
        # back 50 finished results for most of an hour, unsaved.
        futures = [pool.submit(run.guarded, m) for m in mutants]
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            log.flush()
            done += 1
            _progress(done, total, start)
    return start


def main():
    args = _parse_args()
    slug = args.name or re.sub(r"[^A-Za-z0-9]", "_", args.file)
    binary = os.path.abspath(args.bin or os.path.join(oracle.OUT, "mull-" + slug,
                                                      "utilities", "magick"))
    base_bin = oracle.build("base", "origin/main")  # only for the corpus and option lists
    oracle.WRAPPER = sandbox(binary)  # baseline and mutants alike
    _limit_file_size()
    manifest, cases = oracle.load_cases(base_bin)
    run = _Run(binary, slug, manifest, {c["id"]: c for c in cases})
    run.max_cases, run.jobs = args.max_cases, args.jobs
    fmap = casemap.load_map(cases)
    ranges = function_ranges(args.file)

    mutants = _select_mutants(args, binary, ranges)
    run.relevant = _relevant_cases(mutants, fmap, args.cases)
    print("mutate: %d mutants in %s, %d functions" % (len(mutants), args.file, len(run.relevant)))

    # Baseline: the same binary with no mutant switched on.
    needed = sorted({cid for ids in run.relevant.values() for cid in ids})
    start = time.time()
    run.base = run.baseline(needed)
    print("mutate: baseline over %d cases in %.0fs" % (len(needed), time.time() - start))
    run.kills = kill_counts("mutation-%s.json" % slug)

    partial = os.path.join(oracle.WORK, "mutation-%s.partial.jsonl" % slug)
    results, mutants = _resume(partial, mutants)
    start = _run_all(run, mutants, results, partial)
    results.sort(key=_source_order)
    report(results, args, slug, time.time() - start)


def _count(results, status):
    return sum(1 for r in results if r["status"] == status)


def _mark_executed(results):
    """Mark each survivor with whether the oracle executes its line."""
    executed = executed_lines()
    if executed is None:
        return
    for r in results:
        if r["status"] == "survived":
            r["line_executed"] = r["line"] in executed.get(r["file"], ())


def _print_totals(results, elapsed):
    killed, survived, nocov = (_count(results, s) for s in ("killed", "survived", "no-coverage"))
    reached = killed + survived
    print("\nmutate: %d mutants, %.0fs" % (len(results), elapsed))
    print("  killed %d, survived %d (%d capped), no coverage %d, errors %d" % (
        killed, survived, sum(1 for r in results if r.get("capped")), nocov,
        _count(results, "error")))
    if reached:
        print("  mutation score on reached code: %.1f%%   overall: %.1f%%"
              % (100.0 * killed / reached, 100.0 * killed / len(results)))


def _print_file_row(f, rs):
    k, sv = _count(rs, "killed"), _count(rs, "survived")
    print("  %-18s %5d %6d %8d %6d %7d %7.1f%% %7.1f%%" % (
        os.path.basename(f), len(rs), k, sv, _count(rs, "no-coverage"),
        sum(1 for r in rs if r.get("line_executed")),
        100.0 * k / (k + sv) if k + sv else 0, 100.0 * k / len(rs)))


def _print_file_table(results):
    files = sorted({r["file"] for r in results})
    if len(files) <= 1:
        return
    print("\n  %-18s %5s %6s %8s %6s %7s %8s %8s" % (
        "file", "total", "killed", "survived", "no-cov", "exec'd", "reached", "overall"))
    for f in sorted(files, key=lambda f: file_score(results, f)):
        _print_file_row(f, [r for r in results if r["file"] == f])
    print("  (exec'd: survivors on lines the oracle executes; the rest sit on lines it never reaches)")


def _print_function_table(results):
    per_fn = {}
    for r in results:
        per_fn.setdefault(plain(r["function"] or "?"), []).append(r)
    print("\n  %-34s %5s %6s %8s %6s" % ("function", "total", "killed", "survived", "no-cov"))
    for fn, rs in sorted(per_fn.items(), key=lambda x: -len(x[1])):
        print("  %-34s %5d %6d %8d %6d" % (fn[:34], len(rs), _count(rs, "killed"),
                                           _count(rs, "survived"), _count(rs, "no-coverage")))


def _source_line(sources, r):
    """The stripped source line of result r; sources caches each file's lines."""
    if r["file"] not in sources:
        with open(r["file"], errors="replace") as f:
            sources[r["file"]] = f.read().split("\n")  # not splitlines(): sources hold form feeds
    return sources[r["file"]][r["line"] - 1].strip()


def _survivor_mark(r):
    mark = {True: "x", False: " "}.get(r.get("line_executed"), "?")
    return mark + ("c" if r.get("capped") else " ")


def _print_survivors(results):
    surv = [r for r in results if r["status"] == "survived"]
    if not surv:
        return
    print("\n  survivors (equivalent, or a gap in the catalogue):")
    sources = {}
    for r in surv:
        src = _source_line(sources, r)
        print("    %s %s:%d:%d %-26s %s" % (_survivor_mark(r), os.path.basename(r["file"]),
                                           r["line"], r["col"], r["mutator"], src[:90]))
    print("  (x: the oracle executes this line; c: capped, not every reaching case ran)")


def report(results, args, slug, elapsed):
    _mark_executed(results)
    _print_totals(results, elapsed)
    _print_file_table(results)
    _print_function_table(results)
    _print_survivors(results)
    path = os.path.join(oracle.WORK, "mutation-%s.json" % slug)
    with open(path, "w") as f:
        json.dump(results, f, indent=1)
    print("\n  full results: %s" % os.path.relpath(path, oracle.ROOT))


def file_score(results, f):
    rs = [r for r in results if r["file"] == f]
    return sum(1 for r in rs if r["status"] == "killed") / float(len(rs))


if __name__ == "__main__":
    sys.exit(main())
