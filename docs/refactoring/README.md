# Code Health Refactoring Campaign

A structured, measurable campaign to reduce technical debt in ImageMagick, designed so
that the work can be distributed across many agents. It follows the Street Fighter III:
3rd Strike campaign, which took every scored file in that codebase to Code Health 10.00.

Every task is scoped to **one file**, bounded by a **closed catalogue of
transformations** ([`PLAYBOOK.md`](PLAYBOOK.md)), judged by an **external metric**
(CodeScene Code Health) rather than by taste, and checked by a **differential oracle**
that demands byte-identical behaviour ([`ORACLE.md`](ORACLE.md)).

---

## Baseline

Measured on 2026-09-29 at upstream commit `68168e6e5`, with `cs-mcp` 1.5.6 and `cs`
1.0.46, across every `.c` and `.cpp` file in the library subsystems. Tests, fuzzers,
demos, PerlMagick, API examples and the website are excluded.

| Band | Score | Files |
| --- | --- | ---: |
| **Red** - severe debt | 1.0 - 3.9 | **102** |
| **Yellow** - problematic debt | 4.0 - 8.9 | 132 |
| Green | 9.0 - 9.9 | 38 |
| Optimal | 10.0 | 23 |
| **Total scored** | | **295** |

| Subsystem | Files | Mean | Red | Yellow | Green | Optimal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `MagickCore/` | 95 | **4.36** | **51** | 35 | 6 | 3 |
| `coders/` | 145 | 6.26 | 40 | 77 | 23 | 5 |
| `MagickWand/` | 34 | 6.59 | 11 | 10 | 8 | 5 |
| `Magick++/lib/` | 19 | 8.89 | 0 | 9 | 0 | 10 |
| `filters/` | 1 | 8.14 | 0 | 1 | 0 | 0 |
| `utilities/` | 1 | 9.00 | 0 | 0 | 1 | 0 |

**Take the numbers from the JSON, not from this table.**
[`codehealth-baseline.json`](codehealth-baseline.json) is the committed baseline and is
never updated. `python3 tools/codehealth_sweep.py` writes `codehealth-current.json`
beside it, with the date, the commit and the tool versions.

The debt is concentrated in MagickCore: more than half its files are Red, and its worst
score 1.02-1.14 (`display.c`, `pixel.c`, `xwindow.c`, `fx.c`). For comparison, 3SX
started with 19 Red files out of 482.

### Where it stands (2026-09-30)

The first refactoring night: 41 commits, each one recipe on one function, each checked
by the build, the literal and call guards, the oracle on every case reaching the
function, and the CodeScene pre-commit gate. A full oracle run over all 9,751 cases
afterwards: 0 diverged.

| File | Baseline | Now |
| --- | ---: | ---: |
| `MagickCore/shear.c` | 2.05 | 2.90 |
| `MagickCore/segment.c` | 2.30 | 3.19 |
| `MagickCore/enhance.c` | 1.53 | 2.12 |
| `MagickCore/statistic.c` | 1.92 | 2.14 |
| `MagickCore/resize.c` | 1.39 | 1.59 |
| `MagickCore/visual-effects.c` | 1.55 | 1.75 |
| `MagickCore/threshold.c` | 1.89 | 2.06 |
| `MagickCore/morphology.c` | 1.53 | 1.63 |

No file has left the Red band yet. What moved the scores was removing Brain Methods,
ten of them; what stops them is recorded in the playbook's *Known plateaus*,
including a proposed change to the OpenMP rule that would unlock the largest functions.

---

## The central risk

ImageMagick is a library that other programs depend on, and its output is compared
byte for byte by many of them. A refactoring that shifts one pixel by one unit, rounds
one value differently, or changes one message is a regression that no compiler warning
will catch, and that `make check` would not catch either: most of its tests only check
that a command succeeded.

**The oracle is what proves behaviour was preserved.** It runs about 9,500 command lines
on the base build and on the candidate and requires identical exit status, stdout, stderr
and output bytes. Scoped to one function (`oracle.py run --function`), it takes seconds,
so it runs after every commit.

**The oracle only protects what it reaches.** Mutation testing
([`MUTATION.md`](MUTATION.md)) measured how often it notices a deliberate change: in
MagickCore, 77% of mutants on executed lines in the 25 largest files, 68% in the rest,
and much less in code the catalogue never drives. That is why the backlog ranks files by
protection first and by Code Health second.

---

## Scope and phases

**Phase 0 - the safety net** *(done)*. The oracle, mutation testing of it across every
compiled MagickCore file, the guard and CodeScene tools, the baseline.

**Phase 1 - pilot on ready MagickCore files.** Start with `resize.c`, then the other
ready image-processing files in [`BACKLOG.md`](BACKLOG.md). This phase tests whether the
recipes and the verification loop work for ImageMagick, on files where a mistake is
caught.

**Phase 2 - the rest of MagickCore.** Check-per-function files with their mutants run
first; needs-cases files after the catalogue is extended for them.

**Phase 3 - the other subsystems.** The MagickWand command-line files are reachable now.
The coders need their delegate libraries and per-format corpus files, which is easier on
Linux. The Wand and Magick++ APIs need a harness that calls them. Do not generate tasks
for these until Phase 1 has shown the pipeline works and the per-file cost is known.

**Platform code** - X11 (`display.c`, `xwindow.c`, `widget.c`, `animate.c`), OpenCL
(`accelerate.c`, `opencl.c`) and Windows (`nt-base.c`, `nt-feature.c`) - is not compiled
on the macOS reference machine and is out of scope until the campaign moves to a machine
that builds it.

---

## Rules for every agent

1. Apply **only** the recipes in [`PLAYBOOK.md`](PLAYBOOK.md). Nothing else.
2. **One recipe, one function, one commit.**
3. Re-measure after every commit. If the score did not improve, run
   `python3 tools/ch.py --review <file>` and keep the change only when the targeted
   function left a smell category or its complexity dropped. Otherwise revert.
4. Never change literals, arithmetic, comparisons, types, the order of side effects,
   anything public, or anything touching OpenMP. See [`AGENTS.md`](../../AGENTS.md).
5. Found a bug? **Report it, do not fix it.**
6. **4.00 leaves the Red band; it is not the finish line.** Keep applying the catalogue
   until no legal recipe raises the score further, then record where the file plateaued
   and why. The target is 10.00.
7. Blocked, confused, or the function is not reached by any case? **Stop and report.**
   An unfinished task is a fine outcome.

---

## Definition of done, per file

- Code Health at its plateau - no legal recipe raises it further - with the figure and
  the reason recorded in the backlog, and in the playbook's *Known plateaus* if it is
  below 10.00.
- `tools/oracle/build.sh cand` succeeds.
- `python3 tools/refactor_guard.py <file>`, and `--calls` after any extract or split,
  after every commit.
- `python3 tools/oracle/oracle.py run --function <Function>` clean after every commit,
  and `python3 tools/oracle/oracle.py run` clean before the branch is pushed.
- One function per commit, message format `refactor(<file>): simplify <function>`.
- A final `python3 tools/ch.py --review <file>` in the report.

---

## Tracking progress

```bash
python3 tools/codehealth_sweep.py                 # writes codehealth-current.json
python3 tools/codehealth_sweep.py --only MagickCore/
```

Compare the result against the committed baseline to see what the campaign has bought.
Record the tool versions with any figure you report: scores move between CodeScene
releases.

---

## Files in this directory

| Path | Purpose |
| --- | --- |
| [`README.md`](README.md) | This charter |
| [`PLAYBOOK.md`](PLAYBOOK.md) | The closed catalogue of allowed transformations |
| [`BACKLOG.md`](BACKLOG.md) | Every MagickCore file ranked by protection and Code Health |
| [`ORACLE.md`](ORACLE.md) | The differential oracle: what it runs, what it compares |
| [`MUTATION.md`](MUTATION.md) | How well the oracle notices changes, file by file |
| [`codehealth-baseline.json`](codehealth-baseline.json) | The committed baseline sweep |
| [`PORTING.md`](PORTING.md) | Moving the campaign to Linux (WSL2): what changes, what to measure again |
| `tasks/M01..M13` | One task file per Phase 1 file, generated by `tools/make_task.py` |

Repo-root files that agents read: [`../../AGENTS.md`](../../AGENTS.md) (all harnesses)
and [`../../CLAUDE.md`](../../CLAUDE.md) (Claude Code).

## The tools

| Tool | What it answers |
| --- | --- |
| `tools/oracle/oracle.py run [--function F]` | Is behaviour byte-identical to the base? |
| `tools/oracle/casemap.py F` | Which cases execute function `F`? |
| `tools/oracle/mutate.py` | Would the oracle notice a change here? |
| `tools/refactor_guard.py <file>` | Did any literal change? |
| `tools/ch.py [--review] <file>` | What is the Code Health, and which smells remain? |
| `tools/codescene_precommit.py` | Does the staged change lower any file's Code Health? |
| `tools/codehealth_sweep.py` | Where does the whole codebase stand? |
| `tools/make_task.py ID file` | Writes a task file: smells, targets, cases and mutants per function |
