#!/usr/bin/env python3
"""Differential behaviour oracle: a baseline build against a candidate build.

    tools/oracle/oracle.py run [--base REF] [--filter RE] [-j N]
    tools/oracle/oracle.py selfcheck [--filter RE]     baseline against itself
    tools/oracle/oracle.py exec --bin PATH             run cases, compare nothing
    tools/oracle/oracle.py list [--filter RE] [-v]

`run` builds the baseline at REF (default origin/main, built once and cached
per commit) and the candidate from the working tree (incremental), runs every
case in tools/oracle/cases.py on both, and fails unless every case is
identical on both: exit status, normalised stdout and stderr, and the bytes of
every file the case writes. There is no tolerance. Baseline results are cached
per baseline binary, so after the first run only the candidate executes.

`selfcheck` runs the baseline twice without the cache. Any case that differs
from itself is nondeterministic and would make `run` unreliable; it must be
fixed in the catalogue before the oracle is trusted.

`exec` runs the catalogue with any binary and keeps no results. With
LLVM_PROFILE_FILE set and a coverage build (tools/oracle/build.sh cov) it
measures what the oracle reaches.
"""

import argparse
import collections
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cases as catalogue  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "build-oracle")
WORK = os.path.join(OUT, "work")
CORPUS = os.path.join(WORK, "corpus")
CORPUS_REL = "../../../corpus"  # from WORK/runs/<side>/<case>
FIXED_MTIME = 1000000000       # 2001-09-09; file dates end up in properties
# Prepended to every magick invocation by run_case, e.g. a sandbox (mutate.py).
WRAPPER = []
TIMEOUT = 30                   # the slowest legitimate case takes under 3s
HARNESS_VERSION = "9"        # bump when normalisation or execution changes

LISTS = ["Colorspace", "Compose", "Distort", "Filter", "Interpolate",
         "VirtualPixel", "Morphology", "Kernel", "Evaluate", "Statistic",
         "Noise", "Dither", "Layers", "Complex", "Intensity", "SparseColor",
         "Type", "Preview", "Metric"]
MACOS = sys.platform == "darwin"


def default_jobs():
    """Parallel processes when no -j is given: ORACLE_JOBS if set, else one per
    CPU. On a machine short of memory, ORACLE_JOBS=4 bounds every tool at once,
    casemap.py and linecov.py too, which take no -j of their own."""
    return int(os.environ.get("ORACLE_JOBS") or os.cpu_count())


def llvm_tool(name):
    """llvm-profdata, llvm-cov, ... from the LLVM that builds with `clang`.

    On macOS not through xcrun: from an x86_64 Python under Rosetta, xcrun
    fails to load. On Linux, the versioned name matching `clang` comes first,
    so a second LLVM on the system cannot read the profiles by mistake.
    """
    if MACOS:
        return "/Library/Developer/CommandLineTools/usr/bin/" + name
    major = subprocess.run(["clang", "-dumpversion"], stdout=subprocess.PIPE,
                           check=True).stdout.decode().split(".")[0]
    return shutil.which("%s-%s" % (name, major)) or shutil.which(name) or name


# ---------------------------------------------------------------------------
# Environment and normalisation
# ---------------------------------------------------------------------------
def env_for(binary, case_dir, extra_env=None):
    bld = os.path.dirname(os.path.dirname(os.path.abspath(binary)))
    src = source_dir_of(bld)
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin" + (":/opt/homebrew/bin" if MACOS else ""),
        "HOME": case_dir,
        "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
        "MAGICK_CONFIGURE_PATH": "%s/config:%s/config" % (bld, src),
        "MAGICK_TEMPORARY_PATH": case_dir,
        "MAGICK_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1",
        "SOURCE_DATE_EPOCH": str(FIXED_MTIME),
    }
    if not MACOS:
        # Some paths read heap memory they never wrote (single-channel raw
        # formats read back into a full image, `-sample` under a write mask):
        # with glibc their output changed from run to run. A fixed fill byte
        # for every malloc makes that garbage the same in every build and run.
        env["MALLOC_PERTURB_"] = "165"
    if "LLVM_PROFILE_FILE" in os.environ:
        env["LLVM_PROFILE_FILE"] = os.environ["LLVM_PROFILE_FILE"]
    env.update(extra_env or {})  # per-case profiles, Mull mutant switches
    return env


def source_dir_of(build_dir):
    """The srcdir a build directory was configured from."""
    try:
        with open(os.path.join(build_dir, "Makefile")) as f:
            for line in f:
                if line.startswith("abs_top_srcdir = "):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ROOT


NORMALISE = [
    # Source locations in exception messages carry line numbers and function
    # names, which refactoring legitimately changes.
    (re.compile(rb" @ (error|warning|fatal)/[^\s']+"), rb" @ \1/LOCATION"),
    # The build stamp in -version (git revision and date at configure time)
    # differs between the base and candidate builds by design.
    (re.compile(rb"(Version: ImageMagick \S+ \S+ \S+ \S+ )[0-9a-f]+:[0-9]{8}"),
     rb"\1BUILDSTAMP"),
    # Temporary file names are random.
    (re.compile(rb"magick-[A-Za-z0-9_-]{8,}"), rb"magick-TMPFILE"),
    # Timing lines in identify -verbose, info:, json:, yaml:.
    (re.compile(rb"(?im)^(\s*(elapsed time|user time|pixels per second)\s*:).*$"), rb"\1 TIME"),
    (re.compile(rb'(?i)("?(elapsedTime|userTime|pixelsPerSecond)"?\s*:\s*)"?[^",\n]*"?'),
     rb"\1TIME"),
    # User and elapsed time closing a plain identify / info: line.
    (re.compile(rb"\b[0-9]+\.[0-9]+u [0-9]+:[0-9]+\.[0-9]+"), rb"TIMEu TIME"),
    # The PDF writer dates its output from the file ctime, not SOURCE_DATE_EPOCH.
    (re.compile(rb"/(CreationDate|ModDate) \(D:[0-9]+[^)]*\)"), rb"/\1 (D:DATE)"),
    (re.compile(rb"<xmp:(CreateDate|ModifyDate|MetadataDate)>[^<]*<"), rb"<xmp:\1>DATE<"),
]
BUILD_TREE_RE = re.compile(re.escape(OUT.encode()) +
                           rb"/(?:(?:src|base)/[0-9a-f]{40}|cand|cov|asan|mull-[A-Za-z0-9_]+)")
# conjure takes `-key value` script variables, not options; -version and -list
# are accepted only as the first argument. None of them gets -seed.
UNSEEDED = ("conjure", "-version", "-list")
# Subcommands take their options after the subcommand name.
SUBCOMMANDS = ("compare", "identify", "montage", "composite", "conjure", "stream",
               "convert", "mogrify")


def normalise(data, case_dir=None):
    if case_dir:  # absolute paths differ between the base and cand sides
        data = data.replace(case_dir.encode(), b"CASEDIR").replace(WORK.encode(), b"WORK")
    # Build and source trees differ too (-list configure, -list mime print the
    # configuration paths): the base builds in a worktree, the candidate in
    # the checkout itself. Inner paths first, then the checkout.
    data = BUILD_TREE_RE.sub(b"BUILDTREE", data).replace(ROOT.encode(), b"BUILDTREE")
    for pattern, repl in NORMALISE:
        data = pattern.sub(repl, data)
    return data


def needs_normalising(data):
    """Text outputs and PDFs carry paths, timings and dates; image data does
    not, and running the regexes over megabytes of pixels holds the GIL."""
    return data[:5] == b"%PDF-" or b"\0" not in data[:4096]


def digest(data):
    return hashlib.sha256(data).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
def magick(binary, argv, cwd, timeout=TIMEOUT):
    return subprocess.run([binary] + argv, cwd=cwd, env=env_for(binary, cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


# Corpus images made here rather than in the catalogue.
CORPUS_EXTRAS = {
    "rose_patch": ["rose:", "-crop", "10x8+20+15", "+repage"],
    "hald": ["hald:8", "-level", "5%,95%"],
}


def ensure_corpus(binary):
    """Build the input corpus once and freeze it. Returns the manifest."""
    manifest_path = os.path.join(CORPUS, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            return json.load(f)
    tmp = CORPUS + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "files"))
    make_catalogue_images(binary, tmp)
    make_extra_images(binary, tmp)
    write_corpus_texts(tmp)
    files = decode_files()
    copy_decode_files(files, tmp)
    dims = corpus_dims(binary, tmp)
    manifest = {"digest": freeze(tmp), "dims": dims, "decode_files": files}
    with open(os.path.join(tmp, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    os.rename(tmp, CORPUS)
    return manifest


def make_catalogue_images(binary, tmp):
    for name, spec in catalogue.CORPUS.items():
        out = os.path.join(tmp, name + ".miff")
        if isinstance(spec, tuple):
            shutil.copyfile(os.path.join(ROOT, spec[1]), out)
            continue
        r = magick(binary, spec + [out], tmp)
        if r.returncode != 0:
            sys.exit("corpus: %s failed: %s" % (name, r.stderr.decode(errors="replace")))


def make_extra_images(binary, tmp):
    for name, spec in CORPUS_EXTRAS.items():
        r = magick(binary, spec + [os.path.join(tmp, name + ".miff")], tmp)
        if r.returncode != 0:
            sys.exit("corpus: %s failed" % name)


def write_corpus_texts(tmp):
    shutil.copyfile(os.path.join(ROOT, "PerlMagick/t", catalogue.FONT),
                    os.path.join(tmp, catalogue.FONT))
    with open(os.path.join(tmp, "draw.mvg"), "w") as f:
        f.write(catalogue.MVG)
    with open(os.path.join(tmp, "draw.svg"), "w") as f:
        f.write(catalogue.SVG)


def decode_files():
    """The source-tree files the decode cases read, relative to ROOT."""
    files = list(catalogue.DECODE_FILES)
    for pattern in catalogue.DECODE_GLOBS:
        files += sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, pattern))
                        if os.path.isfile(p))
    return sorted(set(files))


def copy_decode_files(files, tmp):
    for rel in files:
        dst = os.path.join(tmp, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, rel), dst)


def corpus_dims(binary, tmp):
    """Width, height and depth of every corpus image, for {W:name} and friends."""
    dims = {}
    for name in list(catalogue.CORPUS) + list(CORPUS_EXTRAS):
        r = magick(binary, ["identify", "-format", "%w %h %z\\n",
                            os.path.join(tmp, name + ".miff")], tmp)
        w, h, d = r.stdout.decode().split("\n")[0].split()
        dims[name] = {"W": w, "H": h, "D": d}
    return dims


def freeze(tmp):
    """Give every corpus file the fixed date and return a digest of them all."""
    h = hashlib.sha256()
    for dirpath, _, names in sorted(os.walk(tmp)):
        for n in sorted(names):
            p = os.path.join(dirpath, n)
            os.utime(p, (FIXED_MTIME, FIXED_MTIME))
            h.update(os.path.relpath(p, tmp).encode() + b"\0")
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def build_lists(binary):
    """Enumerations and writable formats, as the baseline reports them."""
    lists = {}
    for name in LISTS:
        r = magick(binary, ["-list", name], WORK)
        lists[name] = [l.strip() for l in r.stdout.decode().splitlines() if l.strip()]
    r = magick(binary, ["-list", "format"], WORK)
    writable = set()
    for line in r.stdout.decode().splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_-]+)\*?\s+([r-])([w-])([+-])\s", line)
        if m and m.group(3) == "w":
            writable.add(m.group(1).lower())
    return lists, writable


def load_cases(binary):
    os.makedirs(WORK, exist_ok=True)
    manifest = ensure_corpus(binary)
    lists, writable = build_lists(binary)
    lists["__decode_files__"] = manifest["decode_files"]
    return manifest, catalogue.generate(lists, writable)


# ---------------------------------------------------------------------------
# Running one case
# ---------------------------------------------------------------------------
def expand(argv, manifest):
    out = []
    for a in argv:
        a = a.replace("{C}", CORPUS_REL)
        a = re.sub(r"\{([WHD]):([a-z0-9_]+)\}",
                   lambda m: manifest["dims"][m.group(2)][m.group(1)], a)
        out.append(a)
    return out


def case_dir(side, case):
    return os.path.join(WORK, "runs", side, case["id"].replace("/", "_"))


# Output beyond this is not read back. The normal catalogue writes kilobytes;
# a mutant stuck printing warnings wrote gigabytes, which, held in memory,
# got the whole driver killed by the operating system.
READ_CAP = 64 << 20


def read_capped(path):
    """A file's bytes, or the first READ_CAP of them plus a note of the size."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(READ_CAP)
    if size > READ_CAP:
        data += b"\n[oracle: truncated, %d bytes in all]" % size
    return data


def run_case(binary, side, case, manifest, extra_env=None, timeout=None):
    d = case_dir(side, case)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    write_case_files(d, case)
    rcs, outs, errs = [], [], []
    # stdin is a named file for the cases that read "-", and nothing otherwise;
    # inheriting the driver's stdin would make results depend on how it was run.
    stdin_path = os.path.join(d, expand([case["stdin"]], manifest)[0]) if case.get("stdin") \
        else os.devnull
    started = time.time()
    for step in case["steps"]:
        fix_dates(d)
        argv = command_line(binary, expand(step, manifest))
        rc, step_out, step_err = run_step(argv, d, stdin_path, env=env_for(binary, d, extra_env),
                                          timeout=timeout or TIMEOUT)
        rcs.append(rc)
        outs.append(step_out)
        errs.append(step_err)
    files = case_files(d)
    out, err = b"\n".join(outs), b"\n".join(errs)
    return {"rc": rcs, "out": digest(out), "err": digest(err), "files": files,
            "secs": round(time.time() - started, 3),
            "out_text": out[:600].decode(errors="replace"),
            "err_text": err[:600].decode(errors="replace")}


def write_case_files(d, case):
    for name, text in case.get("files", {}).items():  # e.g. an MSL script
        path = os.path.join(d, name)  # a name may hold directories (.config/...)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text.replace("{C}", CORPUS_REL))


def fix_dates(d):
    for n in os.listdir(d):  # files read back must not carry today's date
        try:
            os.utime(os.path.join(d, n), (FIXED_MTIME, FIXED_MTIME))
        except FileNotFoundError:  # a temporary file removed since the listing
            pass


DRIVER_STEP = "@driver"  # a step that calls the API through imdriver (tools/oracle/driver)


def driver_path(binary):
    """The imdriver built against the same build as binary (driver/build.sh)."""
    return os.path.join(os.path.dirname(binary), "imdriver")


def command_line(binary, argv):
    """The full command for one expanded step, wrapper and seed included."""
    if argv and argv[0] == DRIVER_STEP:
        # Without a driver beside the binary the step fails alike in every run of this
        # build, so a driver case can neither kill a mutant nor reach a function there.
        if not os.path.exists(driver_path(binary)):
            return WRAPPER + [binary, "-imdriver-not-built"]
        return WRAPPER + [driver_path(binary)] + argv[1:]
    # Every random generator is seeded; unseeded ones read /dev/urandom.
    # conjure takes `-key value` script variables, not options, so MSL
    # cases must avoid random operators instead.
    if argv and argv[0] in UNSEEDED:
        return WRAPPER + [binary] + argv
    at = 1 if argv and argv[0] in SUBCOMMANDS else 0
    return WRAPPER + [binary] + argv[:at] + ["-seed", "1"] + argv[at:]


def run_step(argv, d, stdin_path, **run_options):
    """Exit status (or "timeout"), normalised stdout and normalised stderr of
    one command run in case directory d."""
    # stdout and stderr go to files beside the case directory, not
    # into memory, and only READ_CAP of each is read back.
    out_path, err_path = d + ".stdout", d + ".stderr"
    try:
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe, \
                open(stdin_path, "rb") as fi:
            r = subprocess.run(argv, cwd=d, stdin=fi, stdout=fo, stderr=fe, **run_options)
        return (r.returncode, normalise(read_capped(out_path), d),
                normalise(read_capped(err_path), d))
    except subprocess.TimeoutExpired:
        return "timeout", b"", b""
    finally:
        remove_existing(out_path, err_path)


def remove_existing(*paths):
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def case_files(d):
    """Digest of every file in case directory d, by path relative to it."""
    files = {}
    for dirpath, _, names in os.walk(d):
        for n in sorted(names):
            p = os.path.join(dirpath, n)
            files[os.path.relpath(p, d)] = file_result(p, d)
    return files


def file_result(p, d):
    try:
        data = read_capped(p)
    except FileNotFoundError:  # a temporary file removed while we walked
        return "vanished"
    if needs_normalising(data):
        data = normalise(data, d)
    return digest(data)


# What two results must agree on; the rest (timings, text excerpts) may differ.
COMPARED = ("rc", "out", "err", "files")


def same(a, b):
    for k in COMPARED:
        if a[k] != b[k]:
            return False
    return True


def explain(a, b):
    why = []
    if a["rc"] != b["rc"]:
        why.append("exit status %s -> %s" % (a["rc"], b["rc"]))
    if a["out"] != b["out"]:
        why.append("stdout differs")
    if a["err"] != b["err"]:
        why.append("stderr differs")
    return why + file_differences(a["files"], b["files"])


def file_differences(a, b):
    names = sorted(set(a) | set(b))
    return [file_difference(n, a, b) for n in names if a.get(n) != b.get(n)]


def file_difference(n, a, b):
    if n not in a:
        return "%s only in candidate" % n
    if n not in b:
        return "%s missing in candidate" % n
    return "%s differs" % n


def pixel_delta(binary, base_file, cand_file):
    """Describe how two image files differ, for the report."""
    r = subprocess.run([binary, "compare", "-metric", "AE", base_file, cand_file, "null:"],
                       env=env_for(binary, WORK), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=TIMEOUT)
    ae = r.stderr.decode(errors="replace").strip().split("\n")[0][:80]
    r = subprocess.run([binary, "compare", "-metric", "PAE", base_file, cand_file, "null:"],
                       env=env_for(binary, WORK), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=TIMEOUT)
    pae = r.stderr.decode(errors="replace").strip().split("\n")[0][:80]
    return "pixels differing: %s, peak error: %s" % (ae, pae)


# ---------------------------------------------------------------------------
# Baseline cache
# ---------------------------------------------------------------------------
def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def library_fingerprint(binary):
    """The shared libraries binary loads, by resolved path and size: an upgrade of one
    (Homebrew upgrades dependencies as it installs) changes results the binary's own
    hash does not see, so it must start a new baseline (2026-10-03)."""
    if sys.platform == "darwin":
        r = subprocess.run(["otool", "-L", binary], capture_output=True, text=True)
        paths = [l.split(" (")[0].strip() for l in r.stdout.splitlines()[1:]]
    else:
        r = subprocess.run(["ldd", binary], capture_output=True, text=True)
        paths = [l.split("=>")[-1].split(" (")[0].strip() for l in r.stdout.splitlines() if "/" in l]
    parts = []
    for path in sorted(p for p in paths if p.startswith("/")):
        real = os.path.realpath(path)
        size = os.path.getsize(real) if os.path.exists(real) else -1
        parts.append("%s:%d" % (real, size))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def cache_path(binary, manifest):
    key = "%s-%s-h%s-l%s" % (file_sha(binary)[:16], manifest["digest"][:12], HARNESS_VERSION,
                             library_fingerprint(binary)[:8])
    return os.path.join(WORK, "cache", key + ".json")


def case_key(case):
    """Everything that determines a case's result: its commands and the files
    it starts with (MSL cases share one command and differ only in script)."""
    what = [case["steps"], sorted(case.get("files", {}).items())]
    return hashlib.sha1(json.dumps(what).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def build(what, ref=None):
    argv = [os.path.join(ROOT, "tools/oracle/build.sh"), what] + ([ref] if ref else [])
    r = subprocess.run(argv, stdout=subprocess.PIPE)
    if r.returncode != 0:
        sys.exit("build %s failed" % what)
    return r.stdout.decode().strip().splitlines()[-1]


def select(cases, pattern):
    if not pattern:
        return cases
    rx = re.compile(pattern)
    return [c for c in cases if rx.search(c["id"]) or rx.search(c["label"])]


def select_by_function(todo, all_cases, functions):
    """The cases that execute any of these functions, from casemap.json.

    Names are those of the base code, so name the function being refactored,
    not a helper just extracted from it: the original still calls the helper,
    so its cases are the ones that matter. A function no case reaches is an
    error, not an empty pass: the oracle cannot vouch for it at all.
    """
    import casemap  # here, not at the top: casemap imports this module
    fmap = casemap.load_map(all_cases)
    wanted = set()
    for name in functions:
        ids = casemap.cases_for(name, fmap)
        if not ids:
            sys.exit("oracle: no case executes %s; the oracle cannot check it "
                     "(see docs/refactoring/MUTATION.md)" % name)
        print("oracle: %d cases execute %s" % (len(ids), name))
        wanted.update(ids)
    return [c for c in todo if c["id"] in wanted]


def parallel(fn, items, jobs, label):
    results, done, start = {}, 0, time.time()
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futures = {pool.submit(fn, it): it for it in items}
        for fut in concurrent.futures.as_completed(futures):
            it = futures[fut]
            results[it["id"]] = fut.result()
            done += 1
            if done % 500 == 0 or done == len(items):
                sys.stderr.write("  %s: %d/%d (%.0fs)\n" % (label, done, len(items),
                                                            time.time() - start))
    return results


# One oracle run: the two binaries, the corpus manifest, the cases selected
# and the baseline results by case_key.
Run = collections.namedtuple("Run", "base_bin cand_bin manifest todo cache")


def cmd_run(args):
    base_bin = args.base_bin or build("base", args.base)
    cand_bin = args.cand_bin or build("cand")
    manifest, all_cases = load_cases(base_bin)
    todo = select_run_cases(all_cases, args)
    cpath = cache_path(base_bin, manifest)
    cache = read_cache(cpath, args.no_cache)
    missing = [c for c in todo if case_key(c) not in cache]
    start = time.time()
    if missing:
        cache.update(run_baseline(base_bin, missing, manifest, args.jobs))
        if not args.filter and not args.function:  # drop entries no longer in the catalogue
            cache = prune_cache(cache, todo)
        write_cache(cpath, cache)
        shutil.rmtree(os.path.join(WORK, "runs", "base"), ignore_errors=True)
    cand_res = parallel(lambda c: run_case(cand_bin, "cand", c, manifest), todo,
                        args.jobs, "candidate")
    failures = compare(todo, cache, cand_res)
    report(Run(base_bin, cand_bin, manifest, todo, cache), failures, time.time() - start, args)
    return 1 if failures else 0


def select_run_cases(all_cases, args):
    todo = select(all_cases, args.filter)
    if args.function:
        todo = select_by_function(todo, all_cases, args.function)
    return todo


def read_cache(cpath, no_cache):
    if no_cache or not os.path.exists(cpath):
        return {}
    with open(cpath) as f:
        return json.load(f)


def run_baseline(base_bin, missing, manifest, jobs):
    """Baseline results for these cases, by case_key."""
    base_res = parallel(lambda c: run_case(base_bin, "base", c, manifest), missing,
                        jobs, "baseline")
    return {case_key(c): base_res[c["id"]] for c in missing}


def prune_cache(cache, todo):
    live = {case_key(c) for c in todo}
    return {k: v for k, v in cache.items() if k in live}


def write_cache(cpath, cache):
    os.makedirs(os.path.dirname(cpath), exist_ok=True)
    with open(cpath + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(cpath + ".tmp", cpath)


def compare(todo, cache, cand_res):
    """(case, baseline, candidate) for every case that diverged. The outputs
    of the cases that agree are removed; those of the rest are kept."""
    failures = []
    for c in todo:
        b, k = cache[case_key(c)], cand_res[c["id"]]
        if same(b, k):
            shutil.rmtree(case_dir("cand", c), ignore_errors=True)
        else:
            failures.append((c, b, k))
    return failures


def report(run, failures, elapsed, args):
    print_summary(run, len(failures), elapsed)
    detail = [divergence(c, b, k, run.manifest) for c, b, k in failures]
    print_divergences(detail, args.show)
    if failures and args.explain:
        print_pixel_deltas(run, failures[:args.show])
    with open(os.path.join(WORK, "last-report.json"), "w") as f:
        json.dump({"cases": len(run.todo), "diverged": detail}, f, indent=1)
    if failures:
        print("\n  full report: %s" % os.path.relpath(os.path.join(WORK, "last-report.json"), ROOT))
        print("  candidate outputs kept in build-oracle/work/runs/cand/")


def print_summary(run, diverged, elapsed):
    base_rcs = [(c, run.cache[case_key(c)]["rc"]) for c in run.todo]
    failing_base = sum(1 for c, rc in base_rcs if rc != [0] * len(c["steps"]))
    print("oracle: %d cases, %d diverged, %.0fs  (baseline %s)"
          % (len(run.todo), diverged, elapsed, run.base_bin.split("/")[-3][:10]))
    print("        %d cases exit non-zero on the baseline (error paths, compared too)"
          % failing_base)
    print_timeouts([c for c, rc in base_rcs if "timeout" in rc])


def print_timeouts(slow):
    if not slow:  # a timeout compares nothing and costs TIMEOUT seconds per run
        return
    print("  CATALOGUE BUG: %d cases time out on the baseline; fix them in cases.py:" % len(slow))
    for c in slow[:10]:
        print("    %s  %s" % (c["id"], c["label"]))


def divergence(c, b, k, manifest):
    """The last-report.json entry for a case whose results b and k differ."""
    return {"id": c["id"], "label": c["label"], "why": explain(b, k),
            "steps": [" ".join(expand(s, manifest)) for s in c["steps"]],
            "base_err": b["err_text"], "cand_err": k["err_text"]}


def print_divergences(detail, show):
    for e in detail[:show]:
        print_divergence(e)
    if len(detail) > show:
        print("\n  ... %d more" % (len(detail) - show))


def print_divergence(e):
    print("\n  DIVERGED %s  %s" % (e["id"], e["label"]))
    for s in e["steps"]:
        print("    $ magick %s" % s)
    for w in e["why"]:
        print("    - %s" % w)


def print_pixel_deltas(run, failures):
    # Re-run the baseline for the first failures so pixel deltas can be shown.
    for c, b, k in failures:
        run_case(run.base_bin, "base", c, run.manifest)
        for n in differing_images(b, k):
            bf, kf = os.path.join(case_dir("base", c), n), os.path.join(case_dir("cand", c), n)
            if os.path.exists(bf):
                print("  %s %s: %s" % (c["id"], n, pixel_delta(run.cand_bin, bf, kf)))


def differing_images(b, k):
    """The MIFF files the candidate wrote that differ from the baseline's."""
    return [n for n in sorted(k["files"])
            if n.endswith(".miff") and b["files"].get(n) != k["files"].get(n)]


def cmd_selfcheck(args):
    base_bin = args.base_bin or build("base", args.base)
    manifest, all_cases = load_cases(base_bin)
    todo = select(all_cases, args.filter)
    # Two runs are not enough: a case that differs 30% of the time under load
    # (resize/06b5a45abd, an upstream bug) agrees with itself in 58% of pairs
    # and passed. --repeat 4 would have caught it three times in four.
    runs = [parallel(lambda c: run_case(base_bin, "self%d" % n, c, manifest), todo, args.jobs,
                     "run %d" % n) for n in range(1, args.repeat + 1)]
    flaky = [c for c in todo if disagreement(runs, c["id"]) is not None]
    print("selfcheck: %d cases, %d runs each, %d nondeterministic"
          % (len(todo), args.repeat, len(flaky)))
    for c in flaky:
        other = disagreement(runs, c["id"])
        print("  %s  %s: %s" % (c["id"], c["label"], "; ".join(explain(runs[0][c["id"]], other))))
    if not flaky:
        remove_self_runs(args.repeat)
    return 1 if flaky else 0


def disagreement(runs, cid):
    """The first later run whose result for case cid differs from the first
    run's, or None when they all agree."""
    first = runs[0][cid]
    return next((r[cid] for r in runs[1:] if not same(first, r[cid])), None)


def remove_self_runs(repeat):
    for n in range(1, repeat + 1):
        shutil.rmtree(os.path.join(WORK, "runs", "self%d" % n), ignore_errors=True)


def cmd_exec(args):
    manifest, all_cases = load_cases(args.base_bin or build("base", args.base))
    todo = select(all_cases, args.filter)
    start = time.time()
    res = parallel(lambda c: run_case(args.bin, "exec", c, manifest), todo, args.jobs, "exec")
    shutil.rmtree(os.path.join(WORK, "runs", "exec"), ignore_errors=True)
    bad = sum(1 for r in res.values() if any(x != 0 for x in r["rc"]))
    print("exec: %d cases in %.0fs, %d exit non-zero" % (len(todo), time.time() - start, bad))
    return 0


def cmd_list(args):
    _, all_cases = load_cases(args.base_bin or build("base", args.base))
    todo = select(all_cases, args.filter)
    fams = {}
    for c in todo:
        fams[c["family"]] = fams.get(c["family"], 0) + 1
    for f, n in sorted(fams.items(), key=lambda x: -x[1]):
        print("%6d  %s" % (n, f))
    print("%6d  total" % len(todo))
    if args.verbose:
        for c in todo:
            print("%s  %s" % (c["id"], c["label"]))
    return 0


def add_common_arguments(s):
    s.add_argument("--base", default="origin/main", help="baseline git ref")
    s.add_argument("--base-bin", help="use this baseline binary instead of building")
    s.add_argument("--filter", help="regex on case id or label")
    s.add_argument("--function", action="append",
                   help="only cases executing this function (casemap.json); repeatable")
    s.add_argument("-j", "--jobs", type=int, default=default_jobs())


def add_run_arguments(s):
    s.add_argument("--cand-bin", help="use this candidate binary instead of building")
    s.add_argument("--no-cache", action="store_true")
    s.add_argument("--show", type=int, default=20, help="divergences to print")
    s.add_argument("--explain", action="store_true", help="pixel deltas for divergences")


def add_selfcheck_arguments(s):
    s.add_argument("--repeat", type=int, default=2,
                   help="runs per case; 4 or more after changing the catalogue")


def add_exec_arguments(s):
    s.add_argument("--bin", required=True)


def add_list_arguments(s):
    s.add_argument("-v", "--verbose", action="store_true")


# Each subcommand: its function and the options it adds to the common ones.
COMMANDS = {
    "run": (cmd_run, add_run_arguments),
    "selfcheck": (cmd_selfcheck, add_selfcheck_arguments),
    "exec": (cmd_exec, add_exec_arguments),
    "list": (cmd_list, add_list_arguments),
}


def absolute_binaries(args):
    for attr in ("bin", "base_bin", "cand_bin"):  # cases run in their own directories
        if getattr(args, attr, None):
            setattr(args, attr, os.path.abspath(getattr(args, attr)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, (_, add_arguments) in COMMANDS.items():
        s = sub.add_parser(name)
        add_common_arguments(s)
        add_arguments(s)
    args = p.parse_args()
    absolute_binaries(args)
    return COMMANDS[args.cmd][0](args)


if __name__ == "__main__":
    sys.exit(main())
