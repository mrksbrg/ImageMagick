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
`type.xml`**, which merge every file found; it does not for `locale.xml` and `log.xml`
(only the first file found is read, the build's), and a `policy.xml`'s `<include>` parses
but never loads (a `type.xml` include does). This opens code that earlier sections called
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
