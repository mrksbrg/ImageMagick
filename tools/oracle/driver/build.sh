#!/bin/bash
# build.sh BUILDDIR: link imdriver against BUILDDIR's own MagickCore (as utilities/magick is
# linked, by the build's libtool), next to it: BUILDDIR/utilities/imdriver. The oracle runs a
# case step that starts with @driver with the imdriver beside the binary under test.
set -euo pipefail
B=$(cd "$1" && pwd)
SRC=$(cd "$(dirname "$0")" && pwd)
cd "$B"
LIB=$(ls MagickCore/.libs/libMagickCore-7.*.a | head -1)
if [ -x utilities/imdriver ] && [ utilities/imdriver -nt "$LIB" ] && [ utilities/imdriver -nt "$SRC/imdriver.c" ]; then
  echo "$B/utilities/imdriver"; exit 0
fi
CC=$(sed -n 's/^CC = //p' Makefile)
CFLAGS=$(sed -n 's/^CFLAGS = //p' Makefile | sed 's/-fpass-plugin=[^ ]*//')
CPPFLAGS=$(sed -n 's/^CPPFLAGS = //p' Makefile)
TOP=$(sed -n 's/^abs_top_srcdir = //p' Makefile)
$CC $CFLAGS $CPPFLAGS -I"$B" -I"$TOP" -c "$SRC/imdriver.c" -o utilities/imdriver.o
./libtool --silent --tag=CC --mode=link $CC $CFLAGS $(sed -n 's/^LDFLAGS = //p' Makefile) \
  -o utilities/imdriver utilities/imdriver.o MagickCore/libMagickCore-7.*.la
echo "$B/utilities/imdriver"
