# The differential oracle

`tools/oracle/` checks that a change to ImageMagick has not changed its
behaviour. It builds a baseline `magick` from a git ref and a candidate from the
working tree, runs the same catalogue of about 9,000 command lines on both, and
fails unless every result is **identical**. There is no tolerance: exit status,
stdout, stderr and the bytes of every file written must match.

It exists because `make check` cannot do this job. Most of `tests/validate`
checks only that a command returned success, and the PerlMagick reference
comparisons allow small errors by design. A refactoring that shifts one
pixel by one unit passes both.

## Using it

```bash
tools/oracle/oracle.py run                      # working tree against origin/main
tools/oracle/oracle.py run --base HEAD~1        # against another ref
tools/oracle/oracle.py run --filter '^compose/' # a subset, by case id or label
tools/oracle/oracle.py run --function ScaleImage # only the cases that execute a function
tools/oracle/oracle.py run --explain            # add pixel deltas for divergences
tools/oracle/oracle.py list [-v]                # what the catalogue contains
tools/oracle/oracle.py selfcheck                # baseline against itself
```

The baseline is built once per commit and its results are cached per binary,
so after the first run only the candidate executes. A warm run takes about
2 minutes on an 8-core M-series Mac; a cold run (new baseline) about 3.5.
The candidate build is incremental: a one-file change rebuilds in seconds.

`--function` picks the cases from `build-oracle/work/casemap.json`, so a
refactoring commit is checked in seconds rather than minutes; it refuses a
function no case executes. It was tried on a real change before the campaign
started: Recipe P on `url_encode` in `resize.c` passed on all 78 cases that
reach it in 9 seconds, and the same change with its condition inverted, which
`refactor_guard.py` cannot see, diverged on 23 of them.

A divergence is reported with the command line and what differed. Candidate
outputs of diverging cases are kept in `build-oracle/work/runs/cand/`, and the
full list goes to `build-oracle/work/last-report.json`.

Everything the oracle builds or writes lives in `build-oracle/`, which
`.git/info/exclude` keeps out of git.

## What a case is

A case is one or more `magick` invocations in an empty directory. The catalogue
in `tools/oracle/cases.py` is generated, not hand-listed, wherever ImageMagick
can enumerate its own options: every compose operator, distort method,
morphology method crossed with every kernel, resize filter, colorspace,
evaluate operator, statistic, layer method, metric, virtual-pixel method and
so on comes from `magick -list <name>` on the baseline. The families are
listed below.

| Family | Cases | What it covers |
| --- | ---: | --- |
| unary | ~2,300 | about 250 operators, including everything in `tests/validate.h`, on 9 inputs |
| morphology | ~1,950 | every method × every kernel, on colour and bilevel input |
| encode | ~900 | every writable native format and its options, then decoding what was written |
| convert, mogrify | ~760 | the unary operators through `MagickWand/mogrify.c`, the legacy front end |
| compose | ~550 | every compose operator on 5 image pairs, plus `compose:sync` and `compose:clamp` |
| colorspace | ~410 | to every colorspace and back, on 5 inputs |
| raw, stream | ~620 | pixel import and export at every depth, storage type and interlace |
| filter, distort, interpolate, virtual-pixel | ~420 | every filter, distort method, interpolation and edge method |
| decode | ~200 | PerlMagick's reader corpus and the repository's test images |
| format, fx-print, identify | ~200 | `-format` escapes and fx functions at `-precision 17`, `identify -verbose` |
| draw, text, gen, montage, sequence, multi, ... | ~500 | drawing primitives, fonts, generators, multi-image operators |

### Inputs

The corpus (`build-oracle/work/corpus/`) is built once from ImageMagick's
built-in images and the repository's test files, then frozen. It includes an
image with alpha, 16-bit gray, CMYK, a palette image, a bilevel image,
**HDRI data outside [0,1]**, a multi-frame sequence and animation, and
degenerate 1×1 and 3×46 images. Every file is given the same modification time,
because file dates end up in image properties.

## Making results reproducible

Two builds of the same source must give byte-identical results, or every run
drowns in false alarms. This took the following, each found by `selfcheck`:

- **Builds:** `--disable-openmp`, static, and the same flags for baseline and
  candidate (`tools/oracle/build.sh`).
- **Randomness:** every invocation gets `-seed 1` (after the subcommand name
  for `compare`, `identify`, `convert`, ...). Noise operators, `-sketch`,
  `-spread` and `-virtual-pixel Random` otherwise read `/dev/urandom`.
- **Time:** `SOURCE_DATE_EPOCH` is set, and timing lines (`Elapsed time`,
  `0.010u 0:00.020`, JSON's `elapsedTime`, ...) are normalised. The PDF writer
  dates its output from the file's ctime instead (see Known upstream issues),
  so `/CreationDate` and `/ModDate` are normalised too.
- **Paths:** each side runs in its own directory. Absolute case paths and
  random temporary file names are normalised out of stdout, stderr and text
  outputs.
- **Source locations:** exception messages end in
  `@ error/file.c/Function/line`. Refactoring legitimately changes all three,
  so the location is normalised; the message text is still compared.
- **No external programs:** readers that hand off to Ghostscript, ffmpeg or
  LibreOffice (PS, PDF, EPS, video, WMF without libwmf) are excluded.
  Two `decode` cases still slip through: `decode/807953767f` and
  `decode/ce0b30b528` read HPGL files, which ImageMagick hands to the
  `hp2xx` delegate through `/bin/sh`. `hp2xx` is not installed, so both
  fail, and their stderr depends on the shell. One of them left a temporary
  file that vanished mid-read and crashed a mutation run. They should be
  removed from the catalogue.

Images are written as 32-bit floating-point MIFF. Under Q16 HDRI this preserves
every pixel value exactly, so the comparison sees rounding differences that an
8- or 16-bit output would hide.

`selfcheck` runs the baseline twice without the cache and reports anything
that differs from itself. It must report 0 before a clean `run` means
anything; run it after changing the catalogue, with `--repeat 4` or more.
Two runs are not enough: a case that goes wrong one time in three agrees with
itself in more than half of all pairs, and one such case (see Known upstream
issues) went unnoticed for a day. A case that times out on the
baseline is reported by `run` as a catalogue bug: it compares nothing and costs
30 seconds on every run.

## What it reaches

Line coverage, measured with a coverage build (`tools/oracle/build.sh cov`,
then `LLVM_PROFILE_FILE=... oracle.py exec --bin build-oracle/cov/utilities/magick`):

| | Lines | Oracle | `make check` | Both |
| --- | ---: | ---: | ---: | ---: |
| MagickCore | 116,787 | **58.5%** | 41.1% | 62.5% |
| coders | 104,682 | **43.0%** | 26.7% | 45.8% |
| MagickWand | 32,963 | 29.5% | 21.4% | 36.2% |
| Magick++/lib | 10,712 | 0.0% | 33.2% | 33.2% |
| **Total** | 265,286 | **46.4%** | 32.7% | 51.4% |

Coverage is not the same as checking. For the oracle the two are close, because
every output it produces is compared. For `make check` they are not: most of
its coverage comes from commands whose output nobody looks at.

Where the oracle is weak:

- **The C and C++ APIs.** `MagickWand/magick-image.c`, `drawing-wand.c`,
  `deprecate.c` and all of Magick++ are unreachable from the command line.
  `make check` exercises them, so refactoring there needs a new harness.
- **`pixel.c`** (36%) and **`profile.c`** (19%): storage conversions the CLI
  does not expose, and ICC and metadata profiles, which need profile files
  that are not in the corpus.
- **Coders for missing delegates.** HEIC, RAW, UHDR, JBIG, DjVu, FFTW, LQR
  and RSVG are not installed on the reference machine, so their code is not
  compiled in.
- **Long-tail branches** inside covered functions. Branch coverage is lower
  than line coverage in every file.

Before refactoring a function, check that the oracle reaches it: measure its
coverage, or better, run a mutant (below) and see whether the oracle catches
it. If it does not, extend the catalogue first.

## Does it catch changes?

Four changes were injected by hand, each the kind of slip a refactoring makes,
and the oracle was run on each one:

| Change | Result |
| --- | --- |
| `resize.c` Triangle filter returns `1.0-x-1e-9` | caught, 14 cases |
| `composite.c` Screen drops `RoundToUnity` on the source | caught, 3 cases, after adding HDRI **source** pairs |
| `fx.c` `hypot(a,b)` rewritten as `sqrt(a*a+b*b)` | caught, 1 case, after adding off-grid `-precision 17` cases |
| `resize.c` `x < 1.0` becomes `x <= 1.0` (equivalent at x = 1) | not flagged, correctly |

The two misses in the first round were gaps in the catalogue, not in the
method. The Screen change only matters when the source is out of range, and
no case put HDRI data in the source. `hypot` and `sqrt` agree exactly on the
integer arguments the corpus produced, and default 6-digit output hid the
remaining bits. Both gaps were closed. Mutation testing should be how the
catalogue grows from here: a surviving mutant is a named gap to close.

## Known upstream issues

Found while making the oracle reproducible. Report them; do not fix them in a
refactoring commit.

- **Displace and Distort compose leave part of the canvas uninitialised.**
  In `CompositeImage()` (`MagickCore/composite.c`), both operators fetch each
  canvas row with `QueueCacheViewAuthenticPixels` and write only
  `x < source_image->columns`. When the destination is wider than the source,
  the remaining columns are synced back from an uninitialised buffer, and the
  output changes from run to run: `magick rose: -size 64x48 gradient: -compose
  distort -define compose:args=20x10 -composite out.miff` differs in a 6×43
  strip at x = 64–69. AddressSanitizer reports nothing, so it is not an
  out-of-bounds access. The catalogue avoids this case (`DEST_WIDER_UNSTABLE`
  in `cases.py`).
- **`-scale` under a write mask leaves output pixels unwritten.**
  `magick rose: -write-mask bilevel.miff -scale 50% +write-mask out.miff`
  (with the corpus's bilevel mask) gives different output from run to run:
  under a parallel load, 19 of 64 runs of the same command differed from the
  rest, by garbage values rather than rounding (an absolute-error count of
  about 4e36 between the variants). Where the mask forbids a write,
  `ScaleImage` apparently leaves the destination pixel as it found it, in a
  cache that was never initialised. Run alone, the output looks stable, so
  `selfcheck` with two runs missed it; it had been counted as a kill in 155
  mutation runs before it was found. The catalogue avoids this case
  (`WRITE_MASK_UNSTABLE` in `cases.py`); the eleven other write-mask cases
  were stable in 16 runs each.
- **The PDF writer does not consult `SOURCE_DATE_EPOCH`.** `GetPdfCreationDate()`
  in `coders/pdf.c` uses `-define pdf:create-epoch` if given, and otherwise the
  output file's ctime, which cannot be set. So PDF output is not reproducible
  without that define. This is a design choice rather than a bug, but it is
  inconsistent with the rest of ImageMagick.
- **Single-channel raw reads and `-sample` under a write mask read unwritten heap
  memory** (found on Linux, 2026-09-30). Reading `r:`, `g:`, `k:`, `o:` and the other
  one-channel raw formats back into a full image, and `-sample` under a write mask,
  gave different output from run to run under glibc: 40 of 9,745 cases in the first
  `selfcheck`. With `MALLOC_PERTURB_` set, the output is the same for the same fill byte
  and differs between fill bytes, so the code reads heap memory it never wrote. The
  oracle sets a fixed `MALLOC_PERTURB_` on Linux (`oracle.env_for`), which makes the
  cases reproducible but hides the reads. On the Mac they happened to be stable.
- **Reading BGRO as floating point is not reproducible** (Linux, 2026-09-30).
  `magick -size 70x46 -depth 64 -define quantum:format=floating-point bgro:enc out.miff`,
  on a file the same build wrote, gives 3 different images in 12 runs, single-threaded
  and with a fixed `MALLOC_PERTURB_`; 24- and 32-bit floats vary too, integer and signed
  BGRO do not, nor does RGBO at any depth. So it is not a heap read the fill byte would
  pin down: `ImportBGROQuantum` in `MagickCore/quantum-import.c`, floating-point branch,
  is the place to look (MemorySanitizer or Valgrind would say more). The catalogue
  leaves those cases out (`QUANTUM_UNSTABLE` in `cases.py`).
- **`tile:` under `-compose multiply` composes onto an uninitialised canvas** (Windows,
  2026-10-02). `magick -size 40x30 -compose multiply tile:rose_patch.miff out.miff` gave
  a different image in 1 of 4 runs without a fixed `MALLOC_PERTURB_`, and a mean near
  5e-50 where black is expected: `TextureImage` composes the tile onto a canvas it never
  cleared. The oracle's fixed `MALLOC_PERTURB_` may hide it, so the catalogue keeps
  `tile:` to the default compose (`_texture_gap_cases` in `cases.py`).
- **Quantizing an image with very many colours is not reproducible** (Windows,
  2026-10-02). `magick hald:8 -colors 64 out.miff` (262,144 colours) gave two different
  images in 10 runs (4 and 6), under the oracle's environment (one thread, fixed
  `MALLOC_PERTURB_`), with or without `-treedepth` and dithering; `hald:8` alone was the
  same every time. Likely the colour-tree pruning that runs when the tree outgrows
  `MaxQNodes` (`PruneLevel` in `quantize.c`), so that function stays untested.
- **`+noise Random` with `-seed` is not reproducible at 600x600** (Windows, 2026-10-02).
  `magick -seed 3 -size 600x600 xc: +noise Random out.miff` gave two different images in
  12 runs (7 and 5) under the oracle's environment; at 48x48 it was the same in 12 of 12,
  so the catalogue's noise images stay small.
- **The raw single-channel writers switch on the input's format** (Windows,
  2026-10-02). `WriteRAWImage` (`coders/raw.c`) picks the channel from `*image->magick`,
  the format the image was read from, not the one being written. From a MIFF (`M...`)
  every `r:`, `g:`, `b:`, `a:`, `o:`, `k:` write fails with ColorSeparatedImageRequired
  (the Magenta case); from a PNG, `o:` writes 3,220 bytes through the default case, not
  opacity. The catalogue's raw single-channel cases read MIFF, so they test this error, and
  `ExportOpacityQuantum` is reached only through RGBO and BGRO with `-interlace line`.
