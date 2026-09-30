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
