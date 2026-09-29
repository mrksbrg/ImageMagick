#!/bin/bash
# Build a `magick` binary for the differential oracle.
#
#   tools/oracle/build.sh base <git-ref>   baseline from a clean worktree at <ref>
#   tools/oracle/build.sh cand             candidate from the working tree
#   tools/oracle/build.sh cov              candidate with clang source-based coverage
#   tools/oracle/build.sh mull <regex> [name]
#                                          candidate with Mull mutants in matching
#                                          files, in build-oracle/mull-<name>
#
# Every flavour uses the same configure flags (apart from coverage
# instrumentation), so any difference in output comes from the source and not
# from the build. Prints the path of the built binary on the last line of
# stdout.
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
              --disable-docs --without-x)
OPT_CFLAGS="-O2 -g"

configure_and_make() {  # <srcdir> <builddir> <extra cflags>
  local src=$1 bld=$2 extra=$3
  mkdir -p "$bld"
  if [ ! -f "$bld/Makefile" ]; then
    (cd "$bld" && CC=clang CXX=clang++ \
       CFLAGS="$OPT_CFLAGS $extra" CXXFLAGS="$OPT_CFLAGS $extra" LDFLAGS="$extra" \
       "$src/configure" "${CONFIG_FLAGS[@]}" > configure.log 2>&1) \
      || { echo "configure failed, see $bld/configure.log" >&2; exit 1; }
  fi
  make -C "$bld" -j"$JOBS" utilities/magick > "$bld/make.log" 2>&1 \
    || { tail -30 "$bld/make.log" >&2; echo "build failed, see $bld/make.log" >&2; exit 1; }
}

case "${1:-}" in
  base)
    ref=${2:?usage: build.sh base <git-ref>}
    sha=$(git -C "$ROOT" rev-parse --verify "$ref^{commit}")
    src="$OUT/src/$sha"
    bld="$OUT/base/$sha"
    if [ ! -x "$bld/utilities/magick" ]; then
      if [ ! -d "$src" ]; then
        git -C "$ROOT" worktree add --detach "$src" "$sha" > /dev/null 2>&1
      fi
      configure_and_make "$src" "$bld" ""
    fi
    echo "$bld/utilities/magick"
    ;;
  cand)
    configure_and_make "$ROOT" "$OUT/cand" ""
    echo "$OUT/cand/utilities/magick"
    ;;
  cov)
    configure_and_make "$ROOT" "$OUT/cov" "-fprofile-instr-generate -fcoverage-mapping"
    echo "$OUT/cov/utilities/magick"
    ;;
  mull)
    # Mutants compiled into the binary, each behind its own switch, for the
    # source files matching <path-regex> only. Needs Homebrew llvm@21 and the
    # matching Mull package in build-oracle/mull (see docs/refactoring/MUTATION.md).
    regex=${2:?usage: build.sh mull <path-regex> [name]}
    slug=${3:-$(echo "$regex" | tr -c 'A-Za-z0-9\n' '_')}
    bld="$OUT/mull-$slug"
    mkdir -p "$bld"
    # mull-ir-frontend reads mull.yml from the compiler's working directory
    # upwards; every object is compiled somewhere under $bld.
    # Single-quoted YAML: a regex's backslashes are not escapes there.
    printf "includePaths:\n  - '%s'\n" "$regex" > "$bld/mull.yml"
    llvm=/opt/homebrew/opt/llvm@21/bin
    plugin="$OUT/mull/lib/mull-ir-frontend-21"
    [ -x "$llvm/clang" ] && [ -f "$plugin" ] || { echo "llvm@21 or Mull missing" >&2; exit 1; }
    if [ ! -f "$bld/Makefile" ]; then
      # /usr/bin/ld explicitly: an older ld earlier on PATH (Anaconda's)
      # cannot read the current SDK.
      (cd "$bld" && CC="$llvm/clang" CXX="$llvm/clang++" \
         CFLAGS="$OPT_CFLAGS -grecord-command-line -fpass-plugin=$plugin" \
         CXXFLAGS="$OPT_CFLAGS" LDFLAGS="-fuse-ld=/usr/bin/ld" \
         "$ROOT/configure" "${CONFIG_FLAGS[@]}" > configure.log 2>&1) \
        || { echo "configure failed, see $bld/configure.log" >&2; exit 1; }
    fi
    make -C "$bld" -j"$JOBS" utilities/magick > "$bld/make.log" 2>&1 \
      || { tail -30 "$bld/make.log" >&2; echo "build failed, see $bld/make.log" >&2; exit 1; }
    echo "$bld/utilities/magick"
    ;;
  *)
    sed -n '2,17p' "$0" >&2
    exit 2
    ;;
esac
