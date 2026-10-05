#!/bin/bash
# Build a `magick` binary for the differential oracle.
#
#   tools/oracle/build.sh base <git-ref>   baseline from a clean worktree at <ref>
#   tools/oracle/build.sh cand             candidate from the working tree
#   tools/oracle/build.sh cov              candidate with clang source-based coverage
#   tools/oracle/build.sh mull <regex> [name]
#                                          candidate with Mull mutants in matching
#                                          files, in build-oracle/mull-<name>;
#                                          defaults plus statement deletion,
#                                          MULL_MUTATORS="..." to choose others
#   tools/oracle/build.sh wide             candidate with X11 and OpenCL as well,
#                                          in build-oracle/wide (WIDE=1 cand)
#   tools/oracle/build.sh win              on Windows, from MSYS2 UCRT64: gcc,
#                                          compiles nt-base.c, nt-feature.c and
#                                          the Windows branches (needs a checkout
#                                          with LF line endings)
#
# The oracle flavours (base, cand, cov, mull) use the same configure flags
# (apart from coverage instrumentation), so any difference in output comes
# from the source and not from the build. Prints the path of the built binary
# on the last line of stdout.
#
# WIDE=1 before any flavour adds X11 and OpenCL (--with-x --enable-opencl), for
# display.c, xwindow.c, widget.c, animate.c, accelerate.c and opencl.c, in
# build directories of their own: base-wide/<sha>, cand-wide, cov-wide (mull:
# give it a name of its own). The oracle runs their cases under Xvfb and pocl
# (oracle.py, start_xvfb and seed_opencl_profile).
#
# Builds live under build-oracle/, which .git/info/exclude keeps out of git.
# A baseline is built once per commit and then reused; the candidate build is
# incremental.
set -euo pipefail

# Called from an x86_64 Python under Rosetta, the toolchain would start as
# x86_64 too and fail to load; run natively instead.
if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ]; then
  exec /usr/bin/arch -arm64 /bin/bash "$0" "$@"
fi

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$ROOT/build-oracle"
JOBS=${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}

# Fixed configuration for all oracle builds.
#  --disable-openmp   thread scheduling must not be able to change results
#  --disable-shared   one self-contained binary, no libtool wrapper scripts
CONFIG_FLAGS=(--disable-shared --enable-static --disable-openmp --without-perl
              --disable-docs)
SUFFIX=""
if [ -n "${WIDE:-}" ]; then
  CONFIG_FLAGS+=(--with-x --enable-opencl)
  SUFFIX=-wide
else
  CONFIG_FLAGS+=(--without-x)
fi
OPT_CFLAGS="-O2 -g"
# Ubuntu's libraw_r.pc links with -fopenmp, which clang resolves to libomp;
# LibRaw itself is built against GCC's libgomp, so link that one instead.
# ImageMagick stays without OpenMP, and the oracle sets OMP_NUM_THREADS=1.
LINK_FLAGS=""
[ "$(uname)" = Linux ] && LINK_FLAGS="-fopenmp=libgomp"
# SYSROOT: a toolchain and libraries unpacked from .debs without root (a
# container with no sudo). Its libraries are found at run time through an
# rpath, since the oracle runs magick with a clean environment.
SYSROOT=${SYSROOT:-}
[ -n "$SYSROOT" ] && LINK_FLAGS="$LINK_FLAGS -Wl,-rpath,$SYSROOT/usr/lib/x86_64-linux-gnu"

CC_NAME=clang CXX_NAME=clang++ EXE=""

configure_and_make() {  # <srcdir> <builddir> <extra cflags> [configure flags...]
  local src=$1 bld=$2 extra=$3
  shift 3
  mkdir -p "$bld"
  if [ ! -f "$bld/Makefile" ]; then
    # Later flags win, so the extra ones can override CONFIG_FLAGS.
    (cd "$bld" && CC=$CC_NAME CXX=$CXX_NAME \
       CFLAGS="$OPT_CFLAGS $extra" CXXFLAGS="$OPT_CFLAGS $extra" LDFLAGS="$LINK_FLAGS $extra" \
       "$src/configure" "${CONFIG_FLAGS[@]}" "$@" > configure.log 2>&1) \
      || { echo "configure failed, see $bld/configure.log" >&2; exit 1; }
  fi
  make -C "$bld" -j"$JOBS" "utilities/magick$EXE" > "$bld/make.log" 2>&1 \
    || { tail -30 "$bld/make.log" >&2; echo "build failed, see $bld/make.log" >&2; exit 1; }
  # imdriver, for the cases that call the API (driver/build.sh); without it those cases
  # fail alike in every run of this build
  "$ROOT/tools/oracle/driver/build.sh" "$bld" > /dev/null 2>> "$bld/make.log" \
    || echo "imdriver not built, see $bld/make.log" >&2
}

case "${1:-}" in
  base)
    ref=${2:?usage: build.sh base <git-ref>}
    sha=$(git -C "$ROOT" rev-parse --verify "$ref^{commit}")
    src="$OUT/src/$sha"
    bld="$OUT/base$SUFFIX/$sha"
    if [ ! -x "$bld/utilities/magick" ]; then
      if [ ! -d "$src" ]; then
        git -C "$ROOT" worktree add --detach "$src" "$sha" > /dev/null 2>&1
      fi
      configure_and_make "$src" "$bld" ""
    fi
    # a cached baseline still needs today's imdriver (driver/build.sh rebuilds it only when
    # driver/imdriver.c or the library is newer), or every new driver command fails on it
    "$ROOT/tools/oracle/driver/build.sh" "$bld" > /dev/null 2>> "$bld/make.log" \
      || echo "imdriver not built, see $bld/make.log" >&2
    echo "$bld/utilities/magick"
    ;;
  cand)
    configure_and_make "$ROOT" "$OUT/cand$SUFFIX" ""
    echo "$OUT/cand$SUFFIX/utilities/magick"
    ;;
  cov)
    configure_and_make "$ROOT" "$OUT/cov$SUFFIX" "-fprofile-instr-generate -fcoverage-mapping"
    echo "$OUT/cov$SUFFIX/utilities/magick"
    ;;
  mull)
    # Mutants compiled into the binary, each behind its own switch, for the
    # source files matching <path-regex> only. Needs, on macOS, Homebrew
    # llvm@21 and the matching Mull package in build-oracle/mull, and on Linux
    # the Mull .deb for the system clang's LLVM (see docs/refactoring/MUTATION.md).
    regex=${2:?usage: build.sh mull <path-regex> [name]}
    slug=${3:-$(echo "$regex" | tr -c 'A-Za-z0-9\n' '_')}
    bld="$OUT/mull-$slug"
    mkdir -p "$bld"
    # mull-ir-frontend reads mull.yml from the compiler's working directory
    # upwards; every object is compiled somewhere under $bld.
    # Single-quoted YAML: a regex's backslashes are not escapes there.
    # The operators: Mull's defaults plus statement deletion (cxx_remove_void_call),
    # the project's set since 2026-10-02 (HARNESS-SPLIT.md). MULL_MUTATORS
    # (space-separated) replaces them, e.g. "cxx_default" for the old set.
    printf "includePaths:\n  - '%s'\n" "$regex" > "$bld/mull.yml"
    printf "mutators:\n" >> "$bld/mull.yml"
    for m in ${MULL_MUTATORS:-cxx_default cxx_remove_void_call}; do
      printf "  - %s\n" "$m" >> "$bld/mull.yml"
    done
    if [ "$(uname)" = Darwin ]; then
      llvm=/opt/homebrew/opt/llvm@21/bin
      plugin="$OUT/mull/lib/mull-ir-frontend-21"
      # /usr/bin/ld explicitly: an older ld earlier on PATH (Anaconda's)
      # cannot read the current SDK.
      ldflags="-fuse-ld=/usr/bin/ld"
    else
      # The system clang's LLVM, and the Mull .deb built for that version.
      major=$(clang -dumpversion | cut -d. -f1)
      llvm=$SYSROOT/usr/lib/llvm-$major/bin
      plugin=$SYSROOT/usr/lib/mull-ir-frontend-$major
      ldflags="$LINK_FLAGS"
    fi
    [ -x "$llvm/clang" ] && [ -f "$plugin" ] || { echo "$llvm/clang or $plugin missing" >&2; exit 1; }
    if [ ! -f "$bld/Makefile" ]; then
      (cd "$bld" && CC="$llvm/clang" CXX="$llvm/clang++" \
         CFLAGS="$OPT_CFLAGS -grecord-command-line -fpass-plugin=$plugin" \
         CXXFLAGS="$OPT_CFLAGS" LDFLAGS="$ldflags" \
         "$ROOT/configure" "${CONFIG_FLAGS[@]}" > configure.log 2>&1) \
        || { echo "configure failed, see $bld/configure.log" >&2; exit 1; }
    fi
    make -C "$bld" -j"$JOBS" utilities/magick > "$bld/make.log" 2>&1 \
      || { tail -30 "$bld/make.log" >&2; echo "build failed, see $bld/make.log" >&2; exit 1; }
    echo "$bld/utilities/magick"
    ;;
  wide)
    # The candidate of WIDE=1, under its first name.
    configure_and_make "$ROOT" "$OUT/wide" "" --with-x --enable-opencl
    echo "$OUT/wide/utilities/magick"
    ;;
  win)
    case "$(uname)" in
      MINGW*|MSYS*) ;;
      *) echo "build.sh win runs on Windows, in an MSYS2 UCRT64 shell" >&2; exit 1 ;;
    esac
    if head -1 "$ROOT/configure" | grep -q $'\r'; then
      echo "configure has CRLF line endings: use a clone made with core.autocrlf=false" >&2
      exit 1
    fi
    CC_NAME=gcc CXX_NAME=g++ EXE=.exe
    configure_and_make "$ROOT" "$OUT/win" "" --without-modules
    echo "$OUT/win/utilities/magick.exe"
    ;;
  *)
    sed -n '2,27p' "$0" >&2
    exit 2
    ;;
esac
