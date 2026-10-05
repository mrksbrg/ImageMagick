# Verification plan: every MagickCore file, and what proves its refactoring

The campaign's aim, as in 3SX, is a MagickCore folder that is green throughout. The
differential oracle ([`ORACLE.md`](ORACLE.md)) is the strongest proof we have, but it
cannot reach every line: a quarter of MagickCore's functions are never called by any case,
and six of the reddest files are not even compiled by the oracle build. This plan says
which evidence each file and function gets, and what has to be built to raise it.

Measured on 2026-09-30 on the Windows desktop: WSL2 Ubuntu 24.04 with clang 18, and MSYS2
UCRT64 with gcc. The levels and the gate are in [`PLAYBOOK.md`](PLAYBOOK.md) (*Two levels of
evidence*) and [`../../AGENTS.md`](../../AGENTS.md) since step 1.

---

## Three builds, three jobs

| Build | Where | Configuration | Job | Differential oracle |
| --- | --- | --- | --- | --- |
| **Oracle build** | WSL | `tools/oracle/build.sh base / cand / cov / mull`: static, no OpenMP, `--without-x`, OpenCL off | behaviour proof and mutation testing | **yes**: 9,745 cases, `selfcheck --repeat 4` reports 0 nondeterministic |
| **Wide build** | WSL, `build-oracle/wide` | the same, plus `--with-x --enable-opencl --enable-deprecated` | compile check for the X11 and OpenCL files | yes, since 2026-10-05, as `WIDE=1` (`base-wide`, `cov-wide`): X11 cases under Xvfb, OpenCL under pocl (`MUTATION.md`, *W01*) |
| **Windows build** | Windows, MSYS2 UCRT64, a clone with LF line endings | `--disable-shared --disable-openmp --without-modules`, no delegate libraries | compile check for the Windows-only files and branches | later: once `oracle.py` runs on Windows (step 4) |

One full oracle today, possibly two later, and one build that only compiles. The GitHub
Actions workflow `main.yml` adds compile checks on macOS and on Visual Studio for every pull
request to `main`.

### What each build compiles

MagickCore has 95 `.c` files. The oracle build compiles 87 of them; the other two builds
reach almost all the rest:

| File | Lines | Baseline | Oracle build | Wide build | Windows build |
| --- | ---: | ---: | --- | --- | --- |
| `display.c` | 16,288 | 1.02 | 23 lines | compiled | - |
| `xwindow.c` | 10,102 | 1.10 | 33 lines | compiled | - |
| `widget.c` | 9,700 | 1.19 | no | compiled | - |
| `animate.c` | 3,059 | 1.77 | 12 lines | compiled | - |
| `accelerate.c` | 4,751 | 2.06 | no | compiled | - |
| `opencl.c` | 3,335 | 2.85 | no | compiled | - |
| `nt-base.c` | 3,175 | 4.12 | no | no | compiled |
| `image-view.c` | 1,205 | 6.24 | compiled, not linked into `magick` | compiled | not checked |
| `nt-feature.c` | 324 | 8.57 | no | no | compiled |
| `deprecate.c` | 436 | 8.63 | compiled, not linked into `magick` | compiled | not checked |
| `vms.c` | 271 | 9.68 | no | no | no (OpenVMS); already green |

The Windows build also compiles the `MAGICKCORE_WINDOWS_SUPPORT` branches of the portable
files (`utility.c`, `blob.c`, `resource.c`, ...) and the Windows-only coders `emf.c`,
`clipboard.c` and `screenshot.c`.

---

## Three levels of evidence

Every refactoring commit states which level verified it.

| Level | Applies to | Verification | Recipes allowed |
| --- | --- | --- | --- |
| **Oracle-verified** | functions that pass the readiness gate below | oracle `run --function`, guard, build | the whole playbook |
| **Guard-verified** | functions that compile in some build but fail the gate: never called by a case, weakly checked, or X11 and OpenCL code | guard `OK` with `--calls`, the build that compiles the file (with `-Werror` on the changed file), and the machine-code comparison where it applies | only the recipes whose guard signature is exact: E, G, P, R, X |
| **Not verified** | code no build here compiles (`vms.c`) | none | untouched |

Guard-verified is how 3SX refactored a decompiled game with no tests: the literal and call
fingerprint (`tools/refactor_guard.py`, ported from 3SX) was the proof of every commit. It
has two blind spots, both named in the 3SX playbook: reordered statements, which the
prohibition list bans outright, and transposed arguments in a call. Recipes D, C and A fold
code together, so the guard cannot follow them, and they stay oracle-only.

### The machine-code comparison (proposed, step 3)

For Recipe E, the extracted `static` helper has one caller, and at `-O2` clang almost always
inlines it back. Compiling the function before and after and comparing its optimised LLVM IR
proves the two identical for that build, including argument and statement order, which the
guard cannot see. A mismatch proves nothing either way (inlining can be declined, blocks laid
out differently), and the commit falls back to guard-only. Not in the 3SX playbook: it is
proposed here as an addition.

**Prototype, measured on the 42 file changes in `night1-refactoring` (2026-09-30).** Each
file is compiled before and after with the oracle build's own flags, at `-O2 -g0`, with
`-D__LINE__=0` and at the same path: ImageMagick's exception macros embed `__LINE__` and
`__FILE__`, so without that every function below an edit differs. Functions are compared
structurally: values are identified by what computes them rather than by their numbers,
side-effect-free instructions form a set within their block, and calls, loads and stores
keep their order.

| Result | File changes |
| --- | ---: |
| identical after optimisation, every function in the file | **18** of 42 |
| differs | 24 |

Why the others differ, in the cases read with `llvm-diff`: an extraction moved a local
variable with an initialiser into the helper (`ThumbnailImage`'s 12 KB `encode_uri`,
now set up only on the path that uses it), a deduplicated helper is not inlined because
it has two callers (the shear and `ModulateImage` commits), or the merged control flow
has a different shape (`SigmoidalContrastImage` has four more `phi` nodes). These are
behaviour-preserving, but not identical code, and the check proves only identity.

**Does it catch mistakes?** Typical slips planted in the lines each identical commit
added (`<` to `<=`, `>` to `>=`, two arguments swapped): all 16 that change behaviour
were reported as differing, including all 5 argument swaps, which the guard cannot see.
The one plant reported identical was `if (lobes < 1) lobes=1;` with `<=`, an equivalent
mutant, which the compiler rightly reduces to the same code.

So the comparison can carry about 40% of extractions to a proof stronger than the oracle's,
and says nothing about the rest. The prototype scripts are in `build-oracle/irq/` on the
WSL clone (not in git); making them a tool is part of step 3.

---

## The readiness gate, per function

A single mutation score for MagickCore is not a useful target: it multiplies reach, the
share of equivalent mutants and the oracle's real strength, and only the last measures the
oracle. The gate is per function, run before refactoring it:

1. **Reach.** The case map lists cases that execute the function (`casemap.py F`);
   `make_task.py` flags functions reached by fewer than 10.
2. **Explained kill rate.** Run its mutants uncapped (`mutate.py --function F --max-cases 0`).
   Each survivor on an executed line is either classified as equivalent or unobservable,
   with its kind named (`classify.py` makes the first pass: logging, progress, loop and
   channel bounds, allocation sizes, ...), or counted as a gap.
   killed / (killed + unexplained survivors):
   - **ready**: 90% or more;
   - **careful**: 75-90%; refactor with extra review, or add a case first;
   - **not ready**: below 75%; add cases, or refactor at the guard-verified level.

This replaces the file-level groups in [`BACKLOG.md`](BACKLOG.md), which were drawn from
40-100 sampled mutants per file. The raw MagickCore score is still reported, as a trend: it
shows whether new cases improve reach, and it keeps Linux and Mac results comparable.

For reference: on the Mac, sampled over all 84 compiled files and weighted by their mutant
counts, about 50% of MagickCore's mutants were killed, and about 74% of those on lines the
oracle executes. The first two full Linux runs, before rerunning capped survivors:
`colorspace.c` 393 of 550 killed (145 of the 156 survivors capped), `morphology.c` 823 of
1,258 (321 of 405 capped).

---

## What the oracle does not reach, and why

On Linux, 441 of MagickCore's 1,891 compiled functions (23%) are never called by a case,
and 62% of instrumented lines are executed. Of the 43,217 unexecuted lines, 40% are in
those never-called functions and 60% are untaken branches (error paths, rare options,
boundary values) inside functions that do run. The never-called functions fall into four
groups; the examples are the largest, classified by hand:

| Group | Examples | Remedy |
| --- | --- | --- |
| **Reachable from the CLI, no case yet** | `PolaroidImage` (`-polaroid`), `ColorDecisionListImage` (`-color-decision-list`), `HuffmanEncodeImage` / `HuffmanDecodeImage` (fax, compressed PS/PDF), the BGRO and CMYKO raw importers and exporters, all of `profile.c` (needs corpus images with EXIF, ICC, XMP) | add cases: cheap, and moves functions to oracle-verified |
| **Reachable only through what the oracle excludes** | `RenderPostscript` (text through Ghostscript), `distribute-cache.c` (a network server), `TranslateEvent` (`-debug` logging) | guard-verified |
| **Public API only, no CLI path** | the typed `Import*Pixel` / `Export*Pixel` in `pixel.c`, `GetImageDynamicThreshold` | guard-verified, or a small C driver (a new harness; the owner decides) |
| **Provably dead** | rare: only a `static` function with no caller; an exported function may be called by any program | report, do not delete |

The share of each group over all 441 functions is not measured yet (step 2).

---

## Steps

| # | Step | Status |
| --- | --- | --- |
| 1 | Write the three levels and the readiness gate into `PLAYBOOK.md` and `AGENTS.md`; extend the backlog with a verification-level column | done in the playbook (*Two levels of evidence*) and `AGENTS.md`, with `tools/oracle/gate.py`; the backlog column is still to do, file by file as the gate is run |
| 2 | Classify all 441 never-called functions into the groups above; list the cases to add for the first group, ordered by the code each would reach | open |
| 3 | Prototype the machine-code comparison on the refactorings in `night1-refactoring`; report how often it matches | prototype done: 18 of 42 identical, 16 of 16 planted slips caught (above). Next: a tool in `tools/`, run by `verify_step.sh` |
| 4 | Run `oracle.py` on Windows, base against candidate as `magick.exe` builds, so that `nt-base.c` becomes oracle-verified | open |
| 5 | Add `wide` (and `win`) to `build.sh`, so the compile checks are one command like the others; find what `deprecate.c` needs | done: `build.sh wide` (69 s in WSL) and `build.sh win` (169 s in MSYS2, LF clone). `deprecate.c` compiles in every build: `--enable-deprecated` excludes the deprecated API, and nothing in `magick` calls the rest, so the linker drops it |
| 6 | OpenCL at runtime: `pocl` 5.0 (Ubuntu 24.04) aborts compiling ImageMagick's kernels (`Assertion 'region_entry_barrier != NULL' failed`); try a newer `pocl`. If it works and `selfcheck` is clean, `accelerate.c` can be oracle-verified | done (2026-10-05): `POCL_WORK_GROUP_METHOD=cbs` avoids the abort; the oracle runs OpenCL and X11 cases under `WIDE=1` (`MUTATION.md`, *W01*) |
| 7 | X11 at runtime: under Xvfb, see which paths of `display.c`, `animate.c` and `xwindow.c` non-interactive commands reach (`import -window root`, ...) | open |
| 8 | Rerun the capped survivors of `colorspace.c` and `morphology.c` uncapped, classify them, and put both files through the gate | `colorspace.c` done: 82% overall, 5 functions ready, the two big ones careful (see `MUTATION.md`, *Linux*); `morphology.c` done: 70% overall. After 109 cases for the gaps: `colorspace.c` 88%, `morphology.c` 77% (`MUTATION.md`) |
| 9 | A sampled mutation sweep over all compiled MagickCore files on Linux, for the trend figure | done: 4,506 mutants; after rerunning the 190 capped survivors uncapped (175 killed), 73.8% killed, 92.3% on executed lines, gate 89.7%, strict 75.6% (`MUTATION.md`, *Linux sweep*) |
