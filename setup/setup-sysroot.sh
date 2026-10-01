#!/bin/bash
# Unpack clang 18, Mull 0.34.1 and ImageMagick's delegate libraries into ~/sysroot, without root.
set -euo pipefail
S=$HOME/sysroot; D=$HOME/debs; mkdir -p $S $D
A="-o Dir::State::Lists=$HOME/apt/lists -o Dir::Cache=$HOME/apt/cache -o Debug::NoLocking=1 -o APT::Sandbox::User=$(id -un)"
PKGS="clang-18 lld-18 llvm-18 libclang-rt-18-dev pkgconf
  libpng-dev libjpeg-dev libtiff-dev libwebp-dev libopenjp2-7-dev libjxl-dev
  libheif-dev libraw-dev libjbig-dev libdjvulibre-dev libfftw3-dev liblqr-1-0-dev
  librsvg2-dev libxml2-dev libzip-dev liblzma-dev libzstd-dev libbz2-dev
  libfreetype-dev libfontconfig-dev liblcms2-dev"
echo "== resolving (only what the host lacks)"
apt-get $A install -qq --print-uris $PKGS 2>/dev/null | grep -o "^'[^']*'" | tr -d "'" > $D/uris.txt
echo "$(wc -l < $D/uris.txt) packages to fetch"
(cd $D && xargs -n 20 -P 4 curl -fsSL --remote-name-all < uris.txt)
MULL=Mull-18-0.34.1-LLVM-18.1.3-ubuntu-amd64-24.04.deb
(cd $D && curl -fsSLO https://github.com/mull-project/mull/releases/download/0.34.1/$MULL)
echo "== unpacking $(ls $D/*.deb | wc -l) debs"
for f in $D/*.deb; do dpkg-deb -x "$f" $S; done
echo "== repointing pkg-config files and absolute symlinks into ~/sysroot"
find $S -name '*.pc' -exec sed -i "s#=/usr#=$S/usr#; s#-I/usr/#-I$S/usr/#g; s#-L/usr/#-L$S/usr/#g" {} +
find $S -type l -lname '/*' | while read l; do t=$(readlink "$l"); [ -e "$S$t" ] && ln -sfn "$S$t" "$l"; done
cat > $HOME/sysroot.env <<ENV
export SYSROOT=$S
export PATH=$S/usr/lib/llvm-18/bin:$S/usr/bin:\$PATH
export LD_LIBRARY_PATH=$S/usr/lib/x86_64-linux-gnu:$S/usr/lib/llvm-18/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export CPATH=$S/usr/include:$S/usr/include/x86_64-linux-gnu
export LIBRARY_PATH=$S/usr/lib/x86_64-linux-gnu
export PKG_CONFIG_PATH=$S/usr/lib/x86_64-linux-gnu/pkgconfig:$S/usr/share/pkgconfig
ENV
. $HOME/sysroot.env
echo "== checks"
clang --version | head -1
ls $S/usr/lib/mull-ir-frontend-18 && echo "mull plugin: ok"
printf 'int f(int a,int b){return a+b;}\nint main(void){return f(1,2)!=3;}\n' > /tmp/m.c
printf "includePaths:\n  - '.*'\n" > /tmp/mull.yml
(cd /tmp && clang -O1 -g -grecord-command-line -fpass-plugin=$S/usr/lib/mull-ir-frontend-18 m.c -o m.out 2>&1 | tail -3) && /tmp/m.out && echo "mull compile: ok"
for p in libpng libjpeg libtiff-4 libwebp libopenjp2 libjxl libheif libraw_r jbig ddjvuapi fftw3 lqr-1 librsvg-2.0 libxml-2.0 libzip liblzma libzstd freetype2 fontconfig lcms2; do
  printf '%-12s %s\n' $p "$(pkg-config --modversion $p 2>&1 | head -1)"; done
echo "== cloning the fork"
mkdir -p $HOME/work && cd $HOME/work
[ -d ImageMagick ] || git clone -q -c core.autocrlf=false -b refactoring-setup https://github.com/mrksbrg/ImageMagick.git
cd ImageMagick && git log --oneline -1
df -h ~ | tail -1
