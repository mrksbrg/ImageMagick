# Mutation testing the oracle

Coverage says which code the oracle ([ORACLE.md](ORACLE.md)) executes. Mutation
testing says whether the oracle would **notice** if that code behaved
differently, which is what a refactoring mistake looks like. Each mutant is a
small, deliberate change (`<` becomes `<=`, `+` becomes `-`, ...); a mutant the
oracle does not flag is either equivalent to the original or a gap in the
catalogue.

## Running it

One-time setup (macOS, Apple silicon):

```bash
brew install llvm@21        # Mull 0.34.1 supports LLVM up to 21; Homebrew's default is 22
mkdir -p build-oracle/mull && cd build-oracle/mull
curl -sSLO https://github.com/mull-project/mull/releases/download/0.34.1/Mull-21-0.34.1-LLVM-21.1.8-macOS-aarch64-26.6.2.zip
unzip Mull-21-*.zip && xattr -dr com.apple.quarantine .
```

Then, per file under test:

```bash
tools/oracle/build.sh mull 'MagickCore/resize\.c$'   # mutants in this file only, ~2.5 min
tools/oracle/build.sh cov && tools/oracle/casemap.py # which cases execute which function, ~6.5 min
tools/oracle/mutate.py --file 'MagickCore/resize\.c$' [--function ScaleImage] [--limit 50]
```

For several files, build once under a name and sample each file equally:

```bash
tools/oracle/build.sh mull "$(cat build-oracle/sweep25.regex)" sweep25     # ~6 min
tools/oracle/mutate.py --file "$(cat build-oracle/sweep25.regex)" --name sweep25 --per-file 100
tools/oracle/mutate.py ... --ids FILE        # rerun chosen mutants, e.g. survivors
```

`casemap.py` only needs rerunning when the catalogue changes (it refuses to
work from a stale map). It also answers the question to ask before refactoring
any function: `tools/oracle/casemap.py ScaleImage` lists the cases that
execute it.

### How it works

Mull compiles every mutant of the selected file into one binary, each behind a
switch: the environment variable named by the mutant's id,
`cxx_add_to_sub:/abs/path/resize.c:601:15:601:16=1`. With no switch set, the
binary behaves like the original. `mutate.py` therefore uses **that same
binary as the baseline**, so no difference in compiler or flags can pass for a
kill. `mull-runner` is not used: the oracle is the test program, and running it
as a whole per mutant would take two minutes each.

For each mutant, `mutate.py` runs only the cases that execute the mutant's
function (`build-oracle/work/casemap.json`), cheapest first, and stops at the
first divergence. The result is one of:

| Status | Meaning |
| --- | --- |
| killed | a case diverged: different output, crash or timeout |
| survived | every case tried gave identical results |
| no coverage | no case executes the function |
| error | the driver failed on this mutant |

The full list goes to `build-oracle/work/mutation-<name>.json`. Each result is
also appended to `mutation-<name>.partial.jsonl` as it arrives, and rerunning
the same command resumes from it. The unmutated baseline is cached per binary
in `build-oracle/work/cache/`.

These rules keep the verdicts honest and the machine safe. Each one was
learned from a wrong result or a failed run in the sweeps below:

- **Every mutated run is sandboxed.** `delegate.c` runs the commands in
  `delegates.xml`: `lpr`, `open -a Preview`, `curl`, `gimp`,
  `xdg-open ...; /bin/rm`. No case asks for them, but a mutant can skip the
  check that stops them (`policy.c` is mutated too). `mutate.py` runs
  baseline and mutants under `sandbox-exec`, allowing only the `magick`
  binary to execute, no network, and writes only under `build-oracle/`. The
  operating system enforces it, so no mutant can switch it off. The Linux
  port needs the same, with bubblewrap or similar.
- **Output is capped.** stdout and stderr go to files and at most 64 MB is
  read back; no child may write a file over 2 GB. Without this the driver was
  killed three times in the second sweep (SIGKILL, at the same mutants each
  time), most likely by holding a runaway mutant's output in memory.
- **Timeouts scale with the case and are confirmed.** A Mull build runs
  several times slower than a normal one: `convert -sketch` takes 9.4 s
  unmutated. With a fixed 10 s limit, any mutant that merely slowed that case
  "killed" it: 90 false kills in the first sweep, 244 in a recheck. A mutant
  now gets 4 × the case's baseline time (10 to 60 s), and a timeout is rerun
  once with 120 s before it counts, because on 8 busy cores a slow case still
  overran 4 × (six more false kills in `composite.c`). Of the first sweep's
  37 timeout kills, 36 held up on confirmation: 31 real endless loops and
  5 that now crash instead.
- **At most 300 cases per mutant** (`--max-cases`). Functions like
  `ReadBlob` are reached by nearly all ~9,500 cases, so without a cap every
  survivor there costs a whole oracle run (the first attempt managed
  25 mutants in 39 minutes). A survivor that hit the cap is flagged
  `capped`: it may be a gap, or a case that was never tried may kill it.
  Uncapped reruns show which is more common: of `composite.c`'s 47 capped
  survivors, 30 were killed by a case beyond the cap. **Read capped
  survivors as mostly missed kills, not gaps.**
- **Proven killers go first.** Before the cap applies, cases that killed
  mutants in earlier reports come first, most kills first, then the cheapest
  case of each family in turn. Kills are concentrated: about 2,300 kills came
  from 488 cases. Timeout kills do not count towards the ranking.
- **The baseline cache knows how it was made.** It is keyed by binary,
  catalogue and the wrapper that runs each case. Adding the sandbox changed
  two cases' stderr (the `hp2xx` cases in ORACLE.md), and a cache from before
  it, still in use, produced 28 false kills that were counted before anyone
  looked at why they died.
- **A kill by a case later found nondeterministic does not count.** On 2026-10-03 a
  rebase of the Mac's mull-macx baseline found 11 of 12,137 cached results that no longer
  matched a fresh run, and all 27 of one rerun's `utility.c` kills came from one of them.
  `rose write-mask -scale 150x100%` leaves pixels unwritten like `-scale 50%` above
  (1 of 80 runs under a load of ten); the ten fontconfig cases sometimes left a
  `.cache/fontconfig` file in the case directory, depending on what other runs had left
  in Homebrew's shared fontconfig cache. Both are fixed in `cases.py` (e46ed05f4), and the
  old ids are listed in `tools/oracle/unstable-killers.json`, which `gate.py` reads: a
  kill credited to one of them counts as a survivor, in old reports and in reports from
  a machine still on the old catalogue. They had been credited with 66 kills of 52
  mutants (17 in `type.c`, 16 in `property.c`, 5 in `resize.c`, the rest one or two a
  file), and ERDC's run on the old catalogue credited them with 14 more, all of mutants
  among those 52; the 52 are rerun uncapped against the fixed catalogue.
- **Runs are resumable and independent.** Results are appended as they
  arrive; each run has its own baseline directory (two concurrent runs once
  deleted each other's); `mutation-<name>.started` lists every mutant as it
  starts, so a mutant that started but never finished can be identified if
  the driver dies.

Practical points found while setting this up:

- Mull's config is `mull.yml` in the compiler's working directory or above it;
  `build.sh` writes it into the build directory. Quote regexes with **single**
  quotes: in a double-quoted YAML string `\.` is an invalid escape, and Mull
  then silently falls back to mutating every file.
- On this machine `ld` on the PATH is Anaconda's, which cannot read the
  current SDK. The Mull build links with `-fuse-ld=/usr/bin/ld`.
- Call `llvm-profdata` and `llvm-cov` by full path, not through `xcrun`. The
  harness runs under an x86_64 Python, and `xcrun` fails to load under Rosetta.

## Pilot: MagickCore/resize.c

`resize.c` has 2,866 lines and 985 mutants across 16 operators (163
`mul_to_div`, 146 `eq_to_ne`, 106 `add_to_sub`, 104 each of `lt_to_le` and
`lt_to_ge`, ...). Each full run takes 17–29 minutes on 8 cores.

| Round | Catalogue | Killed | Survived | No coverage | Score, all mutants | `resize.c` line coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | as built for ORACLE.md | 615 | 275 | 95 | 62.4% | 59.3% |
| 2 | + gaps found in round 1 | 829 | 155 | 1 | 84.2% | 89.5% |
| 3 | + boundary cases from round 2 | 835 | 149 | 1 | 84.8% | 89.5% |

### Round 1 to round 2: what the survivors pointed at

Round-1 survivors split cleanly. 243 of them (95 no-coverage plus 148
survivors on lines never executed) sat on code no case reached:

- **Magnify methods** (`-define magnify:method=eagle2x|fish2x|hq2x|xbr2x|...`),
  none exercised: Xbr2X alone was 56 mutants.
- **One-dimensional scaling** (`-scale 150x100%`): ScaleImage, SampleImage
  and ResizeImage each have an early path for an unchanged row or column count.
- **The 3- and 4-lobe Spline filter** and most **`filter:*` defines**
  (`filter:lobes`, `filter:window`, `filter:filter`, `filter:support`, ...).
- **Write masks** and **`-monitor`**.
- **`MinifyImage`**, which has no command-line option at all. It is reachable
  only from the API and from MSL scripts, so the catalogue gained MSL support
  (cases can now carry files) and an MSL family. That took `coders/msl.c` from
  0.3% to 25% coverage as a side effect.

Survivors on executed lines pointed at **boundaries no input hit**: thumbnail
reduction factors of exactly 2 and 4, file names containing `url_encode`'s
boundary characters (`a`, `z`, `A`, `Z`, `0`, `9`), and exact kernel
breakpoints. `-define filter:verbose=1`, which prints a filter's weight curve
sampled every 0.01 (breakpoints included), became a family of its own.

### What remains after round 2

Of the 155 round-2 survivors, 30 are still on lines no case executes. The rest
are on executed lines and, by reading them:

| Kind | Count | Verdict |
| --- | ---: | --- |
| `<` vs `<=` at the piece boundaries of continuous kernels | 28 | equivalent: both pieces agree at the breakpoint |
| loop bound `i < channels` becomes `<=` | 28 | probably invisible: reads one channel past the end of a row buffer, and the value is overwritten or unused. Memory-safety checking (ASan) might expose some |
| `IsEventLogging()` flipped | 9 | only affects `-debug` logging, which the oracle does not compare |
| allocation, zeroing, thread-local storage | 7 | not observable in output |
| progress monitor | 2 | only affects `-monitor` output |
| other, read by hand | 51 | a mix: exact-half write-mask values, support exactly 0.5 on palette images, thumbnail factors with one side at the boundary (all three addressed in round 3), plus ScaleImage's span arithmetic and Gaussian sigma coefficients not yet understood |

The mutation score on lines the oracle executes was **86.9%** after round 2.
Round 3 added cases for the three boundary groups flagged "addressed in round
3" and killed 6 more mutants. The remaining ones in those groups need inputs
that hit the boundary more precisely than these did, and diminishing returns
set in: most of the 149 survivors left are the equivalent or unobservable
kinds in the table.

## Sweep 1: the 25 largest MagickCore files

> [!NOTE]
> **Corrected on 2026-09-29.** One case, `resize/06b5a45abd`, turned out to
> differ from itself about one run in three under load (an upstream bug, see
> ORACLE.md), and 155 mutation runs had counted it as a kill. Rerun without
> it, 116 of the 141 in this sweep survived. The figures below are the
> corrected ones; an earlier version of this section reported 81.6% on
> executed lines and called the infrastructure files well protected, which
> was wrong.

One Mull build covered the 25 largest MagickCore files that the oracle build
compiles (44,458 mutants). It left out the X11 files (`display.c`,
`xwindow.c`, `widget.c`), which are built `--without-x`, as well as
`accelerate.c` and `opencl.c` (OpenCL is off), `nt-base.c` (Windows only) and
`resize.c` (done above). 100 random mutants per file, 2,500 in all, ran in
74 minutes, then about 6 hours of reruns as the rules above were learned,
and a final rerun against the extended catalogue (see "Catalogue changes").
Merged results: `build-oracle/work/mutation-sweep25-final.json`.

**Overall: 1,332 killed (53.3%). 76.9% of mutants on lines the oracle
executes are killed.** 726 mutants (29%) sit on lines no case executes.

| File | Mutants | Reached | Killed | Survived on executed lines | of which capped | Kill rate, executed lines |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `profile.c` | 100 | 23 | 4 | 19 | 1 | 17% |
| `blob.c` | 100 | 50 | 28 | 22 | 16 | 56% |
| `property.c` | 100 | 41 | 25 | 16 | 12 | 61% |
| `cache.c` | 100 | 62 | 40 | 22 | 19 | 65% |
| `image.c` | 100 | 79 | 51 | 28 | 13 | 65% |
| `option.c` | 100 | 76 | 54 | 22 | 9 | 71% |
| `draw.c` | 100 | 76 | 56 | 20 | 0 | 74% |
| `stream.c` | 100 | 78 | 58 | 20 | 0 | 74% |
| `composite.c` | 100 | 86 | 64 | 22 | 0 | 74% |
| `effect.c` | 100 | 89 | 67 | 22 | 0 | 75% |
| `string.c` | 100 | 69 | 52 | 17 | 5 | 75% |
| `distort.c` | 100 | 68 | 52 | 16 | 0 | 76% |
| `color.c` | 100 | 70 | 54 | 16 | 2 | 77% |
| `fx.c` | 100 | 71 | 55 | 16 | 0 | 77% |
| `quantize.c` | 100 | 85 | 67 | 18 | 0 | 79% |
| `morphology.c` | 100 | 81 | 65 | 16 | 7 | 80% |
| `quantum-export.c` | 100 | 32 | 26 | 6 | 2 | 81% |
| `quantum-import.c` | 100 | 38 | 31 | 7 | 2 | 82% |
| `visual-effects.c` | 100 | 86 | 71 | 15 | 0 | 83% |
| `threshold.c` | 100 | 87 | 74 | 13 | 0 | 85% |
| `compare.c` | 100 | 84 | 72 | 12 | 0 | 86% |
| `pixel.c` | 100 | 35 | 30 | 5 | 0 | 86% |
| `enhance.c` | 100 | 78 | 67 | 11 | 0 | 86% |
| `statistic.c` | 100 | 97 | 86 | 11 | 0 | 89% |
| `colorspace.c` | 100 | 90 | 83 | 7 | 0 | 92% |

"Reached" means the mutant is on a line some case executes. Capped survivors
were rerun uncapped (`composite.c`) or with a 1,500-case cap (the rest); 88
remain capped, nearly all in the infrastructure files.

### What sweep 1 says

- **Reach is the first problem.** 726 of the 2,500 mutants (29%) sit on lines
  no case executes. The worst files are `profile.c`, `quantum-export.c`,
  `quantum-import.c`, `pixel.c` and `composite.c`'s unreached operators.
  The unexecuted code is EXIF, 8BIM and XMP profile handling
  (`GetEXIFProperty`, `SyncExifProfile`, `ProfileImage`), and
  import/export for pixel layouts the catalogue never asks for (index+alpha,
  gray+alpha, opacity, multispectral, and `ExportQuantumPixel`'s storage types).
- **Where the oracle does execute a line, it usually notices a change.**
  The image-processing files kill 74-92% of mutants on executed lines. `resize.c` was at 83%
  before its targeted rounds (round 1: 615 killed, 127 survivors on executed
  lines).
- **`composite.c` needed an uncapped run to settle.** It looked like the best
  file (93%) until the timeout fix, when 59 of its kills turned out to be
  `-sketch` timing out (SketchImage composites internally), and then like
  one of the worst (40%) with 47 capped survivors. Uncapped, it is 74%: 30 of
  the 47 were killed beyond the cap. The 22 real survivors are mostly exact
  breakpoints in blend formulas (`RoundToUnity(Sca) <= 0.5`, `Dca > 0.25`)
  and dissolve and geometry boundaries.
- **The infrastructure files are the weak spot.** `blob.c` (56%),
  `property.c` (61%), `cache.c` and `image.c` (65%) and `option.c` (71%) are,
  after `profile.c`, the least protected code the oracle reaches. The oracle
  checks what commands output, and these files mostly decide *how* the work
  is done: memory, memory-mapped or disk pixel caches, reading through files,
  pipes, memory blobs or compressed streams, filename syntax (`img.png[2]`,
  `png:-`, `@list`), settings and properties. With small corpus images read
  from plain files, a mutant in the other paths changes nothing visible.
  Cases aimed at those paths - a forced disk cache (`-limit memory 0`),
  stdin and stdout, `.gz` input, frame and list syntax, more `-define` and
  `%[...]` escapes - are the way to raise them, and they are cheap.
- **The cap hides fewer kills than it seemed.** Raising it to 1,500 cases
  appeared to kill a third of the capped survivors; most of those kills were
  the flaky case. `composite.c`, rerun with no cap at all, is the clean
  measurement: 30 of its 47 capped survivors were real kills beyond the cap.

### Kinds of survivors

`tools/oracle/classify.py` sorts survivors into the kinds that recur in every
file, so that only the rest need reading:

```bash
tools/oracle/classify.py build-oracle/work/mutation-sweep25-final.json
tools/oracle/classify.py build-oracle/work/mutation-sweep25-final.json --kind unmatched
```

| Kind | Survivors | Of which capped | Meaning |
| --- | ---: | ---: | --- |
| unreached | 436 | 188 | no case executes the line: needs a new input |
| logging | 27 | 11 | only changes `-debug` output |
| progress | 9 | 0 | only changes `-monitor` callbacks |
| free-guard | 9 | 5 | `NULL` test before a free: a leak, never visible in output |
| channel-bound | 10 | 0 | per-channel loop one step past the end, over padding |
| loop-bound | 49 | 6 | a loop runs once more or once less, usually over scratch space |
| memory-size | 9 | 3 | allocation or copy size: invisible while the buffer is big enough |
| threads-resources | 3 | 2 | thread counts and resource limits |
| **unmatched** | **283** | **61** | read by hand: equivalent, or a gap in the catalogue |

In sweep 2 (final), the same kinds covered 128 of 650 survivors (51 logging,
24 threads and resources, 29 loop bounds, 16 free guards, 8 others), 222
were unreached and 300 unmatched, 104 of those capped.

The rules match the source line, so they name a likely kind, not a proven
one, and they are easy to fool. While tuning them: a `NULL` test before
`Clone...` is not harmless (skipping the clone can drop a setting such as
`-page`), and one before `return(Destroy...)` is an error exit, which fails
the normal path when flipped. `morphology.c:1929` looked like a free guard,
but it survived only because the case using that kernel was beyond the cap.

### Gaps in the catalogue

Read from the unmatched survivors that were not capped:

| Gap | Where it shows | Fix |
| --- | --- | --- |
| `compare` prints only the combined metric | ~15 survivors in `compare.c`'s per-channel loops | **Done:** `-verbose -precision 17` on compare cases. Checked: `compare.c:2036` (PSNR `10*log10` becomes `10/log10`) leaves the combined value unchanged but moves red from 0.183 to 0.038 under `-verbose` |
| Statistics printed at 6 significant digits | `GetImageMoments`, perceptual hash, `GetImageStatistics` | **Done:** `-precision 17` on `identify -verbose -moments` and `-features` |
| Read masks never set | 6 survivors in `compare.c` | compare with `-read-mask` |
| Boundaries no input hits | `-range-threshold` limits, hex digits `9`/`A`/`F` in colours, HSL `lightness <= 0.5`, interpolation offsets of exactly 0.75, `ContrastStretch` on palettes | boundary cases, as in `resize.c` round 3 |
| CMYK and alpha paths | `-sparse-color`, `InterpolatePixelInfo`, `-hald-clut`, `-levelize`, `IsSVGCompliant` | those operators on the CMYK and alpha corpus images |
| Operators with few or no cases | `-smush` (10 survivors), Kapur thresholding, `-blue-shift`, `-color-matrix` above 6×6, `-tint` with alpha, plasma fractals, `-morph` | operator cases |
| Drawing edge cases | gradients with more than 2 stops or equal offsets, miter limits, `fill-opacity 0`, SVG compliance, arcs | MVG cases |
| Parsing | option values listed with `|`, `@file` arguments, quoting in `StringToArgv` | option and argument cases |
| Profiles | all of `profile.c`, 8BIM and IPTC properties | corpus images with EXIF, 8BIM, IPTC and XMP profiles |

The first two rows are systemic: one change in `cases.py` each reaches every
metric and every statistic.

### Catalogue changes

The two systemic gaps were closed in `cases.py`, and the HPGL decode cases
removed (they run the `hp2xx` delegate through the shell; see ORACLE.md).
The catalogue went from 9,474 to 9,546 cases, and `selfcheck` reports 0
nondeterministic. Rerunning the affected survivors against it:

| Survivors rerun | Killed now | By |
| --- | ---: | --- |
| `compare.c`, executed lines (21) | 9 | the new `compare -verbose -precision 17` cases |
| `statistic.c`, executed lines (12) | 1 | the new `identify -verbose -precision 17 -moments` cases |
| the 28 false kills from the stale cache | 15 | `resize` cases, which the HPGL cases had been reaching first |

`compare.c` went from 75% to 86% on executed lines with one edit. The
`statistic.c` survivors turned out not to be about precision: they are
boundary checks and moment arithmetic whose results no case prints.

A second round of additions targets the hardly exercised files of sweep 2:
`-encipher`/`-decipher` round trips (`cipher.c`), PostScript, EPS and PDF
output with every compression method (`compress.c`), `-version`
(`version.c`), and twelve `-list` printers (`configure`, `mime`, `policy`,
`log`, `locale`, `type`, `font`, `delegate`, `coder`, `magic`, `resource`,
`format`). Two harness changes came with them: `-version` and `-list` are
only accepted as the first argument, so they no longer get `-seed 1`
prepended (with it, all thirteen failed and compared equal, testing nothing),
and the build stamp in `-version` and the build-tree paths in the `-list`
output are normalised. The catalogue is now 9,702 cases, 0 nondeterministic
in `selfcheck --repeat 4` under full load. The mutation effect on those files
has not been measured yet.

### Cases for the infrastructure paths

A third round added 49 `infra` cases aimed at the paths the oracle missed: disk
and memory-mapped pixel caches, gzip and bzip2 streams, stdout and stdin, the
mpr registry, inline data, frame/crop/size filename syntax, `@` lists, scene
numbering, filename escapes, properties and options. Cases can now feed a file
on stdin. `selfcheck --repeat 4`: 9,751 cases, 0 nondeterministic.

Rerunning the old survivors against the new cases only (`mutate.py --cases`):

| Survivors rerun | Killed by the new cases | Survived | Not reached by them |
| --- | ---: | ---: | ---: |
| sweep 1: blob, cache, image, property, option, string (350) | 15 | 168 | 167 |
| sweep 2: infrastructure and hardly exercised files (573), against `infra`, `cipher`, `info` and `encode` | 143 | 232 | 198 |

The sweep-2 files gained most: the cipher round trips, the `-list` printers and
the PostScript and PDF compression cases reach code nothing reached before. The
sweep-1 infrastructure files gained little: their survivors mostly sit in paths
that small corpus images do not drive whatever the I/O route - cache growth,
threading, resource limits - and several are the harmless kinds.

### Full runs for the Phase 1 files

Every mutant, not a sample, for the files the task files cover, so that each
task lists its survivors function by function:

| File | Mutants | Killed | Survived | No coverage |
| --- | ---: | ---: | ---: | ---: |
| `compare.c` | 672 | 505 | 145 | 22 |
| `colormap.c` | 46 | 41 | 5 | 0 |
| `decorate.c` | 368 | 338 | 30 | 0 |
| `shear.c` | 511 | 333 | 103 | 75 |
| `segment.c` | 443 | 303 | 59 | 81 |
| `threshold.c` | 557 | 410 | 139 | 8 |
| `statistic.c` | 906 | 711 | 192 | 3 |
| `visual-effects.c` | 840 | 568 | 182 | 90 |
| `enhance.c` | 983 | 677 | 208 | 98 |

`colorspace.c` and `morphology.c` were still running when this was written;
`build-oracle/night2.log` records them as they finish. 37 of `statistic.c`'s
survivors hit the 300-case cap.

## Sweep 2: the remaining 58 MagickCore files

A second build covered every other MagickCore file the oracle build compiles
(23,964 mutants; `image-view.c` and `deprecate.c` compile to nothing here).
40 random mutants per file, all of them for the small ones: 2,061 in all, in
53 minutes of mutation after three restarts (see "Output is capped"), then
2.8 hours rerunning the 266 capped survivors with a 1,500-case cap, which
killed 42 of them. Results: `build-oracle/work/mutation-sweep60-final.json`.

**Overall: 893 killed (43.3%), 67.5% on executed lines.** The files fall into
three groups:

| Group | Mutants | Reached | Killed, executed lines |
| --- | ---: | ---: | ---: |
| Image operations: `decorate`, `fourier`, `colormap`, `shear`, `segment`, `histogram`, `gem`, `resample`, `montage`, `feature`, `paint`, `transform`, `matrix`, `attribute`, `channel`, `annotate`, `layer`, `quantum`, `identify`, `vision`, `prepress`, `geometry` | 897 | 81% | 76% |
| Infrastructure: `policy`, `log`, `memory`, `resource`, `xml-tree`, `token`, `list`, `locale`, `magic`, `type`, `delegate`, `registry`, `splay-tree`, `exception`, `signature`, … | 937 | 62% | 57% |
| Hardly exercised: `cipher`, `distribute-cache`, `module`, `mime`, `version`, `compress`, `configure` | 227 | 7% | – |

- **The image operations match sweep 1.** They are as well protected as the
  large files, and `decorate.c` (93%), `segment.c` (90%), `fourier.c`,
  `colormap.c`, `shear.c` and `semaphore.c` (80–82%) are among the best
  measured anywhere.
- **Infrastructure is weaker, and the reruns confirm it.** Unlike sweep 1,
  where raising the cap killed a third of the capped survivors, here it
  killed only 16% (42 of 266). Most survivors are real: logging (51) and
  thread and resource limits (24), which the oracle cannot see by design,
  and code paths no case drives, such as policy rules, locale handling and
  XML configuration parsing. 155 remain capped even at 1,500 cases.
- **Seven files are essentially untested by the oracle.** `cipher.c`
  (`-encipher`/`-decipher`), `compress.c` (Huffman, LZW and RLE for the PS,
  PDF and TIFF writers), `configure.c` and `mime.c` (`-list` output),
  `version.c`, `module.c` (modules are built statically) and
  `distribute-cache.c` (a network pixel cache server). Most need only a few
  cases each; `distribute-cache.c` would need a server running.

| File | Mutants | Reached | Killed | Survived on executed lines | of which capped | Kill rate, executed lines |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cipher.c` | 40 | 0 | 0 | 0 | 0 | – |
| `distribute-cache.c` | 40 | 0 | 0 | 0 | 0 | – |
| `module.c` | 7 | 0 | 0 | 0 | 0 | – |
| `log.c` | 40 | 14 | 2 | 12 | 12 | 14% |
| `random.c` | 40 | 25 | 6 | 19 | 2 | 24% |
| `cache-view.c` | 29 | 10 | 3 | 7 | 6 | 30% |
| `type.c` | 40 | 30 | 9 | 21 | 1 | 30% |
| `monitor.c` | 9 | 9 | 3 | 6 | 6 | 33% |
| `policy.c` | 40 | 14 | 5 | 9 | 9 | 36% |
| `resource.c` | 40 | 28 | 11 | 17 | 13 | 39% |
| `delegate.c` | 40 | 26 | 12 | 14 | 0 | 46% |
| `registry.c` | 31 | 21 | 10 | 11 | 6 | 48% |
| `thread.c` | 2 | 2 | 1 | 1 | 0 | 50% |
| `version.c` | 20 | 2 | 1 | 1 | 0 | 50% |
| `timer.c` | 35 | 31 | 16 | 15 | 6 | 52% |
| `vision.c` | 40 | 11 | 6 | 5 | 0 | 55% |
| `constitute.c` | 40 | 31 | 17 | 14 | 12 | 55% |
| `layer.c` | 40 | 25 | 14 | 11 | 0 | 56% |
| `xml-tree.c` | 40 | 14 | 8 | 6 | 0 | 57% |
| `splay-tree.c` | 40 | 24 | 14 | 10 | 9 | 58% |
| `artifact.c` | 25 | 20 | 12 | 8 | 6 | 60% |
| `client.c` | 5 | 5 | 3 | 2 | 2 | 60% |
| `locale.c` | 40 | 29 | 18 | 11 | 2 | 62% |
| `list.c` | 40 | 32 | 20 | 12 | 4 | 62% |
| `magic.c` | 40 | 29 | 19 | 10 | 10 | 66% |
| `exception.c` | 40 | 35 | 23 | 12 | 4 | 66% |
| `annotate.c` | 40 | 30 | 20 | 10 | 0 | 67% |
| `token.c` | 40 | 24 | 16 | 8 | 4 | 67% |
| `signature.c` | 40 | 34 | 23 | 11 | 0 | 68% |
| `feature.c` | 40 | 38 | 26 | 12 | 0 | 68% |
| `linked-list.c` | 40 | 16 | 11 | 5 | 4 | 69% |
| `resample.c` | 40 | 39 | 27 | 12 | 0 | 69% |
| `quantum.c` | 40 | 36 | 25 | 11 | 9 | 69% |
| `gem.c` | 40 | 40 | 28 | 12 | 0 | 70% |
| `prepress.c` | 17 | 17 | 12 | 5 | 0 | 71% |
| `memory.c` | 40 | 24 | 17 | 7 | 7 | 71% |
| `utility.c` | 40 | 11 | 8 | 3 | 3 | 73% |
| `attribute.c` | 40 | 30 | 22 | 8 | 1 | 73% |
| `paint.c` | 40 | 34 | 25 | 9 | 0 | 74% |
| `configure.c` | 40 | 8 | 6 | 2 | 2 | 75% |
| `montage.c` | 40 | 36 | 27 | 9 | 0 | 75% |
| `transform.c` | 40 | 31 | 24 | 7 | 0 | 77% |
| `histogram.c` | 40 | 36 | 28 | 8 | 0 | 78% |
| `matrix.c` | 40 | 30 | 24 | 6 | 0 | 80% |
| `semaphore.c` | 20 | 20 | 16 | 4 | 4 | 80% |
| `shear.c` | 40 | 35 | 28 | 7 | 0 | 80% |
| `channel.c` | 40 | 26 | 21 | 5 | 0 | 81% |
| `magick.c` | 40 | 27 | 22 | 5 | 4 | 81% |
| `static.c` | 21 | 11 | 9 | 2 | 2 | 82% |
| `compress.c` | 40 | 6 | 5 | 1 | 0 | 83% |
| `geometry.c` | 40 | 26 | 22 | 4 | 4 | 85% |
| `colormap.c` | 40 | 40 | 34 | 6 | 1 | 85% |
| `identify.c` | 40 | 27 | 23 | 4 | 0 | 85% |
| `fourier.c` | 40 | 37 | 32 | 5 | 0 | 86% |
| `segment.c` | 40 | 30 | 27 | 3 | 0 | 90% |
| `decorate.c` | 40 | 40 | 37 | 3 | 0 | 92% |
| `coder.c` | 40 | 15 | 14 | 1 | 1 | 93% |
| `mime.c` | 40 | 1 | 1 | 0 | 0 | 100% |

### Consequences for the campaign

- The per-function check before refactoring, described below, is now
  mandatory rather than advised. File-level scores are only a rough guide:
  every file has well-tested and untested functions side by side.
- The best measured protection, 85% or more on executed lines with high
  reach: `colorspace.c` (92%), `statistic.c` (89%), `enhance.c`,
  `compare.c`, `pixel.c`'s reached code, `threshold.c` (85-86%), and
  `resize.c` (88%). From sweep 2: `decorate.c` (93%), `segment.c` (90%),
  `colormap.c`, `shear.c` and `fourier.c`'s one compiled function (80-89%).
  These are the safest starting points.
- The middle, 74-83%: `visual-effects.c`, `quantum-import.c`,
  `quantum-export.c`, `morphology.c`, `quantize.c`, `fx.c`, `color.c`,
  `distort.c`, `string.c`, `effect.c`, `composite.c`, `stream.c`, `draw.c`.
  Fine to refactor after the per-function check and, where survivors point
  at a gap, a case or two.
- The infrastructure files - `blob.c`, `property.c`, `cache.c`, `image.c`,
  `option.c` - wait for cases aimed at their paths. They are also the files
  every other file depends on, so a mistake there costs the most.
- Do not refactor `profile.c` until the corpus has images with EXIF, 8BIM,
  IPTC and XMP profiles, nor the seven hardly exercised files of sweep 2
  until they have cases.
- For any function with capped survivors, run it uncapped first:
  `mutate.py --function NAME --max-cases 0`. A single function is reached by
  far fewer cases than the whole file.

## Linux (WSL2): the first full runs

Everything above was measured on the MacBook. The campaign now runs on a Windows desktop,
in WSL2 Ubuntu 24.04 with clang 18 and Mull 0.34.1 for LLVM 18 (see
[`PORTING.md`](PORTING.md)). No Mac figure transfers: more delegates compile, and the
libraries, fonts and compiler differ. Measured 2026-09-30, `selfcheck --repeat 4`: 9,745
cases, 0 nondeterministic.

One Mull build mutates `colorspace.c` and `morphology.c` (`build.sh mull
'MagickCore/(colorspace|morphology)\.c$' phase1b`). Every mutant ran, not a sample; then
every capped survivor was rerun against all the cases that reach it (`--max-cases 0`).

| File | Mutants | Killed | Survived | of which capped | No coverage | Uncapped rerun |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `colorspace.c` | 550 | 393 | 156 | 145 | 1 | killed 46 more; **439 killed (80%)**, 110 real survivors |
| `morphology.c` | 1,258 | 823 | 405 | 321 | 30 | killed 15 more; **838 killed (67%)**, 390 real survivors |

A full run took 8.5 minutes for `colorspace.c` and about 45 for `morphology.c` on 16
threads; the uncapped reruns take longer per mutant, since a function in these files is
reached by thousands of cases. On this machine (16 GB, WSL given half) mutation runs use
`-j 8`: at 16 jobs Windows ran short of memory and the run was stopped twice. Results
are saved as they arrive, so a stopped run resumes where it was.

**Capped survivors are mostly real here.** On the Mac, uncapped reruns killed about a
third of the capped survivors; here they killed 46 of 145 in `colorspace.c` and only 15
of 321 in `morphology.c`. Read a capped survivor in these two files as a probable gap.

### colorspace.c through the readiness gate

The gate is the one in [`VERIFICATION.md`](VERIFICATION.md): killed / (killed + unmatched
+ unreached survivors), leaving out only the kinds `classify.py` names as unobservable.
Survivors on lines no case executes count as gaps, not as excused.

| Function | Mutants | Killed | Unobservable | Unmatched | Unreached | Gate | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `TransformsRGBImage` | 232 | 176 | 4 | 18 | 34 | 77% | careful |
| `sRGBTransformImage` | 214 | 176 | 3 | 8 | 27 | 83% | careful |
| `ConvertHSLToRGB` | 41 | 40 | 0 | 1 | 0 | 98% | ready |
| `ConvertRGBToHSL` | 26 | 23 | 0 | 3 | 0 | 88% | careful |
| `SetImageColorspace` | 7 | 6 | 1 | 0 | 0 | 100% | ready |
| `TransformImageColorspace` | 7 | 6 | 1 | 0 | 0 | 100% | ready |
| `SetImageGray` | 6 | 5 | 1 | 0 | 0 | 100% | ready |
| `SetImageMonochrome` | 5 | 4 | 1 | 0 | 0 | 100% | ready |
| `RoundToYCC` | 5 | 3 | 0 | 2 | 0 | 60% | not ready |
| `ConvertGenericToRGB` | 3 | 0 | 0 | 0 | 3 | 0% | not ready |
| `ConvertRGBToGeneric` | 3 | 0 | 0 | 0 | 3 | 0% | not ready |
| `GetImageColorspaceType` | 1 | 0 | 0 | 0 | 0 | - | no cases |
| **All** | 550 | 439 | 11 | 32 | 67 | **82%** | |

**The gap the two big functions share.** Most of their unreached survivors sit in the
`PseudoClass` branch: colorspace conversion of a palette image. The catalogue converts
colorspaces only on truecolor images, although the corpus already holds `palette.miff`.
That branch accounts for 31 of the 61 unreached survivors of `TransformsRGBImage` and
`sRGBTransformImage`; `palette.miff -colorspace <X>` cases should lift both towards
ready. The rest: an invalid `colorspace:illuminant` define (`illuminant_type < 0`), error
paths after a failed `SyncImage`, and `LogColorspace`, whose own parameters account for
10 unmatched survivors. Not yet added.

The merge-and-gate script used here is not in git yet: `build-oracle/irq/gate.py` on the
WSL clone. Reports: `build-oracle/work/mutation-full-*.json`, `mutation-uncap-*.json`,
and the gated results `gate-colorspace.json`.

### morphology.c through the readiness gate

**All: 838 killed, 23 unobservable, 185 unmatched, 182 unreached; gate 70%.**

| Function | Mutants | Killed | Unobservable | Unmatched | Unreached | Gate | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `AcquireKernelBuiltIn` | 469 | 312 | 3 | 72 | 82 | 67% | not ready |
| `MorphologyPrimitive` | 211 | 175 | 8 | 24 | 4 | 86% | careful |
| `MorphologyPrimitiveDirect` | 182 | 100 | 3 | 13 | 66 | 56% | not ready |
| `RotateKernelInfo` | 101 | 57 | 1 | 33 | 10 | 57% | not ready |
| `MorphologyApply` | 78 | 50 | 2 | 13 | 13 | 66% | not ready |
| `ParseKernelArray` | 58 | 48 | 2 | 8 | 0 | 86% | careful |
| `ParseKernelName` | 33 | 25 | 0 | 4 | 4 | 76% | careful |
| `ScaleKernelInfo` | 26 | 15 | 0 | 11 | 0 | 58% | not ready |
| `ShowKernelInfo` | 22 | 0 | 0 | 0 | 0 | - | no cases |
| `MorphologyImage` | 14 | 10 | 1 | 2 | 1 | 77% | careful |
| `AcquireKernelInfo` | 11 | 8 | 1 | 0 | 2 | 80% | careful |
| `SameKernelInfo` | 11 | 9 | 1 | 1 | 0 | 90% | ready |
| `CalcKernelMetaData` | 8 | 6 | 0 | 2 | 0 | 75% | careful |
| `ScaleGeometryKernelInfo` | 4 | 2 | 0 | 2 | 0 | 50% | not ready |
| `ZeroKernelNans`, `UnityAddKernelInfo` | 8 | 0 | 0 | 0 | 0 | - | no cases |
| seven small helpers (`CloneKernelInfo`, `fact`, `ExpandMirrorKernelInfo`, ...) | 22 | 21 | 1 | 0 | 0 | 100% | ready |

**The gaps, all reachable from the command line:**

- `-morphology Voronoi` has no case: 66 unreached survivors in `MorphologyPrimitiveDirect`.
- The `LoG` and `Comet` kernels have no case: 35 and 19 survivors in `AcquireKernelBuiltIn`.
- The Blur kernel's rotation (`Blur:0x1,<angle>` and its variants) is unchecked: 40
  survivors in `RotateKernelInfo`.
- Kernel scaling has only two `convolve:scale` cases: 11 unmatched in `ScaleKernelInfo`.
- `ShowKernelInfo` prints the kernel with `-define morphology:showKernel=1`; no case
  asks for it.

### After adding the cases the gate pointed at

The gaps above became 109 cases (commit `7e32a77c3`): palette images in every colorspace,
explicit and invalid illuminants, kernels with arguments and rotations, Voronoi on a seed
image, seven `convolve:scale` forms and `showKernel`. `selfcheck --repeat 4` over the two
families: 2,463 cases, 0 nondeterministic. Every survivor and every mutant without
coverage was rerun against the new cases only (`mutate.py --cases`), and the reports merged
with `tools/oracle/gate.py`:

| File | Killed before | Killed after | Gate before | Gate after |
| --- | ---: | ---: | ---: | ---: |
| `colorspace.c` | 439 | 472 | 82% | **88%** |
| `morphology.c` | 838 | 953 | 70% | **77%** |

Functions that moved: `AcquireKernelBuiltIn` 67% to 76% and `MorphologyPrimitiveDirect`
(Voronoi) 56% to 85%, both from not ready to careful; `TransformsRGBImage` 77% to 86% and
`sRGBTransformImage` 83% to 89%; `ShowKernelInfo` and `UnityAddKernelInfo` are reached for
the first time. The `convolve:scale` cases killed nothing in `ScaleKernelInfo` (58%) and
the rotations only four more in `RotateKernelInfo` (61%): their survivors need reading, not
more cases of the same kind.

### A second round: asymmetric kernels, mixed-sign scaling

Reading the survivors of `RotateKernelInfo` and `ScaleKernelInfo` showed why the first
round barely moved them. Every kernel tested was symmetric, so a rotation by 90 degrees
and one by 270 give the same kernel; and every scaled kernel was all-positive, so the
separate scaling of positive and negative values never showed. 13 cases fix that:
`Comet` rotated by 90, 180 and 270 degrees, user-defined 3x3 kernels with an off-centre
origin expanded through 45-degree steps (`3x3+2+2@:...`), 1-D user kernels expanded
through 90 degrees, and `DoG` and `Laplacian` under four scaling flags, all printed with
`showKernel` so that the kernel values are compared as well as the image.

Many of the rest are boundary mutants: `>=` against `MagickEpsilon` made `>`, which
differs only at exactly 1e-12. `classify.py` now names them `epsilon-bound`, one of the
kinds the gate leaves out. That reclassified 18 survivors in `morphology.c` and 2 in
`colorspace.c`; the new cases killed 26.

| Function | Gate after round 1 | After round 2 |
| --- | ---: | ---: |
| `RotateKernelInfo` | 61% | **80%** (every line now reached) |
| `ScaleKernelInfo` | 58% | **82%** |
| `ShowKernelInfo` | 59% | 77% |
| `ConvertRGBToHSL` (colorspace.c) | 88% | **96%**, ready (reclassification only) |
| **morphology.c** | 77% | **81%** |
| colorspace.c | 88% | 88% |

`selfcheck --repeat 4` over the morphology family, 1,982 cases: 0 nondeterministic. The
catalogue now has 9,867 cases. Survivors in the angle comparisons of `RotateKernelInfo`
(`angle <= 22.5`, `135.0 < angle`, ...) remain counted: an exact angle is testable.

## Linux sweep: every compiled MagickCore file

One Mull build of all MagickCore files (`build.sh mull 'MagickCore/[^/]+\.c$' sweep-linux`,
built with `JOBS=4`: at 12 jobs the compiler ran out of memory on `composite.c`), then
60 random mutants per file (`mutate.py --per-file 60 --seed 1`, default cap of 300 cases,
`-j 8`): 4,506 mutants in 79 minutes, on the catalogue of 9,867 cases. Run from a
terminal outside Claude Code, whose background jobs were stopped three times when Windows
ran short of memory. Report: `build-oracle/work/mutation-sweep-linux.json`.

| MagickCore, 4,506 sampled mutants | |
| --- | ---: |
| killed, of all mutants | **70.0%** |
| killed, of mutants on executed lines | **88.9%** |
| reach: mutants in functions some case executes | 85% |
| gate over the reached functions (`gate.py`) | **85.7%** |
| strict: the gate with never-executed functions counted as gaps | **72.2%** |
| survivors that hit the case cap, not yet rerun | 190 |

The Mac sweeps killed 53% (sweep 1) and 43% (sweep 2) of all mutants and 77% and 68% on
executed lines; the difference is the grown catalogue (the infra cases, the 122 cases of
the two rounds above) as much as the platform, so the two are not a like-for-like
comparison. With 60 mutants a file, a file's figure is good to about ten points either
way: `morphology.c` shows 95% here and 81% in its full run.

Files by the strict figure (reach and gate folded together):

- **Not reached at all:** `display.c`, `xwindow.c`, `animate.c` (X11, which the oracle
  build leaves out), `distribute-cache.c` (a network server), `module.c` (static build).
- **Below 50%:** `cache-view.c` 10%, `version.c` 15%, `profile.c` 20%, `mime.c` 32%,
  `blob.c` 36%, `compress.c` 37%, `quantum-import.c` 37%, `delegate.c` 39%, `color.c` 39%,
  `linked-list.c` 42%, `log.c` 42%, `constitute.c` 45%, `annotate.c` 47%. In
  `compress.c`, `linked-list.c` and `log.c` what is reached is well checked (gate 96-100%)
  but much is never executed; in `blob.c`, `constitute.c`, `delegate.c` and
  `quantum-import.c` the reverse: reached, and weakly checked.
- **50-75%:** `composite.c`, `cache.c`, `pixel.c`, `configure.c`, `splay-tree.c`,
  `utility.c`, `channel.c`, `quantum-export.c`, `token.c`, `matrix.c`, `vision.c`,
  `string.c`, `attribute.c`, `layer.c`, `type.c`, `cipher.c`, `artifact.c`, `stream.c`,
  `compare.c`, `policy.c`, `static.c`.
- **75% and above:** the other 51 files, most of the image operations among them:
  `effect.c`, `resize.c`, `decorate.c`, `statistic.c`, `morphology.c`, `feature.c`,
  `colormap.c`, `threshold.c`, `transform.c`, `identify.c` and `gem.c` at 90% or more.

The capped survivors clustered in the infrastructure files (`composite.c` 31,
`constitute.c` 30, `blob.c` 20, `color.c` 19, `cache.c` and `channel.c` 18). Rerun
uncapped (`build-oracle/capped-sweep.sh`, 258 s), **175 of the 190 were killed**: nearly
all were missed kills, not gaps. `composite.c` went from 29 to 60 of 60 killed,
`constitute.c` 26 to 56, `channel.c` 32 to 50, `cache.c` 28 to 46, `color.c` 23 to 42,
`blob.c` 20 to 38. The weak-file groups above were drawn before this rerun; the capped
infrastructure files among them are better protected than they show.

| MagickCore, after the capped rerun | |
| --- | ---: |
| killed, of all mutants | **73.8%** |
| killed, of mutants on executed lines | **92.3%** |
| gate over the reached functions | **89.7%** |
| strict | **75.6%** |

So in this sweep a capped survivor was a gap about one time in thirteen. The cap of 300
cases is a sampling device, not a verdict: rerun capped survivors uncapped before reading
any file's figure.

## Reading survivors by hand: enhance.c (Mac)

The gate counts every survivor `classify.py` cannot name against the function. Most of
those are either equivalent mutants or gaps a single case would close, and only reading
tells which. Measured on the MacBook on 2026-09-30, from the full run of `enhance.c`
(983 mutants, none capped), while the WSL machine ran `morphology.c`: the figures are
Mac figures, but the verdicts below are about the source and hold on both machines.

**Verdicts are kept in `tools/oracle/verdicts.json`**, which `classify.py` and
`make_task.py` read. Each is keyed by function, mutator, the mutated line's text and the
operator's column in it, not by line number, so it survives edits elsewhere in the file;
once the line itself changes, the survivor is unmatched again and has to be reread. The
kinds are `equivalent`, `unobservable` (a real change the CLI cannot show), `gap` (with
`killed_by`, a case that killed it) and `unresolved` (counts as a gap). Every gap verdict
was checked by running the mutant against the proposed case before it was recorded.

The 58 unmatched survivors of the first run:

| Verdict | Count | What they were |
| --- | ---: | --- |
| equivalent | 23 | clamps at their own bound (`< 2` → `<= 2` before setting 2), `range_info->min` that is always 0, the red channel's offset 0 (`+i` → `-i`), `0.5*sign` → `0.5/sign` for sign ±1, and `histogram[..]++` → `--` in EqualizeImage, which negates every count and leaves every ratio exactly as it was |
| unobservable | 4 | three return statuses that every CLI caller discards (`(void) CLAHEImage(...)`); one index error that divides by zero, which yields 0 on arm64 and traps on x86, so the Linux build should kill it |
| gap | 26 | closed by 17 new cases, below |
| unresolved | 5 | the colormap alpha of palette images in ContrastStretch, Equalize, Levelize and SigmoidalContrast: no probe kills them, yet LevelImage's identical branch is observable |

**What the gaps had in common** is inputs the families never combine:

- `-clut` ran only as `rose gray16`: a colour image, a gray clut, a clut that is a vertical
  gradient (so the x coordinate never mattered), no CMYK, no alpha on either side.
- `-hald-clut` ran only on `rose`: no gray, CMYK or alpha image, no CMYK clut.
- Histogram thresholds (`-contrast-stretch`, `-linear-stretch`) were given only as
  percentages, which never land exactly on a cumulative pixel count, so `>` against `>=`
  was invisible. `gray16` has exactly 64 pixels a level, and `64x64` hits it.
- `-clahe` ran only with 128 bins, the value one mutant substitutes, and with tiles that
  were never padded by more than 3 rows.
- `-level-colors` used colours whose red is 0 or 255, which leaves red unchanged.
- `-modulate` never had `modulate:colorspace` or `color:illuminant` set.
- **`magick -gamma` does not call GammaImage** (it uses EvaluateImage); only `convert`
  and `mogrify` do. The convert family runs every operator on `rose` and `rose_alpha`
  only, so GammaImage never saw a palette image. The same holds for every other
  operator whose `mogrify.c` path differs from `operation.c`; not measured yet.

A second round of 30 cases reached code no case executed: `-cdl` (ColorDecisionListImage,
66 mutants, none reached before), `+negate`, per-channel `-auto-gamma`, nearest-neighbour
hald cluts, `white-balance:vibrance`, and `-modulate` in each of its eight other
colorspaces on `rose` and on the HDRI image (a wrong hue wrap shows only with
out-of-gamut values). All 47 are the `gaps` family in `cases.py`; `selfcheck --repeat 4`:
0 nondeterministic. The 15 new survivors on newly reached lines were read as well.

| | Before | After |
| --- | ---: | --- |
| Catalogue | 9,751 | 9,798 cases |
| `enhance.c` lines executed | 66.5% (lcov of 2026-09-28) | 83.5% |
| Killed | 677 of 983 (69%) | 823 of 983 (84%) |
| Functions with no case | 9 | 0 |
| Gate, whole file (`gate.py`) | 85% | **93%** |
| Functions ready / careful / not ready / no cases | 15 / 11 / 5 / 9 | 35 / 5 / 0 / 0 |

Gate figures here and below are `tools/oracle/gate.py`'s: killed / (killed + unmatched +
unreached), where gap and unresolved verdicts count as unmatched, equivalent and
unobservable ones are left out with the harmless kinds, and mutants in functions no case
reaches ("no cases") are not in the total. The "before" column already uses today's
verdicts, so the change is the new cases' doing.
What is left against the file is 13 unresolved survivors (the colormap alpha branches,
and two boundaries at exactly half a hald-clut step) and 45 on lines still unreached,
almost all progress-monitor and error paths.

The line coverage the reports use (`build-oracle/oracle.lcov`) had been made by hand;
`tools/oracle/linecov.py` now regenerates it (about 100 s on the Mac). Rerun it, and
`casemap.py`, after changing the catalogue. Reports:
`build-oracle/work/mutation-enhance-merged.json` (the full run with the reruns merged).

## Reading survivors by hand: six more Phase 1 files (Mac)

The same reading for `threshold.c`, `decorate.c`, `colormap.c`, `segment.c`, `shear.c` and
`compare.c`, measured on the MacBook on 2026-09-30 from their full runs. 222 verdicts, all
in `verdicts.json`; every gap verdict was confirmed by rerunning its mutant through
`mutate.py` against the new case, not only by the probe. The `gaps` family is now 123 cases.

| File | Mutants | Killed | Gate | Ready / careful / not ready | Still open |
| --- | ---: | ---: | ---: | --- | --- |
| `threshold.c` | 557 | 410 → 443 | see the next section | | 5 unresolved |
| `decorate.c` | 368 | 338 → 351 | 94% → **98%** | 3/0/0 → 3/0/0 | none |
| `colormap.c` | 46 | 41 → 41 | 98% → **98%** | 3/0/1 → 3/0/1 | 1 unresolved |
| `segment.c` | 443 | 303 → 306 | 94% → **95%** | 12/2/0 → 13/1/0 | 6 unresolved |
| `shear.c` | 511 | 333 → 388 | 88% → **94%** | 3/5/0 → 7/2/0 | 5 unresolved |
| `compare.c` | 672 | 505 → 537 | 84% → **91%** | 10/8/4 → 17/2/2 | 4 unresolved |

Ready / careful / not ready as `gate.py` counts them. Functions no case reaches are left
out of both counts and of the gate; three of them no case can reach from the command
line at all: `GetImageDynamicThreshold` (81 mutants), `ShearRotateImage` (45) and
`IsImagesEqual` (22) have no caller in MagickCore, MagickWand or the coders. They are
the "public API only" group of `VERIFICATION.md`.

**What the gaps had in common**, beyond `enhance.c`'s:

- **Arguments given one way only.** Every `-black-threshold` and `-white-threshold`
  argument was a single value, so per-channel parsing (sigma, xi, psi, chi) and the CMYK
  branches never ran. Every `-random-threshold` was in quantum units (`20x80`,
  not `20x80%`), so nearly every pixel lay above the maximum and the random branch was
  almost never taken.
- **Thresholds that never hit a pixel exactly.** Percentages are computed in floating
  point: 40% of QuantumRange is not exactly 26214, so `<` against `<=` is invisible. An
  8-bit channel value times 257 is exact (102 × 257 = 26214), so `-deskew 26214` with
  pixels of 102, or pixels at exactly 10, 20, 80 and 90% for `-range-threshold`, reach
  the boundary.
- **Outputs that hide the value.** `-auto-threshold` and `-deskew` reduce an image to one
  number and then threshold or rotate with it; a small change in the number rarely moves
  a pixel. `-define auto-threshold:verbose=1` and `-print %[deskew:angle]` at
  `-precision 17` print it.
- **`compare` masks both images.** The read-mask test is `mask(image) <= half ||
  mask(reconstruct) <= half`, and the `compare` utility applies `-read-mask` to both, so a
  mutant of one half is hidden by the other. `magick A -read-mask M B -metric X -compare`
  masks one image only; two such cases per metric close 24 survivors.
- **No virtual canvas, no large images, no degenerate shears.** No case rotated an image
  with a page offset, one taller than a rotation tile (170 rows), or sheared by 0 on one
  axis.

**Things found on the way, for `ORACLE.md` or upstream:**

- `segment.c`: the cluster threshold is compared with the number of clusters kept so far
  (`count*cluster_threshold/100.0`, `count` reset to 0 just before), not with the pixel
  count, so thresholds below about 99% prune nothing. Looks like an upstream bug.
- `shear.c`: `deskew:auto-crop` is both the switch and the border width, and
  `IsStringTrue` accepts only `1` of the widths. In `GetImageBackgroundColor`, `p` is not
  advanced for the skipped middle pixels, so the right-hand border reads the wrong pixels.
- `magick -verbose` ends with an elapsed-time line; the oracle normalises it, a probe that
  does not sees false kills. `-segment` output changes with the OpenMP thread count; the
  oracle runs single-threaded.
- **A case whose baseline times out tests nothing, silently.** `mutate.py` drops it, and
  the mutants it was written for show as survivors or as having no coverage. A
  subimage search on a full-size image did this on a Mull build. `mutate.py` now prints
  the cases it leaves out.
- Each file's mutants live in one Mull build (`mull-sweep25` or `mull-sweep60`); a probe
  against the wrong build shows every mutant surviving.

## Reading survivors by hand: visual-effects.c and statistic.c (Mac)

The last two Phase 1 files the Mac could take while the WSL machine ran `morphology.c`.
`statistic.c`'s 37 capped survivors were rerun against up to 1,500 cases first
(`GetImageStatistics` is reached by only 327, so none stayed capped); 30 of them were
still unmatched and were read with the rest. 247 verdicts; every gap confirmed through
`mutate.py`. `verdicts.json` now holds 531 (219 equivalent, 211 gaps, 45 unobservable, 56
unresolved), and the `gaps` family 173 cases.

| File | Mutants | Killed | Gate | Ready / careful / not ready | Still open |
| --- | ---: | ---: | ---: | --- | --- |
| `visual-effects.c` | 840 | 568 → 662 | 89% → **92%** | 13/5/2 → 18/4/1 | 6 unresolved |
| `statistic.c` | 906 | 711 → 748 | 91% → **96%** | 22/6/3 → 26/4/1 | 14 unresolved |
| `threshold.c` (all rounds) | 557 | 410 → 449 | 86% → **93%** | 6/10/1 → 15/4/0 | 5 unresolved |

What the gaps had in common, beyond the earlier files':

- **Options that exist only in another front end.** `-stegano` and `-stereo` are options
  of the `composite` utility, not of `magick`; the catalogue's `magick rose rose_blur
  -stereo +3+2` failed on both sides and tested nothing. `SteganoImage`, `PolaroidImage`
  and `StereoAnaglyphImage` (90 mutants) had no case at all.
- **Floating-point output hides low-order bits.** `-stegano` writes the watermark into
  the lowest bits; with the catalogue's float MIFF output the change is gone. The stegano
  cases write plain MIFF (`GAP_PLAIN_COMMANDS`).
- **Parameters in units nobody checked.** `-perceptible 0.1` is in quantum units and
  changes almost nothing; `30000` reaches the code. `-function Sinusoid|ArcSin|ArcTan`
  used parameter counts for which every "given or default" test agreed.
- **Fixed-size neighbourhoods.** With a 3x3 `-statistic`, `w*(w/2)` and `w/(w/2)` are
  both 3; a 5x5 one tells them apart. The centre offset is only read under a write mask.
- **Dead values.** `M22` in `GetImageMoments`, `color_vector.alpha` in `TintImage`, the
  alpha blend in `ColorizeImage`, and `sum_cubed`/`sum_fourth_power` in
  `GetImageStatistics` are computed and never reach the output: their mutants are
  equivalent or unobservable, and a refactoring may simplify them only if it keeps the
  public `ChannelStatistics` fields.

**Found on the way, for `ORACLE.md` or upstream:** `magick -perceptible` is rejected
(`perceptible` is missing from `MagickCore/option.c`; `convert` accepts it). `-tint`
ignores its alpha arguments; `-colorize` never applies its alpha percentage (channels
are indexed by offset). `SteganoImage` wraps its position at `columns*columns`, not
`columns*rows`.

### resize.c, after the pilot

The pilot's three rounds left 149 survivors in `resize.c`. Rerun against today's catalogue
(10,050 cases; capped survivors against up to 1,500 cases), one more is killed and 69
remain unmatched; all 69 are read now. The gate is 94% before and after (`gate.py`, today's
verdicts applied to both): 842 of 985 killed, 42 functions ready, 5 careful
(`AcquireResizeFilter` 87%, `SampleImage` 84%, `InterpolativeResizeImage` 88%,
`BesselOrderOne` 89%, `SincFast` 83%), 2 not ready (`ThumbnailImage` 74%, `Fish2X` 73%).

- **37 equivalent**, most of them the piecewise kernels' breakpoints, as the pilot
  found; also Jinc's negative-argument branches (it only ever passes x >= 0) and a Gaussian
  coefficient the source marks as unused.
- **6 gaps, now closed:** `filter:window=Undefined`, a Gaussian `filter:sigma` above 0.5,
  `filter:b` without `filter:c`, and `-resample` without `-density`. The last is odd:
  `magick rose: -density 72 -resample 144` reports 72 dpi, because the `-density` setting
  is re-applied after `-resample` and overwrites the resolution `ResampleImage` sets.
- **24 unresolved**, and these are where to look before refactoring the two not-ready
  functions: the write-mask tests of `ScaleImage`/`SampleImage` (their output is the same
  for every write mask tried, so the per-pixel mask values do not seem to reach it),
  `ScaleImage`'s row and span bookkeeping, `ThumbnailImage`'s sampling shortcut for
  reduction factors above 2 and 4, and ties in `fish2x`.

### Cases that test nothing

`tools/oracle/deadcases.py` runs the catalogue on the base build and groups the cases
that fail by their error. On 2026-09-30, 521 of 9,924 fail. Some failures are the point
of a case (`compare` exits 1 when images differ, error paths such as `-resize 10%` of a
1x1 image), but these groups look like cases that only compare two identical error
messages, and are worth fixing in the catalogue:

| Cases | Error | Example |
| ---: | --- | --- |
| ~225 | `color separated image required` | encoding to `r:`, `c:`, `k:`... and `stream -map cmyk` on non-CMYK images |
| 20 | `Symbol 'v' but fewer than two images` | `-fx 'u*0.5+v*0'` on one image |
| 17 | `non-conforming drawing primitive definition` | `-draw 'matte 10,10 floodfill'` |
| 11 | `unrecognized option` | `-perceptible` (9) |
| 9 | `option deprecated` | `+shade` |

## quantum-import.c and quantum-export.c (Windows)

Full runs (default operators) on WSL, capped survivors rerun uncapped, then cases for the
gaps. Both files hold one routine per pixel layout and per depth, and nearly every
survivor sat on code no case ran: 336 and 232 survivors on unexecuted lines, 159 and 97
mutants in functions never called. What little was reached was checked well (6 and 2
unmatched survivors).

The cases (243, family `quantum`, in the Windows block of `cases.py`): the raw layouts
the raw family never wrote (`graya`, `bgro`, `ycbcra`) at 17 depths and sample formats;
the layouts it has, at the depths it skipped (2, 10 and 24 bits, 24-bit floats, signed
samples, little-endian); UYVY and PAL; palette images in MIFF at depths 1 to 16 and with
alpha; and one image with a meta channel, which takes the multispectral path.
Floating-point BGRO is left out: its reads are not reproducible (ORACLE.md, *Known
upstream issues*). `selfcheck --repeat 8` over the family: 0 nondeterministic.

| File | Mutants | Killed | Plain | Reach | Adjusted |
| --- | ---: | ---: | ---: | ---: | ---: |
| `quantum-import.c`, before | 868 | 362 | 42% | 82% | 42% |
| `quantum-import.c`, after | 868 | 492 | 57% | 94% | **58%** |
| `quantum-export.c`, before | 781 | 415 | 53% | 88% | 56% |
| `quantum-export.c`, after | 781 | 480 | 61% | 88% | **65%** |

Neither file is trusted yet: the survivors left are still mostly unreached.

A second round (31 cases: palette indexes as floating point and at depth 1, the meta
channel as floating point, opacity and alpha as floating point, gray little-endian at
more depths) reached more of both files, unreached survivors 296 to 267 and 148 to 134,
but killed nothing more: the mutants in those branches moved from unreached to unmatched.
One likely reason is that floating-point palette indexes are rounded back to integers,
which hides a small arithmetic change. Those survivors are the next to read. After both
rounds: `quantum-import.c` adjusted 58%, `quantum-export.c` 66%; `selfcheck --repeat 8`,
274 cases: 0 nondeterministic.

## Full runs of the Windows files, night of 2026-09-30 (Windows)

Every mutant of each file (default operators), capped survivors rerun uncapped, gated with
`gate.py`; `build-oracle/harness-file.sh` on WSL. Plain is killed / mutants, reach the
share of mutants in functions some case executes, adjusted counts unreached code as gaps.

| File | Mutants | Plain | Reach | Adjusted | What is left |
| --- | ---: | ---: | ---: | ---: | --- |
| `constitute.c` | 238 | 92% | 100% | 94% | ping over a scene range; MIME types of inline data |
| `blob.c` | 576 | 69% | 83% | 71% | 97 never called, 39 unreached, 26 unmatched |
| `pixel.c` | 2,357 | 42% | 64% | 42% | 860 in the typed Import/Export routines |
| `color.c` | 389 | 77% | 82% | 78% | |
| `cache.c` | 860 | 77% | 84% | 78% | |
| `xml-tree.c` | 620 | 77% | 77% | 77% | |
| `token.c` | 184 | 57% | 85% | 57% | GlobExpression unreached; after 14 glob cases **77%** (below) |
| `splay-tree.c` | 204 | 54% | 55% | 54% | much of it API only |
| `linked-list.c` | 81 | 40% | 40% | 40% | much of it API only |
| `cache-view.c` | 29 | 34% | 38% | 36% | much of it API only |

### constitute.c: trusted

Ten cases (family `constitute`): identify -ping over a range of scenes through a filename
pattern, and inline data URIs with a plain MIME type, an `x-` prefix, a `+suffix` and three
malformed ones, whose errors are compared too. Adjusted 94% to **98%**, reach 100%, no
survivor unreached: **trusted**. The four open survivors:

- `ConstituteImage`, `for (i=0; i < (ssize_t) length; i++)`, `<` to `>=`: an API function
  (the map string of `ConstituteImage()`); no command reaches the loop with a longer map.
- `PingImage`, `if (image != (Image *) NULL)`, flipped: needs a ping that fails after the
  reader returns.
- `GetImplicitDataImageType`, `(slash+1) >= p` and `offset >= MagickPathExtent`, `>=` to
  `>`: boundary mutants, one byte from the end of the type and a type of exactly
  `MagickPathExtent` characters.

### token.c: wildcards in filenames

Nearly all of `token.c`'s unreached code was `GlobExpression_`, the matcher for `*`, `?`,
`[a-z]`, `[!x]`, `{a,b}` and backslash escapes. ImageMagick expands wildcards in input
filenames itself, so 14 cases (family `token`) write six frames and read them back through
a pattern. Some match surprisingly (`frame[!0].miff` gives `frame0.miff` only,
`frame[0-].miff` every frame, `frame{1,}.miff` only `frame1.miff`); that is kept, not
judged. Unreached survivors in `GlobExpression_` 43 to 1, adjusted **57% to 77%**. Left:
`Tokenizer` and `StoreToken` (27 mutants), which nothing on the command line calls, and 14
unmatched. `selfcheck --repeat 8`: 0 nondeterministic.

### pixel.c: not trusted, API only

`ImportImagePixels` and `ExportImagePixels` are called from the command line only by the
JXL coder (and by `ConstituteImage`, itself API), which picks the storage type by depth
(char, short, float) and the map by channels (RGB, RGBA, I, IA). `magick stream` has its
own conversion in `stream.c`. Twelve JXL cases (family `pixel`: 8 and 16 bits and floating
point, RGB, RGBA, gray, gray with alpha) raised the plain score from 42% to **50%**; the
860 mutants in the double, long, long-long and quantum routines, and in the other maps,
are reached only through MagickWand (`MagickImportImagePixels`,
`MagickExportImagePixels`). **Not trusted: API only.** A small C driver calling those
functions would reach them; that is a new kind of harness, for the project owner to
decide.

## Which mutation operators (Windows, 2026-09-30)

Every figure so far comes from **Mull's default operators**: `mull.yml` names only the
files (`includePaths`), so Mull applies its default group at every place in those files
where an operator fits. In all of MagickCore that is 35,266 mutants: equality (`==`/`!=`,
12,330), relational and boundary (`<` to `<=` or `>=` and so on, 10,438), arithmetic (`*`,
`/`, `+`, `-`, `%`, 9,270), increment (`++` to `--`, 3,036) and unary minus (192). "Full"
in this file means every such mutant of a file; "sample" means 60 of them at random.

These model operator slips. The slips refactoring makes are often of another kind: a
statement lost in an extraction (Recipe E), a condition rebuilt wrongly (Recipe P).
Offutt et al.'s sufficient set (ABS, AOR, LCR, ROR, UOI) has logical-connector replacement
(LCR); statement deletion (SDL) has been found cost-effective as well. A pilot added
`cxx_remove_void_call`, `cxx_logical` and `cxx_remove_negation` to the defaults for
`colorspace.c` and `quantum-import.c` (build `mull-trial-ops`, script
`build-oracle/trial-ops.sh`), and ran only the new mutants:

| | `colorspace.c` | `quantum-import.c` |
| --- | ---: | ---: |
| default mutants | 550 | 868 |
| new mutants | 98 (+18%) | 530 (+61%) |
| killed by the existing cases | 93 | 236 |
| open on reached lines | 5 | 4 |
| unreached lines / functions never called | 0 / 0 | 201 / 89 |
| extra time, with the uncapped reruns | about 1 minute | about 8 minutes |

**All 628 new mutants are statement deletions.** `cxx_logical` and `cxx_remove_negation`
generated none, at `-O0` as at `-O2`, by group name or by the operators' own names, and
`cxx_all` adds only `cxx_replace_scalar_call`. The likely reason: Mull mutates LLVM IR, where
C's `&&` and `||` have become branches and `!x` on an `int` a comparison with zero, so the
patterns these operators look for do not occur. So LCR, one of the five sufficient
operators, cannot be had from Mull for this code; nor can ABS. It would take a
source-level tool (Dextool Mutate implements the set) or a small rewriter that switches
`a && b` to `a || b` behind the same environment switch Mull uses.

Statement deletion is cheap and finds the kind of survivor that matters: in
`colorspace.c`, removing `GetPixelInfo(image,&zero)` (lines 800, 2130) or the three
`SetPixelRed/Green/Blue(...gray...)` calls (2283-2285); in `quantum-import.c`, three
`SetPixelAlpha(image,OpaqueAlpha,q)` calls. Not all of them may be gaps (the gray values
may already equal the channels they set), and none has been read yet.

Proposed, not decided: three named operator profiles, so that every figure says which set
it was measured with. `default` (`cxx_default`); `extended` (`cxx_all`, which in practice is
the defaults with statement deletion and scalar-call replacement); `literature`, the
sufficient set as far as Mull can express it (AOR, ROR, SDL for void calls, UOI in part;
no LCR, no ABS). The project owner decides.

## Reading survivors by hand: profile.c, annotate.c, delegate.c (Mac)

Measured on the MacBook, 2026-09-30 and 10-01, following `HARNESS-SPLIT.md`: a full run of
every mutant, the capped survivors rerun uncapped, then reach cases for the code no case
ran, a confirmation rerun, and a verdict on every survivor left. Scores are `gate.py`'s
adjusted figure (functions no case reaches count as gaps). None of the three is trusted;
the reasons are below.

| File | Mutants | Killed | Adjusted | Not trusted because |
| --- | ---: | ---: | ---: | --- |
| `profile.c` | 470 | 34 → 189 | 7% → **42%** | the colour-management transform needs a second, different ICC profile; parser checks need malformed profiles; nested EXIF directories need binary case files |
| `annotate.c` | 578 | 231 → 347 | 41% → **62%** | `RenderPostscript` and its Bézier tracers (94 mutants) run Ghostscript, which the oracle excludes; font metrics that no output shows |
| `delegate.c` | 297 | 111 → 116 | 53% → **54%** | building and running external commands: the sandbox blocks every launch, and the command is not printed even with `-verbose` |

**profile.c.** Two-thirds of the file sat in functions no case called, because the corpus
has one image with profiles (`tests/cli-uhdr-iptc.jpg`: 8BIM, ICC, IPTC). The new cases
build the rest from case text: an EXIF block written with bytes below 128 only (little and
big endian, rationals with denominator 1 and 2, shorts and longs), XMP in attribute and
element form (only the element form is ever rewritten: `GetXMPOffsets` looks for `<name`),
the one ICC profile extracted from the JPEG, and PSD round trips, whose 8BIM carries a
resolution resource and, with an ICC profile, an ICC resource. `-density` and `-orient`
before the write make `SyncImageProfiles` rewrite them.

**annotate.c.** No case drew multi-line text that was also rotated: with a unit scale,
`i*sy*height` and `i/sy*height` agree for the first line and the second, so 30 survivors
in the gravity placements needed `-annotate 20x10+3+4 'one\ntwo\nthree'` under each
gravity. The other gaps: text `-density`, `type:hinting` (a property, set with `-set`),
UTF-8 text, decorations, wrapping captions.

**delegate.c.** Only the `delegates.xml` parsing and `-list delegate` can be observed.

**Found on the way.** `magick ... -define connected-components:verbose=true` prints the
mean colour's alpha as values like `91.02` and `465.79`, not 0 to 1: a display slip, it seems.
**A harness limitation:** case files are written as text, so no case can carry bytes above
127. That rules out EXIF sub-directories (tags `0x8769`, `0xa005`), an 8BIM resolution
resource written by hand (`0x03ED`), and a second ICC profile. Letting a case carry a
binary file (base64 in `cases.py`, decoded by `write_case_files`) would open all three; it
is a change to a shared tool, for the owner to decide.

## Reading survivors by hand: mime.c and cipher.c (Mac)

Measured on the MacBook, 2026-10-01; same procedure as above. Neither needed new cases;
reading the survivors settled both.

| File | Mutants | Killed | Adjusted | Status |
| --- | ---: | ---: | ---: | --- |
| `mime.c` | 128 | 42 | 36% → **40%** | not trusted: `GetMimeInfo`, `GetMimeType`, `GetMimeDescription`, `GetMimeList` and `MagickToMime` (55 mutants) have no command-line caller (only the drawing-wand API calls `MagickToMime`), and the parser's magic-number fields are read only by `GetMimeInfo`; `<include>` handling needs a `mime.xml` the build does not ship |
| `cipher.c` | 155 | 90 | 67% → **85%** | not trusted (below 90%): 10 survivors unresolved, the key-size selection and the counter-mode loop over a partial last block |

**cipher.c: the decryption key schedule is dead code.** `-encipher` and `-decipher` both
run `EncipherAESBlock` in counter mode, so `SetAESKey` computes `decipher_key` (with
`InverseAddRoundKey` and `ByteMultiply`) and nothing ever reads it. Its 31 surviving
mutants are equivalent; a refactoring may delete that code without changing any output.

## Reading survivors by hand: vision.c (Mac)

Measured on the MacBook, 2026-10-01, `mull-sweep60`. Every mutant ran against every case
that reaches it (no cap), then the survivors were rerun after each round of new cases:
four rounds, 101 cases in the gaps family. **Trusted**: every function is at 80% adjusted
or more, the threshold `HARNESS-SPLIT.md` sets.

| Run | Killed | Survived | No coverage |
| --- | ---: | ---: | ---: |
| full run | 161 | 241 | 333 |
| reach cases (`-connected-components` with every `connected-components:` define) | +409 | 165 | 0 |
| rounds 2 to 4 (every metric at `-precision 17`, each sort key, lines of both slopes) | +47 | 118 | 0 |

735 mutants: 617 killed, 58 excused (equivalent or unobservable), 50 open, 10 unreached;
**91% adjusted**. Per function: `ConnectedComponentsImage` 90%, `AngleThreshold` 92%,
the five other `*Threshold` functions 90 to 96%, `IntegralImage` 94%,
`CCObjectInfoCompare` 86%.

- **Dead code in `AngleThreshold`.** The block under `if (fabs(M11) < 0.0)` can never run:
  an absolute value is never negative. Its six mutants are recorded as equivalent; this is
  the first verdict on an unreached line (`classify.py` lets a verdict take precedence
  over "unreached" for that reason). A refactoring may delete the block.
- **Open: 46 unresolved.** 16 at the edges of the keep/remove list parsing (ranges,
  reversed ranges and `;` tried); 11 where a real-valued shape metric would have to equal
  a threshold exactly; 10 in moment arithmetic that reaches the output only through an
  object's keep/remove decision; 2 in the angle's quadrant correction, which needs
  `M20 == M02`; 7 not killed by any of the 27 defines and connectivities tried.

## Reading survivors by hand: layer, transform, attribute, compress, utility, type (Mac)

Measured on the MacBook, 2026-10-01, `mull-sweep60`, no cap. After the reach cases of
`0801cdef0` and a second round of 55 probed cases (`c3c5c9285`), the survivors were rerun
against the gaps family. Only `compress.c` is trusted so far. Under the time budget the project's goal
sets, the open survivors below were read by group, not one by one; each group says why
it is open.

| File | Mutants | Killed | Adjusted | Functions under 80% |
| --- | ---: | ---: | ---: | --- |
| `compress.c` | 224 | 185 | 85% → **88%** | **trusted** after a third round (fax and Group 4 round trips, `bf70839ec`): `HuffmanDecodeImage` 80%; only `Ascii85Initialize`'s single mutant is open, out of reach as explained below |
| `attribute.c` | 513 | 378 | 78% → **80%** | `GetImageBoundingBox` 71%, `FloydSteinbergImageDepth` 69%, `GetImageDepth` 73%, `IsImageOpaque` 62%, the two edge-colour functions 78 to 79%, `GetImageQuantumDepth` 78% |
| `transform.c` | 594 | 411 | 64% → **74%** | `CropImage` 72%, `CropImageToTiles` 56%, `TrimImage` 65%, `TransformImage` 43%; `ExcerptImage` and `ConsolidateCMYKImages` have no command-line caller |
| `layer.c` | 396 | 274 | 61% → **73%** | `OptimizeLayerFrames` 72%, `MergeImageLayers` 66%, `CoalesceImages` 58%, `OptimizeImageTransparency` 57%, `DisposeImages` 29%, `ComparePixels` 77%, `CompositeCanvas` 50% |
| `utility.c` | 337 | 186 | **58%** | most; see below |
| `type.c` | 221 | 118 | **57%** | `LoadTypeCache` 13%, `GetTypeInfoByFamily` 60% |

- **Upstream: `-layers dispose` repeats the first frame.** `DisposeImages` loops with
  `for (next=image; image != NULL; image=GetNextImageInList(image))`: it advances `image`
  and composes `next`, which never moves. Red, blue and green frames come out red, red,
  red (`-layers coalesce` gives red, blue, green). A refactoring has to keep that output;
  fixing it is a behaviour change. Its clipping mutants can be killed only through the
  first frame's offsets; 10 probed cases that do are queued for the next case update.
- **Out of reach with text-only case files.** `HuffmanDecodeImage`'s error paths need a
  corrupt fax stream; a case file cannot hold the bytes.
- **Out of reach with the oracle's configuration.** `ShredFile` (utility.c) runs only when
  `policy.xml` sets a shred count, and shreds a file that is then deleted, so no output
  shows it. `LoadTypeCache` (type.c) parses `type.xml`, of which the build's is fixed;
  no case supplies its own. `AcquireUniqueSymbolicLink`'s copy fallback runs only when
  `symlink()` fails. `ExpandFilename`'s `~user` branch depends on the machine's users.
- **Open in attribute.c.** The edge-colour mutants that read one pixel past the right or
  bottom edge (`columns-1` to `columns+1`) survive `-virtual-pixel Black` too; not settled.
- **`Ascii85Initialize`'s one survivor** (`== NULL` to `!= NULL`) skips the allocation and
  then writes through the pointer, yet no case fails. Likely the compiler, seeing the
  `memset` through the pointer, treats it as non-null and keeps the allocation; under
  another compiler the mutant would crash. Unresolved.

## Batch 3: composite, distort, fx (Windows, 2026-10-01)

Full runs (default operators), then the capped survivors rerun against up to 1,500 cases
(HARNESS-SPLIT.md, step 2), gated with `gate.py`; `build-oracle/harness-file.sh` on WSL,
6 to 10 jobs. The reruns were capped at 1,500, but only `CompositeImage` has more reaching
cases than that (1,443 ran for most of its survivors): in `distort.c` (361-368 reaching
cases) and `fx.c` (370-511) every survivor met every case that reaches it, and none of the
extra cases killed anything.

| File | Mutants | Plain | Reach | Adjusted | Rerun killed | Functions at 80% adjusted |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `composite.c` | 1,289 | 74% | 100% | 76% | 330 of 627 | 9 of 13 |
| `distort.c` | 1,052 | 54% | 100% | 56% | 0 of 281 | 3 of 13 |
| `fx.c` | 927 | 50% | 83% | 50% | 0 of 260 | 19 of 64 |

None of them is trusted. What holds them back:

- **`composite.c`:** `CompositeImage` (972 mutants, adjusted 73%: 117 unmatched, 133 on
  lines no case executes), `TextureImage` 73%, `SeamlessBlendImage` 52%,
  `CompositeOverImage` 78%. The unreached lines are compose operators and argument forms
  the catalogue does not use.
- **`distort.c`:** the polynomial distortion is nearly untested (`poly_basis_fn` 6%,
  `poly_basis_dx` 0%: 74 mutants on unreached lines, so higher orders and the derivative
  never run), `DistortImage` 58%, `GenerateCoefficients` 64%, `SparseColorImage` 52%.
- **`fx.c`:** 156 mutants in functions no case calls: `ImageStat` (33), `DumpRPN` and
  `DumpTables` (62, the `fx:debug` dump), `OprStr`, `GetProperty`, `GetHexColour`
  (hexadecimal colours in an expression). The evaluator itself (`ExecuteRPN`,
  `GetFunction`, `GetOperand`) is at 59-64%.

Next for these files: survivor reading and cases, starting with the polynomial distortion,
`fx.c`'s unreached functions, and `CompositeImage`'s unreached compose operators.

### blob.c: second round

Five cases (family `blob`): `-write inline:svg:-`, which `ImageToBlob` writes through a
temporary file since SVG has no blob support (`png:exclude-chunk=date,time` keeps dates out
of the embedded PNG); the 1.5 MB hald image on stdin, which `ImageToFile` copies in two
1 MiB chunks; and raw gray header offsets inside, at and past the end of the file, so
`DiscardBlobBytes` meets EOF. Together with the first round's seven `ReadBlobString` cases
(CRLF, no final newline): 8 killed, 402 to **408** of 576 killed, adjusted 72% to **73%**.
`selfcheck --repeat 8` over the family: 0 nondeterministic. **Not trusted.** Out of reach
from the command line: `SetBlobExtent` (26 of its 31 mutants are in the file-stream and
mapped branches, but its only callers write to a memory blob) and `SyncBlobStream` (a
borrowed blob is promoted only in `ImagesToBlob`, an API function), with 97 no-coverage
mutants in other API functions (`ImagesToBlob`, `CustomStreamToImage`, `FileToImage`,
`BlobToFile`, `PingBlob`, ...). Still open on reachable code: `ReadBlobString` 53% (7
unmatched in the end-of-line handling), `ImageToFile` 71%, `ImageToBlob` 64%.

### constitute.c: trusted again under the per-function bar

Under the new rule (every function at adjusted 80%), `PingImage` at 75% made `constitute.c`
untrusted: its open mutant flips the check on the image the reader returned, which only a
ping that fails exposes. Three cases (family `constitute`): `identify -ping` of a corrupt
MIFF, a PPM of size zero and a missing file. `PingImage` is now at 100% adjusted (4 killed, 1 unobservable); every function is
at 86% or more (`ConstituteImage` 86%, `GetImplicitDataImageType` 89%), adjusted 98% to
**99%**: **trusted**. `selfcheck --repeat 8`: 0 nondeterministic.

## Batch 4: quantize, stream, matrix, option and five small files (Windows, 2026-10-01)

As batch 3: full runs, capped survivors rerun against up to 1,500 cases, `gate.py`; WSL,
6 jobs, catalogue of 10,612 cases. Few survivors were capped: these files' functions are
reached by fewer than the default 300 cases, except `option.c` (14), `signature.c` (22) and
`registry.c` (1, still capped at 1,500: it is reached by more).

| File | Mutants | Plain | Reach | Adjusted | Rerun killed | Functions at 80% adjusted |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `quantize.c` | 868 | 71% | 95% | 74% | - | 30 of 47 |
| `stream.c` | 492 | 64% | 92% | 69% | - | 6 of 21 |
| `matrix.c` | 214 | 46% | 75% | 47% | - | 2 of 15 |
| `resource.c` | 179 | 79% | 89% | 81% | - | 8 of 13 |
| `option.c` | 149 | 74% | 90% | 74% | 1 of 14 | 12 of 20 |
| `magick.c` | 120 | 80% | 82% | 81% | - | 29 of 32 |
| `signature.c` | 71 | 58% | 99% | 69% | 0 of 22 | 2 of 10 (4 with no score) |
| `timer.c` | 35 | 63% | 89% | 63% | - | 7 of 11 |
| `registry.c` | 31 | 58% | 84% | 69% | 0 of 1 | 6 of 9 |

None is trusted under the per-function bar. The functions furthest below it:

- **`quantize.c`:** `FloydSteinbergDither` 68% (111 mutants), `KmeansImage` 62% (91),
  `PosterizeImage` 49%, `AssignImageColors` 68%, `GetImageQuantizeError` 0% (27; called
  only when `measure_error` is set, which `-verbose` does), `RemapImages` 20%.
- **`stream.c`:** `StreamImagePixels` 79% (367); most of the rest is the stream pixel cache's
  accessors (`GetVirtualPixelStream`, `GetOneVirtualPixelFromStream`, ...), at 0%: no case
  calls them.
- **`matrix.c`:** `MatrixToImage` (32) at 0%, called only by `HoughLineImage` when
  the `hough-lines:accumulator` define is set; `SetMatrixExtent`, `ReadMatrixElements` and
  `WriteMatrixElements` at 0%, the matrix kept in a file when it cannot be kept in memory;
  `GaussJordanElimination` 75%.
- **`option.c`:** `GetCommandOptionFlags` 61% (33), the channel parsers 44-57%, and the
  option iterators (API) at 0%.
- **`magick.c`:** `MagickSignalHandler`, `GetMagickList`, `GetImageMagick` at 0%, every
  other function at 80% or more.
- **`signature.c`:** `SignatureImage` 76%, `TransformSignature` 73%, `FinalizeSignature`
  40%: nearly every line is reached (99%), but the survivors are not yet read.
- **`resource.c`:** `AcquireUniqueFileResource` 48%, `FormatTimeToLive` 0% (18; `-list
  resource` prints it only when a time limit is set).
- **`timer.c`**, **`registry.c`:** `StopTimer`, `ContinueTimer`, `FormatMagickTime`;
  `DefineImageRegistry`, `RemoveImageRegistry` (API).

## Batch 5: feature, montage, histogram, resample and six small files (Windows, 2026-10-01)

As batches 3 and 4 (WSL, 4 to 6 jobs, catalogue of 10,612 cases). Every rerun of capped
survivors killed nothing; `monitor.c` (6) and `quantum.c` (2) still have survivors capped
at 1,500, reached by more cases than that.

| File | Mutants | Plain | Reach | Adjusted | Rerun killed | Functions at 80% adjusted |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `feature.c` | 842 | 73% | 100% | 77% | - | 6 of 8 |
| `resample.c` | 228 | 68% | 100% | 71% | 0 of 72 | 3 of 8 (2 with no score) |
| `montage.c` | 224 | 75% | 100% | 78% | - | 2 of 6 (1 with no score) |
| `histogram.c` | 165 | 79% | 100% | 88% | - | 12 of 18 (2 with no score) |
| `gem.c` | 114 | 76% | 100% | 89% | 0 of 8 | **4 of 4** |
| `quantum.c` | 88 | 86% | 95% | 89% | 0 of 3 | 11 of 15 (2 with no score) |
| `exception.c` | 69 | 94% | 96% | 96% | - | 16 of 19 (1 with no score) |
| `semaphore.c` | 20 | 100% | 100% | 100% | - | **7 of 7** |
| `prepress.c` | 17 | 76% | 100% | 87% | - | **1 of 1** |
| `monitor.c` | 9 | 33% | 100% | 38% | 0 of 6 | 2 of 3 |
| `distribute-cache.c` | 176 | 0% | 0% | 0% | - | 0 (no case reaches it) |

**`semaphore.c` is trusted:** every mutant killed. `gem.c` and `prepress.c` meet the
per-function bar too, but their unmatched survivors (9 and 2) are not yet read, so they are
not trusted until they are listed or explained. Below the bar elsewhere:

- **`feature.c`:** `GetImageFeatures` 72% (509 mutants, the Haralick texture features of
  `-features`), `RenderHoughLines` 69%.
- **`resample.c`:** `ResamplePixelColor` 62% (139, the elliptical weighted average behind
  `-distort`), `SetResampleFilter` 64%.
- **`montage.c`:** `GetMontageGeometry` 75%, `CloneMontageInfo` 0%.
- **`histogram.c`:** `MinMaxStretchImage` 60%, `IsPaletteImage` 67%.
- **`quantum.c`:** `SetQuantumMetaChannel` and `SetQuantumPad` at 0% (API).
- **`exception.c`:** `InheritException`, `SetErrorHandler` at 0% (API).
- **`monitor.c`:** `SetImageProgress` 17% (7 mutants); its survivors are not yet read.
- **`distribute-cache.c`:** the distributed pixel cache server (`-distribute-cache <port>`)
  and its clients, which talk over TCP; no case starts a server. Out of reach for now.

## Reading survivors by hand: effect.c, fourier.c, list.c (Mac, measured on ERDC)

Measured on ERDC, 2026-10-01: a full run, the capped survivors at 1,500 cases (only
`list.c` had any), then the survivors rerun against the gaps family after each round of
cases (`conf1` after `07d5e5564`, `conf2` after `b8cdb780b`). Survivors read on the Mac;
the three probe kills of the second round were checked on the Mac's `mull-sweep60` build
first, and ERDC's `conf2` killed the same three. All three files are **trusted**.

| File | Mutants | Killed | Adjusted | Lowest function |
| --- | ---: | ---: | ---: | --- |
| `effect.c` | 1,154 | 974 | **90%** | `AdaptiveBlurImage` 82% |
| `fourier.c` | 63 | 56 | 93% → **100%** | every reached function at 100% |
| `list.c` | 159 | 120 | 85% → **89%** | `SyncNextImageInList` 80% |

- **`fourier.c`: the oracle builds without FFTW.** `-fft` only warns, so it never makes
  the magnitude and phase pair, and `-ift` after it never ran on two images:
  `InverseFourierTransformImage` was never reached. `-ift` on two read images reaches it
  and its FFTW stub. The forward and inverse transforms themselves are compiled out.
- **`list.c`.** Two cases: `-delete 0-0` (a range ending at 0, which a mutant counts from
  the end and so deletes every frame) and `-insert 0`, the only command-line path to
  `PrependImageToList`. Read and excused: a leak in `DestroyImageList`, a write one past
  the end of `delete_list` in `DeleteImages`, the clean-up after a failed `CloneImage`,
  and `CloneImages`' `step > 0`, which `>=` cannot change since step is never 0. Out of
  reach: `SyncImageList` and `SpliceImageIntoList` (14 mutants), which nothing calls.
  Open: `SyncNextImageInList`'s blob test, since every reader shares the blob with the
  next frame.
- **`effect.c`: 106 open (55 unmatched, 51 unreached), listed by group.** 21 are the
  progress monitor (`progress++` and the `proceed` test) on lines no case reaches without
  `-monitor`, in eleven functions; 6 are the clean-up after a failed allocation
  (`DespeckleImage`, `RotationalBlurImage`, `ShadeImage`); the other 79 are kernel and
  pixel arithmetic, most in `AdaptiveBlurImage`, `AdaptiveSharpenImage`,
  `BilateralBlurImage` and `SelectiveBlurImage` (55 together), then `PreviewImage`,
  `SharpenImage`, `UnsharpMaskImage`, `GetMotionBlurKernel`, `EmbossImage`, `Hull` and
  `LocalContrastImage`. Among them, the kernel normalisation fallbacks
  (`kernel[w][(k-1)/2]=1.0`, lines 235 and 554), the copy-only channels (`p[center+i]`,
  lines 338, 3629, 3688) and `SelectiveBlurImage`'s second kernel loop (3500, 3505) are
  never reached.
- **For `classify.py` (not changed).** A progress-monitor line no case reaches counts as
  unreached, though the same line, reached, is excused as `progress`. Letting the rule
  apply to unreached lines would move every file's figures on both machines.

## Configuration of the case's own: magic, policy, memory, random, geometry, image, type, utility (Mac)

Survivors read on the Mac, 2026-10-01 night, from ERDC's full runs (uncapped reruns of the
capped survivors) for `magic`, `policy`, `memory`, `random`, `geometry` and `image`, and
from the Mac's own runs for `type` and `utility`. The new cases (`fe32da125`, `483fdf1d2`)
were probed on the Mac (`mull-sweep60`; `mull-imagec` for `image.c`) against the new cases
only. **The figures below are previews**: for ERDC's files they merge a Mac probe and
become the file's figures only after ERDC's `conf` rerun.

**A case can now bring its own configuration.** The oracle sets `HOME` to the case
directory, and ImageMagick searches `$HOME/.config/ImageMagick/` too. Case files may now
sit in subdirectories (`oracle.py`, `966a1a639`). It works for **`policy.xml` and
`type.xml`**, which merge every file found. *Corrected 2026-10-02 evening:* a case's
`locale.xml` and `log.xml` are read as well (both appear in `-list locale` and `-list log`);
locale cases compare, but `-list log` orders its files by path, so the build's own `log.xml`
sorts before or after the case's depending on where the build lives, and two builds of the
same code differ: no log case can be compared. `configure.xml` really is first-only
(`AcquireConfigureCache` stops at the first that loads, the build's), and so is `delegates.xml`
(`-list delegate` shows only the build's path; Mac, 2026-10-03). A `policy.xml`'s, a `mime.xml`'s
and a `locale.xml`'s `<include>` never loads (a `type.xml` include does): a `locale.xml` holding
only an include, from a case or alone on the configure path, leaves the cache empty and
ImageMagick falls back to `english.xml` (Mac, 2026-10-03; cause not traced). This opens code that earlier sections called
out of reach: `LoadTypeCache`, shredding (`ShredMagickMemory`, `ShredFile`), the
file-backed virtual memory, rights by path, directory and pattern, symlink protection.

| File | Adjusted before | Preview | Status |
| --- | ---: | ---: | --- |
| `random.c` | 24% | **60%** | every reached function at 100%: trusted on ERDC's figures, with the caveat below |
| `magic.c` | 72% | **84%** | every reached function at 82% or more: trusted once ERDC confirms |
| `type.c` | 57% | 71% | not trusted: `LoadTypeCache` 62%, `GetTypeInfoByFamily` 60% |
| `geometry.c` | 60% | 70% | not trusted: `ParseGeometry` 59%, `ParseGravityGeometry` 60%, `ParseMetaGeometry` 71% |
| `memory.c` | 34% | 63% | not trusted: the exact `max-memory-request` boundaries and the NULL-handler test, in functions of 2 to 4 mutants |
| `utility.c` | 58% | 62% | not trusted: `ShredFile` is reached now, `AcquireUniqueSymbolicLink`, `ExpandFilename` |
| `image.c` | 59% | 61% | not trusted: new cases reach 21 of 33 unreached mutants but kill 14 of 242 |
| `policy.c` | 30% | 55% | not trusted: `IsPathContainsSymlink` (paths with real symlinks), rights matching by canonical path |

- **`random.c`: unobservable by design.** The oracle seeds every command (`-seed 1`), so
  the generator's seed comes from the secret key; the entropy reservoir, the nonce and
  the keyed generator feed only temporary names and shredding. 30 of its 45 mutants are
  excused on that ground, so a mistake in the keyed generator would not be seen: refactor
  it with the guard, not the oracle. `ReadRandom` runs only if `/dev/urandom` opens
  (under Landlock on ERDC it does not); `GetRandomValue` has no caller.
- **`magic.c`.** Extensionless files: `PCD_` at 2048 (the farthest signature, which
  sets how much is read), a file exactly a signature long, SVG with spaces after `<` (the
  only entries that skip spaces). Five survivors are equivalent from the table itself (no
  signature at offset 10, a running maximum, an extent of 2052 bytes).
- **`memory.c`.** `-despeckle` under `max-memory-request=64KiB` sends its scratch buffers
  to a mapped temporary file; the output matches a run without the limit, as it should,
  so the 11 mutants there are unobservable. Open: 4 boundary mutants at exactly the
  maximum request, and `AcquireAlignedMemory`/`RelinquishAlignedMemory`'s handler test,
  which should call a NULL pointer and does not fail any case (not understood).
- **`policy.c`.** Six `GetLogEventMask() & PolicyEvent` guards are logging the `logging`
  rule does not match (it looks for `IsEventLogging`).
- **For the next round.** `image.c` needs reading by hand (129 survivors on reached
  lines); `geometry.c` (69 unmatched) and `type.c` (42) are the next largest.

## Statement deletion on the Mac's files (ERDC, 2026-10-01)

The operator trial `HARNESS-SPLIT.md` asked for, run by `tools/oracle/erdc/night.sh`: one
Mull build of all 48 Mac files with `cxx_default cxx_remove_void_call`, then only the new
mutants, capped at 1,500 cases (`mutation-erdc-sdl-*.json`). 43 files have such mutants.
**A measurement for the owner's decision, not counted towards any file's trust.**

| | |
| --- | ---: |
| new mutants (void calls deleted) | 1,251 |
| on top of the default mutants of those files | 18,854 (+6.6%) |
| killed / survived / no case reaches | 719 / 394 / 138 |
| killed among those reached | 65% |
| ERDC time, build included | 75 minutes |

About a third of the 394 survivors delete a call no output could show: frees and
destroys (46), semaphores (24), memset and resets (10), `random.c`'s key and signature
updates (50, under `-seed`). The rest (about 260) are the slip an extraction makes: a lost
`GetPixelInfo` initialiser (34), a lost `SetPixelChannel` (21) or `SetPixelAlpha` (10)
write, `SetGeometry` (10), `GravityAdjustGeometry` (6), `GetPathComponent` (23),
`SetStringInfoLength` (20). The default operators cannot make those mutants, so the
default figures do not speak about them. Most survivors: `random.c` 59, `image.c` 33,
`profile.c` 32, `draw.c` 23, `transform.c` 21. Recommendation: adopt statement deletion
(the `extended` profile); it is cheap (+6.6% mutants) and models Recipe E's main risk.

## Phase 1 files on today's catalogue (Mac, measured on ERDC)

Full runs on ERDC of the ten Phase 1 files (default operators, capped survivors at 1,500,
`erdc4`), gated with the existing verdicts, so the per-function bar applies to them for
the first time. These replace the Mac's older figures for these files.

| File | Adjusted | Functions under 80% | Status |
| --- | ---: | --- | --- |
| `decorate.c` | 98% | none | **trusted** |
| `statistic.c` | 95% | `MagickSafeReciprocalLD` 50% (2 mutants) | not yet: one small function |
| `colormap.c` | 95% | `IntensityCompare` 0% | not yet: the sort comparator |
| `enhance.c` | 93% | none | **trusted** |
| `threshold.c` | 93% | none | **trusted** |
| `visual-effects.c` | 92% | `ColorMatrixImage` 70%, `PolaroidImage` 63% | not trusted |
| `resize.c` | 90% | `ThumbnailImage` 74%, `Fish2X` 73% | not trusted; `LiquidRescaleImage` is a stub (no liblqr) |
| `compare.c` | 88% | `SimilarityImage` 63%, `GetPHASHSimilarity` 70% | not trusted |
| `shear.c` | 86% | none | **trusted**; `ShearRotateImage` has no caller outside shear.c |
| `segment.c` | 76% | none | **trusted**; `GetImageDynamicThreshold` has no caller outside segment.c |

`GetImageExtrema` (statistic.c) and `IsImagesEqual` (compare.c) have no caller outside
their files either.

## Under the extended operators: the Mac's files, 2026-10-02 (Mac)

Statement deletion was adopted on 2026-10-02 (`HARNESS-SPLIT.md`), so every Mac file was
gated again with its `mutation-erdc-sdl-<file>.json` merged in. Six files trusted on the
defaults fell below the bar (`list`, `enhance`, `threshold`, `segment`, `compress`,
`random`); all six are back above it, with new cases or verdicts. Figures here merge the
Mac's probes (`mull-p1sdl`, `mull-p2ext`, built with both operators), so for ERDC's files
they are previews until `day.sh` re-measures them.

**Trusted under the extended operators (22 of 48):** `artifact`, `cipher`, `client`,
`coder`, `compress`, `decorate`, `effect`, `enhance`, `fourier`, `list`, `magic`,
`random`, `resize`, `segment`, `shear`, `static`, `thread`, `threshold`, `version`,
`vision`, `visual-effects`, and `module` (no case reaches any of its functions, so out of
reach rather than protected). `version.c` is trusted at 14% adjusted: most of it has no
caller. `random.c` is trusted only because its keyed generator cannot be observed under
`-seed`.

What the new survivors showed, and the cases written for them:

- **`ModulateImage`'s colormap branch.** Deleting `ModulateHCL` and the rest survived:
  the `modulate:colorspace` cases used DirectClass images only, and the colormap is
  modulated on its own. Palette cases under all eight colour models kill all eight.
- **`ColorThresholdImage`'s start colour.** Deleting a conversion leaves the start far
  above every pixel, which shows only if the range selects pixels at all, and the first
  ranges selected none. One range per model (HCL, HSB, HSL, HSV, Lab) whose converted
  start lies below its stop kills them; no HWB range tried selects any pixel (2 open).
- **`HuffmanDecodeImage`'s pixel colour.** Fax images were only written back as MIFF,
  which stores the indexes; a fax read back and resized reads the colours.
- **Mutants that should crash and do not.** `GetMagickVersion`, `AcquireAlignedMemory` /
  `RelinquishAlignedMemory`'s handler test and `Ascii85Initialize` each dereference or
  call a pointer the compiler knows to be NULL in the mutated branch. That is undefined
  behaviour and clang removes the branch, so the mutant runs like the original:
  equivalent as compiled.

New cases for code no case reached (probed or to be probed on the Mac):

- **`cipher.c`**: passphrases of 46, 48 and 64 characters, whose second halves are keys
  on either side of `SetAESKey`'s 192- and 256-bit choices; the catalogue's passphrase
  gave 18 bytes, so only the 128-bit schedule ever ran.
- **`identify.c`**: `identify:locate`, `:limit`, `:moments` and `:convex-hull`, a Lab
  image (the default branches of the colourspace switches; features on Lab take minutes,
  so they stay out), a 16-bit image, masks and a meta channel in verbose info, an image
  read smaller than stored, a montage's tile directory, a long property.
- **`compare.c`**: PHASH subimage searches (`GetPHASHSimilarity` serves only the
  search), NCC searches, a blurred patch.
- **`string.c`**: text with a control character (`StringToStrings`' hex-dump layout) and
  `exif:sync-image` set to `false`, `off`, `no`, `0`, `true` (`IsStringFalse`).
- **`draw.c`**: square line caps, images drawn under an affine transform and a rotation.
- **`property.c`**: the profile property readers (EXIF, ICC, IPTC, 8BIM, XMP), which no
  case asked for.
- **`statistic.c`**: a single-colour image, whose one histogram bin passes 0 to
  `MagickSafeReciprocalLD`.

Upstream behaviour a refactoring must keep:

- **`-similarity-threshold` has no effect** (compare.c). `threshold_trigger` is declared
  inside `SimilarityImage`'s row loop, so it is false whenever it is tested; the six
  mutants on the threshold tests are equivalent.
- **`-define draw:render-bounding-rectangles=true` aborts** (exit 134) on a plain
  polygon; no case uses it.
- **A `<include>` in a case's own `policy.xml` or `mime.xml` never loads**; one in
  `type.xml` does. `type.c` reads the include with `FileToString`, `policy.c` and
  `mime.c` with `FileToXML`; why the latter fails was not found.

Out of reach, written down: gradients' reflect and repeat spreads (`gradient:` always
pads, MVG has no spread keyword: `DrawGradientImage` 64 unreached), `ClonePolygonEdgesTLS`
(more than one thread), the `-debug` loggers of `draw.c`.

### Later rounds the same day (Mac, previews)

Probes on the Mac's own builds against only the new cases, uncapped; ERDC's reruns
(`confirm-new.sh`) make them official.

| File | Before | After | What the cases were |
| --- | ---: | ---: | --- |
| `statistic.c` | 95% | **96%, trusted** | `MagickSafeReciprocalLD`'s three mutants are equivalent: for a single-colour channel the only entropy term becomes -0 or NaN, and NaN is skipped |
| `colormap.c` | 91% | **93%, trusted** | PALM files below 8 bits written to the compared output, so `IntensityCompare`'s colormap order is in the bytes (read back, any order decodes alike) |
| `compare.c` | 88% | **90%, trusted** | `phash:normalize` |
| `draw.c` | 64% | 71% | an MVG file with every keyword no case used (named classes and macros, `use`, mask, symbol, scale, the text and font settings); stroke joins turning both ways under each join and miter limit; dash offsets in the pattern's own graphic context; the `alpha` primitive's methods |
| `property.c` | 47% | 56% | the property names no case printed, the 14 properties `SetImageProperty` maps onto image fields, format strings from a file, entities, globs |
| `image.c` | 61% | 63% | smush gaps over fully transparent margins (`rose_alpha` has none, so the gap was always 0); `AcquireImage`'s settings on `xc:` images, which no reader overwrites |
| `string.c` | 55% | 63% | a `label:` with a control character (the hex-dump layout; `-annotate` does not use `StringToStrings`), `exif:sync-image` values, quoted `@list` names; an HDR file as the compared output for `CopyMagickString`'s return value |
| `type.c`, `attribute.c`, `transform.c`, `layer.c` | | +3, +1, 0, 0 | a DOCTYPE in `type.xml`; trims of a bordered image under a black virtual pixel; crop and off-canvas layer edge cases (reached, but the survivors sit at exact boundaries) |

So every Mac file in the backlog's first wave is trusted: `resize`, `compare`, `enhance`,
`visual-effects`, `statistic`, `threshold`, `segment`, `decorate`, `colormap`, `shear`.
`identify.c` (87%) is trusted too; `channel.c` waits only for ERDC to measure a case it
already has.

## Case rounds for distort, fx and composite (Windows, 2026-10-02)

Each file's survivors and no-coverage mutants (full run and 1,500-case rerun) were rerun
against its new family, then gated with all of its reports; `selfcheck --repeat 8` over
each family: 0 nondeterministic. For `composite.c` the catalogue refresh (below) is in
too; it killed nothing more.

| File | Cases | Killed by the round | Adjusted before | After | Functions at 80% |
| --- | ---: | ---: | ---: | ---: | --- |
| `distort.c` | 14 (family of 83) | 95 | 56% | **65%** | 3 to 7 of 13 |
| `fx.c` | 30 | 175 | 50% | **70%** | 19 to 31 of 64 |
| `composite.c` | 25 | 67 | 76% | **82%** | 9 to 10 of 13 |

- **`distort.c`:** polynomials of every order (1, 1.5, 3, 4, 5) over 25 control points,
  with `-verbose` printing the fitted terms: `poly_basis_fn`, `poly_basis_dx` and
  `poly_basis_dy` from 6%, 0% and 0% to **100%**. Still below 80%: `DistortImage` 62%,
  `GenerateCoefficients` 64%, `SparseColorImage` 52%.
- **`fx.c`:** per-pixel statistics, hexadecimal colours, `%[...]` properties, `epoch()`,
  attributes of a second image and the `fx:debug` dump. `DumpRPN` 0% to 87%,
  `GetProperty` 86%, `GetHexColour` 80%, `ImageStat` 0% to 67%. The evaluator
  (`ExecuteRPN`, `GetFunction`, `GetOperand`) is the largest gap left.
- **`composite.c`:** `compose:args` forms (blur angles, displace and distort with
  percent, aspect and centre, dissolve beyond 0-100%, blend, threshold, the blends'
  iterations) and the illuminant and colorspace defines. `CompositeImage` 73% to **81%**.
  Still below: `CompositeOverImage` 78%, `TextureImage` 73%, `SeamlessBlendImage` 52%.

`feature.c` has 12 new cases waiting for their round, and 37 survivors in
`GetImageFeatures` are now recorded as equivalent: the matrix `Q` it accumulates for the
maximum correlation coefficient is never read, since the coefficient is set to
`sqrt(-1.0)`. Its two information measures of correlation print NaN on every catalogue
image (they sum `p*log2(p)` over all pairs of grey levels, and some pair is always
missing), so the new cases use noise images of two or three levels, which give finite
values.

## Catalogue refresh, and rounds for feature, resample and distort (Windows, 2026-10-02)

**Refresh.** Every Windows file's survivors and no-coverage mutants were rerun against the
catalogue as it stood on the morning of 2026-10-02 (10,683 cases, then 10,753; capped at
1,500 cases, reports `mutation-refresh1002-<file>.json`). The cases the Mac and ERDC had
added since the full runs reached almost none of them. **Only `morphology.c` gained: 26
kills, adjusted 78% to 81%.** `blob.c` gained 8 (73% to 74%), and the other 32 files
nothing.

**Merging reports.** `gate.py` lets the later report win for a mutant, which is right for
reruns of survivors, but not when a later, capped rerun meets a mutant an earlier round
killed. The figures here merge every report of a file with a mutant counted as killed if
any report killed it.

**Rounds** (`selfcheck --repeat 8`: 0 nondeterministic each):

| File | Cases | Killed | Adjusted before | After | Functions at 80% |
| --- | ---: | ---: | ---: | ---: | --- |
| `feature.c` | 12 | 62 | 77% | **87%** | 6 to 7 of 8 |
| `distort.c`, second round | 24 more (family of 107) | 91 more | 65% | **74%** | 7 to 8 of 13 |
| `resample.c` | 32 | 7 | 71% | **74%** | 3 of 8 |

- **`feature.c`:** with the noise images and the 37 equivalent mutants in the dead `Q`
  block, `GetImageFeatures` is above 80%; left below: `RenderHoughLines` 69%.
- **`distort.c`:** `SparseColorImage` 52% to over 80% (CMYK, alpha, gray, `-verbose`, close
  points). Left below: `DistortImage` 62%, `GenerateCoefficients` 64%, `RotateImage` 75%,
  `MagickRound` 50%.
- **`resample.c`:** `ResamplePixelColor` 62% to 66% only. Most of its survivors are in
  the shortcut that returns one colour for an area wholly outside the image. Flipping its
  bounds tests mostly changes speed, not output, so they are candidates for `equivalent`
  after a closer reading.

Where the Windows files stand per function now: `constitute.c` and `semaphore.c` trusted;
`feature.c` 7 of 8 functions at 80%, `colorspace.c` 8 of 12 (`RoundToYCC` 60%, and
`ConvertGenericToRGB`, `ConvertRGBToGeneric`, `GetImageColorspaceType` at 0%),
`morphology.c` 17 of 23.

## colorspace.c: trusted under the per-function bar (Windows, 2026-10-02)

Sixteen cases (family `composite`): Hue, Saturate, Luminize and Colorize under
`compose:colorspace` sRGB, Gray, XYZ and Lab. sRGB and Gray are not in the switches of
`ConvertRGBToGeneric` and `ConvertGenericToRGB`, so they take the default branches, which
nothing reached (both functions at 0%). Rerun over `colorspace.c` and `composite.c`:
`selfcheck --repeat 8`, 41 cases: 0 nondeterministic; 6 more kills in `colorspace.c`, both
functions now at 100%; `composite.c` unchanged at 82%. Two survivors in `RoundToYCC` are
`equivalent` (`verdicts.json`): at `value == 0.0` and `value == 1388.0` the mutated clamps
fall through to the rounding, which gives the same index.

**`colorspace.c`: adjusted 88% to 89%, every function at 80% or more, trusted.** Merged
over every report (full, uncapped, `newcases`, `nocov`, the composite rounds and the
refresh), with a mutant counted as killed if any report killed it. Out of reach:
`GetImageColorspaceType` (1 mutant), an API function nothing in ImageMagick calls. Open
survivors, by line (unmatched, or on unreached lines):

- `TransformsRGBImage` (32): 2099, 2106 (2), 2125, 2127, 2183, 2185, 2233, 2256, 2267,
  2276, 2341, 2343, 2428, 2434, 2436, 2443, 2445 (2), 2449, 2511, 2573, 2593, 2595, 2597,
  2628, 2683, 2690, 2832, 2835, 2851, 2896.
- `sRGBTransformImage` (23): 767, 774 (2), 844, 901, 1106, 1165, 1227, 1247, 1249, 1251,
  1401 (3), 1403, 1407, 1411, 1468, 1490, 1493, 1510, 1518, 1535.
- `ConvertHSLToRGB` 328 and `ConvertRGBToHSL` 640 (`<=` to `<`).

## gem.c and prepress.c: trusted (Windows, 2026-10-02)

Both meet the per-function bar on their full runs and reruns (merged as above). Their open
survivors, listed so the refactoring phase knows what is not checked:

- **`gem.c`** (adjusted 89%, 4 of 4 functions at 80%): `GenerateDifferentialNoise` 167,
  170, 178, 181 (unreached), 188, 189 (unreached); `GetOptimalKernelWidth2D` 328 (2),
  336; `GetOptimalKernelWidth1D` 287, 294.
- **`prepress.c`** (adjusted 87%, its one function at 87%): `GetImageTotalInkDensity`
  139, 144.

Not yet: `exception.c` (96%) and `quantum.c` (89%) each have functions at 0% that are not
API-only. `InheritException` is reached from the JPEG coder's error path, `SetErrorHandler`
from the TIFF coder, and `SetQuantumMetaChannel` and `SetQuantumPad` from the TIFF and PSD
coders (meta channels, padding). They need cases on such files. `histogram.c` (88%):
`MinMaxStretchImage` 60%, `DestroyColorCube` 60%, `IsPaletteImage` 67%.

## Rounds for quantum, exception, histogram and matrix (Windows, 2026-10-02, late afternoon)

Each family `selfcheck --repeat 8`: 0 nondeterministic. Figures merge every report of a
file, with a mutant counted as killed if any report killed it.

| File | Family, cases | Adjusted before | After | Below 80% after |
| --- | --- | ---: | ---: | --- |
| `quantum.c` | `metachannel`, 5 | 89% | **94%** | `SetQuantumMetaChannel` 60%, `SetQuantumPad` 0% |
| `quantum-import.c` | `metachannel` | 58% | 61% | many (typed import routines) |
| `quantum-export.c` | `metachannel` | 66% | 68% | many |
| `exception.c` | `exception`, 1 | 96% | 96% | `InheritException` 0%, `SetErrorHandler` |
| `histogram.c` | `histogram`, 4 | 88% | **93%** | `IsPaletteImage` 67% |
| `matrix.c` | `matrix`, 3 | 47% | **70%** | 11 of 15 functions |
| `feature.c` | `matrix` | 87% | 87% | `RenderHoughLines` 69% |

- **`quantum.c`:** an image with a meta channel (`-combine` of five gray images) written as
  TIFF, contiguous and planar at 8 and 16 bits, and as PSD, then read back, reaches both
  functions. Open: `SetQuantumMetaChannel`'s bounds (a meta channel of -1, or one equal to
  the count, which the TIFF reader never passes), and `SetQuantumPad`'s overflow guard and
  logging (it is mostly called with a pad of 0).
- **`exception.c`:** a `policy.xml` of the case's own that denies the GIF module makes
  `ReadImage` inherit the policy error (static.c), which reaches `InheritException`. Its
  two mutants survive: most likely the same NotAuthorized is thrown directly into the
  command's exception by an earlier lookup, and duplicates are dropped. `unresolved` until
  probed. `SetErrorHandler` is called only by the X11 display and animate code.
- **`histogram.c`:** `-auto-level` on a flat image and a flat channel kills
  `MinMaxStretchImage`'s `fabs(min-max)` mutants (60% to over 80%). In `verdicts.json`:
  its two inverted return values are `unobservable` (`AutoLevelImage`'s result is cast to
  `(void)` in operation.c and mogrify.c), and four mutants in `DestroyColorCube` and
  `DestroyHCubeInfo` are `unobservable` (they change only which nodes are freed: a leak).
  Open: `IsPaletteImage`'s `<=` at `MaxColormapSize`. A PseudoClass image of exactly 65,536
  colours (`+dither -colors 65536`) did not kill it; that image reports `TrueColor` either
  way. Other open survivors: `CheckImageColors` 728, 755, 778; `UniqueColorsToImage` 1208
  (unreached), 1211, 1212; `GetNumberColors` 1115 (unreached), 1122;
  `ClassifyImageColors` 318.
- **`matrix.c`:** `-hough-lines` with `hough-lines:accumulator` (the only caller of
  `MatrixToImage`) and with `-limit memory 0 -limit map 0`, which keeps the matrix in a
  file. `MatrixToImage` 0% to 79%, `ReadMatrixElements` 60%, `WriteMatrixElements` 40%,
  `SetMatrixExtent` still 0%.

## A kill stands when reports are merged (Mac, 2026-10-02)

`gate.py` merged reports so that a later one replaced the earlier result of the same mutant.
Probes run with `--cases` and only a few cases, so a probe's "survived" means only that those
cases missed the mutant. Merged after a full run, it overwrote that run's kills: probe p24c
alone took `channel.c`'s `SetImageAlphaChannel` from 99% to 51%. The catalogue only grows,
so a kill now stands, and "no-coverage" still never replaces anything (`gate.replaces`).
Figures computed by merging probes after a full run were too low; on the Mac's 48 files,
`channel.c` went from 74% to 92% (trusted), `type.c` from 63% to 65% and `utility.c` from 61%
to 63%. Figures from a single report do not change. Windows' figures should be recomputed if
they merged reruns limited with `--cases` after a full run.

Hand checks of a mutant must run under the oracle's environment (`oracle.env_for`): outside
it some commands (`-colors` on CMYK) give different output from run to run, and three
`SetImageType` cases added on that evidence killed nothing (replaced in 0d0043cc1).

## Rounds for stream, signature, quantize and resource (Windows, 2026-10-02, evening)

Gated with `gate.py` as of 698cf5fa7 (a kill stands when reports are merged). Re-gating every
Windows file with it gave the same figures as the merge used above. Each family
`selfcheck --repeat 8`: 0 nondeterministic; the whole catalogue, 11,116 cases,
`--repeat 2`: 0 nondeterministic.

| File | Family, cases | Adjusted before | After | Below 80% after |
| --- | --- | ---: | ---: | --- |
| `stream.c` | `stream`, 56 more | 69% | **85%** | `QueueAuthenticPixelsStream`, `ValidatePixelCacheMorphology`, accessors no case calls |
| `signature.c` | `signature`, 6 | 69% | **76%** | `SignatureImage` 76%, `TransformSignature` 73%, `FinalizeSignature` |
| `quantize.c` | `quantizegap`, 17 | 74% | **81%** | `PosterizeImage` 50%, `KmeansImage` 73%, `RemapImage(s)`, small helpers |
| `resource.c` | `resource`, 7 | 81% | **94%** | `AcquireUniqueFileResource` 56%, `AsynchronousResourceComponentTerminus` |

- **`stream.c`:** `magick stream` with maps BGRA and BGRP (their own fast paths) and RO
  and GI (the generic loop's opacity and intensity) at every storage type:
  `StreamImagePixels` 79% to 99%. In `verdicts.json`, 12 `unobservable` in the destroy
  paths (they only change whether buffers are freed, or log with logging off) and 1
  `unresolved` (a heap buffer freed with `munmap`). `ValidatePixelCacheMorphology`'s
  mutants mostly force a needless reallocation; a stream whose frames change geometry
  might kill some, not tried.
- **`signature.c`:** `%#` of small images whose hashed length ends at 56 or 60 mod 64,
  where `FinalizeSignature` needs an extra padding block (every catalogue image ended
  below 56). One kill. In `verdicts.json`, 5 `unobservable` (memset sizes that write
  zeros over bytes set right after or past the block, and a digest word never read) and
  1 `unresolved` (the boundary at 55 mod 64: image signatures hash multiples of 4 bytes,
  random.c's lengths unchecked).
- **`quantize.c`:** `-verbose -colors 16 info:` (the quantization error,
  `GetImageQuantizeError` 0% to over 80%), posterize with dithering and per channel,
  k-means with iterations and seed colours, Floyd-Steinberg on alpha, CMYK and gray: 58
  kills.
- **`resource.c`:** `-list resource` under a time limit of whole years, months, weeks,
  days, hours, minutes and seconds (a `policy.xml` per case; `-limit` before `-list` is
  rejected): `FormatTimeToLive` 0% to 100%. In `verdicts.json`, 5 `unobservable` (Resource
  event logging, a retry counter, a discarded result) and 1 `unresolved` (an unfilled
  temporary-name template, which fails only with two temporary files at once). Left: the
  fallback when creating a temporary file fails (7 mutants, unreached), and the terminus
  run at abnormal exit.

### Two more rounds: quantize and distort (Windows, 2026-10-02, evening)

- **`quantize.c`, family `quantizegap2` (12 cases):** `+dither -posterize` on truecolour,
  palette and alpha images (every posterize case had dithered, so `PosterizeImage`'s plain
  loop and colormap branch never ran), `-kmeans` with fewer seed colours than clusters,
  `-verbose -kmeans`, and `-remap`/`+remap` over a sequence. 39 kills: adjusted 81% to
  **85%**, 35 of 47 functions at 80%. `PosterizeImage` 50% to 76%; `RemapImages` stays at
  20% (a remap of a sequence does not go through it from the command line).
- **`distort.c`, family `distortgap` (47 cases):** `-verbose` for every method (the
  coefficients printed as `-fx`; only Polynomial had it), `+distort` for every method,
  `distort:scale` 2 and 0.05, and a perspective past the horizon. 108 kills: adjusted 74% to
  **83%**; `DistortImage` 62% to over 80%. Below 80%: `GenerateCoefficients` 69%,
  `RotateImage` 75%, `MagickRound` 50%. `resample.c` 1 more kill (74%).
- **`fx.c`, family `fxgap2` (70 cases):** 35 `-fx` expressions on an image with alpha and
  on CMYK, with granite second: `!=`, `<=`, `>=`, `||`, `!`, `jinc`, `clamp`, `drc`,
  `squish`, `++` on a user symbol, the channel symbols `a b c g k m o r y`, hue,
  saturation, lightness and intensity on `p{}` and `p[]` lookups (also of `u[1]`, `v`,
  `s`), the loops and `printsize`. 59 kills: adjusted 70% to **74%**, `ExecuteRPN` 59% to
  71%, 34 of 64 functions at 80%.
- **`cache.c`, family `cachegap` (5 cases):** MPC written and read back for four kinds of
  image (`PersistPixelCache`, run only for MPC, 0% to 33%: its attach path stays open),
  and an MVG drawing under a mask, which did not reach `MaskPixelCacheNexus`. 5 kills, 78% to
  79%. Out of reach: `ReadPixelCacheMetacontent` and `WritePixelCacheMetacontent` (89
  mutants), since nothing on the command line gives an image metacontent.
- **`xml-tree.c`, family `xmlgap` (3 cases):** a `policy.xml` with nested, circular and
  undefined parameter entities in its DOCTYPE did not reach `ValidateEntities`. The file
  stays at 77%, and every mutant left is in a function no case calls: `XMLTreeInfoToXML`,
  `XMLTreeTagToXML` and `SetXMLTreeContent` are called only from MagickWand's drawing wand,
  `AddPathToXMLTree` and `CanonicalXMLContent` from nowhere, `ValidateEntities` by a route
  not found.
- **`color.c`, family `colorgap` (6 cases):** `-list color`, and `%[pixel:]` of CMYK, Oklch,
  HDRI and colours not exact at 8 bits. 24 kills: adjusted 78% to **85%**, 16 of 21
  functions at 80%. Below: `IsSVGCompliant` 46%, `GetColorList` (not reached by `-list
  color`), and `IsEquivalentImage`, `IsEquivalentAlpha`, `IsEquivalentIntensity`, which
  nothing outside color.c calls.
- **`composite.c`, family `texturegap` (5 cases):** `tile:` with `-tile-offset` for an
  opaque texture and one with alpha, and a seamless blend under `-verbose`. 14 kills:
  adjusted 82% to **83%**; `TextureImage` 73% to 92%, `SeamlessBlendImage` 52% to 77%.
  Under `-compose multiply`, `tile:` composes onto an uninitialised canvas (ORACLE.md,
  Known upstream issues), so the cases keep the default compose. `option.c` is set aside:
  the drivers reject an unknown option name before `GetCommandOptionFlags` sees it, so its
  hyphen, underscore and `|` branches look unreachable from the command line.
- **`distort.c`, family `distortargs` (25 cases):** argument counts the distort table never
  gave (Affine with one and two points, Arc with one to four arguments, Polar and DePolar
  with each optional argument, the -1 radius and too many, Barrel with three and eight,
  out-of-range fields of view, too few points for Perspective and Bilinear,
  `shepards:power`), and Arc rotations at `MagickRound`'s tie. 56 kills: adjusted 83% to
  **88%**, `GenerateCoefficients` 69% to 84%. In `verdicts.json`: `RotateImage`'s two
  `shear.x` mutants are `equivalent` (it is used only as `fabs(shear.x) < MagickEpsilon`),
  and `MagickRound`'s `<` to `<=` is `unresolved` (it differs only on an exact .5). 11 of
  12 functions at 80%; **`distort.c` is one mutant short of trusted** (`MagickRound`,
  75%).
- **`fx.c`, family `fxgap3` (18 cases):** colour constants in an expression (`srgb`, `rgb`,
  `hsl`, `cmyk`, `srgba`, `gray`, `device-gray`, a named colour, a missing `)`),
  `page.width` and `page.height`, and channel qualifiers on `u`, `v`, `u[1]` and `s`. 41
  kills: adjusted 74% to **76%**; `GetConstantColour` 20% to 90%, `MaybeXYWH` 23% to 100%,
  `GetChannelQualifier` 47% to 53%. 36 of 64 functions at 80%.
- **`matrix.c`, family `matrixgap2` (2 cases):** `-hough-lines` under a `max-memory-request`
  of 256 bytes did not move the matrix to disk either: `SetMatrixExtent` stays unreached. No
  new kills. In `verdicts.json`, 15 for `GaussJordanElimination`: the copy-back loops are
  `unobservable` (every caller in distort.c frees the matrix at once and reads only the
  solution vectors); the pivot swaps are `unresolved`. Every caller solves least-squares
  normal equations, symmetric positive semidefinite, so in exact arithmetic the largest
  element of the unreduced block is on its diagonal and is found first; rounding in a
  nearly singular system is not ruled out. Adjusted 70% to 71%.
- **`quantize.c`, family `quantizegap3` (16 cases):** `-dither None -posterize`, gray to two
  and eight colours, `-treedepth 3`, and a 600x600 noise image. No new kills: `PruneLevel`
  and `IntensityCompare` stay unreached, so the routes in are not these. 85%. Its
  600x600 noise case was removed afterwards: `+noise Random` is not reproducible at that
  size (ORACLE.md, Known upstream issues).
- **Routes checked first: `tools/oracle/reach.py`.** Several rounds missed because the route
  into a function was guessed. `reach.py FUNC -- args` runs one command on the coverage
  build under the oracle's environment and says whether the functions ran. It showed that
  `IntensityCompare` is reached (its survivors were "unmatched", misread as unreached)
  and that `PruneLevel` needs a deep colour tree. That path turned out not to be
  reproducible: `hald:8 -colors 64` gives two different images (ORACLE.md), so
  `PruneLevel` stays untested.
- **`quantize.c`, family `quantizegap4` (6 cases):** gray quantization to eight colours
  written as palette MIFF and printed with `-verbose`, so the colormap order shows. No
  kills: `IntensityCompare`'s five mutants survive even so, perhaps because the gray
  colormap arrives sorted. Open.
- **`montage.c`, family `montagegap` (5 cases):** `-tile x2`, `x3`, `2x`, `1x1` and `+0+0`
  (the family had `3x` and `2x2` only). 3 kills: adjusted 78% to **80%**,
  `GetMontageGeometry` 75% to 100%.

## feature.c: trusted (Windows, 2026-10-02)

Line coverage (the coverage build, `llvm-cov show` on one function) showed why
`RenderHoughLines`' resolution scaling never ran: `HoughLineImage`, its only caller, passes a
fresh `AcquireImageInfo()` with no density, so the resolution is always 0 and the division
cannot run, even under `-density`. Its two mutants are `equivalent` (`verdicts.json`).

**`feature.c`: adjusted 88%, every function at 80% or more, trusted.** Merged over the full
run, the rounds `feature` and `matrix`, and the refresh. With 37 `equivalent` in the dead `Q`
block and 2 in `RenderHoughLines`. Open survivors, by line (unmatched, or on unreached
lines):

- `GetImageFeatures` (53): 669, 769, 771, 773, 774, 776, 777, 796-806 (allocation-failure
  cleanup), 844-848, 987, 1181, 1187, 1313, 1314, 1382, 1396, 1399, 1413-1416, 1503,
  1506, 1515, 1518, 1552-1583 (the information measures' alpha and black channels),
  1700, 1706.
- `HoughLineImage` (18): 1885, 1923, 1953, 1955, 1977-1987, 2025, 2033, 2070, 2083, 2089,
  2092.
- `CannyEdgeImage` (13): 378, 379, 391, 393, 396, 403, 406, 505, 507, 520, 521, 563, 565.
- `MeanShiftImage` (9): 2261, 2266, 2268, 2279, 2310, 2330, 2332.
- `RenderHoughLines` 1813, 1814 (unreached); `IsAuthenticPixel` 153; `TraceEdges` 221.

## composite.c: trusted (Windows, 2026-10-02)

Two last rounds, each route checked with line coverage first:

- **`composegap` (8 cases):** `compose:clip-to-self=false` reaches `CompositeOverImage`'s
  virtual composite, but every earlier case composed an opaque source, which that path leaves
  unchanged. With a cropped piece of `rose_alpha` as the source it sets the alpha of every
  uncovered pixel. `CompositeOverImage` 79% to 89%.
- **`composegap2` (3 cases):** `SeamlessBlendImage`'s residual is 0 from the first iteration
  on (one iteration and five give the same image; it looks as if the relaxation does
  nothing, worth reporting upstream). So with any threshold above 0 the loop stops at once.
  A threshold of 0 runs every iteration, and `-verbose` prints a residual per tick:
  `SeamlessBlendImage` 77% to 96%.

**`composite.c`: adjusted 76% (this morning) to 84%, all 13 functions at 80% or more,
trusted.** `selfcheck --repeat 8` over each family: 0 nondeterministic. Open survivors, by
line (unmatched, or on unreached lines):

- `CompositeImage` (176): 1492, 1499, 1512, 1536, 1538, 1580, 1610, 1623, 1625, 1652, 1661,
  1683, 1787, 1820, 1830, 1911, 1912, 1921, 1948, 1954, 1959, 1964, 1991, 2025, 2055, 2057,
  2059, 2063, 2064, 2066, 2100, 2174, 2250, 2345, 2354, 2355, 2458, 2465, 2473, 2478, 2534,
  2578, 2581, 2583, 2586, 2588, 2591, 2617, 2620, 2630, 2632, 2638, 2646, 2649, 2661, 2664,
  2674, 2676, 2729, 2799, 2816, 2820, 2919, 2936, 2937, 2938, 2941, 2942, 2943, 2957, 2973,
  2975, 2995, 3003, 3013, 3020, 3024, 3034, 3035, 3036, 3045, 3051, 3116, 3130, 3141, 3149,
  3204, 3205, 3208, 3292, 3316, 3319, 3320, 3325, 3327, 3331, 3339, 3342, 3347, 3355, 3369,
  3371, 3375, 3393, 3394, 3397, 3479, 3499, 3504, 3507, 3511, 3516, 3518, 3524, 3529, 3548,
  3549, 3550, 3553, 3554, 3563, 3564, 3567, 3570, 3573, 3577, 3596, 3610, 3612
- `CompositeOverImage` (8): 988, 1042, 1043, 1044, 1060, 1124, 1138, 1140
- `SaliencyBlendImage` (4): 1227, 1252, 1254
- `TextureImage` (3): 3720, 3775, 3807
- `BlendRMSEResidual` (2): 864, 865
- `BlendMeanImage` (1): 789
- `SeamlessBlendImage` (1): 1388

### Late rounds: fx qualifiers, opacity quantums (Windows, 2026-10-02)

- **`fx.c`, family `fxgap4` (7 cases):** an image attribute with a virtual channel
  (`mean.hue`, `maxima.intensity`, `minima.lightness`) is an error that line coverage showed
  no case reached; `u[1].mean.saturation` a related one in `GetFunction`. 11 kills;
  `GetChannelQualifier` 53% to 60%, `fx.c` 76%.
- **The raw single-channel writers test an error, not a channel.** `WriteRAWImage` picks the
  channel from the input's format, so from a MIFF every `r:`, `g:`, `b:`, `a:`, `o:`, `k:`
  write fails (ORACLE.md, Known upstream issues). The catalogue's raw channel cases read
  MIFF, so `ExportOpacityQuantum` and `ImportOpacityQuantum` were not reached by them.
  `reach.py` found them reached only through RGBO and BGRO with `-interlace line`.
- **`quantum-import.c`, `quantum-export.c`, family `quantumgap5` (9 cases):** RGBO and BGRO
  with `-interlace line` at depths 8, 16, 32 and floating point (BGRO float left out). 32
  kills: `quantum-import.c` 61% to **63%**, `quantum-export.c` 68% to **70%**;
  `ImportOpacityQuantum` 13% to 47%, `ExportOpacityQuantum` 12% to 56%.
- **Family `quantumgap6` (16 cases):** the same at depths 1, 4, 10, 12 and 24 for RGBO,
  BGRO and BGR, and 24-bit floating point for RGBO. 21 kills: `quantum-import.c` 63% to
  **65%**, `quantum-export.c` 70%; `ImportOpacityQuantum` 60%, `ExportOpacityQuantum` 64%.
  `ImportBGRQuantum` and `ExportBGRQuantum` did not move: their 24 unreached mutants each are
  not depth branches. Line-interlaced BGRO is written at the size of BGR, as if its opacity
  were left out; not traced yet.
  The BGR functions' unreached mutants are the unpacked-sample paths (`pack ==
  MagickFalse`) and a 32-bit-quantum variant: only the CIN coder turns packing off, and
  only for RGB, so they are out of reach from the command line.

## signature.c: trusted (Windows, 2026-10-02)

Three rounds (`signature`: messages ending past 56 bytes mod 64; `signaturegap2`: `%#` under
a read mask, no kills) and verdicts read from the source. `FinalizeSignature`'s memset sizes
and digest word are `unobservable`, as noted above. `TransformSignature`'s and
`SignatureImage`'s big-endian loops are `unobservable` (5): `lsb_first` follows the host's
byte order, so on a little-endian host they never run. One more word loaded into `W[16]`,
which the schedule overwrites, is `equivalent`.

**`signature.c`: adjusted 69% (yesterday's run) to 82%, every function at 80% or more,
trusted.** Out of reach: `GetSignatureBlocksize` (1 mutant), an API function nothing calls.
Open survivors:

- `SignatureImage` 507 (2), 521 (2): the size of the row buffer and of its hashed length
  (channels times columns) with `*` to `/`; why no `%#` case shows them is not traced.
- `UpdateSignature` 791 (unreached: the 64-bit length carry, past 2^29 bytes), 798.
- `FinalizeSignature` 240 and `TransformSignature` 701, `unresolved` (`verdicts.json`).

## magick.c: trusted (Windows, 2026-10-02)

Every mutant in the functions the command line reaches is killed (adjusted 81%). The 22 left
are in three functions out of reach, checked with `reach.py` and the callers:
`MagickSignalHandler` (9; runs only when a signal arrives), `GetMagickList` (8; called only
by the X11 widget code and MagickWand) and `GetImageMagick` (5; called by nothing).
**Trusted**, with those three written down as out of reach.

## exception.c: trusted (Windows, 2026-10-02)

The module-policy case reaches `InheritException` (`reach.py`), and its two mutants were run
by hand on the Mull build (the mutant's id as the environment switch) for `gif:` and plain
reads under the policy: output identical. The policy error `ReadImage` inherits has already
been thrown into the command's exception by `SetImageInfo`'s lookup of the same coder, and
`ThrowException` drops duplicates, so both are `unobservable` (`verdicts.json`). **Adjusted
98%, trusted.** Out of reach: `SetErrorHandler` (1 mutant), called only by the X11 display
and animate code. No other survivor is open.

## histogram.c: trusted (Windows, 2026-10-02)

`IsPaletteImage`'s boundary at `MaxColormapSize`: line coverage showed that neither `%[type]`
nor `identify -verbose` calls it (the caller in attribute.c is `GetImageType`, which only
MagickWand uses). `-colors N` on a palette image of at most N colours does, through
`CompressImageColormap` (operation.c). One case (family `histogramgap3`): a palette of
exactly 65,536 colours, quantized to 65,536 again; reproducible, 0.03 s, no tree pruning. The
boundary mutant, run by hand on the Mull build first, changed the output, and the round
killed it. **Adjusted 94%, all 15 functions at 80% or more, trusted.** Open survivors:
`CheckImageColors` 728, 755, 778; `UniqueColorsToImage` 1208 (unreached), 1211, 1212;
`GetNumberColors` 1115 (unreached), 1122; `ClassifyImageColors` 318.

### stream.c, second round (Windows, 2026-10-02)

Family `streamgap2` (5 cases): `magick stream` from PNG and TIFF (which reach
`GetAuthenticPixelsStream`; every earlier case read MIFF), and a GIF of two frame sizes. 2
kills; 85%. `ValidatePixelCacheMorphology`'s 10 mutants, run by hand over four two-frame
sequences (growing, shrinking, gaining alpha, changing colorspace), never differed, so they
are `unresolved` (`verdicts.json`). The other functions below 80% are the stream cache's
virtual-pixel accessors, which only a coder reading virtual pixels while streaming would
call; none of nine formats probed does. Not trusted.

## timer.c and registry.c: trusted (Windows, 2026-10-02)

An earlier version of this section called `timer.c` trusted on a wrong reading: that the date
precision came only from the environment variable `MAGICK_DATE_PRECISION`, so
`FormatMagickTime`'s four survivors could not show. It can also be set with `-define
registry:date:precision=N` (registry.c calls `SetMagickDatePrecision`), which cuts the
PostScript CreationDate to N characters. Those verdicts were removed, and 7 cases added
(family `timergap`): PostScript under precisions 0, 4, 10, 24, 25 and 26 (the timestamp is 25
characters), and a registry string defined and removed again. 6 kills over the two files.
In `verdicts.json`: `FormatMagickTime`'s reading of the variable when it is unset gives the
same precision 0 (`unobservable`), and its cut at a precision equal to the length is
`equivalent`; `StopTimer` and `GetUserTime` change only masked times (`unobservable`);
`SetImageRegistry`'s two mutants are in the `ImageInfoRegistryType` branch, which nothing
outside registry.c uses (`unobservable`).

- **`timer.c`: adjusted 63% to 86%, trusted.** Out of reach: `ContinueTimer` (4), called only
  by `-bench -duration`, whose output carries an unmasked rate, and by the logger.
- **`registry.c`: adjusted 69% to 92%, trusted.** Out of reach: `RemoveImageRegistry` (2),
  called by nothing outside registry.c.

No other survivor is open in either file.

## monitor.c: trusted (Windows, 2026-10-02)

`SetImageProgress` records its last message (percentage, tag and file) as the artifact
`monitor:progress`, which `%[monitor:progress]` prints and no case printed. Three cases (family
`monitorgap`: `-monitor` with `-negate`, `-resize` and `-blur`) killed 5 of its 6 survivors;
the sixth is the semaphore's lazy initialisation, excused by `classify.py`. **Adjusted 38% to
100%, trusted**, with no open survivor.

### resource.c: one function short (Windows, 2026-10-02)

`AcquireUniqueFileResource` (56%) is the one function below 80% that is not API only. Its 7
unreached mutants are the fallback after `mkstemp` fails. The oracle sets
`MAGICK_TEMPORARY_PATH` to the case directory, and a `temporary-path` policy does not override
it (line coverage: `mkstemp` succeeded on every call under such a policy), so no case can make
it fail. The path is reachable in real use (an unwritable temporary directory), so it is not
excused: `resource.c` stays at 94%, not trusted, with this written down.

### CloneMontageInfo's null test, resolved (Windows, 2026-10-02)

`CloneMontageInfo`'s first test, `if (montage_info == NULL) return(clone_info);`, mutated to
`!=`, should crash on the NULL the montage command passes, but changed nothing when run by hand
(the procedure checked against three killed mutants of `MontageImageList`, which did change
the output). On the mutated path `montage_info` is dereferenced at once, so the compiler may
take it to be non-NULL and fold the test: `equivalent` as compiled, as the Mac found for
NULL-pointer mutants (d50e759cc). The six field copies after it run only for a non-NULL
`montage_info`, which only MagickWand and the X11 display pass: `unobservable`.

## montage.c: trusted (Windows, 2026-10-02)

Rounds `montagegap` (tile counts, `GetMontageGeometry` to 100%) and `montagegap2` (frames
picked out of order, which `MontageImageList` sorts by scene: `SceneCompare` to 100%), and the
`CloneMontageInfo` verdicts above. **Adjusted 78% to 85%, every function at 80% or more,
trusted.** Open survivors: `MontageImageList` 441, 443, 445, 446, 643, 645, 865 (unreached),
505, 516, 518, 528, 559, 577, 580, 595, 599, 601, 605, 612, 652, 678, 712, 730, 757, 758,
844, 845, 853, 870.

## morphology.c: trusted (Windows, 2026-10-02)

Four rounds, routes checked first: `morphgap` (`convolve:scale` with a blending factor on
single and multi-kernel lists, `UnityAddKernelInfo`; 6 kills), `morphgap2`
(`-define debug=true`, the artifact `MorphologyApply` reads to print changes per iteration
and stage, with iterations to convergence and multi-stage methods; 28 kills), `morphgap3`
(`morphology:showKernel` for forty built-in kernels and arguments no case built; 107 kills)
and `morphgap4` (`MorphologyImage`'s `convolve:bias` and `morphology:compose` defines; 2
kills). `selfcheck --repeat 8` over each family: 0 nondeterministic.

**`morphology.c`: adjusted 81% to 88%, every function at 80% or more, trusted.** Out of
reach: `ZeroKernelNans` (5), which nothing calls. Open survivors, by line:

- `AcquireKernelBuiltIn` (45): 1065, 1067, 1117, 1121, 1154, 1188, 1195, 1288, 1308, 1315,
  1453, 1537, 1548, 1573, 1582, 1586, 1587, 1606, 1630, 1650, 1669, 1697, 1705, 1706, 1707,
  2080, 2098, 2116, 2139, 2159
- `MorphologyPrimitiveDirect` (24): 3351, 3363, 3365, 3382, 3394, 3396, 3407, 3424, 3425,
  3426, 3515, 3530, 3546, 3559, 3561, 3571, 3572, 3588, 3589, 3590, 3596
- `MorphologyPrimitive` (22): 2746, 2749, 2767, 2770, 2780, 2969, 2971, 2999, 3001, 3034,
  3036, 3040, 3042, 3052, 3074, 3103, 3152, 3166, 3189, 3191
- `RotateKernelInfo` (19): 4245, 4248, 4276, 4278, 4286, 4350, 4351, 4361, 4364, 4370, 4394
- `ParseKernelArray` (8): 270, 282, 296, 297, 339, 349, 362
- `MorphologyApply` (6): 3668, 3669, 3737, 3926, 4035, 4037
- `ParseKernelName` (5): 408, 455, 457, 472
- `ScaleKernelInfo` (4): 4564, 4585, 4591, 4592
- `AcquireKernelInfo` (2): 518, 537
- `CalcKernelMetaData` (1): 2470
- `MorphologyImage` (1): 4156
- `ShowKernelInfo` (1): 4660

## quantize.c: trusted (Windows, 2026-10-02, night)

Six rounds, each route checked with `reach.py` or the line probe and each case hand-run
against its mutants before the round (`~/mutcase.py`, which runs a mutant as `mutate.py`
compares it):

- `quantizegap5`: MSL `<map image="id"/>`, the one route that gives `RemapImages` a reference
  image (`+remap` quantizes the list instead). `RemapImages` 20% to 80%.
- `quantizegap6`: `PruneLevel` runs only once the colour tree passes `MaxQNodes` (266817)
  nodes, which needs `-treedepth 8` (for 64 colours `QuantizeImage` picks depth 4) and about
  360,000 distinct colours: 600x600 colour noise, opaque and with noisy alpha. A 300x300 noise
  palette for `-remap` makes `RemapImage` reduce its reference. `PruneLevel` 0% to 100%.
- `quantizegap7`: `-quantize gray -colors 2`, undithered. `+dither` has to come *before*
  `-colors`: a setting applies only to later operators, and several earlier probes written
  as "undithered" were dithered. A gradient, logo and wizard leave the brighter colormap entry
  first (`DefineImageColormap` lists a parent that absorbed pruned children after its
  surviving child), which the monochrome step tests.
- `quantizegap8`: `-verbose` before `-colors` sets `measure_error`, and `-verbose info:` prints
  the quantize error (25 kills).
- `quantizegap9`: `rgb(127.5,63.75,191.25)` is an exact .5 tie for `-posterize 2` and `3` in
  HDRI (`MagickRound`), `-monitor` over the reduction, `rose_alpha` with `-quantize gray`.
- `quantizegap10`: dithered `-posterize 1` and `17` (the dither path is for 2 to 16 levels) and
  `-monitor` over posterize.

`selfcheck --repeat 8` over each family: 0 nondeterministic. 25 verdicts, among them:
`IntensityCompare` (5, equivalent: the colormap `SetGrayscaleImage` sorts is rebuilt by
`AssignImageColors`), `QuantizeErrorCompare` (4, equivalent; one of them only because glibc's
`qsort` is a merge sort that treats 0 and -1 alike), `PosterizeImage`'s colormap block (7,
`QuantizeImage` rebuilds it from the posterized pixels) and its map's `(r+v)/L` (still a
permutation of every level combination, checked for 2 to 16 levels and 1 to 5 channels),
and `DestroyQCubeInfo`'s frees (3, unobservable: leaks only).

The `quantizegap6` round froze WSL: mutants that stop pruning grew the tree until six of them
filled 8 GB. `mutate.py` now takes `ORACLE_MEM_GB=N` (off unless set), an address-space cap per
run. A capped mutant fails to allocate and is killed, as it would be at the timeout.

**`quantize.c`: adjusted 85% to 91%, reach 100%, every function at 80% or more, trusted.**
Open survivors, by line:

- `FloydSteinbergDither` (16): 1589, 1608, 1609, 1610, 1612, 1624, 1625, 1626, 1628, 1631,
  1632, 1633, 1635, 1680, 1688, 1710
- `KmeansImage` (15): 2574, 2586, 2628, 2644, 2646, 2753, 2758, 2760, 2794, 2795, 2805, 2832
- `SetGrayscaleImage` (7): 4010, 4015, 4067, 4075, 4078, 4083, 4089
- `RiemersmaDither` (5): 1758, 1760, 1762, 1765, 1814
- `ClassifyImageColors` (4): 818, 930, 1017, 1029
- `GetImageQuantizeError` (3): 2308, 2314, 2320; `KmeansMetric` (3): 2476, 2498;
  `QuantizeImage` (3): 3314, 3331, 3351; `QuantizeImages` (3): 3433, 3462, 3483
- `AssignImageColors` (2): 653 (a one-colour image at luma exactly `QuantumRange/2`; no input
  found), 658; `DefineImageColormap` (2): 1320; `GetQCubeInfo` (2): 2109, 2111
- one each: `DestroyPixelTLS` 1457, `DestroyKmeansTLS` 2421, `PruneChild` 3148,
  `QuantizeErrorFlatten` 3546, `Reduce` 3607, `ReduceImageColors` 3721, `RemapImages` 3878

## Overnight refresh and case rounds (Windows, 2026-10-03, interim)

A refresh (`refresh1003`) reruns every Windows file's survivors and no-coverage mutants
against the whole catalogue as of 59cb39e1f (11748 cases, capped at 1500 per mutant), with
`ORACLE_MEM_GB=2`. Done so far, adjusted, before and after: **cache.c 79% → 82%** (31 kills),
**fx.c 76% → 81%** (27), **color.c 85% → 86%**; distort.c unchanged at 88% (no kills among its 155; `MagickRound`
still the one function short: an Arc distortion at -90 degrees reaches its .5 tie, but the
mutant only shifts the angle by a whole turn), quantize.c unchanged (trusted, 91%).

A capped refresh may sample a new family only in part, so the families written tonight get
uncapped case rounds of their own after it (`~/after-refresh3.sh`, `~/after-refresh3c.sh`,
then `~/queue-runner.sh` reading `~/round-queue.txt`). Every case below was hand-run against
the survivors it targets first (`~/mutcase.py`), and run 8 times for determinism:

| family | file | what | hand-run kills |
|---|---|---|---|
| `fxgap5` | fx.c | the RPN dump (`fx:debug`) over compound assignments, symbols, grown tables, 99/100-letter tokens | 9 |
| `fxgap6` | fx.c | jinc, SI and binary number prefixes, lightness/intensity qualifiers, printsize, while, `-monitor -fx` | (lines reached) |
| `fxgap7` | fx.c | gcd at the 0.001 cut-off and of equal arguments, seeded rand(), a sum nested 120 deep | 5 |
| `fxgap8` | fx.c | ImageStat's six statistics, composite and red, `-fx` and `%[fx:]` | 10 |
| `fxgap9` | fx.c | `-fx @file`, `@` alone, `?` with no `:`, standalone `depth.r`/`depth.hue`, `0.5(0.5)`, `0.5}` | 10 |
| `fxgap10` | fx.c | equal-operand comparisons, shifts by 64 and fractions, `~` exact in a long double, sign(0), airy, signed zeros | 21 |
| `fxgap11` | fx.c | image references per image of a list (`pfx->ImgNum` 1), `u[1-1]` (a constant 0 compiles to `u0`), `u[1].p`, HSL symbols alone, nesting at the 600 limit, qualifier errors, if(), `$zz`, artifacts as variables | 36 |
| `cachegap2` | cache.c | named MVG masks (`push mask m1` unquoted never set one), disk caches cloned, a three-image MPC | 8 + masks |
| `matrixgap3` | matrix.c | the hough accumulator black, white and one line; the matrix mapped from a file (`-limit memory 0` alone) | 14 claimed; its round: 31 killed, but not SetMatrixExtent's (see below) |
| `resamplegap` | resample.c | `resample:verbose`'s weighting table, a squeezed perspective | 7 claimed; its round: 5 killed (adjusted 75% to 77%) |
| `quantumgap7` | quantum-import/export.c | min-is-white polarity at every depth, 7-pixel widths for packed depths in 13 layouts, palette with alpha | (round pending) |
| `blobgap` | blob.c | ReadBlobString's newline stripping through `text:` | 3 |

Verdicts tonight (all with the reasoning in `verdicts.json`): fx.c's operator-table ranges
(the sentinels `fNull`, `aNull`, `sNull`, `rNull` are never an element's operator),
`rIfNotZeroGoto` (never generated: a dead case), `ResolveTernaryAddresses`' `:`-without-`?`
branch (`addr_colon` is set only after `addr_query`), table growth and leaks;
ClonePixelCacheOnDisk's sendfile tests (both paths copy the whole file); ClampUpAxes' ties;
IsSVGCompliant's black test. One verdict pushed and withdrawn the same night: FxGcd's `x <= y`
is not equivalent (equal arguments swap for ever), and `gcd(3,3)` now kills it.

Out of reach, written down rather than excused: ClonePixelCacheOnDisk's read/write loop
(runs only if `sendfile` fails or the cache is 2 GiB or more; line probe: never on Linux);
ImportCbYCrYQuantum (only a DPX 4:2:2 file, which the DPX writer never writes); InitFx's and
AcquireFxInfoPrivate's clean-up after an allocation failure; metacontent in cache.c (set only
through the API). ResamplePixelColor's virtual-pixel shortcuts survive under eleven
virtual-pixel methods with a viewport 50 px past the image: the shortcut's single colour and
the full EWA agree there, but that is not proven for the mutants that widen the shortcut, so
they stay open.

**After the first two batches of case rounds (04:25), adjusted:** fx.c **92%** (76% at dusk; fxgap5's round killed 114, fxgap8's 44, fxgap11's 56, fxgap10's 29), cache.c 83%, resample.c 77%, matrix.c 73%, quantum-import.c 65% → 69% (quantumgap8's hand-built files: 105 killed in its round), quantum-export.c 70% → 72%, token.c 78%. (Figures of 57-60% for quantum-import.c given earlier tonight were wrong: the gate globbed `mutation-*-quantum-import.json`, which also takes the operator-set trial's `mutation-trial-*` reports and their 530 statement-deletion mutants; only colorspace.c also has trial reports. The regular sweep has 868 mutants.) fx.c's functions under 80% are now small: InitFx and AcquireFxInfoPrivate (clean-up after an allocation failure, out of reach), and one- or two-mutant functions (AddUserSymbol and PushVal: a table written one past its end before it grows, which only a memory checker would see; PopVal; TranslateStatementList; TopOprIsUnaryPrefix). quantum-import.c's remaining unreached mutants are in layouts and depths no reader feeds: BGRO as floating point (an upstream bug makes it nondeterministic), CMYKO (only SF3), CbYCrY (only DPX 4:2:2), palette with alpha below 8 bits (TIFF writes RGBA, MIFF uses 8 bits or more), and the 32-bit packed long-pixel path.

**Does the 1500-case cap hide killers? No, for these files.** `~/uncap3.sh` reran every survivor (merged over all reports) of fx, cache, color, resample, matrix, distort, stream, blob and quantize against every case that reaches its function, with no cap (reports `mutation-uncap3-<file>.json`): 0 kills among 115 + 55 + 15 + 60 + 68 + 155 + 69 + 127 + ... survivors. `~/uncap4.sh` does the same for fourteen more files; so far quantum-import (213), quantum-export (157) and token (15): 0 kills. The capped refresh and case rounds found what the catalogue can find; the survivors need new inputs or verdicts.

composite.c after the refresh: 83% → 84%.

**The refresh is complete (09:34, three instances).** Adjusted, every regular Windows file, with every report so far (the trial's excluded):

| file | adjusted |
|---|---|
| blob.c | 75% |
| cache.c | 82% (83 after its rounds) |
| cache-view.c | 36% (API) |
| color.c | 86% |
| colorspace.c | 90% |
| composite.c | 84% |
| distort.c | 88% |
| exception.c | 98% |
| feature.c | 88% |
| fx.c | 81% (92 after its rounds) |
| gem.c | 89% |
| histogram.c | 94% |
| linked-list.c | 40% (API) |
| magick.c | 81% |
| matrix.c | 73% |
| monitor.c | 100% |
| montage.c | 85% |
| morphology.c | 89% |
| option.c | 77% |
| pixel.c | 50% (API) |
| prepress.c | 87% |
| quantize.c | 91% |
| quantum.c | 94% |
| quantum-export.c | 72% |
| quantum-import.c | 69% |
| registry.c | 92% |
| resample.c | 75% (77 after its round) |
| resource.c | 94% |
| signature.c | 82% |
| splay-tree.c | 54% (API) |
| stream.c | 86% |
| timer.c | 86% |
| token.c | 78% |
| xml-tree.c | 77% (API) |

**A correction to the hand-run counts.** Until about 01:15, `~/mutcase.py` ran every ad-hoc command in one directory (`runs/hand/adhoc_1`), and two hand-runs at once overwrote each other's files. That happened between about 01:00 and 01:25, while a long resample probe ran beside the matrix, resample and some fx probes, and produced false kills (the matrix SetMatrixExtent kills, and one stray distort kill, which first looked like a nondeterministic Arc distortion). mutcase now uses a directory per process. The case rounds are what count; the table's hand-run figures are replaced by round results as the rounds finish.

Tooling: `mutate.py`'s `ORACLE_MEM_GB` (above). A pull of the WSL clone between a round's
index step and its mutation run makes the casemap stale and the round refuse to start
(cachegap2's first round died so); new families are now checked for determinism from a
scratch copy of `cases.py` instead.

## The Mac's morning case rounds (2026-10-03)

Hand-checked cases, then probes p47 to p53 (`mutation-probe-p4x-*`, `-p5x-*`), moved the Mac's
untrusted files (adjusted; every figure merges ERDC's reports and the probes):

| File | Before (07:20) | Now (09:15) | What holds it back |
| --- | ---: | ---: | --- |
| transform.c | 82% | **85%, trusted** | |
| layer.c | 89% | **92%, trusted** | |
| version.c | 70% | **80%, trusted** | |
| property.c | 61% | 86% | `GetICCProperty` 75%: its last four need an ICC text tag over 4096 bytes |
| string.c | 67% | 85% | five functions, each held by overflow-only sizes or unreachable tails |
| draw.c | 71% | 79% | `DrawGradientImage` (reflect and repeat spreads are API-only), `DrawBoundingRectangles` (aborts) |
| image.c | 66% | 78% | `AcquireImage` and `CloneImageInfo`: the command line overwrites what they set |
| locale.c | 69% | 77% | `IsLocaleTreeInstantiated`: environment fallbacks no case can set |
| utility.c | 71% | 74% | `AcquireUniqueSymbolicLink`: only the inkscape delegate reaches it |
| annotate.c | 66% | 71% | text metrics no output shows, and kerning the corpus font lacks |
| policy.c | 56% | 61% | `IsPathContainsSymlink`: a case cannot make a symlink |
| profile.c | 41% | 52% | `ProfileImage`: ICC transforms need two ICC profiles (see below) |

**What would lift these further is not more cases but three owner decisions:** a C driver for
API-only code (`AcquireImage`'s transfer, the reflect and repeat gradients, the read and
composite masks, `GetMimeInfo`, the policy and locale list functions); whether external
programs may run (inkscape for the SVG delegate, Ghostscript for `RenderPostscript`); and
adding `config/sRGB.icm` and `config/cmyk.icm` to `DECODE_FILES`, which would open
`ProfileImage` and the ICC transforms (it changes the frozen corpus on every machine, so it is
not done unasked).

**memory.c's three `max-memory-request` boundaries stay open.** A case's own policy.xml is
loaded, but `GetMaxMemoryRequestFromPolicy` raises any value below 16 MiB to 16 MiB, so an
allocation exactly at the limit needs a 16 MiB input (too large for a case file) or an image
whose pixel cache is exactly that size, where a refused allocation falls back to a disk cache
with the same output.

**The third is no longer needed (afternoon, 2026-10-03).** The cases now build their own ICC
profiles, ICC v2 with every byte below 0x80 so they fit text case files: matrix/TRC RGB and
kTRC gray display profiles, and lut16 profiles (two grid points, table values at most 0x7F7F)
for CMYK, Lab and XYZ. Little CMS accepts all five, so `ProfileImage` runs real transforms
between every pair of colour spaces it handles. Hand-run against mull-macx, they kill 41 of its
55 open mutants and `CompareStringInfo`'s status test; five more are leaks (verdicts). The
remaining nine are the low-precision path, which an HDRI build never takes, two translations
set to the 0.0 they already hold, the profile iterator's reset, and the `exif:ColorSpace`
checks when the same profile is applied again.

Two earlier verdicts were wrong: `GetMultilineTypeMetrics` and `RenderFreetype` mutants called
"a font metric that no output shows" are killed by a multi-line label (its width is the widest
line's) and by a label with descenders (`label:Ajg_`); the five verdicts are removed.
`macall` (an uncapped rerun of every open mutant of the untrusted files, verdicts included)
will find any other. Cases pushed after 8b0a004ab await a probe after `macall`.

## Behaviour found while writing cases (Mac, 2026-10-03)

The cases record ImageMagick as it behaves, bugs included: a refactoring must keep each of
these until someone decides to fix it on purpose (and then the case's baseline changes).

- **`-define draw:render-bounding-rectangles=true` aborts** (SIGABRT, status 134, no message)
  for every primitive drawn as a polygon, in the plain builds too. `DrawBoundingRectangles`
  therefore has no case; its 59 mutants are recorded as unresolved.
- **`-set intensity` never takes**: `SetImageProperty` parses it with
  `MagickIntensityOptions`, which has no table in `GetCommandOptionInfo` (only
  `MagickPixelIntensityOptions` does), so every value parses to -1.
- **`-set delay N<` takes the delay from sigma**, not rho: `10<` sets 0, `30x20<` sets 20.
- **`%[exif:#hhhh]` and `%[exif:@hhhh]` never return a value**: `GetEXIFProperty` advances its
  `property` pointer while parsing the hex digits and stores the tag under the empty name that
  is left, which only shows as a "read-only property" warning. `%[exif:!]` stores every tag
  under `#hhhh` or `@hhhh`, which a later `%[#hhhh]` in the same format reads back.
- **Round line caps on a polyline fail** (filled or not): `-draw "stroke-linecap round
  polyline ..."` ends in "non-conforming drawing primitive definition" and writes nothing; on a
  line they draw.
- **A locale.xml `<include>` never adds a message** (also with `policy.xml` and `mime.xml`, see
  above; a `type.xml` include works), and a case's `delegates.xml` is never read.
- **An MVG mask macro must have a quoted name** (`push mask "m1"`): unquoted, `mask m1` finds no
  macro and draws unmasked.
- **AcquireImage's settings transfer is overwritten on the command line**: `-delay`, `-density`
  and `-extract` before an image is read are applied again by `ReadImage` and
  `SyncImageSettings`, so only an API caller of `AcquireImage` could see its own transfer.

Hand-made inputs that made unreachable code reachable, all in `cases.py`: an 8BIM profile with
clip paths (every byte below 0x80, so it fits a text case file), 8BIMTEXT for the resource ids
whose bytes are not 7-bit, an EXIF block inside a 4x4 JPEG passed as `inline:` base64 (its tag
numbers are not 7-bit), IPTC records, an XMP profile, a BDF bitmap font (FreeType's
monochrome path), and MSL comments with `&#10;` for a newline that the line-by-line MSL reader
would otherwise turn into a space.

## Statement deletion on the Windows files (Windows, 2026-10-03, evening)

The owner's decision of 2026-10-02 (`HARNESS-SPLIT.md`) makes statement deletion
(`cxx_remove_void_call`) part of every file's operators. ERDC ran it for 32 of the 34
regular Windows files (reports `mutation-erdc-sdl-<file>.json` on `erdc-results`, measured at
3bce668de, which includes the night's case families); fetched here with
`tools/oracle/erdc/fetch-results.sh`. gem.c and prepress.c had no report: Windows builds them
itself (`mull-sdl-gp`, `cxx_default cxx_remove_void_call`, script `~/sdl-gp.sh`, reports
`mutation-sdl-<file>.json`).

Adjusted, with statement deletion counted (Windows, all reports merged, the trial's excluded):
quantum-import 66% (868 → 1398 mutants), quantum-export 72%, fx 89%, cache 80%, blob 71%,
stream 85%, matrix 71%, resample 77%, token 84%, option 75%, xml-tree 76%, color 82%,
distort 87%, composite 84%, feature 87%, morphology 86%, colorspace 90%, quantize 89%,
histogram 90%, montage 83%, signature 81%, quantum 90%, resource 89%, timer 75%, registry
84%, magick 60%, monitor 86%, exception 81%; the API-only files pixel 48%, splay-tree 55%,
linked-list 42%, cache-view 37%.

**Trust, per function, now counting statement deletion:** montage.c, feature.c and
composite.c stay trusted. Below the bar again until their new survivors are read:
colorspace.c (`GetImageColorspaceType`, one mutant, no case), registry.c
(`RemoveImageRegistry`), monitor.c (`MonitorComponentTerminus`), quantize.c
(`SetGrayscaleImage`, `QuantizeImages`, `PruneLevel`, `RemapImage`, `RemapImages`),
signature.c (`FinalizeSignature` and two one-mutant helpers), histogram.c
(`GetNumberColors`, `DestroyColorCube`, `DestroyHCubeInfo`), morphology.c
(`ScaleKernelInfo`, `UnityAddKernelInfo`, `ZeroKernelNans`), exception.c (eight functions,
most of them handler setters and genesis/terminus code), magick.c (seven: terminus, signal
handler, genesis, list functions), timer.c (six). Their survivors are read next, closest to
the bar first.

### Statement-deletion survivors: first verdicts, cases and uncapped reruns (Windows, 2026-10-03, night)

- **A local build with statement deletion** for every Windows file: `mull-sdl-win`
  (`~/build-sdl-win.sh`; instrumenting composite.c and distort.c takes about 2 GB per compiler,
  so `-j2` on an 8 GB WSL; `-j8` froze it). gem.c and prepress.c have no
  `cxx_remove_void_call` mutants at all, so they stay trusted.
- **Uncapped reruns of every statement-deletion survivor** (`~/night-sdl*.sh`, reports
  `mutation-sdl-uncap*-<file>.json`): unlike the default operators, ERDC's 1500-case cap did
  hide killers here. First results: quantize 6 of 27 killed, composite 3 of 12, montage 2 of
  6, registry 1 of 4, signature 1 of 3, histogram 1 of 8, feature 1 of 2, quantum-export 1
  of 8; monitor, colorspace and xml-tree none.
- **Verdicts:** monitor.c 2 (the semaphore is always created at genesis; its release at
  shutdown only leaks), quantize.c 19 (colour writes SyncImage undoes, 12; SetGrayscaleImage's
  sort and index writes, 2; DestroyQCubeInfo, leaks, 5).
- **`morphgap5`**: `morphology:showKernel` for edge kernels with an angle, every FreiChen type
  and the expanding kernels; hand-run with `mull-sdl-win`, 27 statement-deletion survivors
  killed (deleted RotateKernelInfo, ScaleKernelInfo, CalcKernelMetaData, Expand*KernelInfo).
  Queued as a round with statement deletion (`~/sdl-queue-runner.sh`, reports
  `mutation-sdlcases-<family>-<file>.json`).
- colorspace.c's `GetImageColorspaceType` and registry.c's `RemoveImageRegistry` have no
  caller in ImageMagick: API only, out of reach for a command-line oracle.

### Trust with statement deletion, after the night (Windows, 2026-10-04, 04:15)

The uncapped reruns of every statement-deletion survivor finished at 03:56. They killed what
ERDC's 1500-case cap had missed in most files: morphology 27, quantum-import 29, distort 7,
color 5, fx 4, matrix 4, exception 3, stream 2, and one or two in several others.
Statement-deletion rounds: `morphgap5` 3 more, `fxgap14` 1, `colorgap3` 5. The night's verdicts
on statement deletion number about 110 (shutdown clean-up, leaks, colour writes SyncImage
undoes, semaphores created at genesis, prefetch hints, timer figures the oracle masks).

Adjusted, all reports merged (trial excluded), against the evening's figures: monitor 86 → 92,
colorspace 90, registry 84 → 88, quantize 89 → 92, signature 81 → 82, histogram 90, morphology
86 → 88, composite 84, feature 87 → 88, montage 83 → 84, exception 81 → 84, magick 60 → 71,
timer 75 → 79, fx 89 → 91, distort 87 → 88, quantum 90, resource 89 → 90, token 84 → 85,
stream 85, color 82 → 84, matrix 71 → 73, resample 77, blob 71, option 75 → 76,
quantum-export 72 → 73, quantum-import 66 → 68, xml-tree 76, cache 80 → 81.

**Trusted again, counting statement deletion (every function at 80% or written down as out of
reach):** monitor.c, montage.c, composite.c, feature.c; and, with one function each written
down, morphology.c (`ZeroKernelNans`, which nothing calls), colorspace.c
(`GetImageColorspaceType`, no caller in ImageMagick: API only) and registry.c
(`RemoveImageRegistry`, likewise). gem.c and prepress.c have no statement-deletion mutants and
stay trusted. Close: histogram.c (its two destroy functions now have verdicts),
signature.c (`GetSignatureBlocksize` and `SetSignatureDigest`, API only), quantize.c
(`QuantizeImages` at 79%: `quantizegap11`, hand-run, kills its three survivors; its round runs
after the sweep).

A fresh sweep of all 34 files with the statement-deletion build (`~/sweep1004*.sh`, reports
`mutation-sweep1004*-<file>.json`) runs now, to give one consistent report per file.

### The statement-deletion sweep, and trust after it (Windows, 2026-10-04, 15:00)

The sweep finished at 15:01: every regular Windows file against the whole catalogue with the
`mull-sdl-win` build (Mull defaults and `cxx_remove_void_call`), capped at 1500 cases per mutant.
It ran in three instances, cut to two jobs for an hour while the owner worked on the machine.

**A gate fix first.** `gate.merged` lets a later report replace an earlier non-kill, so the
order of the reports matters. The Windows status script passed them in glob order, which is
arbitrary; it now passes them oldest first (by modification time). Only quantize.c moved: 91 →
92, and `AcquirePixelTLS`/`DestroyPixelTLS` from 67/25 to 100 (their survivors are pattern
kinds). Earlier figures in this file may be off by a point for the same reason.

**Verdicts today** (all read by hand, each against a precedent where there is one):
semaphore.c 17 (mutex calls with one thread, a leaked free, the pthread failure paths: no case
reaches them without fault injection), timer.c 6 (stopwatch figures; `SOURCE_DATE_EPOCH` is
never set), exception.c 5 (the semaphore guard `ExceptionComponentGenesis` makes dead, the fatal
path, `InheritException`'s iterator reset, a no-op on its one command-line caller), resource.c
11 (semaphore guards made dead by `ResourceComponentGenesis`, the `open_utf8` fallback this build
never reaches because it has `mkstemp`), quantum.c 1 (a leak), token.c 10 (Tokenizer's
escape, whitespace and second-quote branches: every caller passes escape NUL, no whitespace set,
one quote character and flag 0).

Adjusted, all reports merged oldest first: semaphore 56 → 100, resource 90 → 97, exception 84
→ 91, quantize 92, histogram 92, monitor 92, fx 91, constitute 91, quantum 91, colorspace 90,
token 85 → 90, gem 89, morphology 88, feature 88, distort 88, registry 88, prepress 87, timer
79 → 85, stream 85, color 84 → 85, composite 84, montage 84, signature 82, cache 81, option 76 →
77, magick 71 → 77, resample 77, xml-tree 76, blob 71 → 74, quantum-export 73, matrix 73,
quantum-import 68, splay-tree 55, pixel 48, linked-list 42, cache-view 37.

**Trusted, counting statement deletion (17 of 36):** composite, feature, morphology,
colorspace, quantize, histogram, montage, signature, resource, gem, prepress, registry, magick,
monitor, exception, constitute, semaphore. Written down as out of reach on the way: magick.c's
`MagickSignalHandler` (runs only on a signal), `GetMagickList` (widget.c, a special build) and
`GetImageMagick` (API only); resource.c's `AsynchronousResourceComponentTerminus` (called only
from `MagickSignalHandler`); exception.c's `SetErrorHandler` (animate.c, display.c) and
`CloneExceptionInfo` (API only); signature.c's two setters (API only).

**Short (one to three functions), and what each needs:**

- distort.c `MagickRound` (75%): `<` → `<=` differs only at exactly x.5.
- color.c `IsSVGCompliant` (67%): `>= SVGEpsilon` → `>` needs a channel exactly 1e-6 from an
  8-bit value. From image pixels (32-bit floats) that cannot happen: a float near k·257 has an
  ulp far above 1e-6, and near 0 a float is never the double 1e-6. Colours parsed as doubles are
  not ruled out. A plateau candidate.
- timer.c `ContinueTimer`, `AcquireTimerInfo`: run only under `-bench` (magick-cli.c) and log
  timestamps. Their verdicts are written, but a verdict applies only to a mutant some case
  executes. **Proposal:** a `-bench` case, with a `NORMALISE` rule for the
  `Performance[n]: ...i ...ips ...e ...u ...` line. That changes the oracle on every machine,
  so it is the owner's call.
- quantum.c `SetQuantumMetaChannel` (bounds at -1 and at the meta-channel count): a planar TIFF
  with meta channels, whose reader resets the channel with -1 (tiff.c:2021). `SetQuantumPad`'s
  overflow guard is unresolved.
- token.c `GlobExpression` (76%, glob cases) and `StoreToken`'s truncation at
  `max_token_length-1` (an 8BIMTEXT line whose token fills meta.c's buffer).
- option.c, resample.c, xml-tree.c, quantum.c: gaps; linked-list.c and cache-view.c: one or two
  functions each that a case could reach, the rest API only.

### pixel.c, linked-list.c, splay-tree.c and cache-view.c through imdriver (Windows, 2026-10-04, 16:00)

The Mac's C driver (above) now has four Windows commands, and the family `windrv` 254 cases:
`pixels export|import` (ExportImagePixels and ImportImagePixels with every storage type, over
the maps with a fast path, including char's BGRO and RGBO, and the generic loop, CMYK maps of a
CMYK image, into and from a region, and the refusals); `linkedlist` and `splaytree` scripts of
every operation (strings are interned, so a removal by value finds what a step stored; trees
with relinquish functions, and without a compare function keyed by small integers, as
profile.c and property.c make them; a 1100-node ascending chain makes the tree balance itself
past depth 1024); `cacheview` (the one-pixel getters with every virtual pixel method but
Random, a PixelInfo the getter must fill in itself). Plus `-sort-pixels`, which no case used.

Uncapped statement-deletion rounds (three; the second and third after reading what survived):

| file | before | after |
|---|---|---|
| pixel.c (2624 mutants) | 48% | 99% |
| linked-list.c | 42% | 100% |
| splay-tree.c | 55% | 100% |
| cache-view.c | 37% | 100% |

All four are **trusted**. pixel.c's two functions under the bar are written down:
`LogPixelChannels` (logging; with `-log %e` its `-debug pixel` output is stable by hand but not
under the oracle, so no case uses it) and `ClonePixelInfo` (API only, not in the driver).
Functions the driver reaches no longer count as "API only": they are measured like any other.

**Pitfalls on the way.** (1) The WSL base build had no `imdriver` at all, so the Mac's
driver cases had never run here; it is now built into the base, coverage and `mull-sdl-win`
builds. (2) The driver printed the list through the list's own iterator after every step, so
every `next` in a script returned NULL; it now prints through `LinkedListToArray`. (3)
`mutate.py` resumes a report of the same name, so a round rerun under the same family must have
its earlier report renamed first (here `windrv1`, `windrv2`), or it resumes the old result.

**An upstream bug.** `InsertValueInLinkedList` at a middle index (0 < index < elements) loses
the new element: after the walk it does `next=next->next; element->next=next;`, which links the
element *after* the new one and drops it, but still counts it (`elements++`). The list then
holds one element fewer than it reports; `RemoveLastElementFromLinkedList`, which walks to the
element before the tail, can then run off the end. No caller in ImageMagick inserts at a middle
index, so the command line never sees it. The cases insert at a middle index only as a script's
last step.

Trusted now, Windows: **21 of 36** (the 17 above, and these four).

**xml-tree.c, 76 → 99, trusted.** An `xml` driver command parses a document (or starts from
`NewXMLTreeTag`), walks it (child, sibling, next), adds children at offsets, sets content,
adds paths, and prints it with `XMLTreeInfoToXML`. Twelve documents: attributes, entities,
CDATA, processing instructions before, inside and after the root, a DOCTYPE with entities and
attribute defaults, circular and chained entities, characters to escape, control characters
(CanonicalXMLContent's base64), a mismatched tag, and items longer than the writers' 4 KB of
slack (tag and attribute names, a DTD default, processing-instruction targets and content),
which reach the buffer-growth checks. Four rounds. 14 verdicts: the `>` → `>=` growth checks
(the buffer grows a byte earlier), three leaks in `DestroyXMLTree_`, an allocation failure,
and three that follow from two quirks:

- `ValidateEntities`' inner loop skips entities *while* their names match (it should skip while
  they differ), so any entity value with a delimiter recurses until the depth limit: every
  entity that refers to another is reported as circular.
- `XMLTreeTagToXML` prints DTD default attributes only for the tag of the first ATTLIST.

**A second upstream bug.** An attribute written `a="q\"x"` (XML has no backslash escape)
parses into an attribute with no value, and `XMLTreeInfoToXML` then crashes in
`CanonicalXMLContent(NULL)`. Malformed input only; no case uses it.

Trusted now, Windows: **22 of 36**.

### option.c, blob.c, quantum-import.c and quantum-export.c (Windows, 2026-10-04, evening)

**option.c 77 → 88, trusted.** `optgap`: `-channel-fx` with numeric, negative, out-of-range and
non-numeric channels (ParsePixelChannelOption), `-channel` shorthand with `,type`, including
`Undefined` (ParseChannelOption). 12 verdicts on GetCommandOptionFlags: every command-line
caller passes one option it already recognised by its exact name (a name with an underscore or
a stray dash is rejected as UnrecognizedOption first), so the list, length and retry-without-
dashes branches cannot change the flags. Its three functions under the bar are written down
(GetCommandOptions: display.c; Reset/RemoveImageOption: API only).

**blob.c 74 → 86, not yet trusted.** A `blob` driver command: ImageToBlob and ImagesToBlob over
eleven formats, BlobToImage and PingBlob back, custom streams over a memory buffer with and
without seek and tell (ImageToCustomStream, ImagesToCustomStream, CustomStreamToImage),
MSBOrderLong/Short and FileToImage; formats without blob support (MPC, SHTML, INFO, VICAR) for
the temporary-file route. Seventeen small functions remain under the bar, a few survivors each.
**A third upstream crash:** writing the corpus rose as HTML through ImageToBlob frees an
invalid pointer in DestroyImageInfo (WriteHTMLImage → WriteImage); no case uses it.

**quantum-import.c 68 → 100 and quantum-export.c 73 → 100, trusted.** A `quantum` driver
command: ExportQuantumPixels row by row (the bytes' FNV hash) and ImportQuantumPixels from a
byte pattern or a round trip, for all 27 quantum types at depths 1 to 64, unsigned and
floating point, MSB, min-is-white, unpacked, padded and 32-bit-quantum variants, index and
opacity types of a palette image given an alpha channel; 1252 cases, three rounds. What made
the difference in the last round: the round trip's target is blanked first (a clone of the
source hid every skipped import). Four verdicts on the bit-packing clamps (at equality they
assign the value already there). Driver notes: it uses the QuantumInfo's own buffer
(`GetQuantumPixels`), since ExportBGROQuantum at 24-bit floating point writes past what
`GetQuantumExtent` reports; meta channels are set before `AcquireQuantumInfo` and filled
(they start uninitialised).

Trusted now, Windows: **25 of 36**.

**matrix.c 73 → 99, trusted.** A `matrix` driver command: MatrixInfo in memory, mapped and on
disk (the driver sets the resource limits itself, so the disk path does not depend on load as
the command line's `-limit` cases did), set and read in and out of range, NullMatrix,
MatrixToImage, and the memory, map and disk resources held and released (which makes the
`RelinquishMagickResource` deletions visible); `MAGICK_SYNCHRONIZE` for the preallocation
path; GaussJordanElimination over regular, nearly singular, exactly singular (integer entries,
a zero pivot) and pivoting systems, and least squares through LeastSquaresAddTerms. Seven
verdicts (a pivot of exactly LDBL_MIN, min/max at equality, clean-up after a failed allocation).

### Owner's decisions (2026-10-04, evening)

1. **`-bench` timings are masked.** `oracle.NORMALISE` gains a rule for the
   `Performance[n]: Ni ...ips ...e ...u ...` report: the thread count and the iterations stay,
   the timings are masked. No earlier case used `-bench`, so no recorded result changes. Family
   `benchgap`: three `-bench` cases, two with `-duration 1000` (ContinueTimer; a duration far
   longer than the run keeps every iteration). For timer.c's ContinueTimer and AcquireTimerInfo.
2. **Written off as out of reach:** vms.c (compiled only on VMS), nt-base.c and nt-feature.c
   (compiled only in a native Windows build; the oracle builds run in WSL, Linux). The X11
   files (animate.c, display.c, xwindow.c, widget.c) and the OpenCL files (accelerate.c,
   opencl.c) wait for a later decision on building those variants.
3. **Written off as out of reach:** distribute-cache.c (the distributed pixel cache needs a TCP
   cache server, which the oracle does not start).

### resample.c, timer.c and token.c trusted (Windows, 2026-10-04, night)

**resample.c 77 → 87.** A `resample` driver command: ResamplePixelColor on a half-pixel grid
from 8 (and, second wave, 40) pixels outside the image to 8 or 40 beyond it, with 15 virtual
pixel methods (not Random, which varies between runs), point sampling with three
interpolations and elliptical filters at three scales. The 40 survivors left sit in the
outside-the-image shortcuts, one per line; every function is above the bar.

**timer.c 85 → 100**, with the `benchgap` cases the owner's decision allowed: the verdicts
already written for ContinueTimer and AcquireTimerInfo count once a case reaches them.

**token.c 85 → 94.** `glob` and `tokenize` driver commands: GlobExpression over 32 patterns
(wildcards, sets, ranges, alternatives, escapes, subimage, UTF-8, case folding) against 17
expressions, and Tokenizer with what no caller passes (a short maximum token length, which
reaches StoreToken's truncation; whitespace and escape characters; two quote characters; the
case flags). Four verdicts: GlobExpression_'s loops that advance local pointers just before
`return(MagickTrue)`.

**A fourth upstream bug.** GlobExpression_'s `'\\'` case advances past the backslash and falls
through to the default case, which compares `pc`, still the backslash, with the expression's
character: an escaped character never matches (`a\*c` does not match `a*c`). **And a
performance trap:** matching is exponential in the number of `*`; `*a*b*a*b*z` against a
600-character expression ran for over ten minutes. The cases keep expressions short.

Trusted now, Windows: **29 of 36** regular files; vms.c, nt-base.c, nt-feature.c and
distribute-cache.c written off.

**quantum.c 91 → 100.** The `quantum` driver command reports SetQuantumMetaChannel's and
SetQuantumPad's status: meta channels -2 to 2 of an image with two, and a pad exactly at the
overflow guard (MAGICK_SSIZE_MAX over the channel count; one below it crashes on the
allocation, so no case uses that).

**color.c 85 → 94.** A `color` driver command builds a PixelInfo from doubles, so a channel can
sit exactly SVGEpsilon (1e-6) from an 8-bit value, which image pixels, 32-bit floats, never
do: GetColorTuple's IsSVGCompliant `>=` → `>` is killed (the tuple switches from percent to
value). IsEquivalentAlpha and IsEquivalentIntensity (no caller in ImageMagick) with value pairs
in the narrow windows where each fuzz mutation changes the answer; IsEquivalentImage. The
plateau candidate written down earlier is gone.

**distort.c stays at 88%, written down.** MagickRound's `<` → `<=` differs only at exactly x.5.
It meets x.5 in the Arc angle normalisation (an argument of 270°), where the two roundings
differ by one whole turn that the following normalisation removes, and per pixel only when
an angle falls exactly on half a turn. Unresolved, not provably equivalent.

Trusted now, Windows: **31 of 36**. Far: fx.c, cache.c, stream.c, blob.c (86).

**stream.c 85 → 99, trusted.** A `stream` driver command: ReadStream with a handler that
hashes each row, and one that also asks the streaming image for pixels (GetOneVirtualPixel,
GetOneAuthenticPixel, GetVirtualPixels inside, across and outside the row, the queue and the
metacontent), over six corpus images and seven formats converted first; WriteStream in eight
formats. Asking for pixels inside the handler ends the stream after its first row, every run
alike. Two functions under the bar, written down: GetVirtualPixelsStream is identical to
GetAuthenticPixelsFromStream and folded with it by the compiler (coverage is recorded under
the other name), and GetOneVirtualPixelFromStream is never installed, because of:

**A fifth upstream bug.** SetPixelCacheMethods (cache.c) copies the one-virtual-pixel handler
only when the cache already has one: it tests `cache_info->methods.get_one_virtual_pixel_from_handler`
where the authentic version, two statements later, tests `cache_methods->...`. ReadStream's
GetOneVirtualPixelFromStream is never installed, and GetOneVirtualPixel on a streaming image
falls back to the ordinary pixel cache.

Trusted now, Windows: **33 of 36**. Far: fx.c, cache.c, blob.c (86).

**cache.c 81 → 100, trusted.** First a rerun of its survivors against all windrv cases (the
cache-view and stream commands reach much of it: 65 killed, 86%). Then a `cache` driver
command: the pixel cache in memory and on disk, metacontent (`metacontent_extent` set on the
image, then SyncImagePixelCache) written and read back by rows and through a region narrower
than a row and several rows high (only such a region makes the cache copy it, Read/
WritePixelCacheMetacontent), GetPixelCachePixels, GetOneAuthenticPixel (which calls
GetAuthenticPixelsCache directly), GetOneVirtualPixelInfo with every virtual pixel method, a
clone that is then written (the copy on write; on disk ClonePixelCacheOnDisk),
ReshapePixelCache and DestroyImagePixels. One verdict (ApplyPixelCompositeMask: TransparentAlpha
is 0, so `alpha-TransparentAlpha` and `alpha+TransparentAlpha` are equal). Written down:
DestroyImagePixelCache is installed only by GetPixelCacheMethods, whose one caller (ReadStream)
replaces it with DestroyPixelStream at once.

Trusted now, Windows: **34 of 36**. Left: fx.c (91) and blob.c (87).

### Confirmation sweep with the grown catalogue (Windows, night of 2026-10-04/05)

A fresh statement-deletion sweep of all 36 regular Windows files against the whole catalogue
(14,600 cases, with yesterday's driver families), `mull-sdl-win`, capped at 1500 cases per
mutant, in up to four instances (22:35 to 07:13; reports `mutation-sweep1005*-<file>.json`).
Before it, a determinism selfcheck of the whole catalogue: 14,553 cases, 4 runs each, none
nondeterministic.

**No trusted file lost its trust**, and several gained: monitor 92 → 100, signature 82 → 98,
resource 97 → 99, option 88 → 90, registry 88 → 91, exception 91 → 93, quantize 92 → 95.
Merged adjusted scores: quantum-import, quantum-export, cache, quantum, timer, monitor,
splay-tree, linked-list, cache-view, semaphore 100; matrix, xml-tree, stream, pixel, resource 99;
signature 98; quantize 95; token, color 94; exception 93; histogram, fx 92; constitute, registry
91; option, colorspace 90; gem, blob 89; distort, feature, morphology 88; resample, prepress 87;
composite, montage 84; magick 78 (its three functions under the bar written down).

**fx.c, overnight.** A correction first: last evening's hand-runs built the mutant ids with a
guessed end column (start + 1), which matches no mutant, so every mutant read "same". With the
ids from the report, targeted expressions kill: a space between a token and its bracket or
qualifier (`abs (u)`, `u [1]`, `p {2,3}`, `u .r`: PeekChar's SkipSpaces), empty brackets `( )`,
a spaced assignment `a= 1;a`, a lone unary minus `- `, `epoch( %[date:x])` (PeekStr's
SkipSpaces), a trailing `;`, a nested `%[fx:%[fx:0.25]]`, a bare `#`, and `u[2]` of two images
(family `fxgap15`, 20 cases). Eleven verdicts: `severity >= ErrorException` against `>` (no code
in ImageMagick raises exactly ErrorException, 400; fx raises OptionError, 410), GetPixelInfo
before QueryColorCompliance and InterpolatePixelInfo (both initialise the colour themselves),
and the SkipSpaces in GetOperand, GetOperator, TranslateStatement and TranslateStatementList
(each caller has already skipped). **blob.c:** SetBlobExtent below, at and above what is
already written, and with MAGICK_SYNCHRONIZE; FileToImage of an empty file (a zero buffer
size); three verdicts (a failing fstat only changes the copy's chunk size).

**fx.c 91 → 94, trusted (morning of 2026-10-05).** A fourth `fxgap15` batch: unary prefixes
nested deeper than the operator stack's later top, then a user symbol after a binary operator
(`(-(-(-zz))) + zz * zz`), which kills TopOprIsUnaryPrefix's `usedOprStack-1` → `+1` (it then
reads the slot the deeper prefixes left). Ten more verdicts: InitFx's and
AcquireFxInfoPrivate's clean-up after AcquireVirtualCacheView or AllocFxRt fails (allocation
failure only), AddUserSymbol's `++used >= num` → `>` (the entry written is `used-1`, still inside
the table, so growing a symbol later writes the same entry), and PushVal's and PopVal's bounds
(the value stack is twice the deepest operator stack and the translated RPN never pops more than
it pushed, so the equality cases never occur). No fx.c function is under the bar.

Trusted now, Windows: **35 of 36**. Left: blob.c (89).

**blob.c 74 → 97, trusted (2026-10-05, morning).** After the `blob` and `blobio` driver
commands of yesterday, seven rounds:

- SetBlobExtent below, at and above what is already written, closed right after (the extent
  alone sizes the file), and synchronized through `image_info->synchronize` (the driver had set
  MAGICK_SYNCHRONIZE after the ImageInfo had read it); its branch for a memory-mapped blob is
  never entered (OpenBlob maps only files it reads, and no reader extends its blob): verdicts.
- MAT (no blob support, read back) and PDF of one to three pages (pages to one file) through
  ImageToBlob's and ImagesToBlob's temporary-file routes; PS, EPS and PS2 pinged back through
  Ghostscript from a temporary file. PDF and PostScript carry the date, so only their length is
  printed.
- WriteImages into a caller's memory blob (`image_info->blob`), frame by frame and adjoined:
  SyncBlobStream's hand-over of each later frame's buffer to the list's owner (21 killed).
  **Possibly a sixth upstream bug, not analysed:** with adjoin off, MIFF, PNG, TIFF, PPM and BMP
  corrupt the heap (`realloc(): invalid next size`, `double free or corruption`); no case uses them.
- ReadBlobString through zlib (a `.gz` text image) and CloseBlob's status after reading, which
  shows its error checks; a last line after a CRLF line, whose `\r` the strip leaves in the
  buffer just past the line's end (`string[i-1]` → `string[i+1]`).
- DiscardBlobBytes over several chunks of a 62 KB file; FileToImage of an empty file.
- Verdicts: frees after a failed write, the final trim of a returned blob, EOF and EINTR in
  DiscardBlobBytes, the map-resource bookkeeping in ResetDisassociatedBlobStorage, the pinged
  image's exempt reference to the caller's blob, a leak in DuplicateBlob, fstat failing (only
  the chunk size changes).

Written down: ThrowBlobException (only after an I/O error on the blob) and AttachCustomStream
(no caller in ImageMagick).

## All 36 regular Windows files trusted (2026-10-05)

Every function of the 36 regular Windows files is at 80% adjusted or written down as out of
reach, with statement deletion among the operators. Written off by the owner: vms.c, nt-base.c,
nt-feature.c, distribute-cache.c. Waiting for a decision on building them: animate.c,
display.c, xwindow.c, widget.c (X11) and accelerate.c, opencl.c (OpenCL). deprecate.c has no
mutants in the regular build.

Two days' upstream findings, none in a path the command line takes with valid input: a middle
insertion that drops its element (InsertValueInLinkedList), a crash on an attribute with no
value (XMLTreeInfoToXML), an invalid free (WriteHTMLImage through ImageToBlob), glob escapes that
never match (GlobExpression_) and its exponential matching, a cache method never installed
(SetPixelCacheMethods), and the unanalysed heap corruption above.

## How to use this in the campaign

- **Before refactoring a function**, run its mutants:
  `mutate.py --file <file> --function <name>`. Survivors on executed lines
  that are not obviously equivalent are the places a refactoring mistake
  could pass unnoticed. Close them in the catalogue first.
- **Survivors are data, not failures.** Record why each remaining survivor is
  acceptable (equivalent, logging only, and so on), as the table above does,
  so the next agent does not redo the analysis.
- **The equivalent classes above recur in every file**: kernel breakpoints,
  logging, progress callbacks and allocation. Mull's `--mutators` could exclude
  some operators from specific lines, but the honest record is to count them
  and name them.
- A full-file run costs 20–30 minutes and a single function a minute or two,
  so run per function during refactoring and per file before pushing.

## A C driver and external programs (Mac, evening of 2026-10-03)

The owner allowed both: a C driver for code the command line cannot reach, and external programs
for the delegates, installed with Homebrew.

**`imdriver`** (`tools/oracle/driver/imdriver.c`) calls `GradientImage` with each spread method
(every caller in the library passes `PadSpread`), sets and reads the read, write and composite
masks, runs `AcquireImage` from `ImageInfo` fields the command line overwrites, and prints the
policy, locale and mime lists. `driver/build.sh BUILDDIR` links it against that build's own
MagickCore, beside its `magick`, so a mutant switched on in the environment is active in it too;
`tools/oracle/build.sh` now does this for every oracle build. A case step that starts with
`@driver` runs it (`oracle.command_line`); where it is not built the step runs `magick` with an
unknown option, which fails alike in every run of that build, so a driver case can neither kill
nor reach anything there. 37 cases. Hand-run against mull-macx they kill **59 of draw.c's 72**
open mutants in its functions under the bar (`DrawGradientImage`'s reflect and repeat spreads)
and **10 of image.c's 28** (masks, `AcquireImage`). The list cases kill nothing in locale.c,
policy.c or mime.c: what is open there is loading configuration, not listing it.

**Upstream:** `GetMimeList`'s order differs from run to run (entries that compare equal), so
the driver sorts it.

**External programs:** Ghostscript 10.08.0 and Inkscape 1.4.4 (Homebrew, `/opt/homebrew/bin`,
on the oracle's PATH; an older `gs` in `/usr/local/bin` was never on it). They add little:
PostScript is read through the ps coder's own Ghostscript call, and the PostScript conversions
in `delegates.xml` are not taken when a PostScript image is written to another PostScript
format, so `InvokeDelegate` and the delegate command letters stay unreached; two cases kill
two `ExternalDelegateCommand` mutants. Inkscape's and Graphviz's (`dot`) output differ between
runs, so no case uses them. A program upgrade changes the baselines of the cases that use it.

**ERDC** computes the official figures, so it needs the driver built against its own builds
(`tools/oracle/build.sh` does it on the next build, or `driver/build.sh` on an existing one) and
Ghostscript on its PATH; until then the driver and Ghostscript cases fail alike there and count
for nothing. The kills above reach the official figures once ERDC has both.

**Installing Ghostscript upgraded 15 libraries, and stale baselines faked kills (21:03-21:47).**
`brew install ghostscript` upgraded libtiff, little-cms2, fontconfig, harfbuzz, pango and ten
more. The oracle builds link them dynamically, so cases that encode TIFF or WebP, render text or
list formats changed output; the baseline cache, keyed by the binary's own hash, did not notice,
and the Mac's uncapped rerun (macall2) counted every mutant those cases met as killed: 63 false
kills in image.c, annotate.c, locale.c, memory.c, policy.c and configure.c, set aside and rerun.
The cache key now includes a fingerprint of the shared libraries the binary loads (resolved path
and size, `oracle.library_fingerprint`), so an upgrade starts a new baseline. Hand runs
(`stepkill`) compute their baseline in the same session and were not affected.

**Inkscape removed again (2026-10-04, 08:18).** The Mac's determinism sweep that night
(`selfcheck --repeat 4`, 12,291 cases, mull-macx) found 24 nondeterministic cases: 22 of them
reach the SVG delegate, and Inkscape left a different fontconfig cache under the case's `HOME`
on every run; the other two are Windows' `matrix` cases (`-hough-lines` with the matrix on
disk), which leave differently named temporary files under load. Inkscape was uninstalled; it
killed nothing. No Mac report written while it was installed credits a kill to the 22 cases
(their kills in other reports come from ERDC and from before the install), so nothing is
retracted. Without it, the 24 cases ran 8 times each with no difference. The baseline cache
key now also includes the external programs `delegates.xml` names, as found on the oracle's
PATH (`oracle.program_fingerprint`): the Inkscape-era baselines would otherwise have counted
every mutant the SVG cases meet as killed. The key change starts a new baseline once on every
machine.

## property.c: trusted (Mac, 2026-10-04)

`GetICCProperty` was the one function under the bar (gate 75%), held by four
`cxx_remove_void_call` survivors that delete the `SetStringInfoLength(info,extent+1)`
resize before each `cmsGetProfileInfoASCII` write (description, manufacturer, model,
copyright). `info` comes from `AcquireStringInfo(0)`, whose datum already holds
`MagickPathExtent` zeroed bytes, so lcms's text fits that slack without the resize and
the output is byte-identical; only a tag longer than the slack overflows. Crafted ICC
profiles carrying a 28 KB desc/dmnd/dmdd/cprt tag (every byte < 0x80, so they fit a text
case file) were hand-run against mull-macx: removing any of the four resizes left output
and exit code identical over 10 runs each. A single abort seen on one early run did not
reproduce — heap-layout UB, not an observable kill, the flaky-kill class the harness
rejects. So the four are **unobservable**, not catalogue gaps: dropping the resize is a
latent out-of-bounds write that a differential output oracle cannot deterministically
see. With them reclassified, `GetICCProperty` is 100% and property.c is trusted (adjusted
87%). This is a verdict change only, so it needs no ERDC rerun.

## type.c: GetTypeInfoByFamily stays one function short — font selection is not reproducibly observable (Mac, 2026-10-04)

`GetTypeInfoByFamily` is the one function under the bar (gate ~79%). Its survivors are the
font-matching logic: the first-pass exact-match loop (`while (p != NULL)`, `if (p->family
== NULL)`, the `ResetSplayTreeIterator`), the second-pass scorer (the italic/oblique
`+25`, the stretch `/range` divisor) and the fontmap substitution loop (`fixed`→`courier`,
`wingdings`→`symbol`, ...). I tried to kill them with a type.xml of the case's own that
adds `courier`/`helvetica`/`symbol` families and requests `-family fixed` etc.

**They are not reproducibly killable here, for two reasons, both verified by hand against
mull-sweep60:**

1. **One glyph file.** Every entry in a case's type.xml points at the single corpus font
   `Generic.ttf`, so whichever `TypeInfo` the matcher picks renders identical glyphs and
   metrics. Only *whether a font is found at all* changes output; *which* same-glyph font
   is chosen does not. So the scorer mutants (italic/oblique, stretch divisor) are
   unobservable with the frozen corpus.
2. **Substitution routes through ambiguous system families.** The only find-vs-not-found
   channel is the fontmap substitution (`-family fixed` → `courier`). But `courier`,
   `helvetica` and `symbol` are also defined, with several entries each, by the build's
   bundled `type-ghostscript.xml` (on `MAGICK_CONFIGURE_PATH`), which a case cannot
   suppress. The type cache is a splay tree that **rebalances on every access**, so
   `GetNextValueInSplayTree`'s order — and thus which of the ambiguous courier entries is
   returned — varies from run to run. The base render of `-family fixed label:Ab` was
   nondeterministic (two stdout hashes over 8 runs): an unstable case the harness rejects
   (cf. the Inkscape and matrix cases). A first, hopeful reading that this case "killed"
   eleven survivors was an artefact of diffing against that flaky base; repeating it showed
   only the default-font fallback (`473` loop bound to `>=`, `475` family-NULL test) gives
   a *stable* distinct hash, and even those can't be used while the base is unstable.

The logic that *would* distinguish the choices — real, visually different fonts — exists
only in the system Ghostscript/URW config, which is not part of the reproducible corpus and
differs across the three machines (which is why the cases use `Generic.ttf` alone).

**So GetTypeInfoByFamily plateaus below the bar, and this is an owner decision, not a
catalogue gap:** making font *selection* observable needs a second, visually distinct font
added to the frozen corpus (like `config/sRGB.icm` for ProfileImage), present identically
on all three machines. Until then type.c stays at its adjusted ~84% with this one function
short; its survivors are left `unresolved` (counted against), not written off, because a
second corpus font would turn most of them into clean kills.

## type.c: a second corpus font makes font selection observable (Mac, 2026-10-04) — SUPERSEDED, see the correction below

> **Note (correction):** the "trusted" conclusion in this section is wrong; see "Correction:
> type.c is NOT trusted" further down. The second font and `Narrow.ttf` are real and kept; only
> the trust claim (which rested on a flaky `Helvetica` kill) is retracted.

The owner approved adding a second font to the frozen corpus (the decision the plateau note
above asked for). **`Narrow.ttf`** (`tools/oracle/mknarrow.py`) is Generic.ttf with its glyph
outlines and advance widths scaled to 0.6 of their width — a condensed derivative, same
licence, visibly different glyphs. `oracle.py` copies it into the corpus beside Generic.ttf,
and `CORPUS_VERSION` (new) is bumped to 2 so every machine with an older cached corpus rebuilds
it rather than running against a stale one that lacks the font.

The existing `ScoreFamily` scorer cases (which had used a `face="1"` render-fail trick on a
single glyph file) now point their entries at the two fonts alternately, so *which* `TypeInfo`
the matcher selects shows directly as different rendered glyphs. Measured against mull-sweep60
(`mutation-typescore.json`, cases deterministic over 4 selfcheck runs):

- **Killed:** the second-pass style scorers `446`/`447` (the italic/oblique `+25`, all four
  columns), the stretch `range` computation `458:22` (`sub_to_add`), and the fontmap loop
  index `473:66` — the selection-logic mutants a single font could never distinguish.
- **GetTypeInfoByFamily: 46 killed, gate 82% (adjusted 82%)** — over the bar, so **type.c is
  trusted**.

Remaining survivors, left honestly unresolved (the function already clears the bar without
them): the first-pass mutants `366`/`369`/`371` (breaking the exact-match pass is masked by
the scoring pass, which returns the same font because an exact match holds the unique maximum
score for the corpus's sub-900 weights — very likely equivalent); the stretch divisor `458:65`
(`/range`→`*range`, a gap: a weight-vs-stretch case with distinct fonts would catch it, but
`ScoreFamily`'s several weight-400 entries make such a case tie and go nondeterministic, so it
needs a purpose-built family); and the fontmap/`family==NULL` paths `473:15`, `475`, `429`,
`430`, `477`, `478`, which route through `courier`/`helvetica`/`symbol` — families the bundled
Ghostscript config defines ambiguously (the earlier note's splay-order nondeterminism).

The second font also stands to help annotate.c's text-metric survivors; that is the next
thing to try with it.

## annotate.c: RenderFreetype's metric fields are overwritten before the CLI sees them (Mac, 2026-10-04)

A fresh uncapped run of RenderFreetype's 36 open survivors against the whole current catalogue
(`mutation-rft36.json`, mull-macx) killed **none** — they are genuine gaps, not stale. Reading
them by hand, with the second font now available, placed the largest group:

**The type-metric fields RenderFreetype computes are not observable from the command line,
because the multi-line path overwrites them.** `GetMultilineTypeMetrics` (annotate.c:860)
recomputes `metrics->height` from `ascent-descent` and discards RenderFreetype's
`metrics->height=…/64.0` (L1811); and `label:`, `caption:` and multi-line `-annotate` all size
their image through `GetMultilineTypeMetrics`. Confirmed against mull-macx: mutating L1811
(height `/64`→`*64`), L1813/L1814 (`max_advance`) or L1817/L1818 (the initial `bounds.x2/y2 =
ascent+descent`, which the glyph loop at L1948/L1950 overwrites for any non-empty text) leaves
`label:`/`caption:` `%wx%h`, the rendered pixels and `%[caption:pointsize]` all identical. These
fields reach a caller only through the C/C++ APIs (`GetTypeMetrics` read directly), which are out
of a command-line oracle's reach, like type.c's `GetImageColorspaceType` and the ICC-name
helpers. So they are unobservable here, not catalogue gaps — left `unresolved` for now rather
than written off, pending either a `make check`/driver reader of the metric struct or an audit of
every `GetTypeMetrics` caller in MagickCore for a field the CLI does surface.

The other RenderFreetype survivors split into: the `@`-file font policy check (L1645/L1646,
needs a font loaded through `@path` under a path policy), the charmap/`AppleRoman` encoding
fallbacks (L1714/L1724), the glyph-trace block reached only under `-stroke` (L1953/L1960/L2100),
the non-antialiased mono opacity rounding `fill_opacity >= 0.5` (L2060, an exact-0.5 edge), and
the per-glyph bounds min/max guards with their `!= 0` tests (L1944–L1950). Some of these are
reachable with targeted cases (a stroked `-annotate`, `+antialias`); that is the next pass.
annotate.c stays untrusted (RenderFreetype at gate 77%); closing it is more than a short sitting.

## Correction: type.c is NOT trusted — the earlier "trusted" came from a flaky, non-portable kill (2026-10-04)

The note above ("type.c: add Narrow.ttf ... trusted") was wrong, and this corrects it. The
second font was a real improvement, but the claim that it lifted `GetTypeInfoByFamily` over the
bar relied on a kill that does not hold.

**What happened.** The scoring cases included queries against the `Arial` and `Helvetica`
families. Those families are also defined by the machine's system font config (the Mac resolves
64 `Helvetica` entries from Ghostscript/URW), so the scorer chose among dozens of ambiguous
entries, and which one won depended on the config load order. On the Mac that flaky choice
happened to make mutants `446:19` and `447:51` differ and so "killed" them, pushing the local
figure to 82%. It is not reproducible: a second Mac run did not repeat it, and ERDC (different
system fonts) never saw it. ERDC is the official measure for the Mac's files, and there
`GetTypeInfoByFamily` is **44 killed, gate 78.6% (adjusted 79%) — careful, not trusted**.

**What the second font genuinely bought, portably** (confirmed in ERDC's merged figure): four
scorer kills a single glyph file could not reach — `446:45` and `447:22` (the italic/oblique
`+25`, the clauses a case-local `ScoreFamily` query does decide), `458:22` (the stretch `range`),
and `473:66` (the fontmap index). That moved `GetTypeInfoByFamily` up but left it one kill short.

**Fix applied.** The `Arial`/`Helvetica` scoring queries and the `Score-Helvetica` entry are
removed from `cases.py`; scoring cases now query only `ScoreFamily`, whose entries live in the
case's own type.xml and do not depend on installed fonts. (The `-family Helvetica`/`Times,Courier` *annotate* commands at cases.py ~3220 were the same
hazard — families the system font config also defines — and have now been converted to case-local
`FamTest`/`SecondFam` families too, same code path, portable.)

**Still open** (`GetTypeInfoByFamily`, portable): `446:19`/`447:51` (the request/font italic
clauses — a clean case-local kill is blocked because command-line `-style` adds a synthetic slant
that masks which font was selected); `458:65` (the stretch divisor, order-preserving); `366`/
`369`/`371` (the first exact-match pass, very likely equivalent: breaking it is masked by the
scoring pass, which returns the same font because an exact match holds the unique maximum score
for the corpus's sub-900 weights); `475` and the fontmap/`family==NULL` lines `429`/`430`/`477`/
`478`. type.c stays **careful, not trusted**; the campaign-wide lesson is that a scoring case must
use a case-local family, never one the system font config also defines.

## type.c: trusted, honestly this time — two proven-equivalent verdicts close GetTypeInfoByFamily (2026-10-04)

After the correction above, `GetTypeInfoByFamily` stood at gate 78.6% on four real, portable
font-selection kills, one short of the bar. The gap is closed not with another kill but with two
**proven-equivalent** verdicts for the first exact-match pass:

- `369` `while (p != NULL)` → `== NULL` (disables the first pass), and
- `371` `if (p->family == NULL)` → `!=` (makes the first pass skip every real entry).

Both leave the first pass finding nothing, so control falls to the second (scoring) pass. That
pass returns the same entry the first pass would have: an exact match scores the unique maximum
`32+16+8=56` (exact style, equal weight, exact stretch), and for the corpus's sub-900 weights
"scores 56" is exactly the first pass's exact-match test — so the second pass's top scorer is the
first pass's exact match. Breaking the first pass is therefore masked by the second, and the
chosen font is unchanged. This holds on both machines (the verdicts apply to ERDC's reports too),
and every case-local scoring case leaves these two surviving; only the removed flaky Helvetica
case ever "killed" them. (`366`, the first pass's `ResetSplayTreeIterator`, is left unresolved:
its equivalence is subtler — it depends on the iterator's position when a family has several
equal matches — so it is not claimed here.)

With `369`/`371` equivalent, `GetTypeInfoByFamily` is **44 killed, gate 81.5% (adjusted 81%)**
and **type.c is trusted** (file adjusted 85%). The honest ledger: the second corpus font bought
four portable kills, and the pass-structure proof the last two; the earlier 82% via a flaky
Helvetica kill was never real.

## Upstream bug: no configuration `<include>` ever loads a file (Mac, 2026-10-04, night)

Found while driving locale.c. **`FileToXML(path,~0UL)` returns NULL for every regular file**, and every
configuration loader reads its `<include file=...>` through exactly that call: color.c, configure.c,
delegate.c, locale.c, log.c, mime.c and policy.c (type.c reads its includes another way, which is why
the type.xml include case works). For a seekable file FileToXML computes

    length=(size_t) MagickMin(offset,(MagickOffsetType) extent);

and `(MagickOffsetType) ~0UL` is `-1`, so the minimum is -1, `length` becomes SIZE_MAX, the
`~length >= MagickPathExtent-1` allocation guard refuses, and the function returns NULL. Reproduced in
isolation (a five-line C program with the same macro and types) and through the driver
(`GetPathComponent` gives the right directory; FileToXML of the existing file returns NULL), and seen
in `-debug configure`: the shipped `config/locale.xml`'s `<include locale="C" file="english.xml"/>` is
never followed; english.xml arrives only through AcquireLocaleSplayTree's empty-cache fallback.

Consequences, as the code behaves today:
- non-English locale files can never load, whatever LANG/LC_ALL say;
- **a policy.xml that includes another policy file silently ignores it** (a site policy split across
  files does not apply), and likewise for delegates, colours, logs, mime types and configure options;
- the include branches of all seven loaders are reached but can never load anything, so their mutants,
  and anything whose only effect is the locale string the include filter reads (IsLocaleTreeInstantiated's
  environment fallbacks), are unobservable. Those verdicts cite this bug.

Only a non-seekable file (a FIFO) takes FileToXML's other branch, which works; no case can make one.
**For the owner:** this is a real upstream defect (likely worth reporting); the campaign keeps the
behaviour as it is. If it is ever fixed, the verdicts that cite it must be revisited.

## The Mac's night: imdriver for the API-only Mac files (2026-10-04/05, night)

Owner-approved driver work (see "Owner's decisions"). Every number below is a **Mac
estimate**: the cases were hand-run against the Mac's Mull build (`mull-macx`) with each
mutant switched on, and checked for determinism. ERDC is the official measurer; its confirm
rounds rerun the survivors against each push, so the gate figures change only when those
rounds land. Compare the numbers here with ERDC's, not with each other.

**A harness fix the night depended on.** The macOS sandbox for mutated runs allowed only
`magick` to be executed, so every `@driver` case failed alike under it (status 71) and could
kill nothing on the Mac. `mutate.py` now allows the driver beside the binary too. Driver
cases always worked on Linux, so ERDC's earlier figures are unaffected. The oracle's cache
key also takes the driver's hash now, so a changed `imdriver` invalidates stale baselines.

**New imdriver commands, with the case directory first on `MAGICK_CONFIGURE_PATH`.**
`configure`, `logcfg`, `mimecfg` and `delegatecfg` prepend the case directory before
`MagickCoreGenesis`. The case's own configure.xml, log.xml, mime.xml or delegates.xml is
then parsed first and governs lookups. On the command line it is read only after the
build's own, and ordered by path, so no command-line case can compare it (see the locale and
log notes). The driver prints the case's path as `CASE`.

| file | driver command | what the cases vary | Mac kills |
|---|---|---|---|
| configure.c | `configure` | 7 configure.xml shapes (DOCTYPE, quoted `>`, unclosed comment, 4 KB boundary, includes) | parser survivors; include branch → verdicts |
| log.c | `logcfg` | 8 log.xml shapes (limit at/below/above 1024, unlimited, spaced handlers, events, stealth, include) | 8 kills; 5 include verdicts |
| mime.c | `mimecfg` | byte/short/long/string patterns, masks, LSB/MSB/host endianness, `offset:extent`, escapes, priorities, a pattern, includes; byte strings sized at and around each `offset+4` bound | all 31 GetMimeInfo survivors; 7 LoadMimeCache mutants whose "unobservable" verdicts were wrong (removed); include `depth` `>=`→`<` |
| delegate.c | `delegatecfg` | every %-letter as rose:'s fields change (quality 0, units cm, resolution exactly `MagickEpsilon`, rows/columns 0, extent, scenes, alpha), escapes and `&LT;`/`&GT;`/`&AMP;` (the loader decodes only lower case), lookups by decode/encode/mode, lists, multi-line commands, 7 parser shapes, InvokeDelegate of programs that do not exist, ExternalDelegateCommand against a policy that refuses all but a few tokens | 51 of 74 survivors, plus 34 that had verdicts or kinds (42 verdicts removed) |
| profile.c | `profile` | EXIF, 8BIM and XMP blobs built byte by byte at each bound (`profilecases.py`): IFDs with no room for a next pointer, Exif offsets to 0 / length−2 / length−1, nested IFDs that overlap the Exif IFD's entries at the nesting limit, a 225 KB IFD at offset 0 (0x4949 entries), 8BIM resources of size 0 or ending exactly at the end, clipping paths with ids 1999..2999, XMP resolutions as fractions, a max-profile-size policy | 61 of 98; the rest proven equivalent or leaks |
| log.c | `logcfg … COUNT LEN [method]` | every reproducible format letter, 5000-character events, file rotation (2 and 3 generations, a file at exactly its limit, append), a log method, console/stderr, an unwritable log file, two maps in one file, a log element in a comment | 49 of 99; copy limits never reached (equivalent), timings unobservable |
| also tonight | `string`, `symlink`, `metrics`, `memory`, `pathauth`, `nextimage`, `drawinfo` | see the commits and the sections above | string.c, utility.c, annotate.c, memory.c, policy.c, image.c, draw.c |

Two techniques worth keeping:

- **Deny all, allow a few.** A delegate policy refuses `*` and allows `nosuch`, the driver
  and `selfkill`. Which tokens are refused (`NotAuthorized`) shows which tokens
  `IsExecutableToken` hands to the policy. No program ever runs.
- **`@SELF selfkill`.** The driver runs itself as the delegate and kills itself with SIGKILL,
  which gives a child ended by a signal (status −1) without a shell. Both sandboxes allow it:
  the macOS profile allows the driver, and landlock allows the binary it started.

**Verdicts are now wrong in both directions, and were corrected.** Several mime.c and
delegate.c verdicts said "unobservable: only GetMimeInfo reads it" or "unobservable: the
oracle blocks every launch". The driver now kills those mutants, so 49 such verdicts were
deleted rather than left standing. New verdicts cover:

- leaks
- allocation and temporary-file failures
- the spawn wait (timing only)
- the include branches (see the FileToXML bug below)
- a CR-escape branch that StringToList makes unreachable (it splits commands at every CR)
- the popen output loop, which needs a shell that the sandbox does not have; this one stays **unresolved**

**draw.c, at two bounds no case had reached.**

- *CheckPrimitiveExtent* refuses an extent above max-memory-request / sizeof(PrimitiveInfo).
  The policy's floor is 16 MiB. An ellipse of radius 10000 swept to 247.2495° needs exactly
  that many primitives; the window is 0.0007° wide and was found by bisection, and the case
  sits in its middle. The resize after the test is then the one that fails, which kills
  `>` → `>=`.
- *The x clamp.* Two polygons starting just past the right edge kill it, through a zero-width
  row request.
- *Equivalent.* The y clamp (its row loop is simply empty), the bounds tests and the thread
  count.
- *The point branch* of DrawPolygonPrimitive (21 mutants) is **unreachable**, so its mutants
  are equivalent. The function returns at its top for one coordinate. With two or more, the
  first subpath always yields an edge: ConvertPrimitiveToPath always keeps the subpath's first
  and last points, and ConvertPathToPolygon makes every run of two or more points an edge. So
  `number_edges == 0` never holds either (also checked with `-debug draw`).
- *ClonePolygonEdgesTLS* is only reached with more than one thread. The oracle pins one
  (`MAGICK_THREAD_LIMIT=1`). A `-limit thread 4` case on a 1024×1024 polygon gives four
  threads where the build has OpenMP. The Mac's build caps the limit at 1, so only ERDC can
  measure it.

**locale.c's LocaleInfoCompare stays one function short.** Only one locale.xml can be
supplied: the current directory is not searched in this uninstalled build, and the build's
own files carry no messages, since their includes never load. So all entries share one path,
and the mutant answers "equal" for every pair. Whether qsort then keeps its input order
differs between macOS and glibc.

**Another upstream bug: `-list log` names the wrong handlers.** ListLogInfo prints handler
bit *j* under `LogHandlers[j].name`, but that table is alphabetical (Console, Debug, Event,
File, ...), not in bit order (Console, Stdout, Stderr, File, ...). So a log with
`output="stdout"` lists as "Debug" and `stderr` as "Event". Only Console and File come out
right. The driver's logcfg cases print it as it is.

**Verdict clean-up.** The night removed verdicts on mutants that are now killed, either in
ERDC's reports or by these cases: log, mime, delegate, profile and configure. The `gap`
records (verdicts carrying `killed_by`) are kept. The four log.c mutants at line 1440 (the
buffer-growth test) first looked inert, but the cause was the format's length. A wrong test
doubles the buffer once per format character. With 35 characters that is 141 TB, which macOS
still hands out lazily. A 60-character format overflows it, and the event is dropped. That
case kills two of the four. `>=` → `>` is equivalent (one character's delay, covered by the
free margin). `q-text` → `q+text` stays unresolved: it changes nothing even with 60
characters on the Mac.

**Open items for the owner:**

1. **The FileToXML upstream bug** (section above). No `<include>` in color, configure,
   delegate, locale, log, mime or policy .xml ever loads, which matters most for policy.xml.
   It is worth reporting upstream; doing so is the owner's decision.
2. **delegate.c 556 (`message != NULL` → `==`).** The driver reaches it (signal-killed
   child, no message buffer). The mutant's NULL read does not crash on the Mac, presumably
   because the compiler drops the undefined read. It is recorded as unresolved. Proving it
   would need the disassembly, or lldb with developer mode enabled. I did not enable
   developer mode.
3. **qsort comparators: a decision.** After tonight, the Mac files' remaining shortfalls
   (projected from the Mac's kills, pending ERDC) are almost all qsort comparators:
   - draw.c's StopInfoCompare, locale.c's LocaleInfoCompare and log.c's LogInfoCompare
   - earlier: mime.c's GetMimeList sort and type.c's tie-breaks

   Their mutants change only how ties or an inconsistent order are resolved. macOS's BSD
   qsort and glibc resolve those differently, so a kill on one platform is not a kill on the
   other. With six elements or fewer, BSD qsort uses insertion sort and glibc uses merge sort or
   (2.37 and later) insertion sort. None of these ever moves elements a comparator calls
   "equal" or "less". So most of these mutants are unobservable
   in practice but not provably equivalent. Each such function holds one to three mutants.
   Options:
   - (a) accept "unresolved, non-portable qsort tie" as not counted against the gate, which
     needs a new verdict kind;
   - (b) leave these functions below the bar, to be refactored only under extra review;
   - (c) replace qsort with a stable sort in the refactoring itself. That changes behaviour
     only for ties, so it is not a pure refactoring.

   The decision is the owner's. The remaining Mac-only exception is draw.c's
   ClonePolygonEdgesTLS (more than one thread), which only ERDC's OpenMP build can measure.
4. **ERDC confirmation.** The Mac numbers above are estimates. The confirm loop picks up
   each push (configure, log, mime, delegate, draw, image, policy, memory, annotate) and the
   resweep follows. Read the gate from ERDC's `mutation-erdc-confirm-<sha>-*.json` once they
   land.
