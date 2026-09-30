# Agent instructions

Read this before changing anything. It applies to every agent and every harness.

## What this repository is

This is a private fork of **ImageMagick** (`mrksbrg/ImageMagick`), used for agentic
refactoring research. ImageMagick is a C library (MagickCore, MagickWand), a C++ binding
(Magick++), roughly 150 image format coders, and the `magick` command-line tool. It is
used by millions of programs through a published, stable API.

The practical consequence:

> **Behaviour fidelity outranks code quality, readability, and your own judgement.**
> A change that makes the code cleaner but shifts one pixel by one unit, changes one byte
> of an output file, or alters one message is a defect, even if it looks obviously
> correct.

ImageMagick's arithmetic has been tuned over decades, and much of what looks redundant is
there for rounding, for HDRI (floating-point pixels outside [0,1]), or for a format quirk.
**Report what looks wrong, do not fix it.**

## Build and verification tools

The campaign's tools live in `tools/` and `tools/oracle/`. Everything they build or write
goes under `build-oracle/`, which `.git/info/exclude` keeps out of git.

```bash
tools/oracle/build.sh cand      # incremental build of the working tree, seconds
```

The oracle ([`docs/refactoring/ORACLE.md`](docs/refactoring/ORACLE.md)) is the only
mechanism that proves behaviour was preserved. It builds `magick` from the base commit and
from your working tree, runs about 9,500 command lines on both, and fails unless exit
status, stdout, stderr and every output byte are **identical**. There is no tolerance.

`make check` is not a substitute: most of it checks only that a command succeeded.

## The refactoring campaign

If you were given a task ID, your instructions are in
[`docs/refactoring/tasks/`](docs/refactoring/tasks/). Read, in order:

1. Your task file, if you have one
2. [`docs/refactoring/PLAYBOOK.md`](docs/refactoring/PLAYBOOK.md) - the closed catalogue
   of allowed changes
3. [`docs/refactoring/README.md`](docs/refactoring/README.md) - campaign rules and scope
4. [`docs/refactoring/BACKLOG.md`](docs/refactoring/BACKLOG.md) - which files are ready

You may apply **only** the recipes in the playbook. Anything not in it is out of scope;
the catalogue grows when the project owner authorises an addition.

## Hard prohibitions

Never, in any commit:

- Change a numeric literal, string literal, character constant, or enum value.
- Change arithmetic, bitwise operations, shifts, or the order of floating-point
  operations. `a*b*c` and `a*(b*c)` round differently.
- Change a comparison operator, including `<` to `<=`.
- Change a type, including signedness, width, or `float` to `double`.
- Reorder statements that have side effects.
- Delete code that looks dead - it may be reachable from another format, platform, or the
  API.
- **Change anything public**: the name, signature, or behaviour of a function that is not
  `static`, anything declared in an installed header, a struct layout, or an exported
  symbol. ImageMagick is a library; its ABI belongs to everyone who links it.
- **Edit an OpenMP pragma**, or move code into, out of, or across a `#pragma omp` region
  (see the playbook). The oracle runs single-threaded and cannot see a data race.
- Touch code in a preprocessor branch this build does not compile (X11, OpenCL, Windows,
  a delegate library that is not installed). Nothing can check it.
- Modify a `static const` data table.
- Fix a bug you noticed. Report it.

## Verification sequence

### Before you start on a function

The oracle only protects code its cases reach. Check, then decide:

```bash
python3 tools/oracle/casemap.py <Function>     # which cases execute it
```

A function no case executes cannot be refactored safely. Report it, with the function
name, so cases can be added. For how well the reaching cases check the function, see the
mutation results in [`docs/refactoring/MUTATION.md`](docs/refactoring/MUTATION.md) and
the readiness column in the backlog.

### After every commit

Run all four, in this order:

```bash
# 1. it still builds
tools/oracle/build.sh cand

# 2. no constant was removed or altered (add --calls after an extract or split)
python3 tools/refactor_guard.py <the file you changed>

# 3. behaviour is byte-identical on every case that reaches the function - seconds
python3 tools/oracle/oracle.py run --function <Function>

# 4. the metric improved
python3 tools/ch.py --review <the file you changed>
```

For step 3, name the function you refactored, not a helper you just extracted from it:
the case map knows the original names, and the original still calls the helper.

`refactor_guard.py` reports one of three things:

| Outcome | Meaning |
| --- | --- |
| `OK` | No literal changed. |
| `FAIL` | A value vanished, or a count dropped while another rose: a substituted constant or deleted logic. |
| `WARN` | Counts only dropped with every value still present (deduplication), or only rose (a new guard clause with its own `return`). A request for a second look, not a pass. |

If the guard fails or the oracle diverges, revert immediately:

```bash
git checkout -- <file>
```

### Before pushing a branch

```bash
python3 tools/oracle/oracle.py run              # the whole catalogue, ~2 minutes warm
```

## CodeScene

Code Health is measured with CodeScene, through its MCP server (`cs-mcp`) where the
harness has one, or through `tools/ch.py`, which talks to the same server. Do not use the
`cs` command-line tool for measurement.

- After changing code, run `code_health_review` (or `tools/ch.py --review`) on each changed
  file. If Code Health drops, fix the issues, review again, and confirm the result with
  `code_health_score`.
- Before finishing, run `pre_commit_code_health_safeguard` (or
  `tools/codescene_precommit.py`), and stop only when it passes.
- This applies to the campaign's own tools in `tools/` as well as to ImageMagick's
  sources. For ImageMagick, the playbook's rules still decide which changes are allowed.

## Commits

- One recipe, one function, one commit.
- Message format: `refactor(<file>): simplify <function>`, e.g.
  `refactor(MagickCore/resize.c): simplify ScaleImage`.
- Never squash several functions into one commit. The campaign relies on being able to
  revert a single step.
- The CodeScene gate, `tools/codescene_precommit.py`, checks what is staged: no library
  file may lose Code Health, and a new one must score 10.0. `.githooks/pre-commit` runs
  it on every commit once the clone is set up with `git config core.hooksPath .githooks`.
  It needs `cs-mcp` on the `PATH` (or `CS_MCP_BINARY_PATH`) and `CS_ACCESS_TOKEN`. Do not
  bypass it with `--no-verify`; when it refuses, stop and report, as the playbook says.

## Git remotes and pull requests

This checkout is a **fork**, and the two remotes are easy to confuse:

| Remote | Repository | Use |
| --- | --- | --- |
| `origin` | `mrksbrg/ImageMagick` | **The target for everything.** |
| `upstream` | `ImageMagick/ImageMagick` | The public project. Fetch only. |

> [!WARNING]
> **Every pull request must target `mrksbrg/ImageMagick`.** Never open one against
> `ImageMagick/ImageMagick`.

GitHub's "Compare & pull request" button and `gh pr create` both default the base to the
**upstream parent** when the repository is a fork, so the wrong target is the default.
Always name it:

```bash
gh pr create --repo mrksbrg/ImageMagick --base main
```

`upstream` has its push URL set to `DISABLED`, so a push to it fails rather than
succeeds. Keep it that way. This work is private research, not a contribution.

## When to stop

Stop and report, rather than pressing on, whenever:

- No case executes the function you want to change.
- The build fails and the fix is not obvious.
- The guard fails, or the oracle diverges, and you do not understand why.
- A function's control flow is too tangled to transform confidently.
- The change would touch OpenMP, a public symbol, or code this build does not compile.
- You want to make a change the playbook does not cover.

**An unfinished task is an acceptable outcome. A silently changed image library is not.**
Reporting "I completed 2 of 5 steps and stopped because step 3 was unclear" is a good
result.
