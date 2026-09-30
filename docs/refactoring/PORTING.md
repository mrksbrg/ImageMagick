# Moving the campaign to Linux (WSL2)

The campaign was set up on a MacBook (Apple silicon, macOS). The plan is to drive the
refactoring from a Windows desktop, inside **WSL2 (Ubuntu)**: the tools need a Unix
environment, Mull has no native Windows build, and Linux makes several gaps from the
macOS setup go away. This note lists what has to change and what has to be measured
again.

## Why WSL2 and not native Windows

- `tools/oracle/build.sh` drives ImageMagick's `configure` with clang; Mull, the mutation
  tool, ships Ubuntu packages and no Windows build.
- On Ubuntu the missing delegate libraries are one `apt install` away (below), so the
  coders the Mac cannot compile - HEIC, RAW, JBIG, DjVu, FFTW, LQR, RSVG - become
  testable. FFTW alone brings `fourier.c` and the `SIM*` functions in `compare.c` into
  reach.
- `libx11-dev` compiles `display.c`, `xwindow.c` and `widget.c`, and `pocl` provides
  OpenCL on the CPU for `accelerate.c` and `opencl.c`.
- MemorySanitizer, the tool for uninitialised reads (the Displace/Distort compose issue
  in `ORACLE.md` is one), exists only on Linux.

Windows-only code (`nt-base.c`, `nt-feature.c`) still needs a native build; a Visual
Studio build, as ImageMagick's own Windows releases use, can at least compile-check it.

**Keep the clone on the Linux filesystem** (`~/...`), not under `/mnt/c`. The oracle runs
about 9,500 cases, each with its own directory, and file access across that boundary is
several times slower.

## macOS-specific code in the tools

| File | Line(s) | macOS | Linux |
| --- | --- | --- | --- |
| `tools/oracle/build.sh` | Rosetta check (`sysctl.proc_translated`, `arch -arm64`) | re-executes natively when called from an x86_64 Python | not needed; the check already falls through when `sysctl` is missing |
| `tools/oracle/build.sh` | `JOBS` | `sysctl -n hw.ncpu` | already falls back to `nproc` |
| `tools/oracle/build.sh` | Mull build | `llvm=/opt/homebrew/opt/llvm@21/bin`, plugin from the macOS Mull zip, `-fuse-ld=/usr/bin/ld` (Anaconda's `ld` shadows the system one) | the LLVM version matching the Mull `.deb` (`/usr/lib/llvm-NN/bin`), its plugin from the package, no `-fuse-ld` |
| `tools/oracle/casemap.py` | `PROFDATA` | `/Library/Developer/CommandLineTools/usr/bin/llvm-profdata`, called directly because `xcrun` fails under Rosetta | `llvm-profdata` from the same LLVM that builds the coverage binary |
| `tools/oracle/mutate.py` | `LLVM_COV` | Command Line Tools path | `llvm-cov` from the same LLVM |
| `tools/oracle/mutate.py` | `sandbox()` | `sandbox-exec` profile: only `magick` may execute, no network, writes only under `build-oracle/` | **must be replaced, not dropped**: `bwrap` (bubblewrap) with the build tree bound writable, everything else read-only, `--unshare-net`, and no other binaries on the path. See `MUTATION.md`, "Every mutated run is sandboxed", for why |
| `tools/oracle/oracle.py` | `env_for` `PATH` | includes `/opt/homebrew/bin` | harmless on Linux; keep or drop |
| `tools/ch.py` | fallback `cs-mcp` path | `/opt/homebrew/bin/cs-mcp` | found on `PATH`; install `cs-mcp` and `cs` for Linux |

Best done as platform detection in each tool rather than a Linux fork of them, so both
machines keep working.

## Packages

```bash
sudo apt install build-essential clang lld llvm git python3 pkg-config \
  libpng-dev libjpeg-dev libtiff-dev libwebp-dev libopenjp2-7-dev libjxl-dev \
  libheif-dev libraw-dev libjbig-dev libdjvulibre-dev libfftw3-dev liblqr-1-0-dev \
  librsvg2-dev libxml2-dev libzip-dev liblzma-dev libzstd-dev libbz2-dev \
  libfreetype-dev libfontconfig-dev liblcms2-dev libx11-dev libxext-dev \
  ocl-icd-opencl-dev pocl-opencl-icd bubblewrap
```

Mull: the `.deb` for the Ubuntu release and the LLVM version it names, from the Mull
releases page.

## What must be measured again

Nothing measured on the Mac transfers as a number. Different libraries, fonts and
compilers give different outputs, and more code compiles.

1. `tools/oracle/oracle.py selfcheck` must report 0 nondeterministic before anything
   else. Expect new sources of noise with the new delegates, and fix each as ORACLE.md
   describes.
2. The case map (`tools/oracle/casemap.py`) and the coverage run.
3. The Code Health baseline, with the Linux `cs` and `cs-mcp` versions recorded. Scores
   should match the Mac's for the same source and version; if they do not, record that.
4. Mutation sweeps, starting with the files that newly compile.

What does transfer: the case catalogue and its additions, the survivor analysis in
`MUTATION.md` (kinds of survivor, gaps found), the playbook, and the lessons recorded in
the tools' comments.

## Settings that differ on Windows machines

If any part runs in native Windows after all (for example CodeScene through its Windows
MCP server), keep paths with forward slashes: the 3SX tools found that backslashes get
mangled through several layers.
