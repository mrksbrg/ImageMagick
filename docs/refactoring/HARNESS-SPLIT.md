# The harness phase: who does which file

**Why the harness exists.** The project asks whether healthy code is cheaper for agents to
work with. Its deliverable is a version of the codebase at Code Health 10; the harness is
the evidence that the refactored code still does the same, argued from the oracle's
mutation score. Size the harness work by what that argument needs, not by perfection per
file (decided by the project owner, 2026-10-01).

**This phase is only about the test harness.** The goal is a mutation score that can be
trusted for every MagickCore file: cases for the gaps, verdicts on the survivors, and the
readiness gate ([`VERIFICATION.md`](VERIFICATION.md)) run per file. **No refactoring of
ImageMagick's sources, and no refactoring branches, until the project owner starts that
phase.**

Two machines share the work, each owning half of MagickCore's 95 `.c` files:

- **Mac**: the MacBook (macOS, Apple silicon), which already holds the verdicts for the
  Phase 1 files.
- **Windows**: the Windows desktop, working in WSL2 (Ubuntu 24.04), with the `wide`
  (X11, OpenCL) and `win` (MSYS2) builds that only it can make.

A third machine computes for the Mac (2026-10-01): **ERDC**, a JupyterHub container
with 30 AMD EPYC cores and Ubuntu 24.04, no root and no mounts. Its toolchain is unpacked
from the Ubuntu .debs into `~/sysroot` (clang 18, Mull 0.34.1 for LLVM 18, the delegate
libraries; `build.sh` takes it through `SYSROOT`), and mutants run under `landlock.py`
instead of bubblewrap, which the container cannot start. `selfcheck --repeat 4`: 10,525
cases, 0 nondeterministic. It runs whole files of the Mac's list, full run and capped
rerun on one build, and the reports come back to the Mac as `mutation-erdc-*.json`;
the Mac reads the survivors and writes the verdicts. ERDC pushes them, with its logs and
scripts, to the branch `erdc-results` with `tools/oracle/erdc/push-results.sh` (kept in
`~/imagemagick-mutation/setup/` there), from a repository of its own; its token can write
only to the fork. That branch holds nothing else, and ERDC never commits to
`refactoring-setup`. Each commit records the ImageMagick commit it measured
(`MEASURED_AT`). On the Mac, `tools/oracle/erdc/fetch-results.sh` copies the reports into
`build-oracle/work`, rewriting ERDC's paths to the Mac's, and lists what is new. A file's figures come from one
machine only: a run there is never merged with a run on the Mac. About 3.5 times the
Mac's speed (`draw.c`, 2,493 mutants, in 21 minutes).

Only the owner of a file runs its mutation analysis, reads its survivors, writes its
verdicts and adds cases for it. The split was balanced on the remaining work, a file's
mutants times the share not yet killed or explained (strict figure, from the Linux sweep
of 2026-09-30 after its capped rerun): about 4,000 mutants per side. Related files stay
with one owner. Files only one machine can build go to that machine.

**Update (project owner, 2026-10-05): ownership is a split of work, not of capability.**
The Mac now builds X11 and OpenCL as well (`build-oracle/x11cl`). Only `nt-base.c`,
`nt-feature.c` (native Windows) and `vms.c` build on neither, and they stay written off.

- **Labels.** "Mac" and "Windows" below say who did a file's harness work. What still
  matters per file is which machine **measured** it.
- **Platform differences** are handled per mutant, not per file: glibc against BSD qsort,
  and `MALLOC_PERTURB_` hiding uninitialised reads on Linux. See
  `tools/oracle/platform-kills/`.
- **The X11 and OpenCL files** go to the Windows desktop as task
  [`tasks/W01-x11-opencl.md`](tasks/W01-x11-opencl.md): Xvfb, a newer pocl, and the
  likely upstream OpenCL bind bug.

## Mac: 48 files

Fixed: the Phase 1 files with verdicts already (`resize.c`, `compare.c`, `enhance.c`,
`visual-effects.c`, `statistic.c`, `threshold.c`, `shear.c`, `segment.c`, `decorate.c`,
`colormap.c`). With them: the configuration and registry files (`configure.c`, `mime.c`,
`type.c`, `locale.c`, `log.c`, `magic.c`, `coder.c`, `delegate.c`, `policy.c`,
`module.c`, `version.c`), drawing and text (`draw.c`, `annotate.c`, `paint.c`), `image.c`
with `image-view.c`, `property.c` with `artifact.c`, `string.c` with `utility.c`, and
`profile.c`.

| File | Lines | Mutants | Strict, Linux sweep |
| --- | ---: | ---: | ---: |
| `module.c` | 1,712 | 7 | 0% |
| `version.c` | 697 | 20 | 15% |
| `profile.c` | 2,996 | 470 | 20% |
| `mime.c` | 1,107 | 128 | 32% |
| `compress.c` | 1,298 | 224 | 37% |
| `delegate.c` | 2,373 | 297 | 39% |
| `log.c` | 1,977 | 215 | 42% |
| `annotate.c` | 2,507 | 578 | 47% |
| `utility.c` | 2,087 | 335 | 57% |
| `configure.c` | 1,360 | 116 | 58% |
| `vision.c` | 1,838 | 735 | 62% |
| `string.c` | 2,683 | 372 | 64% |
| `thread.c` | 250 | 3 | 67% |
| `attribute.c` | 2,444 | 513 | 68% |
| `layer.c` | 2,097 | 396 | 68% |
| `type.c` | 1,418 | 221 | 69% |
| `cipher.c` | 1,195 | 155 | 70% |
| `policy.c` | 1,618 | 235 | 75% |
| `static.c` | 379 | 21 | 75% |
| `property.c` | 4,879 | 748 | 77% |
| `draw.c` | 7,976 | 2,493 | 77% |
| `list.c` | 1,504 | 159 | 78% |
| `artifact.c` | 491 | 25 | 78% |
| `compare.c` | 4,987 | 672 | 82% |
| `fourier.c` | 1,626 | 63 | 82% |
| `coder.c` | 562 | 49 | 83% |
| `paint.c` | 1,299 | 282 | 83% |
| `shear.c` | 1,830 | 511 | 83% |
| `image.c` | 4,364 | 644 | 86% |
| `enhance.c` | 4,596 | 983 | 86% |
| `random.c` | 996 | 45 | 87% |
| `segment.c` | 1,934 | 443 | 88% |
| `channel.c` | 1,394 | 225 | 89% |
| `magic.c` | 823 | 84 | 90% |
| `visual-effects.c` | 3,789 | 841 | 91% |
| `identify.c` | 1,705 | 368 | 92% |
| `locale.c` | 1,716 | 164 | 92% |
| `memory.c` | 1,713 | 68 | 92% |
| `transform.c` | 2,599 | 594 | 92% |
| `threshold.c` | 2,648 | 557 | 93% |
| `decorate.c` | 901 | 368 | 97% |
| `geometry.c` | 1,831 | 330 | 97% |
| `statistic.c` | 3,158 | 906 | 98% |
| `effect.c` | 4,405 | 1,154 | 98% |
| `resize.c` | 4,704 | 1,020 | 98% |
| `client.c` | 163 | 5 | 100% |
| `colormap.c` | 388 | 46 | 100% |
| `image-view.c` | 1,205 | - | - |

## Windows: 47 files

Fixed: `colorspace.c` and `morphology.c` (gated here: 88% and 81%), and the files only
this machine builds: `display.c`, `xwindow.c`, `widget.c`, `animate.c`, `accelerate.c`,
`opencl.c` (`build.sh wide`), `nt-base.c`, `nt-feature.c` (`build.sh win`), and `vms.c`,
which nothing here compiles. With them: the pixel cache (`cache.c`, `cache-view.c`,
`distribute-cache.c`), the quantum files (`quantum-import.c`, `quantum-export.c`,
`quantum.c`), `blob.c` with `constitute.c`, `pixel.c`, `composite.c`, `color.c`, and the
containers (`splay-tree.c`, `linked-list.c`, `xml-tree.c`, `token.c`).

| File | Lines | Mutants | Strict, Linux sweep |
| --- | ---: | ---: | ---: |
| `animate.c` | 3,059 | 1 | 0% |
| `display.c` | 16,288 | 2 | 0% |
| `distribute-cache.c` | 2,072 | 176 | 0% |
| `xwindow.c` | 10,102 | 1 | 0% |
| `cache-view.c` | 1,114 | 29 | 33% |
| `quantum-import.c` | 4,518 | 868 | 37% |
| `linked-list.c` | 1,040 | 81 | 42% |
| `pixel.c` | 6,532 | 2,357 | 53% |
| `splay-tree.c` | 1,631 | 204 | 55% |
| `quantum-export.c` | 3,901 | 781 | 57% |
| `token.c` | 1,068 | 184 | 58% |
| `matrix.c` | 1,146 | 214 | 61% |
| `blob.c` | 6,756 | 576 | 68% |
| `color.c` | 2,792 | 389 | 70% |
| `stream.c` | 2,832 | 492 | 73% |
| `timer.c` | 664 | 35 | 77% |
| `cache.c` | 6,108 | 860 | 78% |
| `magick.c` | 1,866 | 120 | 78% |
| `fx.c` | 4,536 | 927 | 80% |
| `registry.c` | 537 | 31 | 83% |
| `quantize.c` | 4,150 | 868 | 83% |
| `distort.c` | 3,466 | 1,052 | 83% |
| `xml-tree.c` | 2,347 | 620 | 83% |
| `option.c` | 3,549 | 149 | 85% |
| `montage.c` | 898 | 224 | 86% |
| `prepress.c` | 154 | 17 | 87% |
| `quantum.c` | 1,110 | 88 | 88% |
| `signature.c` | 818 | 71 | 88% |
| `resource.c` | 1,598 | 179 | 90% |
| `constitute.c` | 1,618 | 238 | 95% |
| `exception.c` | 1,158 | 69 | 95% |
| `feature.c` | 2,340 | 842 | 95% |
| `morphology.c` | 4,764 | 1,258 | 95% |
| `colorspace.c` | 2,899 | 550 | 98% |
| `composite.c` | 3,815 | 1,289 | 100% |
| `gem.c` | 348 | 114 | 100% |
| `histogram.c` | 1,246 | 165 | 100% |
| `monitor.c` | 263 | 9 | 100% |
| `resample.c` | 1,463 | 228 | 100% |
| `semaphore.c` | 482 | 20 | 100% |
| `accelerate.c` | 4,751 | - | - |
| `deprecate.c` | 436 | - | - |
| `nt-base.c` | 3,175 | - | - |
| `nt-feature.c` | 324 | - | - |
| `opencl.c` | 3,335 | - | - |
| `vms.c` | 271 | - | - |
| `widget.c` | 9,700 | - | - |

## The procedure, per file

The same on both machines, so the results can be compared:

1. Pull. Rebuild the indexes if the catalogue changed: `casemap.py`, then `linecov.py`.
2. Full mutation run of the file, then its capped survivors rerun against up to 1,500
   cases: `mutate.py --file 'MagickCore/<file>\.c$' --name full-<file>`, then
   `--ids <capped> --max-cases 1500 --name cap1500-<file>`. Not uncapped: in functions
   nearly every case reaches, an uncapped survivor costs up to ~10,000 case runs (a file
   took 5 hours on the Mac), and the figure barely moves; the Linux sweep found 175 of 190
   capped survivors were simply killed by a later case. Say in the file's section that the
   rerun was capped at 1,500.
3. Gate it: `gate.py mutation-full-<file>.json mutation-cap1500-<file>.json`.
4. Read every unmatched survivor. Record a verdict in `verdicts.json` (`equivalent`,
   `unobservable`, `gap` with `killed_by`, or `unresolved`). A `gap` verdict is recorded
   only after the mutant has been run against the proposed case and killed.
5. Add the cases the gaps call for. `selfcheck --repeat 4` over the families touched must
   report 0 nondeterministic before they are committed.
6. Rerun the survivors against the new cases only (`--cases`), gate again, and record the
   before and after in `MUTATION.md`, in a section headed with the file and the machine.

### When a file is trusted

The aim of this phase is test cases we can trust for every file. Every function will be
refactored sooner or later, so the measure is per function: a file's pooled score can hide
a weak function behind strong ones. A file is **trusted** when all of these hold:

- a **full run**: every mutant Mull generates for the file, not a sample;
- every capped survivor **rerun against up to 1,500 cases** (step 2);
- **every function at an adjusted score of 80% or more** (`gate.py`, the function's row),
  or written down as out of reach, with the reason (below). The adjusted score counts the
  mutants in functions no case executes as gaps, so unreached code lowers it. 80% on this
  measure is strict: unresolved survivors count against it, and only named reasons excuse
  one. The file's `ALL` row is reported as a summary;
- every excused survivor **named with its reason**, by a `classify.py` rule or a hand
  verdict in `verdicts.json`; a `gap` verdict only once its case is in and has killed it;
- every survivor still open **listed** in the file's section of `MUTATION.md`.

The refactoring phase keeps the gate's bands per function: **ready** at 90% or more,
**careful** at 75-90% (extra review, or a case added first). So a function that passes the
harness at 82% is refactored with care.

Otherwise the file is **not trusted**, and its section says why: API functions no command
reaches, X11 without a display, OpenCL without a working runtime, an external program.
Writing the reason down does not make a file trusted. It tells the later refactoring phase
that the file can only be guard-verified.

**Decided (project owner, 2026-10-02): the operators are Mull's defaults plus statement
deletion, on all three machines** (Mac, Windows, ERDC). The equivalence argument is that the
oracle would catch a refactoring mistake, so the operators should model the mistakes
refactoring makes, and the one an extraction makes most is a lost statement. The trial on
the Mac's 48 files (`MUTATION.md`, *Statement deletion on the Mac's files*) added 6.6% more
mutants and found about 260 survivors of that kind: lost initialisers, pixel writes and
geometry calls the defaults cannot model. Logical connectors (`&&`, `||`) cannot be had from
Mull for this code (the Windows pilot), so they are left out.

- `build.sh mull` builds `cxx_default cxx_remove_void_call` unless `MULL_MUTATORS` says
  otherwise. **Give every new Mull build a new name**: rebuilding in an existing
  directory recompiles only changed sources, so an old build would keep its old mutants.
- **A file's trust now counts its statement-deletion mutants.** A file already fully run
  on the defaults needs only the new mutants: list the build's `cxx_remove_void_call`
  mutants of the file (`mutate.list_mutants`), run them with `--ids` capped at 1,500
  (`night.sh` step 2 shows how), and pass that report to `gate.py` after the others.
  New full runs include them anyway.
- **Files trusted on the defaults are trusted again only once their new survivors are
  read.** On 2026-10-02 that took `list.c`, `enhance.c`, `threshold.c`, `segment.c`,
  `compress.c` and `random.c` back below the bar; `effect.c`, `fourier.c`, `magic.c`,
  `decorate.c`, `shear.c` and `vision.c` stay trusted.
- **ERDC is the main workhorse** (owner, 2026-10-02): it runs the heavy mutation runs for
  the Mac's files, and its figures replace the Mac's (`string.c` and `property.c`
  included). It can run the statement-deletion mutants of the Windows files too, except
  those only Windows builds; their reports come back on `erdc-results` like the Mac's, and
  Windows, as the owner of those files, reads the survivors and writes the verdicts.

## Working in the same repository

Both machines commit to `refactoring-setup`. To keep merges clean:

- **Pull before starting a step and again right before committing; push straight after.**
  Small commits, one file's round at a time.
- **`cases.py`**: the Mac adds its cases to the `GAP_*` lists (family `gaps`). Windows
  adds its cases in its own generators next to the families they extend
  (`_morphology_arg_cases`, `_shown_kernel_cases`, ...) or in a block of its own marked
  `# ---- gaps found on the Windows machine`, never inside the Mac's lists.
- **`verdicts.json`**: keys stay sorted (`json.dump(..., sort_keys=True, indent=1)`), so
  each machine's additions land among its own functions and git merges them. Never
  reformat the whole file.
- **`MUTATION.md`**: each round is a new section, headed with the file and the machine
  (`## Reading survivors by hand: blob.c (Windows)`), added before *How to use this in
  the campaign*. Do not edit the other machine's sections; correct them in your own.
- **Shared tools** (`classify.py`, `gate.py`, `mutate.py`, `oracle.py`): a change goes in
  its own commit, says what it changes for the other machine, and must keep the tool's
  Code Health at 10.00.
- After pulling a catalogue change, rebuild `casemap.py` and `linecov.py` before the next
  mutation run: `mutate.py` refuses a stale case map.
- Figures are per machine: say which machine measured them. Verdicts are about the source
  and hold on both.

## Message for the Mac agent

> The harness work on MagickCore is now split between two machines. Pull
> `refactoring-setup` and read `docs/refactoring/HARNESS-SPLIT.md`. You own the 48 files
> listed under *Mac*, the Phase 1 files among them. Windows owns the other 47: don't run
> survivor analysis or add cases for those. No refactoring in this phase, only the test
> harness. Follow the procedure and the rules for shared files in that document; in
> particular, pull right before every commit, add cases only to the `GAP_*` lists, and
> keep `verdicts.json` sorted.

## Message for the Windows agent (2026-10-02)

> The project owner has decided the mutation operators: Mull's defaults plus statement
> deletion (`cxx_remove_void_call`), on all three machines. Pull `refactoring-setup`
> and read *Decided (project owner, 2026-10-02)* in `docs/refactoring/HARNESS-SPLIT.md`.
> `build.sh mull` now builds both by default; give every new Mull build a new name. Your
> files' trust now counts their statement-deletion mutants. ERDC will run those mutants
> for the Windows files it can build and push the reports to the `erdc-results` branch
> (`tools/oracle/erdc/fetch-results.sh` copies them into `build-oracle/work` as
> `mutation-erdc-sdl-<file>.json`); for `display.c`, `xwindow.c`, `widget.c`,
> `animate.c`, `accelerate.c`, `opencl.c`, `nt-base.c`, `nt-feature.c` and `vms.c`, run
> them yourself. You still read the survivors and write the verdicts for your files.
> Also new: case files may sit in subdirectories, so a case can bring its own
> `.config/ImageMagick/policy.xml` or `type.xml` (`MUTATION.md`, *Configuration of the
> case's own*).

## Message for the Windows agent (2026-10-05)

> The project owner has given you the X11 and OpenCL files: pull `refactoring-setup` and
> follow [`docs/refactoring/tasks/W01-x11-opencl.md`](tasks/W01-x11-opencl.md).
>
> In short:
> - Xvfb for the four X11 files.
> - A newer pocl and a pinned device for `accelerate.c` and `opencl.c`.
> - Check the likely upstream bug described there (OpenCL never binds when the build finds
>   the OpenCL header).
> - Then the usual: cases, a Mull build, survivors, verdicts.
>
> Still the harness phase: no changes to ImageMagick's sources. Also new since your last
> pull:
> - `tools/oracle/platform-kills/`, read by `gate.py`.
> - `HARNESS_VERSION` 10: `-list configure`'s toolchain lines are normalised.
> - Rebuild baseline and candidate together after a library upgrade.
> - Four of your `blob writeimages … adjoin` cases (GIF, TIFF, PPM, MIFF) hash 4096 bytes of
>   `image_info->blob` after WriteImages has outgrown the caller's buffer. They differ from
>   run to run on the Mac (Linux's `MALLOC_PERTURB_` masks it). Hash only the written
>   length, and check whether the blob pointer is still live.
