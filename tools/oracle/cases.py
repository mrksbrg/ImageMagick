"""Case catalogue for the differential oracle.

A case is one or more `magick` invocations run in an empty directory. The oracle
runs every case on a baseline build and on a candidate build and requires the
results to be identical: exit status, normalised stdout and stderr, and the
bytes of every file the case writes.

Cases are generated, not hand-listed, wherever ImageMagick can enumerate its own
options (`magick -list compose`, `-list distort`, ...), so a method is covered
because it exists rather than because someone remembered it.

Placeholders in argv:
  {C}        the corpus directory (same relative path on both sides)
  {C}/x.miff a corpus image, see CORPUS below
  {FONT}     a TrueType font shipped in the corpus
"""

import base64
import hashlib
import itertools
import json
import math
import string
import struct

# Written as floating point at 32 bits so no HDRI precision is lost on output:
# under Q16 HDRI, SetImageDepth() leaves pixels untouched for depth >= 16, so
# this only changes how the MIFF is encoded.
FLOAT_OUT = ["-define", "quantum:format=floating-point", "-depth", "32"]

# ---------------------------------------------------------------------------
# Corpus: generated once with the baseline binary, then frozen for the run.
# name -> magick argv producing it (output path appended), or ("copy", path).
# ---------------------------------------------------------------------------
CORPUS = {
    "rose":      ["rose:"],
    "rose_alpha": ["rose:", "(", "-size", "70x46", "gradient:white-black",
                   "-rotate", "0", ")", "-alpha", "off", "-compose",
                   "CopyOpacity", "-composite"],
    "rose_blur": ["rose:", "-blur", "0x1.5", "-modulate", "100,90,100"],
    "gray16":    ["-size", "64x48", "gradient:black-white", "-colorspace",
                  "Gray", "-depth", "16"],
    "cmyk":      ["rose:", "-colorspace", "CMYK"],
    "hdri":      ["rose:", "-evaluate", "multiply", "1.6", "-evaluate",
                  "subtract", "25%"] + FLOAT_OUT,
    "granite":   ["granite:"],
    "logo":      ["logo:", "-sample", "25%"],
    "wizard":    ["wizard:", "-resize", "96x"],
    "wide":      ["-seed", "7", "-size", "257x3", "plasma:red-blue"],
    "tiny":      ["-size", "1x1", "xc:#336699"],
    "tall":      ["rose:", "-crop", "3x46+10+0", "+repage"],
    "bilevel":   ("copy", "tests/input_bilevel.miff"),
    "palette":   ("copy", "tests/input_256c.miff"),
    "gray8":     ("copy", "tests/input_gray.miff"),
    "truecolor": ("copy", "tests/input_truecolor.miff"),
    "seq":       ("copy", "tests/sequence.miff"),
    "anim":      ("copy", "Magick++/tests/test_image_anim.miff"),
    "photo":     ("copy", "Magick++/tests/test_image.miff"),
}

# Single-frame images every unary operator is applied to.
UNARY_INPUTS = ["rose", "rose_alpha", "gray16", "cmyk", "hdri", "palette",
                "bilevel", "tiny", "tall"]
# A smaller set for the large enumerated families.
FAMILY_INPUTS = ["rose", "rose_alpha", "gray16"]

# Extra files copied verbatim into the corpus for the decoder cases.
DECODE_FILES = [
    "tests/rose.pnm",
    "tests/input_svg_gradient_transform.svg",
    "tests/input_svg_inline_style.svg",
    "tests/cli-uhdr-iptc.jpg",
]
DECODE_GLOBS = [  # PerlMagick's reader corpus
    "PerlMagick/t/input*",
    "PerlMagick/t/MasterImage_70x46.ppm",
    "PerlMagick/t/png/input*", "PerlMagick/t/tiff/input*",
    "PerlMagick/t/jpeg/input*", "PerlMagick/t/jng/input*",
    "PerlMagick/t/openjp2/input*", "PerlMagick/t/bzlib/input*",
    "PerlMagick/t/zlib/input*", "PerlMagick/t/jbig/input*",
    "PerlMagick/t/rad/input*", "PerlMagick/t/cgm/input*",
    "PerlMagick/t/hpgl/input*", "PerlMagick/t/xfig/input*",
    "PerlMagick/t/x11/input.xwd",
]
# Raw readers need the geometry on the command line.
RAW_DECODE = {
    "input_70x46.cmyk": ["-size", "70x46", "-depth", "8"],
    "input_70x46.gray": ["-size", "70x46", "-depth", "8"],
    "input_70x46.rgb": ["-size", "70x46", "-depth", "8"],
    "input_70x46.rgba": ["-size", "70x46", "-depth", "8"],
    "input_70x46.uyvy": ["-size", "70x46", "-depth", "8"],
    "input_70x46.yuv": ["-size", "70x46", "-depth", "8"],
}
# Readers that hand off to an external program (Ghostscript, ffmpeg, ...):
# slow, and outside the code under refactoring.
EXTERNAL_DECODE = (".ps", ".eps", ".pdf", ".ai", ".m2v", ".mpg", ".fpx", ".hdf",
                   ".wmf",   # WMF goes through LibreOffice without libwmf
                   ".hpgl")  # the hp2xx delegate, run through /bin/sh

FONT = "Generic.ttf"  # copied from PerlMagick/t
FONT2 = "Narrow.ttf"  # a 0.6x-condensed derivative of Generic.ttf (tools/oracle/mknarrow.py):
# a second, visually distinct corpus font, so the oracle can see which TypeInfo the font
# matcher picks (type.c GetTypeInfoByFamily, annotate.c), which one glyph file cannot


# Upstream bug (docs/refactoring/ORACLE.md, "Known upstream issues"): the
# Displace and Distort compose operators leave the canvas columns beyond the
# source's width uninitialised when the destination is wider than the source,
# so those outputs change from run to run. The oracle keeps them off that path.
DEST_WIDER_UNSTABLE = ("Displace", "Distort")

# Upstream bug (ORACLE.md): -scale 50% under a bilevel write mask leaves output
# pixels unwritten, so the image holds whatever memory held: under a parallel
# load 19 of 64 runs of the same command differed. selfcheck, which runs each
# case twice, missed it, and it counted as a kill in 155 mutation runs.
# -scale 150x100% does the same, more rarely: 1 of 80 runs under a load of ten
# (2026-10-03), once in a cached baseline, so every mutant it met counted as killed.
WRITE_MASK_UNSTABLE = ("-scale 50%", "-scale 150x100%")


def img(name):
    return "{C}/%s.miff" % name


# ---------------------------------------------------------------------------
# Hand-written operator lists: everything in tests/validate.h plus the
# operators it misses.
# ---------------------------------------------------------------------------
UNARY_OPS = [
    # --- from tests/validate.h convert_options
    "", "-alpha set", "-black-threshold 20%", "-blur 0x0.5", "-blur 0x1.0",
    "-blur 0x2.0", "-bordercolor red -border 6x6", "-canny 0x1+10%+80%",
    "-channel red -negate", "-colorspace CMYK -channel Cyan -negate",
    "-charcoal 0x1", "-chop 80x60+10+20", "-chop 8x6+20+30",
    "-colorize 30%/20%/50%", "-color-matrix '0,0,1,0,1,0,1,0,0'",
    "-color-matrix '0.9 0 0, 0 0.9 0, 0 0 1.2'",
    "-color-matrix '.22,.72,.07,.22,.72,.07,.22,.72,.07'", "-colors 16",
    "-convolve 1,1,1,1,4,1,1,1,1", "-crop 17x9+10+10", "-crop 60x70+10+10",
    "-cycle 200", "-define connected-components:area-threshold=16 "
    "-connected-components 8", "-density 75x75 -resample 50x50", "-depth 7",
    "-depth 16", "-despeckle", "+distort AffineProjection '1,0,0.785,1,0,0'",
    "-draw 'affine 1,0,0.785,1,0,0'", "-draw 'rectangle 20,10 80,50'",
    "-edge 0x1", "-emboss 0x1", "-enhance", "-equalize",
    "-extent 120x90-10-10", "-fill blue -fuzz 35% -opaque red",
    "-flip", "-flop", "-frame 15x15+3+3", "-fuzz 35% -transparent red",
    "-fuzz 5% -trim", "-fx '(1.0/(1.0+exp(10.0*(0.5-u)))-0.006693)*1.0092503'",
    "-gamma 1.6", "-gaussian-blur 0x0.5", "-gaussian-blur 0x2.0",
    "-implode 0.5", "-implode -1", "-label Magick", "-lat 10x10-5%",
    "-level 10%,1.2,90%", "+level 10%,90%", "-magnify",
    "-modulate 110/100/95", "-monochrome", "-motion-blur 0x3+30", "-negate",
    "-noop", "-normalize", "-ordered-dither 2x2", "-ordered-dither 3x3",
    "-ordered-dither 4x4", "-ordered-dither o8x8", "-ordered-dither h6x6a",
    "-ordered-dither checks,6", "-paint 0x1", "-raise 10x10", "+raise 5x5",
    "-remap netscape:", "-resize 10%", "-resize 150%", "-resize 150x75%",
    "-resize 50%", "-resize 50x150%", "-resize 33x33!", "-resize 40x40^",
    "-resize '200@'", "-roll +20+10", "-rotate 15", "-rotate 180",
    "-rotate 270", "-rotate 45", "-rotate 90", "-sample 150x50%",
    "-sample 50%", "-sample 5%", "-scale 150%", "-scale 50x150%",
    "-scale 5%", "-segment 0.5x0.25", "-segment 1x1.5", "-shade 30x30",
    "+shade 120x45", "-sharpen 0x0.5", "-sharpen 0x2.0", "-shave 10x10",
    "-shear 25x20", "-shear 45x45", "-solarize 50%", "-statistic Median 1",
    "-statistic NonPeak 2", "-swirl 90", "-threshold 35%", "-trim",
    "-unsharp 0x0.5+20+1", "-unsharp 0x1.0+20+1", "-wave 25x150",
    "-white-threshold 80%",
    # --- operators validate.h does not reach
    "-adaptive-blur 0x1.5", "-adaptive-resize 60%", "-adaptive-sharpen 0x1",
    "-auto-gamma", "-auto-level", "-auto-orient", "-bilateral-blur 3",
    "-blue-shift 1.5", "-brightness-contrast 10x20",
    "-channel-fx 'red<=>blue'", "-channel-fx 'red=>alpha'", "-clamp",
    "-clahe 25x25%+128+3", "-contrast", "+contrast",
    "-contrast-stretch 2%x1%", "-deskew 40%", "-despeckle", "-extent 50x30",
    "-gravity center -extent 90x60", "-gravity southeast -crop 30x20+0+0",
    "-grayscale Rec709Luminance", "-hough-lines 9x9+10", "-kmeans 5",
    "-kuwahara 2", "-linear-stretch 1x1%", "-local-contrast 5x30",
    "-mean-shift 3x3+10%", "-mode 3", "-median 2", "-perceptible 0.1",
    "-posterize 4", "-range-threshold 10,20,80,90%", "-rotational-blur 10",
    "-selective-blur 0x2+10%", "-sepia-tone 80%",
    "-sigmoidal-contrast 3x50%", "+sigmoidal-contrast 3x50%",
    "-sketch 0x2+30", "-splice 10x5+3+4", "-strip", "-thumbnail 30x20",
    "-fill red -tint 50", "-transpose", "-transverse", "-unique-colors",
    "-vignette 0x3", "-wavelet-denoise 5%", "-white-balance", "-orient TopRight",
    "-colors 2", "-colors 64 -treedepth 4", "+dither -colors 8",
    "-quantize YIQ -colors 8", "-colorspace Gray -colors 4",
    "-channel R -separate", "-separate", "-separate -combine",
    "-channel A -evaluate multiply 0.5 +channel", "-channel RGB -blur 0x1",
    "-alpha extract", "-alpha remove", "-alpha shape", "-alpha background",
    "-alpha copy", "-alpha deactivate", "-background gray -flatten",
    "-fill '#ff000080' -draw 'color 10,10 floodfill'",
    "-fuzz 20% -fill blue -floodfill +5+5 white", "-noise 2",
    "-seed 3 -spread 2", "-seed 3 -random-threshold 20x80",
    "-seed 3 -attenuate 0.6 +noise Gaussian", "-define filter:blur=0.8 -resize 70%",
    "-filter Lanczos -define filter:lobes=4 -resize 170%",
    "-distort SRT 0.7,25 +repage", "+distort SRT 1.2,-10",
    "-virtual-pixel tile -distort Arc 90", "-morphology Close Disk:2.5",
    "-morphology Convolve 'Blur:0x1'", "-morphology Distance Euclidean:4",
    "-morphology EdgeOut Diamond", "-define morphology:compose=Lighten -morphology Convolve 'Sobel:>'",
    "-fx 'u*0.5+v*0'", "-fx 'p{i-1,j}.r'", "-fx 'j/h'", "-fx 'hypot(i-w/2,j-h/2)/w'",
    "-fx 'u>0.5?1:0'", "-fx 'sin(u*pi)^2'", "-fx 'mod(i,7)/7'",
    "-fx 'rand()*0+debug(u)*0+u.lightness'", "-fx 'minima+maxima*0'",
    "-fx 'intensity'", "-fx 'luminance'", "-fx 'u.hue'", "-fx 's.saturation'",
    "-fx 'xx=u; yy=xx*xx; yy'", "-fx 'i%3==0 && j%2==1'",
    "-fx 'floor(u*8)/8+trunc(0.7)'", "-fx 'atan2(j-h/2,i-w/2)/pi'",
    "-fx 'u[0].r'", "-fx 'mean.r'", "-fx 'standard_deviation'",
    "-fx 'kurtosis+skewness*0'", "-fx 'isnan(u)+isnan(0/0)'",
    "-fx 'aa=0; while(aa<3, aa=aa+1); aa/3'",
    "-channel B -fx 'u.r*u.g'", "-fx 'gauss(u)'", "-fx 'sinc(u*4)'",
    "-fx 'u^0.4545'", "-fx 'log(u+1)+logtwo(2)+ln(e)'",
    "-fx 'hypot(u*1.37,v*0.61+i*0.013)'", "-fx 'pow(u+0.013*j,1.31)'",
    "-fx 'exp(-u*2.7)*sin(i*0.37)'",
    "-evaluate Pow 0.5", "-evaluate Log 5", "-evaluate Threshold 50%",
    "-function Polynomial 3,-2.5,0.5", "-function Sinusoid 3,-90",
    "-function ArcSin 1", "-function ArcTan 10,.7",
    "-auto-threshold OTSU", "-auto-threshold Kapur", "-auto-threshold Triangle",
    "-channel-fx 'gray'", "-color-threshold 'sRGB(10,10,10)-sRGB(200,200,200)'",
    "-level-colors navy,gold",
    "+level-colors ,red", "-fill gold -colorize 50", "-negate -channel G",
    "-set colorspace RGB -colorspace sRGB", "-strip -set comment hi",
    "-gravity north -background red -splice 0x5", "-trim +repage",
    "-define trim:percent-background=50% -trim", "-shave 1x1 -shave 1x1",
    "-roll -7-3", "-flip -flop -transpose", "-fill red -opaque white",
    "+opaque blue", "-fill none -draw 'matte 10,10 floodfill'",
    "-colorspace HSL -channel L -equalize +channel -colorspace sRGB",
    "-channel RGBA -fx 'u*0.9'", "-alpha on -channel A -fx 'i/w' +channel",
    "-define convolve:scale='!' -morphology Convolve Laplacian:3",
    "-define convolve:scale=50%! -morphology Correlate Gaussian:0x1",
    "-print '%[fx:mean]\\n'", "-identify", "-set option:x 3 -resize '%[x]0%'",
]

DRAW = [
    "line 5,5 60,40", "point 10,10", "arc 5,5 60,40 30,270",
    "ellipse 35,23 20,10 0,360", "ellipse 35,23 20,10 45,200",
    "circle 35,23 45,30", "rectangle 5,5 60,40", "roundrectangle 5,5 60,40 8,6",
    "polyline 5,5 60,40 10,40 50,5", "polygon 5,5 60,40 10,40 50,5",
    "bezier 5,40 20,0 50,45 65,5",
    "path 'M 10,10 L 60,10 60,40 Z'",
    "path 'M 5 23 C 20 0 50 46 65 23 S 20 40 10 30 Q 30 5 50 20 T 60 40'",
    "path 'M 35 5 A 18 18 0 1 0 36 5 z m 5 5 h 10 v 10 h -10 z'",
    "path 'M10 40 a 20 10 -30 0 1 40 -20'",
    "text 5,30 'Magick'", "image over 10,10 20,15 'rose:'",
    "color 30,20 replace", "color 30,20 point", "color 30,20 reset",
    "alpha 20,20 floodfill", "gravity center text 0,0 'Mid'",
    "push graphic-context translate 30,20 rotate 30 rectangle -10,-5 10,5 pop graphic-context",
    "push graphic-context scale 1.5,0.8 skewX 20 circle 20,15 25,20 pop graphic-context",
    "push graphic-context clip-path c push clip-path c circle 35,23 35,5 pop clip-path "
    "rectangle 0,0 70,46 pop graphic-context",
]
DRAW_SETTINGS = [
    "-fill blue -stroke red -strokewidth 2",
    "-fill none -stroke gold -strokewidth 3 -draw 'stroke-linejoin round' "
    "-draw 'stroke-linecap round'",
    "-fill '#00ff0080' -stroke black -draw 'stroke-dasharray 5 3 2 3' "
    "-draw 'stroke-dashoffset 2'",
    "-fill red +antialias -stroke blue",
    "-fill green -draw 'fill-rule evenodd' -draw 'stroke-miterlimit 2' "
    "-stroke black -strokewidth 1.5",
]

TEXT_OPS = [
    "-font {FONT} -pointsize 14 -fill gold -annotate +5+20 Magick",
    "-font {FONT} -pointsize 12 -gravity center -annotate 20x20+0+0 'Tilt'",
    "-font {FONT} -pointsize 10 -gravity south -stroke red -annotate +0+2 'Low'",
    "-font {FONT} -pointsize 12 -kerning 2 -interword-spacing 8 "
    "-annotate +2+30 'a b c'",
    "-font {FONT} -pointsize 11 -interline-spacing 3 -annotate +2+10 'one\\ntwo'",
    "-font {FONT} -pointsize 16 -undercolor '#0008' -fill white "
    "-gravity northeast -annotate +3+3 'UC'",
    "-font {FONT} -pointsize 12 -draw 'decorate underline text 5,20 Deco'",
    "-font {FONT} -pointsize 12 -direction right-to-left -annotate +60+20 abc",
]

GENERATORS = [
    "-size 60x40 gradient:", "-size 60x40 gradient:red-blue",
    "-size 60x40 -define gradient:angle=45 gradient:yellow-navy",
    "-size 60x40 -define gradient:direction=east gradient:",
    "-size 60x40 -define gradient:vector=5,5,50,30 gradient:red-green",
    "-size 60x40 radial-gradient:", "-size 60x40 radial-gradient:white-black",
    "-size 60x40 -define gradient:radii=20,10 -define gradient:extent=Circle "
    "radial-gradient:red-blue",
    "-size 60x40 -define gradient:center=10,10 -define gradient:extent=Farthest "
    "radial-gradient:",
    "-seed 5 -size 50x30 plasma:", "-seed 5 -size 50x30 plasma:fractal",
    "-seed 5 -size 50x30 plasma:tomato-steelblue",
    "-size 40x30 xc:gold", "-size 40x30 canvas:'rgba(10,20,30,0.4)'",
    "-size 40x30 xc:'hsl(120,50%,50%)'", "-size 40x30 xc:'cmyk(10%,20%,30%,5%)'",
    "-size 40x30 xc:'gray(40%)'", "-size 40x30 xc:'#abc'", "-size 40x30 xc:'icc-color(rgb,0.1,0.2,0.3)'",
    "-size 40x30 xc:'lab(50%,10,-20)'", "-size 40x30 xc:'device-cmyk(0.1,0.2,0.3,0.4)'",
    "hald:4", "netscape:", "-size 40x30 pattern:checkerboard",
    "-size 40x30 pattern:hexagons", "-size 40x30 pattern:bricks",
    "-size 40x30 pattern:gray50", "-size 40x30 tile:pattern:circles",
    "-font {FONT} -pointsize 20 label:Magick", "-font {FONT} -size 80x label:Wrap",
    "-font {FONT} -size 60x40 caption:'Some wrapped caption text'",
    "-font {FONT} -size 60x40 -gravity center caption:'Centre'",
    "-seed 2 -size 30x20 fractal:", "logo: -resize 20%", "wizard: -resize 15%",
    "-size 40x30 xc:white -fill red -draw 'circle 20,15 20,5'",
    "-seed 4 -size 60x40 xc: +noise Random -channel G -threshold 50%",
    "-size 40x40 -seed 9 xc: -sparse-color Voronoi '5,5 red 30,30 blue 10,35 lime'",
]

TWO_IMAGE_OPS = [
    ("-append", ["rose", "gray16"]), ("+append", ["rose", "gray16"]),
    ("-smush 4", ["rose", "rose_blur"]), ("+smush -3", ["rose", "rose_blur"]),
    ("-compose over -composite", ["rose", "rose_alpha"]),
    ("-gravity center -geometry +5+3 -composite", ["granite", "rose_alpha"]),
    ("-compose blend -define compose:args=30 -composite", ["rose", "rose_blur"]),
    ("-compose dissolve -define compose:args=60,40 -composite", ["rose", "rose_alpha"]),
    ("-compose mathematics -define compose:args=0.5,0.3,0.2,0 -composite", ["rose", "rose_blur"]),
    ("-compose displace -define compose:args=10x5 -composite", ["rose", "gray8"]),
    ("-compose distort -define compose:args=20x10 -composite", ["rose", "gray8"]),
    ("-compose modulate -define compose:args=80x120 -composite", ["rose", "rose_blur"]),
    ("-compose colorize -composite", ["rose", "palette"]),
    ("-fx 'u*v'", ["rose", "rose_blur"]), ("-fx 'u[1].r+u.g*0'", ["rose", "gray16"]),
    ("-evaluate-sequence mean", ["rose", "rose_blur"]),
    ("-clut", ["rose", "gray16"]), ("-hald-clut", ["rose", "hald"]),
    ("-morph 2", ["rose", "rose_blur"]), ("-mosaic", ["rose", "tall"]),
    ("-flatten", ["granite", "rose_alpha"]), ("-layers merge", ["granite", "rose_alpha"]),
    ("-combine", ["gray8", "gray8", "gray8"]),
    ("-colorspace CMYK -combine", ["gray8", "gray8", "gray8", "gray8"]),
    ("-compare -metric RMSE", ["rose", "rose_blur"]),
    ("-alpha off -compose copyopacity -composite", ["rose", "gray8"]),
    ("-poly '0.5,1 0.5,2'", ["rose", "rose_blur"]),
    ("-channel-fx 'red; blue=>green'", ["rose", "rose_blur"]),
    ("-compose multiply -composite", ["rose", "gray8"]),
    ("-set option:distort:viewport 50x30+5+5 -distort SRT 10 -compose over -composite", ["granite", "rose_alpha"]),
]

SEQ_OPS = [
    "-coalesce", "-deconstruct", "-flatten", "-mosaic", "-append", "+append",
    "-reverse", "-delete 1", "-delete 0--2", "-swap 0,2", "-duplicate 2,0",
    "-insert 1", "-clone 1,2 -append", "-evaluate-sequence median",
    "-evaluate-sequence max", "-evaluate-sequence mean",
    "-morph 1", "-fx 'u[t]*0.5+v*0.5'", "-fx 'u[-1]'", "-separate",
    "-set delay 20 -loop 2", "-resize 50% -coalesce", "-dispose Background -coalesce",
    "-page +10+5 -flatten", "-quiet -layers optimize", "-layers compare-any",
    "-layers compare-clear", "-layers compare-overlay", "-layers optimize-frame",
    "-layers optimize-plus", "-layers optimize-transparency", "-layers remove-dups",
    "-layers remove-zero", "-layers trim-bounds", "-layers flatten",
    "-layers merge", "-layers mosaic",
    "-scene 3 -set filename:f %p -resize 1x1!",
    "-channel-fx 'red'", "-compose over -layers composite",
]

TEXT_OUTPUTS = [  # `-format` escapes, written through info:
    "%b %c %d %e %f %g %h %i %k %l %m %n %o %p %q %r %s %t %u %w %x %y %z",
    "%A %B %C %D %G %H %M %O %P %Q %S %T %U %W %X %Y %Z %@ %# %[type]",
    "%[fx:mean] %[fx:maxima.r] %[fx:minima] %[fx:standard_deviation] %[fx:w*h]",
    "%[mean] %[standard-deviation] %[kurtosis] %[skewness] %[entropy] "
    "%[max] %[min] %[median]",
    "%[pixel:p{10,10}] %[pixel:u.r] %[hex:p{5,5}] %[fx:p{3,3}.g]",
    "%[colorspace] %[compression] %[orientation] %[resolution.x] %[units] "
    "%[gamma] %[rendering-intent] %[channels] %[depth] %[bit-depth]",
    "%[convex-hull] | %[minimum-bounding-box] | %[minimum-bounding-box:angle]",
    "%[profiles] %[copyright] %[version]",
    "%[fx:hypot(w,h)] %[fx:int(mean*255)] %[fx:rand()*0]",
    "%[opaque] %[size] %[scene] %[scenes] %[page] %[printsize.x]",
    "%[magick] %[extension] %[basename] %[directory] %[input]",
]

# fx functions on off-grid arguments, printed at full precision: integer
# arguments make many rewrites (hypot as sqrt, pow as exp/log) exact.
FX_PRINT = [
    "%[fx:hypot(w*0.37,h*1.13)] %[fx:hypot(mean*3.1,maxima+0.7)]",
    "%[fx:pow(1.37,mean*9.1)] %[fx:exp(-mean*2.3)] %[fx:log(mean+0.37)] "
    "%[fx:logtwo(w*1.7)] %[fx:ln(h+0.3)]",
    "%[fx:sin(1.3*mean)] %[fx:cos(0.7*w)] %[fx:tan(0.37)] %[fx:asin(0.31)] "
    "%[fx:acos(mean*0.9)] %[fx:atan(3.3)] %[fx:atan2(0.3,-1.7)] %[fx:sinh(0.8)] "
    "%[fx:cosh(0.8)] %[fx:tanh(mean)] %[fx:asinh(0.4)] %[fx:acosh(1.7)] %[fx:atanh(0.4)]",
    "%[fx:sqrt(mean*2.7)] %[fx:abs(-1.37*mean)] %[fx:ceil(mean*9.7)] %[fx:floor(-mean*9.7)] "
    "%[fx:round(mean*9.5)] %[fx:trunc(-2.7)] %[fx:sign(-mean)] %[fx:mod(w*1.3,7.1)] "
    "%[fx:gcd(84,36)] %[fx:max(mean,0.3)] %[fx:min(mean,0.3)]",
    "%[fx:erf(mean)] %[fx:gauss(0.7)] %[fx:sinc(1.3)] %[fx:j0(1.7)] %[fx:j1(1.7)] "
    "%[fx:jinc(1.7)] %[fx:squish(0.3)] %[fx:xx=0; do(xx<3, xx=xx+1); xx] %[fx:alt(3)] %[fx:not(0.2)]",
    "%[fx:mean.r*0.3+mean.g*0.59+mean.b*0.11] %[fx:standard_deviation.b] "
    "%[fx:kurtosis.r] %[fx:skewness.g] %[fx:median]",
    "%[fx:p{3.7,2.2}.r] %[fx:p{-1.5,4.5}.g] %[fx:p[1,1].b] %[fx:u.p{10.25,7.75}.hue]",
    "%[fx:1.0/3.0] %[fx:2^0.5] %[fx:7.3%2] %[fx:3<<2] %[fx:17>>1] %[fx:5&3] %[fx:5|3] "
    "%[fx:~5] %[fx:0.1+0.2==0.3] %[fx:1.5e3*2] %[fx:-0.0] %[fx:pi*e]",
    "%[fx:aa=1.1; bb=aa*aa; for(xx=0, xx<5, xx=xx+1; bb=bb*1.01); bb] %[fx:isnan(0/0)] %[fx:QuantumRange] "
    "%[fx:QuantumScale*7] %[fx:Opaque] %[fx:Transparent] %[fx:phi]",
]

INFO_OPS = [  # stdout of identify / info:
    ["identify"], ["identify", "-verbose"], ["identify", "-verbose", "-moments"],
    ["identify", "-verbose", "-features", "1"], ["identify", "-unique", "-verbose"],
    # Moments and features are computed values printed at 6 digits by default.
    ["identify", "-verbose", "-precision", "17", "-moments"],
    ["identify", "-verbose", "-precision", "17", "-features", "1"],
    ["identify", "-ping", "-format", "%wx%h %m\\n"],
]

MONTAGE_OPS = [
    "-tile 3x -geometry +2+2", "-tile 2x2 -geometry 30x30+1+1 -background gray",
    "-font {FONT} -label %p -geometry +4+4 -pointsize 8",
    "-font {FONT} -title Test -frame 3 -shadow -geometry 20x20+2+2",
    "-mode concatenate -tile x1", "-border 2 -geometry +3+3",
]

# Formats written by ImageMagick's own coders. Formats the build cannot write,
# or that shell out to an external delegate, simply fail on both sides and are
# filtered at list time by the oracle.
ENCODE_VARIANTS = {
    "png": [[], ["-quality", "0"], ["-quality", "95"], ["-define", "png:compression-filter=5"],
            ["-define", "png:bit-depth=8", "-define", "png:color-type=2"],
            ["-define", "png:exclude-chunk=all"]],
    "png8": [[]], "png24": [[]], "png32": [[]], "png48": [[]], "png64": [[]],
    "jpeg": [[], ["-quality", "30"], ["-quality", "95", "-sampling-factor", "4:4:4"],
             ["-interlace", "plane"], ["-define", "jpeg:dct-method=float"],
             ["-define", "jpeg:optimize-coding=false"]],
    "tiff": [["-compress", c] for c in ("None", "LZW", "Zip", "JPEG", "RLE", "LZMA", "Zstd",
                                         "Group4", "Fax", "WebP")]
            + [["-define", "tiff:tile-geometry=16x16"], ["-endian", "MSB"],
               ["-interlace", "plane"], ["-define", "quantum:format=floating-point"]],
    "miff": [["-compress", c] for c in ("None", "RLE", "Zip", "BZip", "LZMA", "Zstd")],
    "bmp": [[]], "bmp2": [[]], "bmp3": [[]], "gif": [[]], "gif87": [[]],
    "webp": [[], ["-quality", "50"], ["-define", "webp:lossless=true"]],
    "jxl": [["-quality", "90"], ["-quality", "100"]],
    "jp2": [[], ["-quality", "40"]], "j2k": [[]],
    "exr": [[]], "hdr": [[]], "psd": [[], ["-compress", "RLE"]], "psb": [[]],
    "dds": [[], ["-define", "dds:compression=none"], ["-define", "dds:compression=dxt5"],
            ["-define", "dds:mipmaps=0"]],
    "pnm": [[], ["-compress", "none"]], "pbm": [[]], "pgm": [[]], "ppm": [[]],
    "pam": [[]], "pfm": [[]], "phm": [[]], "tga": [[], ["-compress", "RLE"]],
    "sgi": [[], ["-compress", "RLE"]], "sun": [[]], "viff": [[]], "xpm": [[]],
    "xbm": [[]], "pcx": [[]], "dcx": [[]], "pict": [[]], "wbmp": [[]], "ico": [[]],
    "cur": [[]], "fits": [[]], "dpx": [[]], "cin": [[]], "mtv": [[]], "otb": [[]],
    "palm": [[]], "pdb": [[]], "picon": [[]], "rgf": [[]], "sixel": [[]], "uil": [[]],
    "vicar": [[]], "vips": [[]], "xwd": [[]], "yuv": [[]], "avs": [[]], "aai": [[]],
    "art": [[]], "hrz": [[]], "ipl": [[]], "jng": [[]], "mng": [[]], "mat": [[]],
    "mono": [[]], "pal": [[]], "ptif": [[]], "rgb": [[]],
    "rgba": [[]], "gray": [[]], "cmyk": [[]], "uyvy": [[]], "ycbcr": [[]], "h": [[]],
    "html": [[]], "json": [[]], "yaml": [[]], "txt": [[]], "sparse-color": [[]],
    "histogram": [[]], "info": [[]], "svg": [[]],
    # The PostScript and PDF writers hold most callers of MagickCore/compress.c.
    "ps": [[]] + [["-compress", c] for c in ("RLE", "Fax", "Group4", "JPEG")],
    "ps2": [[]] + [["-compress", c] for c in ("LZW", "RLE", "Zip", "Fax", "Group4", "JPEG")],
    "ps3": [[]] + [["-compress", c] for c in ("LZW", "RLE", "Zip", "Fax", "Group4", "JPEG")],
    "eps": [[], ["-compress", "LZW"]],
    "pdf": [[]] + [["-compress", c] for c in ("Zip", "LZW", "RLE", "Fax", "Group4", "JPEG")],
    "pcl": [[]], "braille": [[]], "ftxt": [[]], "qoi": [[]],
    "farbfeld": [[]], "mask": [[]], "strimg": [[]],
    "wpg": [[]], "fl32": [[]], "ashlar": [[]],
    "cals": [[]], "dib": [[]], "clip": [[]],
    "thumbnail": [[]], "vid": [[]], "a": [[]],
    "ycbcra": [[]], "rgbo": [[]], "bgr": [[]], "bgra": [[]], "ms": [[]],
}
ENCODE_INPUTS = ["rose", "rose_alpha", "gray16", "palette", "bilevel", "hdri"]
ENCODE_SEQ_FORMATS = ["gif", "tiff", "miff", "psd", "pdf", "mng", "apng", "ico",
                      "dcx", "webp", "jxl", "ps", "pam"]
# Raw formats have no header; decoding needs the geometry and depth.
RAW_ENCODE = {"rgb", "rgba", "gray", "cmyk", "uyvy", "ycbcr", "ycbcra", "yuv",
              "mono", "pal", "a", "rgbo", "bgr", "bgra"}
# Formats whose writer is useful but whose reader needs Ghostscript, or which
# have no reader at all: only the encoded bytes are compared.
ENCODE_ONLY = {"ps", "ps2", "ps3", "eps", "pdf", "pcl", "braille", "html",
               "histogram", "info", "json", "yaml", "h", "thumbnail", "ashlar",
               "strimg", "sparse-color", "picon", "uil", "clip", "mask",
               "vid", "ms", "ftxt"}


def _split(opstr):
    """Split an option string like a POSIX shell, keeping quoted groups."""
    import shlex
    return shlex.split(opstr)


def _fmt(opstr):
    """Split an option string, pointing {FONT} at the corpus font."""
    return _split(opstr.replace("{FONT}", "{C}/" + FONT))


def _each(lists, listname):
    """The values of an enumeration (`magick -list <listname>`), less Undefined."""
    return [v for v in lists.get(listname, []) if v.lower() != "undefined"]


def _case_id(family, steps, files=None, stdin=None):
    key = steps if not files else [steps, sorted(files.items())]
    if stdin:
        key = [key, "stdin", stdin]
    ident = hashlib.sha1(json.dumps(key).encode()).hexdigest()[:10]
    return "%s/%s" % (family, ident)


def _case(family, label, steps, outputs):
    return {"id": _case_id(family, steps), "family": family, "label": label,
            "steps": steps, "outputs": outputs, "stdout": True}


def _with_inputs(case, files=None, stdin=None):
    """`files` maps a name to text written into the case directory first;
    `stdin` names a file (corpus paths as `{C}/...`) fed to every step.
    Both are part of the case's id."""
    case["id"] = _case_id(case["family"], case["steps"], files, stdin)
    if files:
        case["files"] = files
    if stdin:
        case["stdin"] = stdin
    return case


def _op_to(family, label, argv, out):
    return _case(family, label, [argv + [out]], [out])


def _op(family, label, pre, args):
    return _op_to(family, label, pre + args + FLOAT_OUT, "out.miff")


# ---- unary operators over the full single-frame input set
def _unary_cases():
    for name, op in itertools.product(UNARY_INPUTS, UNARY_OPS):
        yield _op("unary", "%s %s" % (name, op), [img(name)], _fmt(op))


# ---- the same operators through the legacy front end. `magick <args>`
# parses with MagickWand/operation.c; `convert` and `mogrify` go through
# MagickWand/mogrify.c, a separate implementation of every option.
def _convert_cases():
    for name, op in itertools.product(("rose", "rose_alpha"), UNARY_OPS):
        yield _case("convert", "convert %s %s" % (name, op),
                    [["convert", img(name)] + _fmt(op) + FLOAT_OUT + ["out.miff"]],
                    ["out.miff"])


def _mogrify_cases():
    for op in filter(None, UNARY_OPS):
        yield _case("mogrify", "mogrify rose %s" % op,
                    [[img("rose"), "work.miff"],
                     ["mogrify"] + _fmt(op) + FLOAT_OUT + ["work.miff"]], ["work.miff"])


# ---- stream: pixel export by map and storage type (stream.c, pixel.c)
def _stream_cases():
    for name in ("rose", "rose_alpha", "cmyk", "hdri"):
        for m, t in itertools.product(("rgb", "rgba", "bgr", "i", "cmyk", "rgbp", "a"),
                                      ("char", "short", "long", "longlong", "float",
                                       "double", "quantum")):
            yield _case("stream", "stream %s -map %s -storage-type %s" % (name, m, t),
                        [["stream", "-map", m, "-storage-type", t, img(name),
                          "out.raw"]], ["out.raw"])
        yield _case("stream", "stream %s -extract" % name,
                    [["stream", "-map", "rgb", "-storage-type", "char", "-extract",
                      "20x10+5+5", img(name), "out.raw"]], ["out.raw"])


# ---- resize.c paths that the generated families miss, found by mutation
# testing (docs/refactoring/MUTATION.md): magnify methods, one-dimensional
# scaling, write masks, progress monitoring, exact thumbnail factors, and
# the filter:* defines.
def _magnify_cases():
    for method, name in itertools.product(
            ("eagle2x", "eagle3x", "eagle3xb", "epbx2x", "fish2x", "hq2x",
             "scale2x", "scale3x", "xbr2x"),
            ("rose", "palette", "rose_alpha", "tiny")):
        yield _op("resize", "%s magnify %s" % (name, method), [img(name)],
                  ["-define", "magnify:method=" + method, "-magnify"])


# Support exactly 0.5 (Box and Point, enlarging): decides the storage class,
# which only shows on a palette image.
def _palette_filter_cases():
    for f, geo in itertools.product(("Box", "Point", "Triangle"),
                                    ("150%", "150x100%", "100x150%", "60%")):
        yield _op("resize", "palette -filter %s -resize %s" % (f, geo),
                  [img("palette")], ["-filter", f, "-resize", geo])
        yield _case("resize", "palette -filter %s -resize %s class" % (f, geo),
                    [[img("palette"), "-filter", f, "-resize", geo, "-format",
                      "%r %k\\n", "info:"]], [])


def _msl_cases():
    for name in ("rose", "rose_alpha", "tiny"):  # no CLI option; MSL reaches MinifyImage
        yield _with_inputs(
            _case("resize", "%s msl minify" % name, [["conjure", "msl:minify.msl"]], ["out.miff"]),
            files={"minify.msl": MSL_TEMPLATE % (img(name), "<minify />")})
    for op in MSL_OPS:
        yield _with_inputs(
            _case("msl", op, [["conjure", "msl:script.msl"]], ["out.miff"]),
            files={"script.msl": MSL_TEMPLATE % (img("rose"), op)})


def _one_dimension_cases():
    for how, geo, name in itertools.product(
            ("-scale", "-sample", "-resize", "-adaptive-resize", "-interpolative-resize"),
            ("150x100%", "100x60%", "70x13!", "9x46!", "100%"),
            ("rose", "rose_alpha")):
        yield _op("resize", "%s %s %s" % (name, how, geo), [img(name)], [how, geo])


def _write_mask_cases():
    for how in ("-scale 150%", "-sample 60%", "-resize 150%", "-resize 40%", "-scale 50%",
                "-scale 150x100%"):
        if how not in WRITE_MASK_UNSTABLE:
            yield _op("resize", "rose write-mask %s" % how, [img("rose")],
                      ["-write-mask", img("bilevel")] + how.split() + ["+write-mask"])
        # A mask of exactly one half: `<= QuantumRange/2` against `<` differs only there.
        yield _case("resize", "rose half write-mask %s" % how,
                    [["-size", "70x46", "xc:gray(50%)", "mask.miff"],
                     [img("rose"), "-write-mask", "mask.miff"] + how.split()
                     + ["+write-mask"] + FLOAT_OUT + ["out.miff"]], ["out.miff"])
        yield _op("resize", "rose -monitor %s" % how, [img("rose")],
                  ["-monitor"] + how.split())


# x/y factors of exactly 4 and 2, alone and with the other factor above:
# each mutant flips one comparison of `x_factor > 4 && y_factor > 4`.
def _thumbnail_cases():
    for geo in ("17x11", "17x9", "14x11", "35x23", "35x15", "23x23", "18x12", "8x6", "69x45"):
        yield _op("resize", "rose -thumbnail %s" % geo, [img("rose")], ["-thumbnail", geo])
    for name in ("azAZ09", "rose"):  # Thumb::URI is url-encoded from the path
        yield _case("resize", "%s -thumbnail to png" % name,
                    [[img("rose"), name + ".miff"],
                     [name + ".miff", "-thumbnail", "30x", "thumb.png"]], ["thumb.png"])


def _filter_curve_cases(lists):
    for f, extra in itertools.product(
            _each(lists, "Filter"),
            ([], ["-define", "filter:lobes=3"], ["-define", "filter:lobes=4"],
             ["-define", "filter:support=1.5"], ["-define", "filter:blur=0.7"])):
        yield _case("filter-curve", "%s %s" % (f, " ".join(extra)),
                    [["rose:", "-filter", f] + extra
                     + ["-define", "filter:verbose=1", "-resize", "150%", "null:"]], [])


def _filter_define_cases():
    for defs, how in itertools.product(
            (["filter:filter=Sinc", "filter:window=Jinc"], ["filter:filter=Jinc"],
             ["filter:window=Kaiser", "filter:kaiser-beta=4.5"],
             ["filter:window=Kaiser", "filter:kaiser-alpha=3"],
             ["filter:b=0.2", "filter:c=0.4"], ["filter:sigma=0.8"],
             ["filter:win-support=3"], ["filter:alpha=2.5"], ["filter:support=0"],
             ["filter:blur=0"], ["filter:lobes=0"], ["filter:support=20"]),
            (["-resize", "140%"], ["+distort", "SRT", "0.7,10"])):
        argv = [a for d in defs for a in ("-define", d)]
        yield _op("resize", "rose %s %s" % (" ".join(defs), " ".join(how)),
                  [img("rose")], argv + how)
        yield _case("filter-curve", "%s %s" % (" ".join(defs), " ".join(how)),
                    [["rose:"] + argv + ["-define", "filter:verbose=1"] + how
                     + ["null:"]], [])


# ---- draw primitives under several stroke/fill settings
def _draw_cases():
    for s, d in itertools.product(DRAW_SETTINGS, DRAW):
        yield _op("draw", "%s -draw %s" % (s, d), [img("rose")],
                  _fmt(s) + ["-font", "{C}/" + FONT, "-draw", d])


def _text_cases():
    for op, name in itertools.product(TEXT_OPS, ("rose", "rose_alpha")):
        yield _op("text", "%s %s" % (name, op), [img(name)], _fmt(op))


# ---- generators (no input image)
def _generator_cases():
    for g in GENERATORS:
        yield _op("gen", g, [], _fmt(g))


# ---- enumerated families
def _colorspace_cases(lists):
    # palette: a PseudoClass image converts through its colormap, a separate
    # branch in TransformsRGBImage and sRGBTransformImage.
    for name, cs in itertools.product(FAMILY_INPUTS + ["hdri", "cmyk", "palette"],
                                      _each(lists, "Colorspace")):
        yield _op("colorspace", "%s -> %s" % (name, cs), [img(name)],
                  ["-colorspace", cs])
        yield _op("colorspace", "%s -> %s -> sRGB" % (name, cs), [img(name)],
                  ["-colorspace", cs, "-colorspace", "sRGB"])
    for illuminant in ("A", "nosuch"):
        yield _op("colorspace", "rose illuminant %s -> Lab" % illuminant, [img("rose")],
                  ["-define", "colorspace:illuminant=" + illuminant, "-colorspace", "Lab"])


def _compose_cases(lists):
    for c in _each(lists, "Compose"):
        yield from _compose_pair_cases(c)
        for define in ("compose:sync=false", "compose:clamp=false"):
            yield _op("compose", "rose_alpha %s %s hdri" % (c, define),
                      [img("rose_alpha"), img("hdri")],
                      ["-define", define, "-gravity", "center", "-compose", c,
                       "-composite"])


def _compose_pair_cases(c):
    # HDRI on both sides: some operators clamp only the source, some only
    # the destination.
    for a, b in (("rose", "rose_alpha"), ("rose_alpha", "granite"), ("hdri", "gray16"),
                 ("gray16", "hdri"), ("rose_alpha", "hdri")):
        if c in DEST_WIDER_UNSTABLE and (a, b) == ("hdri", "gray16"):
            continue
        yield _op("compose", "%s %s %s" % (a, c, b), [img(a), img(b)],
                  ["-gravity", "center", "-compose", c, "-composite"])


_DISTORT_ARGS = {
    "Affine": "0,0 5,5  60,0 55,10  0,40 10,45",
    "AffineProjection": "1,0.2,0.1,1,3,4",
    "ScaleRotateTranslate": "0.9 20",
    "SRT": "0.9 20",
    "Perspective": "0,0 3,4  69,0 60,5  0,45 8,40  69,45 66,42",
    "PerspectiveProjection": "1.1,0.1,2,0.05,1,3,0.0005,0.001",
    "BilinearForward": "0,0 3,4  69,0 60,5  0,45 8,40  69,45 66,42",
    "BilinearReverse": "0,0 3,4  69,0 60,5  0,45 8,40  69,45 66,42",
    "Polynomial": "2  0,0 1,1  69,0 65,4  0,45 3,41  69,45 60,40  35,23 33,22  10,30 12,28",
    "Arc": "60", "Polar": "0", "DePolar": "0",
    "Barrel": "0.0 0.0 -0.2 1.1", "BarrelInverse": "0.0 0.0 -0.1 1.0",
    "Shepards": "10,10 15,12  50,30 45,25  30,40 30,40",
    "Resize": "50x30", "Cylinder2Plane": "60", "Plane2Cylinder": "60",
    "RigidAffine": "0,0 2,3  60,0 61,5  30,40 28,42",
}


def _distort_cases(lists):
    for m, name, sign in itertools.product(_each(lists, "Distort"), ("rose", "rose_alpha"),
                                           ("-", "+")):
        yield _op("distort", "%s %sdistort %s" % (name, sign, m), [img(name)],
                  [sign + "distort", m, _DISTORT_ARGS.get(m, "0.9 20")])


def _filter_cases(lists):
    for f, name, how in itertools.product(
            _each(lists, "Filter"), ("rose", "gray16"),
            (["-resize", "60%"], ["-resize", "150%"],
             ["+distort", "SRT", "0.8,15"], ["-distort", "Resize", "140%"])):
        yield _op("filter", "%s -filter %s %s" % (name, f, " ".join(how)),
                  [img(name)], ["-filter", f] + how)


def _interpolate_cases(lists):
    for m, how in itertools.product(
            _each(lists, "Interpolate"),
            (["-filter", "point", "-distort", "SRT", "1.3,20"],
             ["-interpolative-resize", "170%"], ["-fx", "p{i*0.7,j*0.6}"])):
        yield _op("interpolate", "rose -interpolate %s %s" % (m, " ".join(how)),
                  [img("rose")], ["-interpolate", m] + how)


def _virtual_pixel_cases(lists):
    for v, how in itertools.product(
            _each(lists, "VirtualPixel"),
            (["-distort", "SRT", "0.6,30"], ["-blur", "0x3"],
             ["-define", "distort:viewport=100x80-15-15", "-distort", "SRT", "0"])):
        yield _op("virtual-pixel", "rose_alpha -virtual-pixel %s %s" % (v, " ".join(how)),
                  [img("rose_alpha")], ["-virtual-pixel", v] + how)


def _morphology_cases(lists):
    for m, k, name in itertools.product(_each(lists, "Morphology"), _each(lists, "Kernel"),
                                        ("rose", "bilevel")):
        yield _op("morphology", "%s -morphology %s %s" % (name, m, k),
                  [img(name)], ["-morphology", m, k])


# Kernel names alone take their default arguments, which leave LoG and Comet
# degenerate and never rotate a kernel; a ",angle" rotates it, by 45 degrees
# only if it is 3x3 (other sizes warn, and the warning is compared too).
MORPHOLOGY_KERNEL_ARGS = [
    "LoG:0x1", "LoG:5x1.5", "DoG:0x1,2", "Comet:0x2", "Comet:5x2+2,30",
    "Comet:1x1,45", "Blur:0x1,90", "Blur:0x2,45", "Blur:1x0.5,45", "Blur:0x1,135",
    "Gaussian:0x1,30", "Sobel:45", "Sobel:135",
]
CONVOLVE_SCALES = ["!", "^", "50%", "0.5,2", "1.5!", "-1^", "0,1"]
# Rotating a symmetric kernel (Blur) by 90 or 270 degrees gives the same
# kernel, so a wrong rotation passes unseen; these are asymmetric, some with
# an off-centre origin, and "@" or ">" expands them through 45 or 90 degrees.
ROTATED_KERNELS = [
    "Comet:0x2,90", "Comet:0x2,180", "Comet:0x2,270",
    "3x3+2+2@:1,2,3,4,5,6,7,8,9", "3x3+0+1@:1,2,3,4,5,6,7,8,9",
    "3x3+1+0@:1,-2,3,4,5,-6,7,8,9", "5x1+0+0>:1,2,3,4,5", "1x5+0+2>:1,2,3,4,5",
]
# Scaling treats positive and negative kernel values apart only when a kernel
# has both, which Blur does not.
MIXED_SIGN_SCALES = [("DoG:0x1,2", "^"), ("DoG:0x1,2", "!"), ("DoG:0x1,2", "50%!"),
                     ("DoG:0x1,2", "0.5^"), ("Laplacian:3", "^")]
# Voronoi fills transparent pixels from the nearest opaque seed: it needs an
# image that is mostly transparent.
VORONOI_SEEDS = ["-size", "60x40", "xc:none", "-fill", "red", "-draw", "point 10,10",
                 "-fill", "blue", "-draw", "point 45,30", "-fill", "lime",
                 "-draw", "point 30,5"]


def _morphology_arg_cases():
    for k in MORPHOLOGY_KERNEL_ARGS:
        yield _op("morphology", "rose -morphology Convolve %s" % k, [img("rose")],
                  ["-morphology", "Convolve", k])
    for k in ("Euclidean:4", "Manhattan", "Chebyshev:2"):
        yield _op("morphology", "seeds -morphology Voronoi %s" % k, VORONOI_SEEDS,
                  ["-morphology", "Voronoi", k])
    yield _op("morphology", "rose_alpha thresholded alpha -morphology Voronoi",
              [img("rose_alpha")],
              ["-channel", "A", "-threshold", "50%", "+channel",
               "-morphology", "Voronoi", "Euclidean:2"])
    for s in CONVOLVE_SCALES:
        yield _op("morphology", "rose convolve:scale=%s Blur:0x1" % s, [img("rose")],
                  ["-define", "convolve:scale=" + s, "-morphology", "Convolve", "Blur:0x1"])
    yield _op("morphology", "rose showKernel Laplacian:3", [img("rose")],
              ["-define", "morphology:showKernel=1", "-morphology", "Convolve",
               "Laplacian:3"])
    yield from _shown_kernel_cases()


def _shown_kernel_cases():
    """Rotated and scaled kernels, printed with showKernel so that the kernel
    values are compared as well as the image they produce."""
    show = ["-define", "morphology:showKernel=1"]
    for k in ROTATED_KERNELS:
        yield _op("morphology", "rose showKernel rotated %s" % k, [img("rose")],
                  show + ["-morphology", "Convolve", k])
    for k, s in MIXED_SIGN_SCALES:
        yield _op("morphology", "rose showKernel convolve:scale=%s %s" % (s, k),
                  [img("rose")],
                  show + ["-define", "convolve:scale=" + s, "-morphology", "Convolve", k])


def _evaluate_cases(lists):
    for e in _each(lists, "Evaluate"):
        yield from _evaluate_method_cases(e)


def _evaluate_method_cases(e):
    for v, name in itertools.product(("1.5", "30%"), ("rose", "hdri")):
        yield _op("evaluate", "%s -evaluate %s %s" % (name, e, v), [img(name)],
                  ["-evaluate", e, v])
    if e not in ("LeftShift", "RightShift"):  # shift by pixel value: minutes per image
        yield _op("evaluate-sequence", "seq -evaluate-sequence %s" % e, [img("seq")],
                  ["-evaluate-sequence", e])


def _statistic_cases(lists):
    for s, g, name in itertools.product(_each(lists, "Statistic"), ("3x3", "5x2"),
                                        ("rose", "gray16")):
        yield _op("statistic", "%s -statistic %s %s" % (name, s, g), [img(name)],
                  ["-statistic", s, g])


def _noise_cases(lists):
    for n, name in itertools.product(_each(lists, "Noise"), ("rose", "gray16")):
        yield _op("noise", "%s +noise %s" % (name, n), [img(name)],
                  ["-seed", "3", "-attenuate", "0.7", "+noise", n])


def _dither_cases(lists):
    for d, name in itertools.product(_each(lists, "Dither"), ("rose", "granite")):
        yield _op("dither", "%s -dither %s -colors 8" % (name, d), [img(name)],
                  ["-dither", d, "-colors", "8"])
        yield _op("dither", "%s -dither %s -remap netscape:" % (name, d), [img(name)],
                  ["-dither", d, "-remap", "netscape:"])


def _layers_cases(lists):
    for l, name in itertools.product(_each(lists, "Layers"), ("seq", "anim")):
        yield _op("layers", "%s -layers %s" % (name, l), [img(name)], ["-layers", l])


def _complex_cases(lists):
    for c in _each(lists, "Complex"):
        yield _op("complex", "rose rose_blur -complex %s" % c,
                  [img("rose"), img("rose_blur")], ["-complex", c])


def _intensity_cases(lists):
    for i, name in itertools.product(_each(lists, "Intensity"), ("rose", "hdri")):
        yield _op("intensity", "%s -grayscale %s" % (name, i), [img(name)],
                  ["-grayscale", i])


def _sparse_color_cases(lists):
    for s in _each(lists, "SparseColor"):
        yield _op("sparse-color", "rose -sparse-color %s" % s, [img("rose")],
                  ["-sparse-color", s, "5,5 red  60,10 blue  30,40 green  10,40 yellow"])


def _type_cases(lists):
    for t, name in itertools.product(_each(lists, "Type"), ("rose", "rose_alpha")):
        yield _op("type", "%s -type %s" % (name, t), [img(name)], ["-type", t])


def _preview_cases(lists):
    for p in _each(lists, "Preview"):
        # a 9-frame montage; 8 bits keeps it small
        yield _op_to("preview", "rose -preview %s" % p,
                     [img("rose"), "-preview", p, "-font", "{C}/" + FONT, "-depth", "8"],
                     "preview:out.miff")


# ---- two-image and sequence operators
def _multi_cases():
    for op, names in TWO_IMAGE_OPS:
        yield _op("multi", "%s %s" % (" ".join(names), op),
                  [img(n) for n in names], _fmt(op))


def _sequence_cases():
    for op, name in itertools.product(SEQ_OPS, ("seq", "anim")):
        yield _op("sequence", "%s %s" % (name, op), [img(name)], _fmt(op))


# ---- compare, all metrics
def _compare_cases(lists):
    for m, (a, b, extra) in itertools.product(
            _each(lists, "Metric"),
            (("rose", "rose_blur", []), ("rose", "rose", []),
             ("rose", "rose_blur", ["-fuzz", "5%"]),
             ("rose_alpha", "rose", ["-highlight-color", "blue"]))):
        steps = [["compare", "-metric", m] + extra + [img(a), img(b)] + FLOAT_OUT
                 + ["diff.miff"]]
        yield _case("compare", "%s %s %s %s" % (m, a, b, " ".join(extra)),
                    steps, ["diff.miff"])
        # Without -verbose only the combined metric is printed, so a
        # change to one channel's value goes unseen; at default precision
        # so does a change in the last digits.
        steps = [["compare", "-verbose", "-precision", "17", "-metric", m] + extra
                 + [img(a), img(b)] + FLOAT_OUT + ["diff.miff"]]
        yield _case("compare", "verbose %s %s %s %s" % (m, a, b, " ".join(extra)),
                    steps, ["diff.miff"])
    yield _case("compare", "subimage-search",
                [["compare", "-metric", "RMSE", "-subimage-search",
                  img("rose"), "{C}/rose_patch.miff"] + FLOAT_OUT + ["diff.miff"]],
                ["diff-0.miff", "diff-1.miff"])


# ---- text output: -format escapes and identify
def _text_output_cases():
    for name in ("rose", "rose_alpha", "gray16", "cmyk", "palette", "hdri", "seq"):
        yield from _text_output_image_cases(name)


def _text_output_image_cases(name):
    for f in TEXT_OUTPUTS:
        yield _case("format", "%s %s" % (name, f),
                    [[img(name), "-format", f + "\\n", "info:"]], [])
        # Default precision prints 6 significant digits, which hides
        # last-bit differences in every computed statistic.
        yield _case("format", "%s -precision 17 %s" % (name, f),
                    [[img(name), "-precision", "17", "-format", f + "\\n",
                      "info:"]], [])
    for f in FX_PRINT:
        yield _case("fx-print", "%s %s" % (name, f),
                    [[img(name), "-precision", "17", "-format", f + "\\n",
                      "info:"]], [])
    for argv in INFO_OPS:
        yield _case("identify", "%s %s" % (name, " ".join(argv)),
                    [argv + [img(name)]], [])


# ---- montage
def _montage_cases():
    for op in MONTAGE_OPS:
        yield _case("montage", op,
                    [["montage"] + [img(n) for n in ("rose", "gray16", "palette", "granite")]
                     + _fmt(op) + ["out.miff"]], ["out.miff"])


# ---- encoders, with a decode of what was written
def _encode_cases(writable_formats):
    for f, variants in sorted(ENCODE_VARIANTS.items()):
        if f in writable_formats:
            yield from _encode_format_cases(f, variants)


def _encode_format_cases(f, variants):
    inputs = list(ENCODE_INPUTS) + (["seq"] if f in ENCODE_SEQ_FORMATS else [])
    for v, name in itertools.product(variants, inputs):
        yield _encode_case(f, v, name)


def _encode_case(f, v, name):
    enc = "enc.%s" % f
    steps = [[img(name)] + v + ["%s:%s" % (f, enc)]]
    outputs = [enc]
    if f not in ENCODE_ONLY:
        raw = ["-size", "{W:%s}x{H:%s}" % (name, name), "-depth",
               "{D:%s}" % name] if f in RAW_ENCODE else []
        steps.append(raw + ["%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"])
        outputs.append("dec.miff")
    return _case("encode", "%s %s -> %s" % (name, " ".join(v), f), steps, outputs)


# ---- raw formats at every depth and as floating point (quantum-export.c,
# quantum-import.c)
def _raw_cases(writable_formats):
    for f in ("rgb", "rgba", "gray", "cmyk", "cmyka", "bgr", "bgra", "rgbo", "ycbcr", "a",
              "r", "g", "b", "k", "o", "c", "m", "y"):
        if f in writable_formats:
            yield from _raw_format_cases(f)


def _raw_format_cases(f):
    for (depth, extra), name in itertools.product(
            (("1", []), ("4", []), ("12", []), ("16", []), ("32", []),
             ("16", ["-define", "quantum:format=floating-point"]),
             ("32", ["-define", "quantum:format=floating-point"]),
             ("64", ["-define", "quantum:format=floating-point"]),
             ("16", ["-endian", "MSB"]), ("8", ["-interlace", "plane"]),
             ("8", ["-interlace", "line"])),
            ("rose_alpha", "hdri")):
        enc = "enc.%s" % f
        steps = [[img(name), "-depth", depth] + extra + ["%s:%s" % (f, enc)],
                 ["-size", "{W:%s}x{H:%s}" % (name, name), "-depth", depth] + extra
                 + ["%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"]]
        yield _case("raw", "%s -depth %s %s -> %s" % (name, depth, " ".join(extra), f),
                    steps, [enc, "dec.miff"])


# ---- gaps found on the Windows machine (docs/refactoring/HARNESS-SPLIT.md)
# quantum-import.c and quantum-export.c: one routine per pixel layout and
# depth, and the raw family above reaches only some of them.
_FLOAT = ["-define", "quantum:format=floating-point"]
_SIGNED = ["-define", "quantum:format=signed"]
# Layouts the raw family never writes: GrayAlpha, BGRO and YCbCrA.
QUANTUM_NEW_FORMATS = ["graya", "bgro", "ycbcra"]
QUANTUM_NEW_FORMAT_DEPTHS = [
    ("8", []), ("1", []), ("2", []), ("4", []), ("10", []), ("12", []), ("16", []),
    ("24", []), ("32", []), ("16", _FLOAT), ("24", _FLOAT), ("32", _FLOAT),
    ("64", _FLOAT), ("8", _SIGNED), ("16", _SIGNED), ("16", ["-endian", "LSB"]),
    ("8", ["-interlace", "plane"]),
]
# Depths and sample formats the raw family skips, for the layouts it has:
# 2, 10 and 24 bits, 24-bit floats, signed samples, little-endian.
QUANTUM_OLD_FORMATS = ["gray", "rgb", "bgr", "rgba", "bgra", "rgbo", "o", "a", "cmyk",
                       "cmyka"]
QUANTUM_EXTRA_DEPTHS = [
    ("2", []), ("10", []), ("24", []), ("24", _FLOAT), ("8", _SIGNED), ("16", _SIGNED),
    ("16", ["-endian", "LSB"]),
]
# Palette images are stored as colormap indexes, at their own depths.
QUANTUM_INDEX_DEPTHS = ["1", "2", "4", "8", "16"]
# Upstream bug (ORACLE.md, "Known upstream issues"): reading BGRO as
# floating point gives a different image from run to run, single-threaded and
# with a fixed malloc fill: 3 decodes in 12 runs at 64 bits, 2 at 24 and 32.
# Integer and signed BGRO, and RGBO at every depth, are stable.
QUANTUM_UNSTABLE = {("bgro", "floating-point")}


def _quantum_unstable(f, extra):
    return (f, "floating-point") in QUANTUM_UNSTABLE and _FLOAT[1] in extra


def _quantum_round_trip(f, depth, extra, name):
    enc = "enc.%s" % f
    steps = [[img(name), "-depth", depth] + extra + ["%s:%s" % (f, enc)],
             ["-size", "{W:%s}x{H:%s}" % (name, name), "-depth", depth] + extra
             + ["%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"]]
    return _case("quantum", "%s -depth %s %s -> %s" % (name, depth, " ".join(extra), f),
                 steps, [enc, "dec.miff"])


def _quantum_layout_cases(writable_formats):
    combos = itertools.chain(
        itertools.product(QUANTUM_NEW_FORMATS, QUANTUM_NEW_FORMAT_DEPTHS),
        itertools.product(QUANTUM_OLD_FORMATS, QUANTUM_EXTRA_DEPTHS))
    for (f, (depth, extra)), name in itertools.product(combos, ("rose_alpha", "hdri")):
        if f in writable_formats and not _quantum_unstable(f, extra):
            yield _quantum_round_trip(f, depth, extra, name)


def _quantum_yuv_cases():
    # CbYCrY: UYVY and PAL, 16 bits a pixel, read back with the geometry.
    for f in ("uyvy", "pal"):
        steps = [[img("rose"), "%s:enc.%s" % (f, f)],
                 ["-size", "{W:rose}x{H:rose}", "%s:enc.%s" % (f, f)] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantum", "rose -> %s -> miff" % f, steps, ["enc." + f, "dec.miff"])


def _quantum_index_cases():
    for depth in QUANTUM_INDEX_DEPTHS:
        steps = [[img("palette"), "-depth", depth, "miff:enc.miff"],
                 ["enc.miff"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantum", "palette -depth %s -> miff" % depth, steps,
                    ["enc.miff", "dec.miff"])
    steps = [[img("rose_alpha"), "-colors", "8", "-type", "PaletteAlpha", "miff:enc.miff"],
             ["enc.miff"] + FLOAT_OUT + ["dec.miff"]]
    yield _case("quantum", "rose_alpha PaletteAlpha -> miff", steps, ["enc.miff", "dec.miff"])


def _quantum_meta_cases():
    # A meta channel makes the image multispectral: its own import and export,
    # whose floating-point branch needs a floating-point MIFF.
    for extra in ([], ["-depth", "16"]) + tuple(["-depth", d] + _FLOAT for d in ("16", "32", "64")):
        steps = [[img("rose"), "-channel-fx", "red=>meta"] + extra + ["miff:enc.miff"],
                 ["enc.miff"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantum", "rose red=>meta %s -> miff" % " ".join(extra), steps,
                    ["enc.miff", "dec.miff"])


# The second round: branches the first left unreached. Palette indexes as
# floating point, and at depth 1, which needs a two-colour palette; opacity
# and alpha as floating point; gray little-endian at more depths.
QUANTUM_INDEX_VARIANTS = [
    ("bilevel", ["-type", "Palette", "-depth", "1"]),
    ("bilevel", ["-type", "PaletteBilevelAlpha", "-depth", "1"]),
    ("palette", ["-depth", "16"] + _FLOAT), ("palette", ["-depth", "32"] + _FLOAT),
    ("rose_alpha", ["-colors", "8", "-type", "PaletteAlpha", "-depth", "32"] + _FLOAT),
]
QUANTUM_ROUND2 = [
    (f, depth, extra) for f in ("o", "a")
    for depth, extra in (("16", _FLOAT), ("32", _FLOAT), ("64", _FLOAT))
] + [("gray", depth, ["-endian", "LSB"] + x)
     for depth, x in (("32", []), ("64", _FLOAT), ("32", _FLOAT), ("24", []), ("8", []))]


def _quantum_round2_cases(writable_formats):
    for name, args in QUANTUM_INDEX_VARIANTS:
        steps = [[img(name)] + args + ["miff:enc.miff"], ["enc.miff"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantum", "%s %s -> miff" % (name, " ".join(args)), steps,
                    ["enc.miff", "dec.miff"])
    for (f, depth, extra), name in itertools.product(QUANTUM_ROUND2, ("rose_alpha", "hdri")):
        if f in writable_formats:
            yield _quantum_round_trip(f, depth, extra, name)


# pixel.c: the typed Import/Export*Pixel routines are called from the command
# line only through the JXL coder, which picks the storage type by depth (8 bits
# char, 16 short, floating point float) and the map by channels (RGB, RGBA, I,
# IA). The double, long, long-long and quantum routines are API only.
_GRAY_ALPHA = ["-alpha", "set", "-channel", "A", "-evaluate", "set", "60%", "+channel"]
PIXEL_JXL_INPUTS = [
    ("rose", []), ("rose_alpha", []), ("gray16", []), ("gray16", _GRAY_ALPHA),
]
PIXEL_JXL_DEPTHS = [["-depth", "8"], ["-depth", "16"], ["-depth", "32"] + _FLOAT]


def _pixel_jxl_cases(writable_formats):
    if "jxl" not in writable_formats:
        return
    for (name, pre), depth in itertools.product(PIXEL_JXL_INPUTS, PIXEL_JXL_DEPTHS):
        args = [img(name)] + pre + depth + ["-quality", "100", "enc.jxl"]
        steps = [args, ["enc.jxl"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("pixel", "%s %s -> jxl" % (name, " ".join(pre + depth)), steps,
                    ["enc.jxl", "dec.miff"])


# constitute.c: pinging a range of scenes through a filename pattern, and the
# MIME types of inline data URIs (GetImplicitDataImageType): a plain type, an
# "x-" prefix, a "+suffix", and malformed ones, whose errors are compared too.
_PPM_2X1 = "P3\n2 1\n255\n255 0 0 0 0 255\n"
_SVG_4X3 = ('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3">'
            '<rect width="4" height="3" fill="red"/></svg>')
DATA_URI_TYPES = [("image/ppm", _PPM_2X1), ("image/x-portable-pixmap", _PPM_2X1),
                  ("image/svg+xml", _SVG_4X3), ("image/x-svg", _SVG_4X3),
                  ("noslash", _PPM_2X1), ("image/", _PPM_2X1), ("image/x-", _PPM_2X1)]
PING_SCENES = ["frame%d.miff[0-2]", "frame%d.miff[1]", "frame%d.miff[0-1]"]


def _constitute_cases():
    for mime, text in DATA_URI_TYPES:
        uri = "inline:data:%s;base64,%s" % (mime, base64.b64encode(text.encode()).decode())
        yield _op_to("constitute", "inline data %s" % mime, [uri] + FLOAT_OUT, "out.miff")
    for pattern in PING_SCENES:
        steps = [[img("anim"), "+adjoin", "frame%d.miff"], ["identify", "-ping", pattern]]
        yield _case("constitute", "identify -ping %s" % pattern, steps, [])
    # Pings that fail: PingImage must not touch the image the reader did not return.
    for name, text in (("bad.miff", "garbage"), ("zero.ppm", "P6\n0 0\n255\n")):
        yield _with_inputs(_case("constitute", "identify -ping failing %s" % name,
                                 [["identify", "-ping", name]], []), files={name: text})
    yield _case("constitute", "identify -ping missing file",
                [["identify", "-ping", "missing.miff"]], [])


# token.c: GlobExpression, reached through wildcards in input filenames,
# which ImageMagick expands itself. Some patterns match surprisingly
# (`frame[!0]` gives frame0 only, `frame[0-]` every frame); that is what the
# oracle keeps.
GLOB_PATTERNS = ["frame*.miff", "frame?.miff", "frame[0-1].miff", "frame[!0].miff",
                 "frame[^0].miff", "frame{0,2}.miff", "fr*me?.miff", "frame[12]*",
                 "fram\\e1.miff", "frame\\*.miff", "*[2].miff", "frame[0-].miff",
                 "frame{1,}.miff", "**.miff"]


def _glob_cases():
    for pattern in GLOB_PATTERNS:
        steps = [[img("anim"), "+adjoin", "frame%d.miff"],
                 [pattern, "-format", "%f %wx%h\\n", "info:"]]
        yield _case("token", "glob %s" % pattern, steps, [])


# blob.c: ReadBlobString, which the text coders read lines with. Every text
# file the catalogue read ended in a newline, and the parsers ignore trailing
# whitespace, so the end-of-line and end-of-file handling was never tested:
# these end without a newline, or with CRLF.
_TXT_HEADER = "# ImageMagick pixel enumeration: 2,1,255,srgb"
_TXT_LINES = [_TXT_HEADER, "0,0: (255,0,0)", "1,0: (0,0,255)"]
_CUBE_LINES = ["LUT_3D_SIZE 2", "0 0 0", "1 0 0", "0 1 0", "1 1 0", "0 0 1", "1 0 1",
               "0 1 1", "1 1 1"]
LINE_ENDINGS = [("lf", "\n", "\n"), ("lf, no final newline", "\n", ""),
                ("crlf", "\r\n", "\r\n"), ("crlf, no final newline", "\r\n", "")]


def _text_file(lines, eol, final):
    return eol.join(lines) + final


def _read_blob_string_cases():
    for label, eol, final in LINE_ENDINGS:
        case = _op_to("blob", "txt %s" % label, ["txt:in.txt"] + FLOAT_OUT, "out.miff")
        yield _with_inputs(case, files={"in.txt": _text_file(_TXT_LINES, eol, final)})
    for label, eol, final in LINE_ENDINGS[1:]:
        case = _case("blob", "cube %s" % label,
                     [["cube:lut.cube", "-format", "%wx%h %[fx:mean]\\n", "info:"]], [])
        yield _with_inputs(case, files={"lut.cube": _text_file(_CUBE_LINES, eol, final)})


# blob.c: the paths through a temporary file and past the end of a file.
# ImageToBlob writes formats without blob support (SVG) to a temporary file and
# reads it back; the PNG that SVG embeds would carry dates without the define.
# ImageToFile copies a non-seekable stdin to a temporary file in 1 MiB chunks,
# and the hald image (1.5 MB) takes two. A raw header offset past the end of
# the file makes DiscardBlobBytes reach EOF.
def _poly_points():
    """25 control points on a 5x5 grid over rose, each moved by a smooth wave:
    enough for a quintic (21 terms), and not a plain affine map."""
    pts = []
    for j in range(5):
        for i in range(5):
            x, y = i * 17.0, j * 11.0
            u = x + 2.0 * math.sin(0.09 * x + 0.13 * y)
            v = y + 1.5 * math.cos(0.11 * x - 0.07 * y)
            pts.append("%g,%g %.2f,%.2f" % (x, y, u, v))
    return "  ".join(pts)


# distort.c: the catalogue's only polynomial was order 2, so the bilinear
# order, the cubic to quintic terms (poly_basis_fn/dx/dy) and the order and
# control-point checks never ran. -verbose prints the fitted terms as an -fx
# expression; +verbose keeps the timing line of the write out.
def _distort_poly_cases():
    pts = _poly_points()
    for order in ("1", "1.5", "3", "4", "5"):
        yield _op("distort", "polynomial order %s" % order, [img("rose")],
                  ["-distort", "Polynomial", "%s %s" % (order, pts)])
        yield _op("distort", "polynomial order %s verbose" % order, [img("rose")],
                  ["-verbose", "-distort", "Polynomial", "%s %s" % (order, pts), "+verbose"])
    yield _op("distort", "polynomial order 3 +distort", [img("rose")],
              ["+distort", "Polynomial", "3 " + pts])
    for order in ("0.5", "2.5", "6"):
        yield _op("distort", "polynomial invalid order %s" % order, [img("rose")],
                  ["-distort", "Polynomial", "%s %s" % (order, pts)])
    yield _op("distort", "polynomial too few points", [img("rose")],
              ["-distort", "Polynomial", "3 0,0 1,1  69,0 65,4  0,45 3,41  69,45 60,40"])


# fx.c: image statistics per pixel (ImageStat), hexadecimal colours
# (GetHexColour), %[...] properties and epoch() (GetProperty), attributes of
# other images, and the fx:debug dump of the compiled expression (DumpTables,
# DumpRPN, OprStr), none of which the catalogue's expressions used.
FX_EXPRESSIONS = [
    "u.mean", "u.maxima-u.minima", "u.standard_deviation", "u.kurtosis", "u.skewness/10",
    "u.median", "u.depth/16", "u.mean.r", "mean.g", "u.r.mean",
    "u.extent/1e5", "u.page.x", "u.resolution.x", "u.printsize.x", "u.quality/100",
    "#ff8000", "#f80", "#ff800080", "#ff80", "u*0.5+#102030", "#ff8",
    "%[w]/100", "%[myval]", "epoch(%[mydate])/1e10", "%[nosuch",
]
FX_DEBUG_EXPRESSIONS = ["u*0.5+0.1", "xx=u.mean; yy=#ff0000; u*xx+yy*(1-xx)",
                        "u.mean.r+v.maxima+u[1].minima", "%[w]>50 ? u : 1-u"]


def _fx_gap_cases():
    props = ["-set", "myval", "0.25", "-set", "mydate", "2020-01-02T03:04:05"]
    for e in FX_EXPRESSIONS:
        yield _op("fx", "-fx %s" % e, [img("rose")] + props, ["-fx", e])
    yield _op("fx", "-fx attributes of other images", [img("rose"), img("granite")],
              ["-fx", "v.mean+u[1].maxima-s.minima"])
    for e in FX_DEBUG_EXPRESSIONS:
        yield _case("fx", "fx:debug %s" % e,
                    [[img("rose"), img("granite"), "-define", "fx:debug=true", "-fx", e,
                      "null:"]], [])


# composite.c: compose:args forms the catalogue never gave. Blur with an
# ellipse, an angle and an angle range; displace and distort with percent,
# aspect (!) and centre offsets; dissolve above 100% and below 0; blend with
# both factors; threshold with and without its threshold; the blends' iteration
# arguments; and the compose:illuminant and compose:colorspace defines.
COMPOSE_ARGS = [
    ("blur", "3", "gray8"), ("blur", "3x1.5", "gray8"), ("blur", "3x1.5+30", "gray8"),
    ("blur", "3x1.5+0+90", "gray8"),
    ("displace", "50x50%", "gray8"), ("displace", "50x50%!", "gray8"),
    ("displace", "20x10!", "gray8"), ("displace", "20x10+5+3", "gray8"),
    ("displace", "20x10+5+3!", "gray8"),
    ("distort", "50x50%", "gray8"), ("distort", "50x50%!", "gray8"),
    ("distort", "20x10!", "gray8"), ("distort", "20x10+5+3", "gray8"),
    ("distort", "20x10+5+3!", "gray8"),
    ("dissolve", "150", "rose_alpha"), ("dissolve", "60x150", "rose_alpha"),
    ("dissolve", "-10", "rose_alpha"), ("blend", "30x80", "rose_blur"),
    ("threshold", "0.5x0.1", "rose_blur"), ("threshold", "0.5", "rose_blur"),
    ("saliency-blend", "20x0.001+5", "rose_patch"),
    ("seamless-blend", "20x0.001+5", "rose_patch"),
]
COMPOSE_DEFINES = ["compose:illuminant=nosuch", "compose:colorspace=nosuch",
                   "compose:illuminant=A"]


# colorspace.c and composite.c: Hue, Saturate, Luminize and Colorize convert
# through compose:colorspace (HCL by default). A colorspace the generic
# converters do not list (sRGB, Gray) takes their default branch, which no
# case reached; XYZ and Lab take listed ones.
COMPOSE_HUE_OPS = ["hue", "saturate", "luminize", "colorize"]
COMPOSE_COLORSPACES = ["sRGB", "Gray", "XYZ", "Lab"]


def _compose_colorspace_gap_cases():
    for c, cs in itertools.product(COMPOSE_HUE_OPS, COMPOSE_COLORSPACES):
        yield _op("composite", "rose %s rose_blur compose:colorspace=%s" % (c, cs),
                  [img("rose"), img("rose_blur")],
                  ["-define", "compose:colorspace=" + cs, "-compose", c, "-composite"])


def _composite_gap_cases():
    for c, args, src in COMPOSE_ARGS:
        yield _op("composite", "rose %s compose:args=%s %s" % (c, args, src),
                  [img("rose"), img(src)],
                  ["-define", "compose:args=" + args, "-compose", c, "-composite"])
    for define in COMPOSE_DEFINES:
        yield _op("composite", "rose over rose_alpha %s" % define,
                  [img("rose"), img("rose_alpha")],
                  ["-define", define, "-compose", "over", "-composite"])


# feature.c: the information measures of correlation sum p*log2(p) over every
# pair of grey levels, so they print NaN unless every pair occurs in every
# direction: in the catalogue's images they always did, and no mutant there
# could show. Noise images with two or three levels give finite values; with
# CMYK and alpha for those channels, and distances at and past the image size.
# The images are made in the command and printed with -verbose info:, and the
# date properties removed, which would otherwise date each run.
_NOISE = ["-seed", "5", "-size", "48x48", "xc:", "+noise", "Random"]
FEATURE_IMAGES = [
    ("gray, 2 levels", ["-seed", "3", "-size", "32x32", "xc:", "+noise", "Random",
                        "-colorspace", "gray", "-threshold", "50%"]),
    ("gray, 3 levels", _NOISE + ["-colorspace", "gray", "-posterize", "3"]),
    ("rgb, 2 levels", _NOISE + ["-posterize", "2"]),
    ("cmyk, 2 levels", _NOISE + ["-colorspace", "CMYK", "-posterize", "2"]),
    ("rgba, 2 levels", _NOISE + ["-posterize", "2", "(", "-seed", "9", "-size", "48x48",
                                 "xc:", "+noise", "Random", "-colorspace", "gray",
                                 "-threshold", "50%", ")", "-alpha", "off", "-compose",
                                 "CopyOpacity", "-composite"]),
]
_NO_DATES = ["+set", "date:create", "+set", "date:modify", "+set", "date:timestamp"]


def _feature_cases():
    for label, make in FEATURE_IMAGES:
        for distance in ("1", "2"):
            yield _case("feature", "features %s distance %s" % (label, distance),
                        [make + _NO_DATES + ["-precision", "17", "-features", distance,
                                             "-verbose", "info:"]], [])
    small = ["-seed", "3", "-size", "8x8", "xc:", "+noise", "Random", "-colorspace", "gray",
             "-threshold", "50%"]
    for distance in ("7", "8"):
        yield _case("feature", "features 8x8 distance %s" % distance,
                    [small + _NO_DATES + ["-precision", "17", "-features", distance,
                                          "-verbose", "info:"]], [])


# resample.c: ResamplePixelColor's shortcuts for areas outside the image,
# per virtual-pixel method, and its averaged result once the EWA ellipse hits
# its limits. A steep perspective puts a horizon in the viewport, where the
# ellipses grow without bound; a 2.5x magnification near the edges gives small
# ellipses that straddle the border.
RESAMPLE_VIRTUAL_PIXELS = [
    "background", "black", "checker-tile", "dither", "edge", "gray", "horizontal-tile",
    "horizontal-tile-edge", "mirror", "none", "random", "tile", "transparent",
    "vertical-tile", "vertical-tile-edge", "white",
]
RESAMPLE_DISTORTIONS = [
    ("steep perspective", ["-define", "distort:viewport=90x70-10-10", "+distort",
                           "Perspective", "0,0 0,0  69,0 69,0  0,45 30,6  69,45 39,6"]),
    ("2.5x near the edges", ["-define", "distort:viewport=60x40+150+95", "-distort", "SRT",
                             "0,0 2.5 0 0,0"]),
]


# distort.c: SparseColorImage only ever ran on RGB with the default channels.
# Every method on CMYK (-channel CMYK), with alpha (-channel RGBA, colours with
# alpha) and on a gray image; the -verbose report of the fitted coefficients for
# the two fitted methods, in RGBA and CMYK; and two points closer than a pixel,
# which caps the inverse-distance weight. Colours in hex: names need colors.xml.
SPARSE_METHODS = ["Barycentric", "Bilinear", "Shepards", "Inverse", "Voronoi", "Manhattan"]
_SPARSE_CMYK = "5,5 cmyk(10%,20%,30%,40%)  60,10 cmyk(80%,0,0,10%)  30,40 cmyk(0,50%,50%,0)"
_SPARSE_RGBA = "5,5 #ff000080  60,10 #0000ff  30,40 #00ff0040  10,40 #ffff00"
_SPARSE_GRAY = "5,5 #ffffff  30,10 #000000  10,25 #808080"


def _sparse_color_gap_cases():
    for s in SPARSE_METHODS:
        yield _op("distort", "cmyk -sparse-color %s" % s, [img("cmyk")],
                  ["-channel", "CMYK", "-sparse-color", s, _SPARSE_CMYK])
        yield _op("distort", "rose_alpha -channel RGBA -sparse-color %s" % s,
                  [img("rose_alpha")], ["-channel", "RGBA", "-sparse-color", s, _SPARSE_RGBA])
        yield _op("distort", "gray8 -sparse-color %s" % s, [img("gray8")],
                  ["-sparse-color", s, _SPARSE_GRAY])
    for s in ("Barycentric", "Bilinear"):
        yield _op("distort", "rose_alpha -verbose -sparse-color %s" % s, [img("rose_alpha")],
                  ["-verbose", "-channel", "RGBA", "-sparse-color", s, _SPARSE_RGBA,
                   "+verbose"])
        yield _op("distort", "cmyk -verbose -sparse-color %s" % s, [img("cmyk")],
                  ["-verbose", "-channel", "CMYK", "-sparse-color", s, _SPARSE_CMYK,
                   "+verbose"])
    for s in ("Shepards", "Inverse"):
        yield _op("distort", "rose -sparse-color %s points 0.2 apart" % s, [img("rose")],
                  ["-sparse-color", s, "5,5 #ff0000  5.2,5 #0000ff  40,30 #00ff00"])


# quantum.c: SetQuantumMetaChannel and SetQuantumPad are called by the TIFF and
# PSD coders for images with meta channels, which no case had. -combine with
# five gray images makes one (RGBA plus a meta channel); written as TIFF,
# contiguous and planar at 8 and 16 bits, and as PSD, then read back.
_META5 = [img("rose"), "-separate", img("gray8"), "-resize", "70x46!", img("granite"),
          "-resize", "70x46!", "-colorspace", "gray", "-combine", "m5.miff"]
META_CHANNEL_WRITES = [
    ("tif", []), ("tif", ["-interlace", "plane"]), ("tif", ["-depth", "16"]),
    ("tif", ["-depth", "16", "-interlace", "plane"]), ("psd", []),
]


def _meta_channel_gap_cases():
    for fmt, extra in META_CHANNEL_WRITES:
        enc = "enc." + fmt
        yield _case("metachannel", "5 channels %s %s" % (" ".join(extra), fmt),
                    [_META5, ["m5.miff"] + extra + [enc],
                     [enc] + FLOAT_OUT + ["dec.miff"]], ["dec.miff"])


# exception.c: InheritException is reached when looking up a coder raises a
# policy error, which a module policy does (static.c, RegisterStaticModule).
# The policy file is the case's own ($HOME is the case directory).
def _exception_gap_cases():
    policy = (".config/ImageMagick/policy.xml",
              '<policymap>\n  <policy domain="module" rights="none" pattern="GIF" />\n'
              '</policymap>\n')
    # x.gif holds MIFF (the policy forbids writing GIF too); gif: forces the GIF lookup.
    steps = [[img("rose"), "miff:x.gif"], ["gif:x.gif", "out.miff"], [img("rose"), "out.miff"]]
    yield _with_inputs(_case("exception", "module policy denies GIF, then read a GIF",
                             steps, ["out.miff"]), files=dict([policy]))


# histogram.c: MinMaxStretchImage skips LevelImage when the image is flat
# (minimum equals maximum), overall and per channel; no -auto-level case had a
# flat image or a flat channel.
def _auto_level_gap_cases():
    yield _op("histogram", "flat gray -auto-level", ["-size", "8x6", "xc:#666666"],
              ["-auto-level"])
    yield _op("histogram", "flat red channel -channel R -auto-level",
              ["-size", "8x6", "gradient:#406080-#40a0ff"], ["-channel", "R", "-auto-level"])
    # IsPaletteImage's boundary: a PseudoClass image of exactly MaxColormapSize colours.
    yield _case("histogram", "65536-colour palette, type and colours",
                [["-size", "256x256", "xc:#000000", "-channel", "R", "-fx", "i/255",
                  "-channel", "G", "-fx", "j/255", "+channel", "-depth", "16", "+dither",
                  "-colors", "65536", "-format", "%[type] %k %r\n", "info:"]], [])
    yield _op("histogram", "gradient -channel RGB -auto-level",
              ["-size", "8x6", "gradient:#406080-#40a0ff"], ["-channel", "RGB", "-auto-level"])


# matrix.c: MatrixToImage runs only for hough-lines:accumulator, and the matrix
# is kept in a file (SetMatrixExtent, Read/WriteMatrixElements) only when memory
# and map are exhausted, which -limit memory 0 -limit map 0 forces.
_HOUGH_INPUT = ["-size", "40x30", "xc:#000000", "-fill", "#ffffff", "-draw", "line 2,3 37,25",
                "-draw", "line 5,27 35,4"]
_NO_MEMORY = ["-limit", "memory", "0", "-limit", "map", "0"]


def _matrix_gap_cases():
    for label, pre in (("accumulator", ["-define", "hough-lines:accumulator=true"]),
                       ("accumulator, matrix on disk",
                        _NO_MEMORY + ["-define", "hough-lines:accumulator=true"]),
                       ("matrix on disk", _NO_MEMORY)):
        yield _op("matrix", "-hough-lines %s" % label, _HOUGH_INPUT,
                  pre + ["-hough-lines", "9x9+10"])


# stream.c: StreamImagePixels has a fast path per map and storage type, and
# the generic loop for the rest. The stream family above has no BGRA or BGRP
# map, and no multi-letter map with O (opacity) or I (intensity), which only the
# generic loop handles.
STREAM_GAP_MAPS = ["bgra", "bgrp", "ro", "gi"]
STREAM_STORAGE_TYPES = ["char", "short", "long", "longlong", "float", "double", "quantum"]


def _stream_gap_cases():
    for name, m, t in itertools.product(("rose", "rose_alpha"), STREAM_GAP_MAPS,
                                        STREAM_STORAGE_TYPES):
        yield _case("stream", "stream %s -map %s -storage-type %s" % (name, m, t),
                    [["stream", "-map", m, "-storage-type", t, img(name), "out.raw"]],
                    ["out.raw"])


# signature.c: FinalizeSignature pads the message to 56 bytes mod 64, with an
# extra block when it is already past 56. An image signature hashes 4 bytes per
# channel and pixel, and the catalogue's images all ended below 56 mod 64. RGB
# rows of 10 and 5 pixels (120 and 60 bytes) and gray rows of 14 and 15 (56,
# 60) end past it; with one and three rows.
SIGNATURE_IMAGES = [("rgb", "10x1"), ("rgb", "5x1"), ("rgb", "10x3"), ("gray", "14x1"),
                    ("gray", "15x1"), ("gray", "15x3")]


def _signature_gap_cases():
    for kind, size in SIGNATURE_IMAGES:
        make = ["-size", size, "gradient:#336699-#99ccff"]
        if kind == "gray":
            make += ["-colorspace", "gray"]
        yield _case("signature", "%%# of a %s %s image" % (kind, size),
                    [make + ["-format", "%# %[channels]\\n", "info:"]], [])


# quantize.c: GetImageQuantizeError runs only under -verbose, whose report
# prints the mean and maximum error; posterize with dithering and per channel,
# k-means with an iteration limit and tolerance and with seed colours, and
# Floyd-Steinberg on alpha, CMYK and gray, which the catalogue gave only rose.
QUANTIZE_GAP_OPS = [
    ["-posterize", "3", "-dither", "FloydSteinberg"], ["-channel", "R", "-posterize", "2"],
    ["-kmeans", "5x10+0.01"],
    ["-define", "kmeans:seed-colors=#ff0000;#00ff00;#0000ff", "-kmeans", "3"],
    ["-dither", "FloydSteinberg", "-colors", "6"],
]


def _quantize_gap_cases():
    for name in ("rose", "rose_alpha"):
        yield _case("quantizegap", "%s -verbose -colors 16 info:" % name,
                    [[img(name), "-verbose", "-colors", "16", "info:"]], [])
    for name, op in itertools.product(("rose_alpha", "cmyk", "gray8"), QUANTIZE_GAP_OPS):
        yield _op("quantizegap", "%s %s" % (name, " ".join(op)), [img(name)], op)


# resource.c: FormatTimeToLive prints the time limit in -list resource, as
# years, months, weeks, days, hours, minutes or seconds; no case set a time
# limit. -limit before -list is rejected, so a policy.xml of the case's own
# sets it.
RESOURCE_TIME_LIMITS = ["31536000", "2628000", "1209600", "172800", "7200", "120", "61"]


def _resource_gap_cases():
    for t in RESOURCE_TIME_LIMITS:
        policy = ('<policymap>\n  <policy domain="resource" name="time" value="%s"/>\n'
                  '</policymap>\n' % t)
        yield _with_inputs(_case("resource", "-list resource with a time limit of %s" % t,
                                 [["-list", "resource"]], []),
                           files={".config/ImageMagick/policy.xml": policy})


# quantize.c, second round: every posterize case dithered, so PosterizeImage's
# plain loop and its colormap branch never ran (+dither); k-means with fewer
# seed colours than clusters, and under -verbose (the colours per iteration);
# a remap over a sequence (RemapImages, -remap and +remap).
QUANTIZE_GAP2_OPS = [
    ["+dither", "-posterize", "3"], ["+dither", "-channel", "R", "-posterize", "2"],
]


def _quantize_gap2_cases():
    for name, op in itertools.product(("rose", "palette", "rose_alpha"), QUANTIZE_GAP2_OPS):
        yield _op("quantizegap2", "%s %s" % (name, " ".join(op)), [img(name)], op)
    yield _op("quantizegap2", "rose -kmeans 4 with two seed colours", [img("rose")],
              ["-define", "kmeans:seed-colors=#ff0000;#00ff00", "-kmeans", "4"])
    for name in ("rose", "rose_alpha", "cmyk"):
        yield _case("quantizegap2", "%s -verbose -kmeans 4x5+0.001" % name,
                    [[img(name), "-verbose", "-kmeans", "4x5+0.001", "+verbose", "null:"]], [])
    yield _op("quantizegap2", "seq -remap palette", [img("seq")], ["-remap", img("palette")])
    yield _op("quantizegap2", "seq +remap", [img("seq")], ["+remap"])


# distort.c, DistortImage: -verbose prints each method's coefficients as an
# -fx expression, which only Polynomial had; +distort (best fit) for every
# method; distort:scale above and below 1; and a perspective whose viewport
# shows the horizon, where pixels past it are invalid.
def _distort_gap_cases():
    for m, args in sorted(_DISTORT_ARGS.items()):
        yield _op("distortgap", "rose -verbose -distort %s" % m, [img("rose")],
                  ["-verbose", "-distort", m, args, "+verbose"])
        yield _op("distortgap", "rose +distort %s" % m, [img("rose")], ["+distort", m, args])
    for m in ("SRT", "Arc", "Barrel", "Cylinder2Plane"):
        for scale in ("2", "0.05"):
            yield _op("distortgap", "rose distort:scale=%s -distort %s" % (scale, m),
                      [img("rose")], ["-define", "distort:scale=" + scale, "-distort", m,
                                      _DISTORT_ARGS[m]])
    yield _op("distortgap", "rose +distort Perspective past the horizon", [img("rose")],
              ["-define", "distort:viewport=90x70-10-10", "+distort", "Perspective",
               "0,0 0,0  69,0 69,0  0,45 30,6  69,45 39,6"])


# fx.c, ExecuteRPN: operators, functions and symbols no expression used (!=,
# <=, >=, ||, !, jinc, clamp, drc, squish, ++ on a user symbol), the
# per-channel symbols a b c g k m o r y, channel qualifiers on p{} and p[]
# lookups, also of the second image (u[1], v, s), the loops, and printsize; on
# an image with alpha and on CMYK, with granite as the second image.
FX_GAP2_EXPRESSIONS = [
    "u!=0.5", "u<=0.5", "u>=0.5", "u||0", "0||u", "!u", "jinc(u)", "jinc(0)",
    "clamp(u*2-0.5)", "drc(u,0.5)", "squish(u)", "xx=0.1; xx++; xx",
    "a", "b", "c", "g", "k", "m", "o", "r", "y",
    "p{1,1}.hue", "p{1,1}.saturation", "p{1,1}.lightness", "p{1,1}.intensity",
    "p[1,1].hue", "p[1,1].intensity", "u[1].p{2,2}.hue", "v.p{1,1}.intensity",
    "v.p[1,1].lightness", "s.p{1,1}.saturation",
    "xx=0; while(xx<3, xx++); xx/3", "xx=0; do(xx++, xx<3); xx/3",
    "for(xx=0, xx<3, xx++); xx/3", "u.printsize.y/1e14",
]


def _fx_gap2_cases():
    for name, e in itertools.product(("rose_alpha", "cmyk"), FX_GAP2_EXPRESSIONS):
        yield _op("fxgap2", "%s granite -fx %s" % (name, e), [img(name), img("granite")],
                  ["-fx", e])


# cache.c: PersistPixelCache runs only for the MPC format, which no case wrote
# or read; written and read back for four kinds of image. And an MVG mask
# (draw.c sets a composite mask), which may reach MaskPixelCacheNexus.
_MVG_MASK = ("viewbox 0 0 40 30\npush defs\npush mask m1\nfill #ffffff\n"
             "circle 20,15 20,4\npop mask\npop defs\npush graphic-context\n"
             "mask url(#m1)\nfill #ff0000\nrectangle 0,0 40,30\npop graphic-context\n")


def _cache_gap_cases():
    for name in ("rose", "rose_alpha", "cmyk", "palette"):
        yield _case("cachegap", "%s through MPC" % name,
                    [[img(name), "out.mpc"], ["out.mpc"] + FLOAT_OUT + ["dec.miff"]],
                    ["dec.miff"])
    yield _with_inputs(_op_to("cachegap", "MVG with a mask",
                              ["-size", "40x30", "xc:#0000ff", "-draw", "@m.mvg"] + FLOAT_OUT,
                              "out.miff"), files={"m.mvg": _MVG_MASK})


# xml-tree.c: ValidateEntities checks parameter entities in an internal
# DOCTYPE, which no configuration file had: nested, circular and undefined
# ones, in a policy.xml of the case's own, listed. The other unreached
# functions (XMLTreeInfoToXML, AddPathToXMLTree, CanonicalXMLContent, ...) are
# called only from MagickWand's drawing wand, or nowhere.
XML_DOCTYPES = {
    "nested": '<!ENTITY % w "10KP">\n  <!ENTITY % nested "%w;">\n  <!ENTITY limit "%nested;">',
    "circular": '<!ENTITY % a "%b;">\n  <!ENTITY % b "%a;">\n  <!ENTITY limit "%a;">',
    "undefined": '<!ENTITY limit "%nosuch;">',
}


def _xml_gap_cases():
    for label, doctype in sorted(XML_DOCTYPES.items()):
        policy = ('<?xml version="1.0"?>\n<!DOCTYPE policymap [\n  %s\n]>\n<policymap>\n'
                  '  <policy domain="resource" name="width" value="&limit;"/>\n'
                  '</policymap>\n' % doctype)
        yield _with_inputs(_case("xmlgap", "policy.xml with %s parameter entities" % label,
                                 [["-list", "policy"]], []),
                           files={".config/ImageMagick/policy.xml": policy})


# color.c: -list color (ListColorInfo, GetColorInfoList, GetColorList), and
# %[pixel:] on CMYK, Oklch (the hue component), HDRI (QueryColorname above 16
# bits) and on colours that are not exact at 8 bits (IsSVGCompliant).
COLOR_PIXEL_IMAGES = [
    ("cmyk", [img("cmyk")]), ("oklch", [img("rose"), "-colorspace", "Oklch"]),
    ("hdri", [img("hdri")]), ("16-bit", ["-size", "1x1", "xc:srgb(50.5%,10.25%,20%)",
                                        "-depth", "16"]),
    ("8-bit off by one", ["-size", "1x1", "xc:#ff0001"]),
]


def _color_gap_cases():
    yield _case("colorgap", "-list color", [["-list", "color"]], [])
    for label, make in COLOR_PIXEL_IMAGES:
        yield _case("colorgap", "%%[pixel:] of %s" % label,
                    [make + ["-format", "%[pixel:p{0,0}] %[pixel:p]\\n", "info:"]], [])


# composite.c: TextureImage with a tile offset and a texture with alpha
# (tile:), and SeamlessBlendImage under -verbose, which prints its residual per
# tick. Not under -compose multiply: tile: then composes onto a canvas that is
# not initialised, and the output differs from run to run (1 in 4; ORACLE.md,
# "Known upstream issues").
def _texture_gap_cases():
    for t, offset in itertools.product(("rose_patch", "rose_alpha"), ("+3+2", "+7+1")):
        yield _op_to("texturegap", "tile:%s -tile-offset %s" % (t, offset),
                     ["-size", "40x30", "-tile-offset", offset, "tile:" + img(t)] + FLOAT_OUT,
                     "out.miff")
    yield _case("texturegap", "seamless-blend -verbose",
                [[img("rose"), img("rose_patch"), "-verbose", "-define",
                  "compose:args=50x0.0001+10", "-compose", "seamless-blend", "-composite",
                  "+verbose", "null:"]], [])


# distort.c, GenerateCoefficients: argument counts the distort table never
# gave. Affine with one and two control points; Arc with one to four
# arguments; Polar and DePolar with each optional argument, the -1 radius and
# too many; Barrel with three and eight; out-of-range fields of view for the
# cylinder methods; shepards:power; too few points for Perspective and
# Bilinear. Errors are compared too.
DISTORT_ARG_CASES = [
    ("Affine", "10,10 20,15"), ("Affine", "10,10 20,15  50,30 55,40"),
    ("Arc", "60"), ("Arc", "60 10"), ("Arc", "60 10 50"), ("Arc", "60 10 50 20"),
    # rotations whose normalised start angle is exactly 0.5 or 0 turns (MagickRound's tie)
    ("Arc", "60 270"), ("Arc", "360 90"),
    ("Polar", "-1"), ("Polar", "40 10"), ("Polar", "40 10 30 20"),
    ("Polar", "40 10 30 20 10 350"), ("Polar", "1 2 3 4 5 6 7"),
    ("DePolar", "-1"), ("DePolar", "40 10 30 20 10 350"),
    ("Barrel", "0.1 0.0 -0.2"), ("Barrel", "0.0 0.0 -0.2 1.1 0.1 0.0 0.05 1.0"),
    ("Barrel", "1 2 3 4 5 6 7"),
    ("Cylinder2Plane", "170"), ("Cylinder2Plane", "0"), ("Plane2Cylinder", "170"),
    ("Perspective", "0,0 3,4  69,0 60,5  0,45 8,40"),
    ("BilinearForward", "0,0 3,4  69,0 60,5  0,45 8,40"),
]


def _distort_args_gap_cases():
    for m, args in DISTORT_ARG_CASES:
        yield _op("distortargs", "rose -distort %s %s" % (m, args), [img("rose")],
                  ["-distort", m, args])
    for power in ("3", "0.5"):
        yield _op("distortargs", "rose shepards:power=%s" % power, [img("rose")],
                  ["-define", "shepards:power=" + power, "-distort", "Shepards",
                   _DISTORT_ARGS["Shepards"]])


# fx.c, third round: colour constants in an expression (GetConstantColour,
# 20%): colour functions srgb, rgb, hsl, cmyk, srgba, gray, device-gray, a
# named colour, an out-of-range component and a missing ')'; page.width and
# page.height (MaybeXYWH, 23%); and channel qualifiers on u, v, u[1] and s
# (GetChannelQualifier, 47%).
FX_GAP3_EXPRESSIONS = [
    "srgb(50%,20%,10%)", "rgb(255,0,0)*u", "hsl(120,50%,50%)", "cmyk(0,50%,50%,0)",
    "srgba(10%,20%,30%,0.5)", "navy", "u*red", "rgb(300,0,0)", "srgb(10%,20%",
    "gray(50%)", "device-gray(0.5)",
    "u.page.width/100", "u.page.height/100", "u.page.x+u.page.width/100",
    "u.r", "v.g", "u[1].b", "s.b",
]


def _fx_gap3_cases():
    for e in FX_GAP3_EXPRESSIONS:
        yield _op("fxgap3", "rose granite -fx %s" % e, [img("rose"), img("granite")], ["-fx", e])


# matrix.c: AcquireMatrixInfo keeps a matrix in a file only when it is larger
# than the max-memory-request policy (not when memory is limited), so
# SetMatrixExtent never ran; a policy.xml of the case's own sets it to 256 bytes.
def _matrix_gap2_cases():
    policy = ('<policymap>\n  <policy domain="system" name="max-memory-request" '
              'value="256"/>\n</policymap>\n')
    for label, pre in (("accumulator", ["-define", "hough-lines:accumulator=true"]), ("lines", [])):
        yield _with_inputs(_op("matrixgap2", "-hough-lines %s, max-memory-request 256" % label,
                               _HOUGH_INPUT, pre + ["-hough-lines", "9x9+10"]),
                           files={".config/ImageMagick/policy.xml": policy})


# quantize.c, third round: -dither None for posterize (+dither does not reach
# PosterizeImage's dither method); two colours in gray, with and without
# dithering (AssignImageColors' and SetAssociatedAlpha's two-colour branches);
# eight colours in gray (SetGrayscaleImage's IntensityCompare); -treedepth. (A
# 600x600 noise image is not reproducible; ORACLE.md, Known upstream issues.)
QUANTIZE_GAP3_OPS = [
    ["-dither", "None", "-posterize", "3"], ["-colorspace", "gray", "+dither", "-colors", "2"],
    ["-colorspace", "gray", "-colors", "2"], ["-colorspace", "gray", "-colors", "8"],
    ["-treedepth", "3", "-colors", "16"],
]


def _quantize_gap3_cases():
    for name, op in itertools.product(("rose", "palette", "rose_alpha"), QUANTIZE_GAP3_OPS):
        yield _op("quantizegap3", "%s %s" % (name, " ".join(op)), [img(name)], op)


# quantize.c, fourth round, routes checked with the coverage build first:
# IntensityCompare sorts a gray colormap, whose order a float write loses, so
# these write a palette MIFF or print the colormap. PruneLevel is left out: it
# runs only on images with very many colours, whose quantization is not
# reproducible (ORACLE.md, Known upstream issues).
def _quantize_gap4_cases():
    for name in ("rose", "rose_alpha", "gray16"):
        yield _op_to("quantizegap4", "%s -colorspace gray -colors 8, palette MIFF" % name,
                     [img(name), "-colorspace", "gray", "-colors", "8"], "out.miff")
        yield _case("quantizegap4", "%s -colorspace gray -colors 8 -verbose info:" % name,
                    [[img(name), "-colorspace", "gray", "-colors", "8", "-verbose", "info:"]], [])


# montage.c: GetMontageGeometry fills in whichever tile count is missing, or
# both. The montage family has -tile 3x and 2x2 only; rows only (x2, x3), columns
# only (2x), 1x1 (one image per page) and an offset with no counts.
MONTAGE_TILES = ["x2", "x3", "2x", "1x1", "+0+0"]


def _montage_gap_cases():
    inputs = [img(n) for n in ("rose", "granite", "logo", "wizard", "tiny")]
    for t in MONTAGE_TILES:
        yield _op_to("montagegap", "montage of five -tile %s" % t,
                     ["montage"] + inputs + ["-tile", t, "-geometry", "20x20+1+1"] + FLOAT_OUT,
                     "out.miff")


# composite.c: CompositeOverImage's virtual composite (outside the source),
# run only with compose:clip-to-self=false, sets the alpha of every pixel the
# source does not cover; it shows only with a source that has alpha (line
# coverage showed the path run but change nothing with an opaque source).
_ALPHA_PATCH = ["(", img("rose_alpha"), "-crop", "20x15+10+10", "+repage", ")"]


def _compose_over_gap_cases():
    for dest, offset, clip in itertools.product(("rose", "rose_alpha"), ("-3-2", "+40+25"),
                                                ("false", "true")):
        yield _op("composegap", "%s over an alpha patch at %s, clip-to-self=%s"
                  % (dest, offset, clip), [img(dest)] + _ALPHA_PATCH,
                  ["-geometry", offset, "-define", "compose:clip-to-self=" + clip,
                   "-compose", "over", "-composite"])


# composite.c: SeamlessBlendImage's residual is 0 from the first iteration on
# (one iteration and five give the same image), so with any threshold above 0
# the loop stops at once and the iteration code never runs. A threshold of 0
# makes it run every iteration, and -verbose prints one residual per tick.
def _seamless_gap_cases():
    for args, verbose in (("5x0+1", True), ("5x0+2", True), ("5x0+1", False)):
        pre = ["-verbose"] if verbose else []
        post = ["+verbose", "null:"] if verbose else FLOAT_OUT + ["out.miff"]
        yield _case("composegap2", "seamless-blend args=%s%s" % (args, " -verbose" if verbose else ""),
                    [[img("rose")] + _ALPHA_PATCH + ["-geometry", "+20+10"] + pre
                     + ["-define", "compose:args=" + args, "-compose", "seamless-blend",
                        "-composite"] + post], [] if verbose else ["out.miff"])


# fx.c, fourth round (routes checked with line coverage): an image attribute
# with a virtual channel qualifier is an error (GetChannelQualifier), and with
# u[1] another one (GetFunction); with a real channel it is allowed.
FX_GAP4_EXPRESSIONS = ["mean.hue", "maxima.intensity", "minima.lightness",
                       "u[1].mean.saturation", "mean.r", "maxima.g", "standard_deviation.b"]


def _fx_gap4_cases():
    for e in FX_GAP4_EXPRESSIONS:
        yield _op("fxgap4", "rose granite -fx %s" % e, [img("rose"), img("granite")], ["-fx", e])


# quantum-import.c, quantum-export.c: Export/ImportOpacityQuantum run only for
# RGBO and BGRO with -interlace line (reach.py: not with plane or none), and
# the raw o: writer cannot reach them (it switches on the input's format;
# ORACLE.md, Known upstream issues). Line-interlaced round trips at each depth,
# integer and floating point.
OPACITY_LINE_DEPTHS = [("8", []), ("16", []), ("32", []), ("16", _FLOAT), ("32", _FLOAT),
                       ("64", _FLOAT)]


def _opacity_line_gap_cases():
    for f, (depth, extra) in itertools.product(("rgbo", "bgro"), OPACITY_LINE_DEPTHS):
        if _quantum_unstable(f, extra):
            continue
        enc = "enc." + f
        steps = [[img("rose_alpha"), "-depth", depth] + extra + ["-interlace", "line", "%s:%s" % (f, enc)],
                 ["-size", "{W:rose_alpha}x{H:rose_alpha}", "-depth", depth] + extra
                 + ["-interlace", "line", "%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap5", "rose_alpha -depth %s %s -interlace line -> %s"
                    % (depth, " ".join(extra), f), steps, [enc, "dec.miff"])


# Second line-interlaced round: the other depths (1, 4, 10, 12, 24, and 24-bit
# floating point), for RGBO, BGRO and BGR. (Line-interlaced BGRO comes out the
# size of BGR, as if its opacity were not written; kept as it is.)
OPACITY_LINE_DEPTHS2 = [("1", []), ("4", []), ("10", []), ("12", []), ("24", [])]


def _opacity_line_gap2_cases():
    combos = list(itertools.product(("rgbo", "bgro", "bgr"), OPACITY_LINE_DEPTHS2))
    combos.append(("rgbo", ("24", _FLOAT)))
    for f, (depth, extra) in combos:
        enc = "enc." + f
        steps = [[img("rose_alpha"), "-depth", depth] + extra + ["-interlace", "line", "%s:%s" % (f, enc)],
                 ["-size", "{W:rose_alpha}x{H:rose_alpha}", "-depth", depth] + extra
                 + ["-interlace", "line", "%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap6", "rose_alpha -depth %s %s -interlace line -> %s"
                    % (depth, " ".join(extra), f), steps, [enc, "dec.miff"])


# signature.c: SignatureImage skips pixels a read mask excludes (mask at or
# below half), which no %# case had: a bilevel mask, a gray mask with values on
# both sides of half, and the mask removed again.
def _signature_gap2_cases():
    for label, mask in (("bilevel", ["-read-mask", img("bilevel")]),
                        ("gray8", ["-read-mask", img("gray8")]),
                        ("gray8, removed", ["-read-mask", img("gray8"), "+read-mask"])):
        yield _case("signaturegap2", "rose %%# under a %s read mask" % label,
                    [[img("rose")] + mask + ["-format", "%#\\n", "info:"]], [])


# histogram.c: IsPaletteImage's boundary at MaxColormapSize. -colors N on a
# palette image of N colours or fewer calls CompressImageColormap, and that
# IsPaletteImage (GetImageType, the other caller, is MagickWand only); a
# palette of exactly 65536 colours, reproducible and quick (checked: no tree
# pruning). The boundary mutant was run by hand on this route: it differs.
_PALETTE_65536 = ["-size", "256x256", "xc:#000000", "-channel", "R", "-fx", "i/255",
                  "-channel", "G", "-fx", "j/255", "+channel", "-depth", "16", "+dither",
                  "-colors", "65536"]


def _histogram_gap3_cases():
    yield _case("histogramgap3", "65536-colour palette, -colors 65536 again",
                [_PALETTE_65536 + ["p.miff"], ["p.miff", "-colors", "65536", "-depth", "16", "out.miff"]],
                ["out.miff"])


# stream.c, second round (reach.py): every stream case read MIFF; PNG and TIFF
# reach GetAuthenticPixelsStream, which no case did. And a GIF whose two frames
# differ in size, so the stream's pixel cache changes geometry between frames
# (ValidatePixelCacheMorphology).
def _stream_gap2_cases():
    for fmt, (m, t) in itertools.product(("png", "tif"), (("rgba", "char"), ("rgb", "float"))):
        yield _case("streamgap2", "stream %s -map %s -storage-type %s" % (fmt, m, t),
                    [[img("rose_alpha"), "in." + fmt],
                     ["stream", "-map", m, "-storage-type", t, "in." + fmt, "out.raw"]], ["out.raw"])
    yield _case("streamgap2", "stream a GIF of two frame sizes",
                [[img("rose"), "(", img("rose"), "-resize", "50%", ")", "seq.gif"],
                 ["stream", "-map", "rgb", "-storage-type", "char", "seq.gif", "out.raw"]], ["out.raw"])


# color.c, second round: IsSVGCompliant checks red, green and blue in turn
# (and black for CMYK), and %[pixel:] prints percentages when one is not exact
# at 8 bits. The first round's colour was off in all three; these are off in one
# channel each, in black, in none, and in alpha only.
COLOR_SVG_COMPLIANCE = ["srgb(50.5%,40%,20%)", "srgb(40%,50.5%,20%)", "srgb(40%,20%,50.5%)",
                        "srgb(40%,20%,60%)", "cmyk(10%,20%,30%,40.5%)", "cmyk(10%,20%,30%,40%)",
                        "srgba(40%,20%,60%,0.505)"]


def _color_gap2_cases():
    for c in COLOR_SVG_COMPLIANCE:
        yield _case("colorgap2", "%%[pixel:] of %s at 16 bits" % c,
                    [["-size", "1x1", "xc:" + c, "-depth", "16", "-format", "%[pixel:p{0,0}]\\n",
                      "info:"]], [])


# timer.c and registry.c: -define registry:date:precision=N (DefineImageRegistry,
# then SetMagickDatePrecision) cuts the timestamps FormatMagickTime writes, as in
# the PostScript CreationDate. The timestamp is 25 characters, so 24, 25 and 26
# sit on the boundary; 4 and 10 cut it, 0 leaves it. Also a registry string
# defined and removed again (+define).
TIMER_PRECISIONS = ["0", "4", "10", "24", "25", "26"]


def _timer_gap_cases():
    for prec in TIMER_PRECISIONS:
        yield _op_to("timergap", "rose -> PostScript, registry date precision %s" % prec,
                     ["-define", "registry:date:precision=" + prec, img("rose")], "out.ps")
    yield _op_to("timergap", "registry string defined and removed",
                 ["-define", "registry:mykey=myvalue", "+define", "registry:mykey", img("rose")]
                 + FLOAT_OUT, "out.miff")


# monitor.c: SetImageProgress records its last message (percentage, tag and
# file) as the artifact monitor:progress, which %[monitor:progress] prints; no
# case printed it. Under -monitor, after three operators.
def _monitor_gap_cases():
    for op in (["-negate"], ["-resize", "50%"], ["-blur", "0x1"]):
        yield _case("monitorgap", "rose -monitor %s, %%[monitor:progress]" % " ".join(op),
                    [[img("rose"), "-monitor"] + op + ["-format", "%[monitor:progress]\\n", "info:"]], [])


# montage.c: MontageImageList sorts the images by scene (SceneCompare) when
# none has scene 0, which frames picked out of a sequence keep; out of order.
def _montage_gap2_cases():
    yield _op_to("montagegap2", "montage of anim frames 3,1,2 (sorted by scene)",
                 ["montage", img("anim") + "[3,1,2]", "-tile", "3x", "-geometry", "+1+1"] + FLOAT_OUT,
                 "out.miff")


# morphology.c: convolve:scale with a second, blending factor adds a scaled
# unity kernel (UnityAddKernelInfo), to every kernel of a list; single and
# multi-kernel, plain, percent and normalised ('!') scales.
MORPH_SCALE_KERNELS = ["Sobel", "Sobel:0;Sobel:90", "3x3:1,2,1,0,0,0,-1,-2,-1"]
MORPH_SCALES = ["1,0.5", "50%,25%", "!,0.5"]


def _morph_gap_cases():
    for k, sc in itertools.product(MORPH_SCALE_KERNELS, MORPH_SCALES):
        yield _op("morphgap", "gray16 convolve:scale=%s -morphology Convolve %s" % (sc, k),
                  [img("gray16")], ["-define", "convolve:scale=" + sc, "-morphology", "Convolve", k])


# morphology.c, MorphologyApply: -define debug=true prints the changes per
# iteration and stage, which no case printed; iterations of -1 (until nothing
# changes); multi-stage methods (Close, Open) and multi-kernel lists (Corners).
MORPH_DEBUG_OPS = [("Thinning:-1", "Skeleton"), ("Close:2", "Disk:1"), ("Open", "Disk:1"),
                   ("HitAndMiss", "Corners"), ("Dilate:-1", "Diamond")]


def _morph_gap2_cases():
    for method, kernel in MORPH_DEBUG_OPS:
        yield _case("morphgap2", "bilevel debug -morphology %s %s" % (method, kernel),
                    [[img("bilevel"), "-define", "debug=true", "-morphology", method, kernel,
                      "null:"]], [])
        yield _op("morphgap2", "bilevel -morphology %s %s" % (method, kernel), [img("bilevel")],
                  ["-morphology", method, kernel])


# morphology.c, AcquireKernelBuiltIn: kernel types and arguments the catalogue
# never built (FreiChen's numbered kernels, Ridges, Skeleton, Peaks, the shape
# and distance kernels with sizes and scales); morphology:showKernel prints the
# values, so any change to the builder shows.
MORPH_SHOW_KERNELS = [
    "FreiChen:0", "FreiChen:1", "FreiChen:2", "FreiChen:5", "FreiChen:7", "FreiChen:10",
    "FreiChen:11", "FreiChen:1,45", "Ridges:1", "Ridges:2", "Skeleton:1", "Skeleton:2",
    "Skeleton:3", "Peaks:1.5,2.5", "Peaks:2,4", "Binomial:1", "Binomial:2", "Binomial:3",
    "Diamond:2,3", "Octagon:2,5", "Plus:2,3", "Cross:2,3", "Disk:2.5,3", "Rectangle:3x2+1+1",
    "Manhattan:2,3", "Octagonal:2,3", "Chebyshev:2,3", "Euclidean:2,3", "Comet:2,3",
    "Comet:2,3,45", "LoG:0x1", "Blur:0x1,45", "Roberts:45", "Prewitt:90", "Compass:45",
    "Kirsch:90", "LineEnds:1", "LineJunctions:1", "ThinSE:41", "Diagonals:1",
]


def _morph_gap3_cases():
    for k in MORPH_SHOW_KERNELS:
        yield _case("morphgap3", "showKernel %s" % k,
                    [["-size", "4x4", "xc:#808080", "-define", "morphology:showKernel=1",
                      "-morphology", "Convolve:1", k, "null:"]], [])


# morphology.c, MorphologyImage: an invalid convolve:bias (a warning) and a
# valid one; morphology:compose Undefined (parses to 0, the boundary of its
# check), Lighten and an unknown name, on a multi-kernel list, where the compose
# method combines the kernels' results.
MORPH_IMAGE_DEFINES = ["convolve:bias=abc", "convolve:bias=10%", "morphology:compose=Undefined",
                       "morphology:compose=Lighten", "morphology:compose=nosuch"]


def _morph_gap4_cases():
    for d in MORPH_IMAGE_DEFINES:
        yield _op("morphgap4", "gray16 %s -morphology Convolve Sobel:>" % d, [img("gray16")],
                  ["-define", d, "-morphology", "Convolve", "Sobel:>"])


# quantize.c, RemapImages with a reference image: the command line passes none
# (+remap quantizes the list instead); MSL's <map image="id"/> passes one (line
# coverage: the reference branch runs). With and without dithering.
_MSL_MAP = """<?xml version="1.0" encoding="UTF-8"?>
<group>
  <image id="pal">
    <read filename="%s" />
  </image>
  <image>
    <read filename="%s" />
    <map image="pal" dither="%s" />
    <write filename="out.miff" />
  </image>
</group>
"""


def _quantize_gap5_cases():
    for dither in ("false", "true"):
        yield _with_inputs(_case("quantizegap5", "msl map to palette, dither %s" % dither,
                                 [["conjure", "msl:map.msl"]], ["out.miff"]),
                           files={"map.msl": _MSL_MAP % (img("palette"), img("rose"), dither)})


# quantize.c: PruneLevel runs only once the colour tree passes MaxQNodes (266817)
# nodes, which needs a deep tree (-treedepth 8; for 64 colours QuantizeImage
# picks depth 4) and some 360,000 distinct colours: colour noise, opaque and with
# noisy alpha (16 children a node). RemapImage reduces the reference only when
# it has more than MaxColormapSize (65536) colours: a 300x300 noise palette.
_COLOUR_NOISE = ["-seed", "3", "-size", "600x600", "xc:#808080", "+noise", "Random"]


def _quantize_gap6_cases():
    yield _op_to("quantizegap6", "600x600 colour noise -treedepth 8 -colors 64",
                 _COLOUR_NOISE + ["-treedepth", "8", "-colors", "64"], "out.miff")
    yield _op_to("quantizegap6", "600x600 colour noise, noisy alpha, -treedepth 8 -colors 64",
                 _COLOUR_NOISE + ["-alpha", "set", "-channel", "A", "+noise", "Random", "+channel",
                                  "-treedepth", "8", "-colors", "64"], "out.miff")
    yield _op_to("quantizegap6", "rose -remap a 300x300 colour noise palette",
                 ["-seed", "3", "-size", "300x300", "xc:#808080", "+noise", "Random",
                  "-write", "mpr:pal", "+delete", img("rose"), "-remap", "mpr:pal"], "out.miff")


# quantize.c: AssignImageColors' monochrome step (-quantize gray -colors 2) sets
# colormap 0 black or white by which entry is brighter. Undithered (+dither must
# come before -colors), the entry of a parent that took in pruned children comes
# after its surviving child (DefineImageColormap is post-order), so entry 0 is
# the brighter one for a gradient, logo and wizard; one-colour images take the
# colors == 1 branch.
def _quantize_gap7_cases():
    for name, src in (("gradient", ["-size", "16x256", "gradient:"]),
                      ("three grays", ["-size", "2x2", "xc:gray(5%)", "-size", "30x30", "xc:gray(60%)",
                                       "xc:gray(70%)", "+append"]),
                      ("logo", [img("logo")]), ("wizard", [img("wizard")]), ("rose", [img("rose")]),
                      ("white", ["-size", "8x8", "xc:white"]), ("gray50", ["-size", "8x8", "xc:gray50"])):
        for dither in ("+dither", "-dither"):
            yield _op_to("quantizegap7", "%s %s -quantize gray -colors 2" % (name, dither),
                         src + ([dither] if dither == "+dither" else ["-dither", "FloydSteinberg"])
                         + ["-quantize", "gray", "-colors", "2"], "out.miff")


# quantize.c: -verbose before -colors sets measure_error, and AssignImageColors
# then leaves the pixels for GetImageQuantizeError, whose figures -verbose info:
# prints ("Mean error per pixel"); undithered, so the loop that skips them runs.
def _quantize_gap8_cases():
    for name in ("rose", "rose_alpha"):
        yield _case("quantizegap8", "%s +dither -verbose -colors 16 info:" % name,
                    [[img(name), "+dither", "-verbose", "-colors", "16", "info:"]], [])


# quantize.c: PosterizePixel's MagickRound breaks a tie (fraction exactly .5)
# upwards: in HDRI rgb(127.5,63.75,191.25) is exactly such a tie at 2 and 3
# levels. -monitor prints ReduceImageColors' progress. SetAssociatedAlpha leaves
# alpha out for two gray colours only: an alpha image at 2 and 8 gray colours.
def _quantize_gap9_cases():
    for levels in ("2", "3"):
        yield _op_to("quantizegap9", "half-way colour +dither -posterize %s" % levels,
                     ["-size", "4x4", "xc:rgb(127.5,63.75,191.25)", "+dither", "-posterize", levels],
                     "out.miff")
    yield _case("quantizegap9", "rose -monitor -colors 16",
                [[img("rose"), "-monitor", "-colors", "16", "null:"]], [])
    for colors in ("2", "8"):
        for dither in (["+dither"], ["-dither", "FloydSteinberg"]):
            yield _op_to("quantizegap9", "rose_alpha %s -quantize gray -colors %s" % (dither[0], colors),
                         [img("rose_alpha")] + dither + ["-quantize", "gray", "-colors", colors],
                         "out.miff")


# quantize.c: PosterizeImage dithers through a map image for 2..16 levels only:
# 1 and 17 levels, dithered, take the other path; -monitor prints its progress,
# dithered and not (each hand-run first).
def _quantize_gap10_cases():
    for levels in ("1", "17"):
        yield _op_to("quantizegap10", "rose -posterize %s, dithered" % levels,
                     [img("rose"), "-posterize", levels], "out.miff")
    for dither in ([], ["+dither"]):
        yield _case("quantizegap10", "rose %s-monitor -posterize 4" % (dither[0] + " " if dither else ""),
                    [[img("rose")] + dither + ["-monitor", "-posterize", "4", "null:"]], [])


# cache.c: MaskPixelCacheNexus and ApplyPixelCompositeMask run under a composite
# mask, which MVG sets for `mask "id"` only when the mask is a quoted, named
# macro (GetMVGMacros skips `push mask m1`, so cachegap's MVG never reached
# them; reach.py: now reached), with greys in the mask, on opaque and alpha
# images and under SVG compliance (draw.c sets the mask per primitive).
# ClonePixelCacheOnDisk runs when a cache on disk is cloned to another on disk:
# +clone under -limit memory 0 -limit map 0.
def _mvg_named_mask(compliance=""):
    return ("viewbox 0 0 40 30\npush defs\npush mask \"m1\"\nfill white\ncircle 20,15 20,4\n"
            "fill gray50\nrectangle 0,0 10,30\npop mask\npop defs\npush graphic-context\n%s"
            "mask \"m1\"\nfill #ff0000\nrectangle 0,0 40,30\npop graphic-context\n" % compliance)


def _cache_gap2_cases():
    for label, src in (("blue", ["-size", "40x30", "xc:#0000ff"]),
                       ("rose_alpha", [img("rose_alpha"), "-resize", "40x30!"])):
        for compliance in ("", "compliance SVG\n"):
            yield _with_inputs(_op_to("cachegap2", "named MVG mask on %s%s" % (
                label, ", SVG compliance" if compliance else ""),
                src + ["-draw", "@m.mvg"] + FLOAT_OUT, "out.miff"),
                files={"m.mvg": _mvg_named_mask(compliance)})
    for name in ("rose", "rose_alpha", "cmyk"):
        yield _op("cachegap2", "%s on disk, a negated clone composed over it" % name,
                  _NO_MEMORY + [img(name)], ["(", "+clone", "-negate", ")", "-compose", "over",
                                             "-composite"])
    yield _op("cachegap2", "rose on disk, resized and flipped",
              _NO_MEMORY + [img("rose")], ["-resize", "50%", "-flip"])
    # PersistPixelCache steps each image's offset in the .cache file to a page
    # boundary; only a list of images uses it (cachegap's MPCs held one).
    three = [img("rose"), img("granite"), img("logo")]
    yield _case("cachegap2", "three images to one MPC", [three + ["out.mpc"]], ["out.mpc"])
    yield _case("cachegap2", "three images to one MPC, read back",
                [three + ["-write", "out.mpc", "-delete", "0--1", "out.mpc"] + FLOAT_OUT + ["dec.miff"]],
                ["dec.miff"])


# fx.c, with fx:debug=true (DumpRPN names every element, OprStr, and marks the
# in-place operators): compound assignments (+= is operator 0, -- the last in
# place), the symbols table, more than 100 elements and more than 50 user
# symbols (the tables grow), and user symbols 99 and 100 letters long (the
# token limit). User symbols must be letters only and longer than one letter.
# Each hand-run first: 9 survivors killed.
def _fx_gap5_cases():
    names = ["zq" + a + b for a, b in itertools.product("abc", string.ascii_lowercase)][:55]
    exprs = [("compound assignments", "zz=0.5; zz+=u; zz-=0.1; zz*=2; zz/=3; zz++; zz--; zz"),
             ("symbols", "r*0.5+hue+luma+intensity-lightness+saturation+b+g+a+c+y+k+m+o"),
             ("60 terms", "+".join(["u"] * 60) + "-59*u"),
             ("55 user symbols", ";".join("%s=%d" % (n, i) for i, n in enumerate(names))
              + "; (%s+%s)/100" % (names[1], names[54])),
             ("99-letter symbol", "a" * 99 + "=0.5; " + "a" * 99),
             ("100-letter symbol", "a" * 100 + "=0.5; " + "a" * 100)]
    for label, e in exprs:
        yield _op("fxgap5", "fx:debug %s" % label, ["-size", "4x4", "xc:gray"],
                  ["-define", "fx:debug=true", "-fx", e])


# fx.c: lines no case executed: jinc (and jinc(0)), SI and binary number
# prefixes (1ki is 1024; K is not a prefix), the lightness and intensity
# qualifiers on u, p, u[1] and v, printsize.x/y, a while loop, gcd with the
# smaller argument first, -monitor over FxImage, and a constant expression
# (DumpRPN's CornerOnly) under fx:debug. Two images, so u[1] and v exist.
_FX_GAP6 = [
    ("jinc", "jinc(u*2)/2+jinc(0)/4"),
    ("number prefixes", "1ki/4000+1Mi/8388608+2m*100+1c*10+1h/800+1.5Gi/3e10"),
    ("lightness and intensity", "u.lightness*0.3+u.intensity*0.3+p[1,1].lightness*0.2+p[1,1].intensity*0.2"),
    ("lightness and intensity of the second image", "u[1].intensity*0.5+u[1].lightness*0.25+v.p[1,1].lightness*0.25"),
    ("printsize", "u.printsize.x/10+u.printsize.y/10"),
    ("while", "zz=0; while(zz<3, zz=zz+1); zz/4"),
    ("gcd both ways", "gcd(8,12)/8+gcd(12,8)/8"),
]


def _fx_gap6_cases():
    two = [img("rose"), "-resize", "8x8", img("granite"), "-resize", "8x8", "-density", "72"]
    for label, e in _FX_GAP6:
        yield _op("fxgap6", "fx %s" % label, two, ["-fx", e])
    yield _case("fxgap6", "-monitor -fx", [[img("rose"), "-monitor", "-fx", "u*0.5", "null:"]], [])
    yield _op("fxgap6", "fx:debug, a constant expression", ["-size", "4x4", "xc:gray"],
              ["-define", "fx:debug=true", "-fx", "0.25"])


# fx.c: gcd(1,0.001) meets FxGcd's 0.001 cut-off exactly, and gcd(3,3) has equal
# arguments (x <= y would swap them for ever); rand() under -seed
# shows how many values AllocFxRt discards first; a sum nested 120 deep needs
# a value stack larger than the minimum of 100 (hand-run: 5 survivors killed).
def _fx_gap7_cases():
    deep = "u*0.001" + "".join(["+(u*0.001"] * 120) + ")" * 120
    yield _op("fxgap7", "fx gcd at the cut-off", ["-size", "2x2", "xc:gray"], ["-fx", "gcd(1,0.001)/2"])
    yield _op("fxgap7", "fx gcd of equal arguments", ["-size", "2x2", "xc:gray"], ["-fx", "gcd(3,3)/6"])
    yield _op("fxgap7", "fx rand() under -seed", ["-seed", "7", "-size", "4x4", "xc:gray"], ["-fx", "rand()"])
    yield _op("fxgap7", "fx sum nested 120 deep", ["-size", "2x2", "xc:gray"], ["-fx", deep])


# fx.c: ImageStat for kurtosis, maxima, median, minima, skewness and standard
# deviation, which only u.mean reached before. An attribute with no qualifier
# reads the composite channel (MaxPixelChannels), with .r channel 0; under
# %[fx:] the statistics are collected per call, under -fx once (hand-run: 10
# survivors killed).
_FX_STATS = "u.kurtosis%s/100+u.maxima%s+u.median%s+u.minima%s+u.skewness%s/10+u.standard_deviation%s"


def _fx_gap8_cases():
    small = [img("rose"), "-resize", "8x8"]
    for q in ("", ".r"):
        e = _FX_STATS % ((q,) * 6)
        yield _case("fxgap8", "%%[fx:] statistics%s" % (" of red" if q else ""),
                    [small + ["-format", "%%[fx:%s]" % e, "info:"]], [])
        yield _op("fxgap8", "-fx statistics%s" % (" of red" if q else ""), small, ["-fx", e])


# fx.c: an expression read from a file (-fx @file), and "@" alone, which
# AcquireFxInfoPrivate takes literally (hand-run: both length tests killed),
# and a "?" with no ":".
def _fx_gap9_cases():
    yield _with_inputs(_op("fxgap9", "-fx @file", ["-size", "2x2", "xc:gray"], ["-fx", "@e.fx"]),
                       files={"e.fx": "u*0.5\n"})
    yield _case("fxgap9", "-fx @ alone", [["-size", "2x2", "xc:gray", "-fx", "@", "null:"]], [])
    # A "?" with no ":" (ResolveTernaryAddresses' error; hand-run: 2 killed).
    # A standalone attribute with a channel qualifier, depth being the first
    # attribute (GetChannelQualifier's range tests; hand-run: 2 killed).
    # And an operand followed by "(" or "}", which GetOperator rejects as not a
    # real operator (IsRealOperator's two bounds; hand-run: 2 killed).
    for e in ("u>0.5 ? 1", "zz=u>0.5 ? 1; zz", "depth.r/32", "depth.hue", "0.5(0.5)", "0.5}"):
        yield _case("fxgap9", "-fx %s" % e, [["-size", "2x2", "xc:gray", "-fx", e, "null:"]], [])


# fx.c, ExecuteRPN's boundaries: comparisons of equal operands, shifts by 64 and
# by a fraction, | and >> rounding a fraction, ~ of a fraction (exact in a long
# double, so ~2.6 - ~0 shows it), sign(0), airy, and signed zeros, which %[fx:]
# prints as -0: clamp(-0), max(0,-0), min(-0,0) (hand-run: 21 survivors killed).
_FX_GAP10 = ["(0.5<=0.5)/2+(0.5>=0.5)/4+(0.5>0.5)/8+(0.5!=0.5)/16",
             "((1<<64)+(1>>64)+(1<<63.6)+(4>>63.6))/4",
             "(2.6>>0)/16+(2.6|0)/32+(0|2.6)/64",
             "((~2.6)-(~0)+4)/8",
             "sign(0)/2+0.5",
             "airy(0)/2+airy(0.3)/2",
             "clamp(-0)", "max(0,-0)", "min(-0,0)"]


def _fx_gap10_cases():
    for e in _FX_GAP10:
        yield _case("fxgap10", "%%[fx:%s]" % e, [["-size", "2x2", "xc:gray", "-format", "%%[fx:%s]" % e, "info:"]], [])


# fx.c, ExecuteRPN's image references under %[fx:] on each image of a list
# (pfx->ImgNum is 1 for the second): u with a computed index (a constant 0
# compiles to u0) and qualifiers, u[1].p relative and absolute, and u, u.r;
# the HSL symbols alone (each sets NeedHsl itself); nesting exactly at the
# 600 limit, by parentheses and by unary minus (hand-run: 36 killed).
_FX_GAP11_TWO = ["u[1-1]", "u[1-1].r", "u[1-1].lightness", "u[1-1].intensity", "u[1-1].hue",
                 "u[1].p[1,1].r", "u[1].p{2,2}", "u[1].p[1,1].lightness", "u[1].p[1,1].intensity",
                 "u", "u.r",
                 # GetFunction's qualifier errors, which name the attribute, and if()'s jump
                 "u.depth.hue", "u.w.r", "u.mean.intensity", "if(u>0.5,0.25,0.75)"]


def _fx_gap11_cases():
    two = [img("rose"), "-resize", "6x6", img("granite"), "-resize", "6x6"]
    for e in _FX_GAP11_TWO:
        yield _case("fxgap11", "%%[fx:%s] on two images" % e, [two + ["-format", "%%[fx:%s]\\n" % e, "info:"]], [])
    for label, e in (("hue", "hue"), ("saturation", "saturation"), ("lightness", "lightness"),
                     ("600 parentheses", "(" * 600 + "0.5" + ")" * 600), ("600 minus signs", "-" * 600 + "0.5")):
        yield _case("fxgap11", "%%[fx:] %s" % label,
                    [[img("rose"), "-resize", "4x4", "-format", "%%[fx:%s]\\n" % e, "info:"]], [])
    # An operand GetOperand cannot read ($zz), and image artifacts used as
    # variables, a number and not (hand-run: 3 killed).
    for e in ("$zz", "zzk", "zzb"):
        yield _case("fxgap11", "-fx %s with artifacts" % e,
                    [["-size", "2x2", "xc:gray", "-define", "zzk=0.25", "-define", "zzb=abc",
                      "-fx", e, "-format", "%[fx:u]", "info:"]], [])


# matrix.c: MatrixToImage scales the hough accumulator by its range: all zero
# for a black image, a white one, and one horizontal line (its round: 31 killed in all).
# And SetMatrixExtent, below.
def _matrix_gap3_cases():
    for label, src in (("black", ["-size", "20x15", "xc:black"]),
                       ("white", ["-size", "20x15", "xc:white"]),
                       ("one horizontal line", ["-size", "20x15", "xc:black", "-fill", "white",
                                                "-draw", "line 0,7 19,7"])):
        yield _op("matrixgap3", "hough accumulator of %s" % label, src,
                  ["-define", "hough-lines:accumulator=true", "-hough-lines", "5x5+3"])
    # With memory exhausted but mapping allowed (-limit memory 0 alone), the
    # matrix is a file mapped into memory, the one route to SetMatrixExtent
    # (reached; the hand-run kills were false, from a shared run directory).
    yield _op("matrixgap3", "hough accumulator, matrix mapped from a file",
              ["-limit", "memory", "0"] + _HOUGH_INPUT,
              ["-define", "hough-lines:accumulator=true", "-hough-lines", "9x9+10"])


# resample.c: resample:verbose prints SetResampleFilter's weighting table, and a
# perspective squeezed into 20x20 drives ScaleResampleFilter near its limit
# (its round: 5 killed).
def _resample_gap_cases():
    yield _case("resamplegap", "distort with resample:verbose",
                [[img("rose"), "-define", "resample:verbose=1", "-distort", "SRT", "0.5,10", "null:"]], [])
    yield _op("resamplegap", "perspective squeezed into 20x20", [img("rose")],
              ["-define", "distort:viewport=20x20", "-distort", "Perspective",
               "0,0 0,0  69,0 69,0  0,45 30,1  69,45 39,1"])


# quantum-import.c / quantum-export.c: branches no round trip reached. The
# min-is-white polarity (quantum:polarity) for gray and gray-alpha at every
# depth; an odd width (7 pixels) for the packed depths 1, 2 and 4, whose last
# byte holds fewer pixels, in every raw layout; palette with alpha (index and
# alpha) at the packed depths, odd width, both polarities. A 7x5 crop.
_ODD = ["-crop", "7x5+20+10", "+repage"]
QUANTUM_ALL_DEPTHS = [("1", []), ("2", []), ("4", []), ("8", []), ("10", []), ("12", []), ("16", []),
                      ("24", []), ("32", []), ("16", _FLOAT), ("32", _FLOAT), ("64", _FLOAT)]
QUANTUM_PACKED_LAYOUTS = ["gray", "graya", "rgb", "rgba", "bgr", "bgra", "rgbo", "cmyk", "cmyka",
                          "o", "a", "ycbcr", "ycbcra"]
_MIN_IS_WHITE = ["-define", "quantum:polarity=min-is-white"]


def _quantum_odd_round_trip(family, label, f, pre):
    enc = "enc.%s" % f
    steps = [[img("rose_alpha")] + _ODD + pre + ["%s:%s" % (f, enc)],
             ["-size", "7x5"] + pre + ["%s:%s" % (f, enc)] + FLOAT_OUT + ["dec.miff"]]
    return _case(family, label, steps, [enc, "dec.miff"])


def _quantum_gap7_cases(writable_formats):
    for f, (depth, extra) in itertools.product(("gray", "graya"), QUANTUM_ALL_DEPTHS):
        if f in writable_formats:
            yield _quantum_odd_round_trip("quantumgap7", "7x5 -depth %s %s min-is-white -> %s"
                                          % (depth, " ".join(extra), f), f,
                                          ["-depth", depth] + extra + _MIN_IS_WHITE)
    for f, depth in itertools.product(QUANTUM_PACKED_LAYOUTS, ("1", "2", "4")):
        if f in writable_formats and not (f in ("gray", "graya")):
            yield _quantum_odd_round_trip("quantumgap7", "7x5 -depth %s -> %s" % (depth, f), f,
                                          ["-depth", depth])
    for depth, pol in itertools.product(("1", "2", "4", "8", "16"), ([], _MIN_IS_WHITE)):
        steps = [[img("rose_alpha")] + _ODD + ["-colors", "4", "-type", "PaletteAlpha", "-depth", depth]
                 + pol + ["miff:enc.miff"], pol + ["enc.miff"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap7", "7x5 PaletteAlpha -depth %s%s -> miff"
                    % (depth, " min-is-white" if pol else ""), steps, ["enc.miff", "dec.miff"])


# blob.c: ReadBlobString strips a line's trailing newline; the TEXT reader
# renders each line it reads, so an unstripped newline shows. A file with an
# empty line, a CRLF line and no final newline (hand-run: 3 killed).
def _blob_gap_cases():
    yield _with_inputs(_op_to("blobgap", "text: with empty, CRLF and unterminated lines",
                              ["-size", "60x60", "-pointsize", "10", "text:t.txt"] + FLOAT_OUT, "out.miff"),
                       files={"t.txt": "ab\n\ncd\r\nef"})


# fx.c: loops of 300 iterations, where an element that should not push would
# overflow the value stack (GetFunction's do_push for while and do), and for()
# and while() with too many arguments (hand-run: 3 killed).
def _fx_gap12_cases():
    for e in ("zz=0; while(zz<300, zz=zz+1); zz/600", "zz=0; do(zz<300, zz=zz+1); zz/600",
              "zz=0; for(ii=0, ii<300, ii=ii+1, zz=zz+2); zz/1000",
              "zz=0; while(zz<3, zz=zz+1, zz=zz+0.5); zz/8",
              # an in-place operator on the second user symbol, which the
              # element must name (TranslateExpression; hand-run: killed)
              "aa=0.1; bb=0.2; bb+=0.3; bb", "aa=0.1; bb=0.2; bb*=2; aa+bb"):
        yield _case("fxgap12", "%%[fx:%s]" % e, [["-size", "2x2", "xc:gray", "-format", "%%[fx:%s]\\n" % e, "info:"]], [])


# cache.c: with the cache:synchronize policy, SetPixelCacheExtent reserves the
# disk cache with posix_fallocate (hand-run: 2 killed).
_SYNC_POLICY = '<policymap>\n  <policy domain="cache" name="synchronize" value="True"/>\n</policymap>\n'


def _cache_gap3_cases():
    yield _with_inputs(_op("cachegap3", "disk cache under cache:synchronize",
                           _NO_MEMORY + [img("rose")], ["(", "+clone", "-negate", ")", "-compose", "over", "-composite"]),
                       files={".config/ImageMagick/policy.xml": _SYNC_POLICY})


# token.c: a policy's coder pattern is matched case-sensitively, so "g*" does
# not block GIF (hand-run: GlobExpression_'s case test killed).
def _token_gap_cases():
    pol = '<policymap>\n  <policy domain="coder" rights="none" pattern="g*" />\n</policymap>\n'
    yield _with_inputs(_case("tokengap", "write GIF under a coder policy for g*",
                             [[img("rose"), "-resize", "8x8", "gif:out.gif"]], ["out.gif"]),
                       files={".config/ImageMagick/policy.xml": pol})


# quantum-import.c: importers no writer feeds. ImportOpacityQuantum reads the O
# line of a line-interlaced RGBO or BGRO file, which the writers leave out
# (ORACLE.md); one row built by hand is that layout: -separate -append stacks
# the R, G, B (or B, G, R) and A lines. ImportGrayAlphaQuantum reads a gray
# file twice as wide as gray-alpha, the same bytes (reach.py: both reached).
QUANTUM_GAP8_DEPTHS = [("1", []), ("4", []), ("8", []), ("10", []), ("12", []), ("16", []), ("24", []),
                       ("32", []), ("16", _FLOAT), ("24", _FLOAT), ("32", _FLOAT), ("64", _FLOAT)]


def _quantum_gap8_cases():
    for (depth, extra), f in itertools.product(QUANTUM_GAP8_DEPTHS, ("rgbo", "bgro")):
        if _quantum_unstable(f, extra):
            continue
        swap = ["-swap", "0,2"] if f == "bgro" else []
        steps = [[img("rose_alpha"), "-crop", "7x1+20+10", "+repage", "-separate"] + swap
                 + ["-append", "-depth", depth] + extra + ["gray:l.raw"],
                 ["-size", "7x1", "-depth", depth] + extra + ["-interlace", "line", "%s:l.raw" % f]
                 + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap8", "one hand-built line-interlaced %s row, -depth %s %s"
                    % (f, depth, " ".join(extra)), steps, ["l.raw", "dec.miff"])
    for depth, extra in QUANTUM_GAP8_DEPTHS + [("2", [])]:
        steps = [[img("rose"), "-resize", "14x5!", "-colorspace", "gray", "-depth", depth] + extra + ["gray:g.raw"],
                 ["-size", "7x5", "-depth", depth] + extra + ["graya:g.raw"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap8", "a 14x5 gray file read as 7x5 gray-alpha, -depth %s %s"
                    % (depth, " ".join(extra)), steps, ["g.raw", "dec.miff"])
    # ImportIndexQuantum at 1, 2 and 4 bits: palette TIFFs keep the palette's
    # own bits per sample (MIFF stores indexes in 8 bits or more), at an odd
    # width, under both polarities (line probe: the 1- and 4-bit branches run).
    for (colors, depth), pol in itertools.product((("2", "1"), ("4", "2"), ("16", "4")), ([], _MIN_IS_WHITE)):
        steps = [[img("rose"), "-resize", "7x5!", "-colors", colors, "-type", "Palette", "-depth", depth,
                  "tiff:p.tif"], pol + ["p.tif"] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap8", "7x5 palette TIFF, %s colours at %s bits%s"
                    % (colors, depth, ", min-is-white" if pol else ""), steps, ["p.tif", "dec.miff"])


# fx.c: SetPtrShortExp cuts an error message's expression after 20 characters;
# an unreadable operand of exactly 20 puts it at the cut (hand-run: killed at
# 20, not at 19 or 21).
def _fx_gap13_cases():
    yield _case("fxgap13", "-fx with a 20-character unreadable operand",
                [["-size", "2x2", "xc:gray", "-fx", "$abcdefghijklmnopqrs", "null:"]], [])


# quantum-import/export.c: multispectral (meta channel) samples at 32-bit
# integer (MIFF and TIFF) and 64-bit (TIFF only: MIFF stores 64 as 32), written
# and read back (line probe: the 32-bit integer and both 64-bit branches run).
def _quantum_gap9_cases():
    for fmt, args in (("miff", ["-depth", "32"]), ("tiff", ["-depth", "32"]), ("tiff", ["-depth", "64"]),
                      ("tiff", ["-depth", "64"] + _FLOAT), ("tiff", ["-depth", "16"])):
        steps = [[img("rose"), "-resize", "8x6!", "-channel-fx", "red=>meta"] + args + ["%s:enc.%s" % (fmt, fmt)],
                 ["enc.%s" % fmt] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap9", "rose with a meta channel %s -> %s" % (" ".join(args), fmt), steps,
                    ["enc.%s" % fmt, "dec.miff"])


# quantum-import/export.c: RGB at 10 and 12 bits with packing off, which only
# Cineon and DPX ask for (line probe: the 10- and 12-bit unpacked branches run),
# written and read back at an odd and an even width.
def _quantum_gap10_cases():
    for fmt, depth, size in itertools.product(("cin", "dpx"), ("10", "12"), ("7x5", "8x5")):
        steps = [[img("rose"), "-resize", size + "!", "-depth", depth, "%s:enc.%s" % (fmt, fmt)],
                 ["enc.%s" % fmt] + FLOAT_OUT + ["dec.miff"]]
        yield _case("quantumgap10", "rose %s -depth %s -> %s" % (size, depth, fmt), steps,
                    ["enc.%s" % fmt, "dec.miff"])


# morphology.c, statement deletion: built-in kernels whose construction rotates,
# scales or expands them (deleted RotateKernelInfo, ScaleKernelInfo,
# CalcKernelMetaData, Expand*KernelInfo calls); morphology:showKernel prints the
# kernel. Edge kernels with an angle, every FreiChen type, and the expanding
# kernels (hand-run with the mull-sdl-win build: 27 survivors killed).
MORPH_GAP5_KERNELS = (["Roberts:90", "Prewitt:135", "Compass:180", "Kirsch:225"]
                      + ["FreiChen:%d" % t for t in range(12)]
                      + ["FreiChen:3,45", "FreiChen:11,90", "Diagonals:1,45", "LineEnds:1,90",
                         "LineJunctions:2,45", "Ridges:2", "Skeleton:1", "Skeleton:2", "Skeleton:3",
                         "ThinSE:41,90", "ConvexHull"])


def _morph_gap5_cases():
    for k in MORPH_GAP5_KERNELS:
        yield _case("morphgap5", "showKernel %s" % k,
                    [["-size", "3x3", "xc:gray", "-define", "morphology:showKernel=1",
                      "-morphology", "Convolve:1", k, "null:"]], [])


# fx.c, statement deletion: expressions spaced around operators, after commas
# and inside brackets, where TranslateExpression's SkipSpaces calls matter
# (hand-run with the mull-sdl-win build: 2 survivors killed).
_FX_GAP14 = [" u * 0.5 + 0.1 ", "( u + 0.1 ) * 2", "max( u , 0.2 )", " zz = 0.5 ; zz + 0.1 ",
             "p[ 1 , 1 ].r * 0.5"]


def _fx_gap14_cases():
    for e in _FX_GAP14:
        yield _case("fxgap14", "%%[fx:%s] spaced" % e.strip(),
                    [["-size", "2x2", "xc:gray", "-format", "%%[fx:%s]\\n" % e, "info:"]], [])


# color.c, statement deletion: colours given in the HCL, HSB, HSL, HSV and HWB
# models, which QueryColorCompliance converts to RGB, upper-case and with alpha
# (hand-run with the mull-sdl-win build: the five conversions killed).
_COLOR_GAP3 = ["hcl(120,50%,50%)", "hsb(120,50%,50%)", "hsl(120,50%,50%)", "hsv(120,50%,50%)",
               "hwb(120,20%,30%)", "HSL(120,50%,50%)", "hsla(200,40%,60%,0.5)"]


def _color_gap3_cases():
    for c in _COLOR_GAP3:
        yield _case("colorgap3", "xc:%s" % c,
                    [["-size", "1x1", "xc:%s" % c, "-format", "%[pixel:p{0,0}]\\n", "info:"]], [])


# quantize.c, statement deletion: +remap quantizes a list with more colours
# than 256 together (QuantizeImages must reduce them), and -monitor prints its
# per-image progress (hand-run with mull-sdl-win: the deleted
# ReduceImageColors and both progress counters killed).
def _quantize_gap11_cases():
    two = [img("rose"), img("granite")]
    yield _op_to("quantizegap11", "rose granite +remap -append", two + ["+remap", "-append"], "out.miff")
    yield _case("quantizegap11", "rose granite -monitor +remap", [two + ["-monitor", "+remap", "null:"]], [])


def _resample_cases():
    for v in RESAMPLE_VIRTUAL_PIXELS:
        for label, how in RESAMPLE_DISTORTIONS:
            yield _op("resample", "rose_alpha -virtual-pixel %s %s" % (v, label),
                      [img("rose_alpha")], ["-virtual-pixel", v] + how)


def _blob_path_cases():
    yield _case("blob", "inline svg through a temporary file",
                [[img("rose"), "-resize", "4x4", "-define", "png:exclude-chunk=date,time",
                  "-write", "inline:svg:-", "null:"]], [])
    yield _with_inputs(_case("blob", "stdin miff over 1 MiB",
                             [["miff:-", "-scale", "16x16"] + FLOAT_OUT + ["out.miff"]],
                             ["out.miff"]), stdin=img("hald"))
    raw = [img("rose"), "-depth", "8", "gray:raw.gray"]
    for offset in ("70", "3220", "100000"):
        yield _case("blob", "raw header offset %s" % offset,
                    [raw, ["-size", "70x45+" + offset, "-depth", "8", "gray:raw.gray",
                           "-format", "%[fx:mean]\\n", "info:"]], [])


def _quantum_cases(writable_formats):
    yield from _quantum_layout_cases(writable_formats)
    yield from _quantum_yuv_cases()
    yield from _quantum_index_cases()
    yield from _quantum_meta_cases()
    yield from _quantum_round2_cases(writable_formats)


# ---- decoders over the frozen reader corpus
# Raw decode files, read with an explicit format prefix.
_RAW_DECODE_SUFFIXES = (".cmyk", ".gray", ".rgba", ".rgb", ".uyvy", ".yuv")


def _decode_cases(lists):
    for fname in lists.get("__decode_files__", []):
        base = fname.rsplit("/", 1)[-1]
        if not base.lower().endswith(EXTERNAL_DECODE):
            yield from _decode_file_cases(fname, base)


def _decode_file_cases(fname, base):
    pre = RAW_DECODE.get(base, [])
    spec = "{C}/files/" + fname
    if base.endswith(_RAW_DECODE_SUFFIXES):
        spec = base.rsplit(".", 1)[1] + ":" + spec
    yield _case("decode", fname, [pre + [spec] + FLOAT_OUT + ["dec.miff"]], ["dec.miff"])
    yield _case("decode", "identify -verbose " + fname,
                [["identify", "-verbose"] + pre + [spec]], [])


# ---- infrastructure: how the work is done rather than what it computes.
# Mutation testing found blob.c, cache.c, image.c, property.c and option.c
# the least protected code the oracle reaches (docs/refactoring/MUTATION.md):
# small images read from plain files never take their other paths.
# The pixel cache on disk, and memory-mapped.
def _infra_cache_cases():
    for tag, limits in (("disk", ["-limit", "memory", "0", "-limit", "map", "0"]),
                        ("map", ["-limit", "memory", "0"])):
        for op in ("-resize 150%", "-blur 0x1", "-rotate 30", "-flop", "-colorspace Lab",
                   "-distort SRT 20", "-morphology Dilate Disk:1", "-crop 30x20+10+10 +repage"):
            yield _op("infra", "%s cache rose %s" % (tag, op), limits + [img("rose")],
                      op.split())
        yield _op("infra", "%s cache seq -append" % tag, limits + [img("seq")],
                  ["-append"])
        yield _op("infra", "%s cache rose clone composite" % tag,
                  limits + [img("rose")], ["(", "+clone", "-negate", ")", "-composite"])


# Compressed streams and in-memory blobs (blob.c, registry.c).
def _infra_blob_cases():
    for ext in ("gz", "bz2"):
        yield _case("infra", "blob %s round trip" % ext,
                    [[img("rose"), "out.miff." + ext],
                     ["out.miff." + ext] + FLOAT_OUT + ["dec.miff"]],
                    ["out.miff." + ext, "dec.miff"])
    for fmt in ("png", "miff", "ppm", "gif", "tiff"):
        yield _case("infra", "stdout " + fmt, [[img("rose"), fmt + ":-"]], [])
    for fmt in ("", "miff:", "ppm:"):
        src = "{C}/rose.miff" if fmt != "ppm:" else "{C}/files/PerlMagick/t/MasterImage_70x46.ppm"
        yield _with_inputs(_case("infra", "stdin %s-" % fmt,
                                 [[fmt + "-"] + FLOAT_OUT + ["out.miff"]], ["out.miff"]),
                           stdin=src)
    yield _op("infra", "mpr registry", [img("rose")],
              ["-write", "mpr:a", "+delete", "mpr:a", "-negate", "mpr:a", "-append"])
    yield _case("infra", "write mid-pipeline",
                [[img("rose"), "-write", "mid.miff", "-negate"] + FLOAT_OUT + ["out.miff"]],
                ["mid.miff", "out.miff"])
    yield _op("infra", "inline data URI",
              ["inline:data:image/gif;base64,"
               "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"], [])


# Filename syntax (image.c, option.c): frames, crops and sizes on read,
# explicit formats, lists, scene numbering, filename escapes.
def _infra_filename_cases():
    for spec in ("seq.miff[0]", "seq.miff[1-2]", "seq.miff[2,0]", "seq.miff[-1]",
                 "rose.miff[20x20+5+5]", "rose.miff[50%]", "rose.miff[30x20]", "rose.miff[1]",
                 "anim.miff[0--1]"):
        yield _op("infra", "read " + spec, ["{C}/" + spec], [])
    yield _op_to("infra", "explicit format prefix", ["miff:{C}/rose.miff"] + FLOAT_OUT,
                 "png:out.dat")
    yield _with_inputs(_case("infra", "@list of files",
                             [["@list.txt", "-append"] + FLOAT_OUT + ["out.miff"]],
                             ["out.miff"]),
                       files={"list.txt": "{C}/rose.miff\n{C}/granite.miff\n"})
    yield _case("infra", "+adjoin scene numbering",
                [[img("seq"), "-scene", "5", "+adjoin", "out-%02d.miff"]], [])
    yield _case("infra", "filename escape",
                [[img("rose"), "-set", "filename:dims", "%wx%h",
                  "out-%[filename:dims].miff"]], [])


# Properties, options and artifacts (property.c, option.c).
def _infra_property_cases():
    yield _case("infra", "set and read properties",
                [[img("rose"), "-set", "label", "Hello", "-set", "comment", "World",
                  "-set", "Title", "A title", "-define", "myopt=1",
                  "-set", "option:myopt2", "x", "-format",
                  "%[label]|%[comment]|%[Title]|%[property:Title]|%[option:myopt]|"
                  "%[myopt]|%[option:myopt2]|%l|%c\n", "info:"]], [])
    yield _case("infra", "list every property",
                [[img("rose"), "-set", "comment", "x", "-format", "%[*]\n", "info:"]], [])
    yield _case("infra", "comment and label settings",
                [["-comment", "%wx%h %m", "-label", "%f", img("rose"), "-format",
                  "%c|%l\n", "info:"]], [])


# ---- cipher.c: -encipher then -decipher, a round trip
def _cipher_cases():
    for name in ("rose", "rose_alpha", "gray16"):
        yield _with_inputs(
            _case("cipher", "encipher " + name,
                  [[img(name), "-encipher", "pass.txt", "enc.miff"],
                   ["enc.miff", "-decipher", "pass.txt"] + FLOAT_OUT + ["dec.miff"]],
                  ["enc.miff", "dec.miff"]),
            files={"pass.txt": "A refactoring changes no behaviour.\n"})


# ---- version.c and the -list printers of the infrastructure files
def _info_cases():
    yield _case("info", "version", [["-version"]], [])
    for name in ("configure", "mime", "policy", "log", "locale", "type", "font", "delegate",
                 "coder", "magic", "resource", "format", "threshold"):
        yield _case("info", "list " + name, [["-list", name]], [])


# ---- MVG and SVG through the internal renderer
def _mvg_cases():
    for mvg in ("draw.mvg",):
        yield _case("mvg", mvg, [["mvg:{C}/" + mvg] + FLOAT_OUT + ["out.miff"]],
                    ["out.miff"])
        yield _case("mvg", "svg-out " + mvg,
                    [["{C}/%s" % mvg.replace(".mvg", ".svg")] + FLOAT_OUT + ["out.miff"]],
                    ["out.miff"])


# ---- gaps found by reading surviving mutants (tools/oracle/verdicts.json).
# Each case killed the survivors named beside it when it was added; the
# verdict explains why no existing case could.
GAP_CASES = [
    # enhance.c
    ("rose -clahe 10x20!+64+3", ["-clahe", "10x20!+64+3"], ["rose"]),  # bins other than 128, tall padding
    ("gray16 rose -clut", ["-clut"], ["gray16", "rose"]),                # colour clut on gray; clut varies in x
    ("cmyk rose -clut", ["-clut"], ["cmyk", "rose"]),
    ("rose_alpha rose -clut", ["-clut"], ["rose_alpha", "rose"]),
    ("rose rose_alpha -clut", ["-clut"], ["rose", "rose_alpha"]),         # clut with alpha
    ("gray16 -contrast-stretch 64x64", ["-contrast-stretch", "64x64"], ["gray16"]),  # 64 pixels a level
    ("gray16 -linear-stretch 64x64", ["-linear-stretch", "64x64"], ["gray16"]),
    ("gray16 hald -hald-clut", ["-hald-clut"], ["gray16", "hald"]),       # colorspace differs from the clut's
    ("rose_alpha hald -hald-clut", ["-hald-clut"], ["rose_alpha", "hald"]),
    ("cmyk hald-cmyk -hald-clut", ["(", img("hald"), "-colorspace", "CMYK", ")", "-hald-clut"],
     ["cmyk"]),
    ("rose_alpha -colors 16 -level", ["-colors", "16", "-level", "10%,90%"], ["rose_alpha"]),
    ("gray16 -level-colors navy,gray", ["-level-colors", "navy,gray(80%)"], ["gray16"]),
    ("gray16 -level-colors gray,gold", ["-level-colors", "gray(20%),gold"], ["gray16"]),
    ("rose +level-colors mid red", ["+level-colors", "#402000,#c0e0ff"], ["rose"]),
    ("rose modulate:colorspace", ["-define", "modulate:colorspace=HSB", "-modulate", "110/90/80"],
     ["rose"]),
    ("rose modulate color:illuminant", ["-define", "color:illuminant=D50", "-define",
                                        "modulate:colorspace=LCHab", "-modulate", "110/90/80"],
     ["rose"]),
]
# Code in enhance.c that no case executed.
REACH_CASES = [
    ("rose -channel RG -auto-gamma", ["-channel", "RG", "-auto-gamma"], ["rose"]),  # per channel
    ("rose +negate", ["+negate"], ["rose"]),                                # gray pixels only
    ("gray16 +negate", ["+negate"], ["gray16"]),
    ("palette +negate", ["+negate"], ["palette"]),
    ("rose nearest hald -hald-clut", ["-interpolate", "Nearest", img("hald"), "-hald-clut"],
     ["rose"]),
    ("rose_alpha -colors 16 -equalize", ["-colors", "16", "-equalize"], ["rose_alpha"]),
    ("rose_alpha -colors 16 -contrast-stretch", ["-colors", "16", "-contrast-stretch", "2%x1%"],
     ["rose_alpha"]),
    ("rose invalid color:illuminant", ["-define", "color:illuminant=bogus", "-define",
                                       "modulate:colorspace=LCHab", "-modulate", "110/90/80"],
     ["rose"]),  # an invalid illuminant also resets the colorspace to the default
    ("rose white-balance:vibrance %", ["-define", "white-balance:vibrance=10%", "-white-balance"],
     ["rose"]),
    ("rose white-balance:vibrance", ["-define", "white-balance:vibrance=2000", "-white-balance"],
     ["rose"]),
] + [("%s modulate:colorspace=%s" % (name, cs), ["-define", "modulate:colorspace=" + cs,
                                                 "-modulate", "110/100/95"], [name])
     # the HDRI image's out-of-gamut values make a wrong hue wrap visible
     for name in ("rose", "hdri")
     for cs in ("HCL", "HCLp", "HSB", "HSI", "HSV", "HWB", "LCHab", "LCHuv")]
# ColorDecisionListImage: the sample from its documentation, with offsets that
# keep every value positive (a negative base to Power 0.8 is NaN).
CDL = """<ColorCorrectionCollection xmlns="urn:ASC:CDL:v1.2">
  <ColorCorrection id="cc03345">
    <SOPNode>
      <Slope> 0.9 1.2 0.5 </Slope>
      <Offset> 0.04 0.05 0.06 </Offset>
      <Power> 1.0 0.8 1.5 </Power>
    </SOPNode>
    <SATNode>
      <Saturation> 0.85 </Saturation>
    </SATNode>
  </ColorCorrection>
</ColorCorrectionCollection>
"""
CDL_INPUTS = ["rose", "rose_alpha", "palette", "gray16"]
# Whole commands, {C} for the corpus, as tools/oracle/verdicts.json names them.
_VERBOSE_AT = "-precision 17 -define auto-threshold:verbose=1 -auto-threshold "
GAP_COMMANDS = [
    # threshold.c: -auto-threshold prints its threshold; a histogram whose maximum
    # entropy is at bin 0 (Kapur), one not starting at 0 and one symmetric about
    # its peak (Triangle)
    "{C}/rose.miff " + _VERBOSE_AT + "Triangle",
    "-size 18x1 xc:black -size 1x1 xc:gray50 xc:white +append " + _VERBOSE_AT + "Kapur",
    "-size 1x1 xc:rgb(20,20,20) xc:rgb(30,30,30) xc:rgb(40,40,40) xc:rgb(40,40,40) "
    "xc:rgb(40,40,40) xc:rgb(40,40,40) xc:rgb(60,60,60) xc:rgb(80,80,80) "
    "xc:rgb(100,100,100) +append " + _VERBOSE_AT + "Triangle",
    "-size 1x1 xc:rgb(0,0,0) xc:rgb(5,5,5) xc:rgb(5,5,5) xc:rgb(5,5,5) xc:rgb(1,1,1) "
    "xc:rgb(9,9,9) xc:rgb(10,10,10) +append " + _VERBOSE_AT + "Triangle",
    # per-channel thresholds, CMYK with alpha included
    "{C}/rose.miff -black-threshold 20,40,60%",
    "{C}/cmyk.miff -black-threshold 20,30,40,50,60%",
    "{C}/rose_alpha.miff -colorspace CMYK -black-threshold 20,30,40,50,60%",
    "{C}/rose.miff -white-threshold 60,70,80%",
    "{C}/cmyk.miff -white-threshold 60,70,80,50,40%",
    "{C}/rose_alpha.miff -colorspace CMYK -white-threshold 60,70,80,50,40%",
    "{C}/rose.miff -colorspace Lab -define color:illuminant=A "
    "-color-threshold 'cielab(50,10,10)-cielab(80,40,40)'",
    # -ordered-dither: the divisor-2 map, a leading separator, several levels, level 1
    "{C}/rose.miff -ordered-dither threshold",
    "{C}/rose.miff -ordered-dither ,o4x4",
    "{C}/rose.miff -ordered-dither o4x4,3,6,9",
    "{C}/rose.miff -ordered-dither o4x4,1",
    "{C}/rose.miff -ordered-dither o4x4,1,3",
    # limits in percent, and pixels exactly on the -range-threshold limits
    "{C}/rose.miff -seed 3 -random-threshold 20x80%",
    "-size 1x1 xc:gray(10%) xc:gray(20%) xc:gray(50%) xc:gray(80%) xc:gray(90%) +append "
    "( {C}/gray16.miff -scale 5x5! ) -append -range-threshold 10,20,80,90%",
    # decorate.c: frames smaller than their bevels (errors), a matte colour with
    # alpha or with black, a frame larger than a 1x1 image, bevels of exactly half
    "{C}/rose.miff -frame 3x10+2+2",
    "{C}/rose.miff -frame 10x3+2+2",
    "{C}/rose.miff -mattecolor #8888 -frame 10x10+3+3",
    "{C}/cmyk.miff -mattecolor cmyk(10%,20%,30%,40%) -frame 10x10+3+3",
    "{C}/tiny.miff -frame 2x2+1+1",
    "{C}/rose.miff -raise 35x10",
    "{C}/rose.miff -raise 10x23",
    # segment.c: a cluster with no pixels; cluster thresholds that prune
    "{C}/wizard.miff -segment 1x0.01",
    "{C}/photo.miff -segment 50x0.5",
    "{C}/photo.miff -segment 99x0.5",
    # shear.c: rotating a virtual canvas, images taller than one rotation tile,
    # shears of 0 on one axis and with transparent background, and -deskew on
    # skewed images with the angle printed (one with pixels on the threshold)
    "{C}/rose.miff -repage 100x80+5+7 -rotate 90",
    "{C}/rose.miff -repage 100x80+5+7 -rotate 180",
    "{C}/rose.miff -repage 100x80+5+7 -rotate 270",
    "{C}/rose.miff -scale 300x200! -rotate 90",
    "{C}/rose.miff -scale 300x200! -rotate 270",
    "{C}/rose.miff -shear 0x20",
    "{C}/rose.miff -shear 20x0",
    "{C}/rose.miff -background none -shear 10x30",
    # auto-crop averages the border for the background; =1 is the only width
    # IsStringTrue lets through, =true gives width 0
    "{C}/rose.miff -define deskew:auto-crop=1 -deskew 40%",
    "{C}/rose_alpha.miff -define deskew:auto-crop=1 -deskew 40%",
    "{C}/rose.miff -define deskew:auto-crop=true -deskew 40%",
    "{C}/rose.miff -background white -rotate 7 -define deskew:auto-crop=1 -deskew 40%",
    "{C}/rose.miff -background white -rotate 7 -deskew 40% -precision 17 "
    "-print %[deskew:angle]",
    "-size 70x40 xc:white -fill rgb(102,200,200) -draw 'line 0,10 69,16' "
    "-fill rgb(200,102,200) -draw 'line 0,20 69,26' -fill rgb(200,200,102) "
    "-draw 'line 0,30 69,36' -deskew 26214 -precision 17 -print %[deskew:angle]",
    # compare.c: a 1x1 PHASE, a masklight colour, subimage searches with an equal-size
    # and an inexact patch
    "compare -metric PHASE {C}/tiny.miff {C}/tiny.miff",
    "compare -metric AE -size 70x46 -read-mask xc:gray(20%) -define compare:masklight-color=blue "
    "{C}/rose.miff {C}/rose_blur.miff",
    # (small: a full-size equal search is too slow on a Mull build, and a baseline
    # that times out is dropped)
    "compare -metric RMSE -subimage-search ( {C}/rose.miff -crop 20x20+0+0 +repage ) "
    "( {C}/rose_blur.miff -crop 20x20+0+0 +repage )",
    "compare -metric RMSE -subimage-search {C}/rose.miff "
    "( {C}/rose_blur.miff -crop 20x20+10+10 +repage )",
    # visual-effects.c: plasma on images small enough for segments to degenerate,
    # CMYK and alpha inputs, transparent backgrounds, a matrix above 6x6, a
    # virtual canvas for -shadow, exact -solarize thresholds, a -tint colour with
    # green and blue
    "{C}/cmyk.miff -fill cmyk(20%,40%,60%,30%) -colorize 10,20,30,40,50",
    "{C}/rose.miff -color-matrix '1 0 0 0 0 0 0, 0 1 0 0 0 0 0, 0 0 0.9 0 0 0 0, 0 0 0 1 0 0 0, 0 0 0 0 1 0 0, 0 0 0 0 0 1 0, 0.1 0 0 0 0 0 1'",
    "{C}/cmyk.miff -color-matrix '0.9 0 0 0 0.1, 0 1 0 0 0, 0 0 1.1 0 0, 0 0 0 0.8 0, 0 0 0 0 1'",
    "{C}/rose_alpha.miff -color-matrix '0.9 0 0 0 0.1, 0 1 0 0 0, 0 0 1.1 0 0, 0 0 0 0.8 0, 0 0 0 0 1'",
    "{C}/rose.miff -background none -implode 0.5",
    "-seed 1 -size 1x1 plasma:",
    "-seed 1 -size 2x2 plasma:",
    "{C}/gray16.miff -shadow 80x3+5+5",
    "{C}/rose.miff -repage 100x80+5+7 -shadow 80x3+5+5",
    "-size 1x1 xc:rgb(102,102,102) xc:rgb(10,200,102) xc:rgb(102,30,250) +append -type palette -solarize 26214",
    "-size 1x1 xc:rgb(102,102,102) xc:rgb(10,200,102) xc:rgb(102,30,250) +append -solarize 26214",
    "{C}/rose.miff -fill #80c040 -tint 50",
    "{C}/cmyk.miff -fill cmyk(20%,40%,60%,30%) -tint 10,20,30,40,50",
    "{C}/rose.miff -background none -wave 5x20",
]
# visual-effects.c: -stegano and -stereo exist only in the composite utility (a
# `magick ... -stereo` case failed on both sides and tested nothing), -polaroid
GAP_COMMANDS += [
    "composite -stereo +3+2 {C}/rose_blur.miff {C}/rose.miff",
    "composite -stereo -2-1 {C}/rose_alpha.miff {C}/rose.miff",
    "{C}/rose.miff -polaroid 10",
    "{C}/rose.miff -scale 300x200! -polaroid 10",
    "composite -stereo 0 {C}/rose.miff {C}/rose_alpha.miff",
    "{C}/rose.miff -font {C}/Generic.ttf -caption Hi -background white +polaroid",
]
# statistic.c: moments of a uniform image, mixed sizes for -evaluate-sequence and
# ties in its median, each -function with exactly as many parameters as a default
# test counts, HDRI powers and clamping, -poly with 3 terms, write masks for
# -statistic, and phash colorspace lists
GAP_COMMANDS += [
    "-size 1x1 xc:rgb(30,20,10) xc:rgb(10,20,30) xc:rgb(20,20,20) xc:rgb(20,30,10) -evaluate-sequence median",
    "{C}/hdri.miff -evaluate pow 2",
    "{C}/tall.miff {C}/rose.miff -evaluate-sequence mean",
    "{C}/rose.miff {C}/tall.miff -evaluate-sequence mean",
    "{C}/rose.miff {C}/gray16.miff -evaluate-sequence mean",
    "{C}/hdri.miff -define evaluate:clamp=true -evaluate add 50%",
    "{C}/rose.miff -function Sinusoid 3",
    "{C}/rose.miff -function Sinusoid 3,-90,0.2",
    "{C}/rose.miff -function Sinusoid 3,-90,0.2,0.6",
    "{C}/rose.miff -function ArcSin 2",
    "{C}/rose.miff -function ArcSin 2,0.4",
    "{C}/rose.miff -function ArcSin 2,0.4,0.8",
    "{C}/rose.miff -function ArcSin 2,0.4,0.8,0.3",
    "{C}/rose.miff -function ArcTan 10",
    "{C}/rose.miff -function ArcTan 10,.7,0.8",
    "{C}/rose.miff -function ArcTan 10,.7,0.8,0.3",
    "identify -verbose -precision 17 -moments {C}/tiny.miff",
    "identify -verbose -precision 17 -moments -define phash:colorspaces=sRGB,HCLp,Lab,XYZ,HSB,HSV,HSL,LCH {C}/rose.miff",
    "identify -verbose -precision 17 -moments -define phash:colorspaces=Undefined,sRGB {C}/rose.miff",
    "{C}/rose.miff {C}/rose_blur.miff {C}/rose.miff -poly '0.5,1 0.3,2 0.2,1'",
    "{C}/rose.miff -size 70x46 -write-mask gradient: -statistic Median 3",
    "{C}/rose.miff -size 70x46 -write-mask gradient: -statistic Median 5",
    "{C}/rose.miff -size 70x46 -read-mask xc:gray(50%) -precision 17 -verbose -write info:",
    "{C}/rose.miff -size 70x46 -write-mask xc:gray(50%) -statistic Median 3",
]
# resize.c: -resample without -density (the setting overwrites the resolution
# ResampleImage sets), and filter defines no case set
GAP_COMMANDS += [
    "{C}/rose.miff -resample 144",
    "{C}/rose.miff -define filter:window=Undefined -define filter:verbose=1 -resize 50%",
    "{C}/rose.miff -filter Gaussian -define filter:sigma=0.8 -define filter:verbose=1 -resize 50%",
    "{C}/rose.miff -filter Cubic -define filter:b=0.3 -define filter:verbose=1 -resize 50%",
]
# annotate.c: every gravity with two lines and with a rotation, decorations, no
# antialiasing, undercolor, kerning, wrapping captions, font encodings
GAP_COMMANDS += [
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity NorthWest -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity NorthWest -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity North -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity North -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity West -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity West -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity Center -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity Center -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity East -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity East -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthWest -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthWest -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity South -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity South -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthEast -annotate +2+2 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthEast -annotate 15x0+3+4 'Tilt'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -draw \"decorate underline text 5,20 'Deco'\"",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -draw \"decorate overline text 5,20 'Deco'\"",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -draw \"decorate line-through text 5,20 'Deco'\"",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 +antialias -annotate +5+20 Mono",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -undercolor navy -fill white -annotate +5+20 'Under'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -kerning 2 -interword-spacing 6 -annotate +2+20 'a b c'",
    "-size 40x -font {C}/Generic.ttf -pointsize 11 caption:'a bb ccc dddd eeeee'",
    "-size 30x -font {C}/Generic.ttf -pointsize 11 caption:'nospacesinthislongword'",
    "-size 60x40 -font {C}/Generic.ttf -pointsize 11 caption:'line one\\nline two'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -encoding Unicode -annotate +5+20 'Enc'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -encoding None -annotate +5+20 'Enc'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -encoding AppleRoman -annotate +5+20 'Enc'",
]
# vision.c: a few distinct blobs through every connected-components define, and
# -integral
GAP_COMMANDS += [
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -connected-components 4",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:area-threshold=10-200 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:angle-threshold=10-80 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:circularity-threshold=0.3-0.9 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:eccentricity-threshold=0.1-0.9 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:major-axis-threshold=5-30 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:minor-axis-threshold=2-12 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:perimeter-threshold=10-60 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:mean-color=true -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep=1,2 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:remove=2 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep-colors=white -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:remove-colors=gray -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep-top=2 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:sort=area -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:sort-order=decreasing -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:exclude-header=true -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:background-id=0 -connected-components 8",
    "{C}/rose.miff -define connected-components:verbose=true -define connected-components:sort=circularity -define connected-components:area-threshold=20 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:diameter-threshold=5-20 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep-ids=9,11 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:remove-ids=58 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:exclude-ids=0 -connected-components 8",
    "{C}/rose.miff -integral",
    "{C}/gray16.miff -integral",
    "{C}/rose_alpha.miff -integral",
]
# profile.c: an EXIF block (every byte below 128, so it can be case text), XMP as
# attributes and as elements, the ICC profile of the one JPEG that carries one,
# and PSD round trips whose 8BIM holds resolution and ICC resources. Each entry:
# label, steps (the last writes out.miff), files written into the case first.
EXIF_BLOCK = "Exif\u0000\u0000II*\u0000\b\u0000\u0000\u0000\u0004\u0000\u0012\u0001\u0003\u0000\u0001\u0000\u0000\u0000\u0001\u0000\u0000\u0000\u001a\u0001\u0005\u0000\u0001\u0000\u0000\u0000>\u0000\u0000\u0000\u001b\u0001\u0005\u0000\u0001\u0000\u0000\u0000F\u0000\u0000\u0000(\u0001\u0003\u0000\u0001\u0000\u0000\u0000\u0002\u0000\u0000\u0000\u0000\u0000\u0000\u0000H\u0000\u0000\u0000\u0001\u0000\u0000\u0000H\u0000\u0000\u0000\u0001\u0000\u0000\u0000"
XMP_ATTRIBUTES = "<?xpacket begin=\"\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n<rdf:Description rdf:about=\"\" xmlns:tiff=\"http://ns.adobe.com/tiff/1.0/\"\n tiff:XResolution=\"72/1\" tiff:YResolution=\"72/1\" tiff:ResolutionUnit=\"2\" tiff:Orientation=\"1\"/>\n</rdf:RDF></x:xmpmeta>\n<?xpacket end=\"w\"?>"
XMP_ELEMENTS = "<?xpacket begin=\"\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n<rdf:Description rdf:about=\"\" xmlns:tiff=\"http://ns.adobe.com/tiff/1.0/\"\n><tiff:XResolution>72/1</tiff:XResolution><tiff:YResolution>72/1</tiff:YResolution><tiff:ResolutionUnit>2</tiff:ResolutionUnit><tiff:Orientation>1</tiff:Orientation></rdf:Description>\n</rdf:RDF></x:xmpmeta>\n<?xpacket end=\"w\"?>"
_UHDR_JPG = "{C}/files/tests/cli-uhdr-iptc.jpg"
GAP_STEP_CASES = [
    ("rose exif profile, density and orientation",
     [["{C}/rose.miff", "-profile", "APP1:exif.bin", "-density", "300", "-orient", "BottomLeft",
       "out.miff"]], {"exif.bin": EXIF_BLOCK}),
    ("rose xmp attributes, density and orientation",
     [["{C}/rose.miff", "-profile", "meta.xmp", "-density", "300", "-orient", "BottomLeft",
       "out.miff"]], {"meta.xmp": XMP_ATTRIBUTES}),
    ("rose xmp elements, density and orientation",
     [["{C}/rose.miff", "-profile", "meta.xmp", "-density", "300", "-orient", "BottomLeft",
       "out.miff"]], {"meta.xmp": XMP_ELEMENTS}),
    ("rose icc applied twice",
     [[_UHDR_JPG, "icc.icc"], ["{C}/rose.miff", "-profile", "icc.icc", "-profile", "icc.icc",
                                "out.miff"]], {}),
    ("psd 8bim resolution rewritten",
     [["{C}/rose.miff", "-density", "150", "-units", "PixelsPerInch", "r.psd"],
      ["r.psd", "-density", "300", "-units", "PixelsPerInch", "out.miff"]], {}),
    ("psd 8bim with icc, icc removed",
     [[_UHDR_JPG, "icc.icc"],
      ["{C}/rose.miff", "-profile", "icc.icc", "-density", "150", "-units", "PixelsPerInch", "r.psd"],
      ["r.psd", "+profile", "icc", "out.miff"]], {}),
    ("psd 8bim with icc, xmp added",
     [[_UHDR_JPG, "icc.icc"],
      ["{C}/rose.miff", "-profile", "icc.icc", "-density", "150", "-units", "PixelsPerInch", "r.psd"],
      ["r.psd", "-profile", "meta.xmp", "out.miff"]], {"meta.xmp": XMP_ELEMENTS}),
    # second round: rationals with denominator 2, big-endian longs, XMP values
    # changing length and unequal x and y density
    ("rose exif little-endian rationals /2, density and orientation",
     [["{C}/rose.miff", "-profile", "APP1:exif.bin", "-density", "300", "-orient", "BottomLeft", "out.miff"]],
     {"exif.bin": "Exif\u0000\u0000II*\u0000\b\u0000\u0000\u0000\u0004\u0000\u0012\u0001\u0004\u0000\u0001\u0000\u0000\u0000\u0001\u0000\u0000\u0000\u001a\u0001\u0005\u0000\u0001\u0000\u0000\u0000>\u0000\u0000\u0000\u001b\u0001\u0005\u0000\u0001\u0000\u0000\u0000F\u0000\u0000\u0000(\u0001\u0004\u0000\u0001\u0000\u0000\u0000\u0002\u0000\u0000\u0000\u0000\u0000\u0000\u0000F\u0000\u0000\u0000\u0002\u0000\u0000\u0000F\u0000\u0000\u0000\u0002\u0000\u0000\u0000"}),
    ("rose exif big-endian longs, density and orientation",
     [["{C}/rose.miff", "-profile", "APP1:exif.bin", "-density", "300", "-orient", "BottomLeft", "out.miff"]],
     {"exif.bin": "Exif\u0000\u0000MM\u0000*\u0000\u0000\u0000\b\u0000\u0004\u0001\u0012\u0000\u0004\u0000\u0000\u0000\u0001\u0000\u0000\u0000\u0001\u0001\u001a\u0000\u0005\u0000\u0000\u0000\u0001\u0000\u0000\u0000>\u0001\u001b\u0000\u0005\u0000\u0000\u0000\u0001\u0000\u0000\u0000F\u0001(\u0000\u0004\u0000\u0000\u0000\u0001\u0000\u0000\u0000\u0002\u0000\u0000\u0000\u0000\u0000\u0000\u0000F\u0000\u0000\u0000\u0002\u0000\u0000\u0000F\u0000\u0000\u0000\u0002"}),
    ("rose xmp elements, unequal density",
     [["{C}/rose.miff", "-profile", "meta.xmp", "-density", "300x150", "out.miff"]],
     {"meta.xmp": "<?xpacket begin=\"\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n<rdf:Description rdf:about=\"\" xmlns:tiff=\"http://ns.adobe.com/tiff/1.0/\"\n><tiff:XResolution>72/1</tiff:XResolution><tiff:YResolution>72/1</tiff:YResolution><tiff:ResolutionUnit>2</tiff:ResolutionUnit><tiff:Orientation>1</tiff:Orientation></rdf:Description>\n</rdf:RDF></x:xmpmeta>\n<?xpacket end=\"w\"?>"}),
    ("rose xmp elements, shorter value",
     [["{C}/rose.miff", "-profile", "meta.xmp", "-density", "7", "out.miff"]],
     {"meta.xmp": "<?xpacket begin=\"\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n<rdf:Description rdf:about=\"\" xmlns:tiff=\"http://ns.adobe.com/tiff/1.0/\"\n><tiff:XResolution>72/1</tiff:XResolution><tiff:YResolution>72/1</tiff:YResolution><tiff:ResolutionUnit>2</tiff:ResolutionUnit><tiff:Orientation>1</tiff:Orientation></rdf:Description>\n</rdf:RDF></x:xmpmeta>\n<?xpacket end=\"w\"?>"}),
    # compress.c: fax decoding (HuffmanDecodeImage) of a file the case writes first
    ("fax written and read back",
     [["{C}/bilevel.miff", "b.fax"], ["fax:b.fax", "out.miff"]],
     {}),
    ("fax of a dithered photo read back",
     [["{C}/rose.miff", "-monochrome", "b.fax"], ["fax:b.fax", "out.miff"]],
     {}),
]
# magic.c (ERDC's runs): files with no extension, so only the signature table decides:
# PCD_ at 2048 (the farthest signature, which sets how much is read), a file exactly as
# long as a signature, SVG with and without spaces after the '<' (the only entries
# that skip spaces), and a file matching two signatures at different offsets
GAP_STEP_CASES += [
    ("signature at offset 2048 (pcd)", [["pcdsig", "out.miff"]],
     {"pcdsig": "A" * 2048 + "PCD_" + "A" * 60}),
    ("file exactly a signature long (gif)", [["gifsig", "out.miff"]], {"gifsig": "GIF8"}),
    ("svg signature without extension", [["plainsvg", "out.miff"]],
     {"plainsvg": "<svg xmlns='http://www.w3.org/2000/svg' width='4' height='3'>"
                  "<rect width='4' height='3' fill='red'/></svg>\n"}),
    ("svg signature after spaces", [["spacesvg", "out.miff"]],
     {"spacesvg": "<  svg xmlns='http://www.w3.org/2000/svg' width='4' height='3'>"
                  "<rect width='4' height='3' fill='red'/></svg>\n"}),
    ("gif and dicom signatures in one file", [["gifdcm", "out.miff"]],
     {"gifdcm": "GIF8" + "A" * 124 + "DICM" + "A" * 60}),
]
# policy.c, memory.c (ERDC's runs): a policy.xml of the case's own. The oracle sets HOME
# to the case directory, and ImageMagick reads every policy.xml on its configure path,
# $HOME/.config/ImageMagick/ among them, on top of the build's
_POLICY = ".config/ImageMagick/policy.xml"


def _policy(*lines):
    return "<policymap>\n%s\n</policymap>\n" % "\n".join("  " + x for x in lines)


GAP_STEP_CASES += [
    ("policy denies a coder", [["{C}/rose.miff", "x.gif"], ["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="coder" rights="none" pattern="GIF" />')}),
    ("policy denies a path pattern",
     [["{C}/rose.miff", "secret-1.miff"], ["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="none" pattern="*secret*" />')}),
    ("policy denies writing into a directory",
     [["{C}/rose.miff", "sub/x.miff"], ["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="read" pattern="*/sub" />'),
      "sub/keep.txt": "kept\n"}),
    ("policy allows reading only",
     [["{C}/rose.miff", "x.png"], ["x.png", "out.miff"], ["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="read" pattern="*.png" />')}),
    ("policy names, values and stealth, listed", [["-list", "policy"]],
     {_POLICY: _policy('<policy domain="resource" name="width" value="10KP"/>',
                       '<policy domain="system" name="precision" value="6"/>',
                       '<policy domain="cache" name="shared-secret" value="x" stealth="True"/>',
                       '<policy domain="delegate" rights="none" pattern="HTTPS" />')}),
    ("policy included from another file",
     [["{C}/rose.miff", "x.gif"], ["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<include file="extra.xml"/>'),
      ".config/ImageMagick/extra.xml": _policy(
          '<policy domain="coder" rights="none" pattern="GIF" />')}),
    ("policy forbids following symlinks", [["{C}/rose.miff", "-resize", "50%", "out.miff"]],
     {_POLICY: _policy('<policy domain="system" name="symlink" rights="none" pattern="follow" />')}),
    ("policy max-memory-request, scratch buffers in a mapped file",
     [["{C}/rose.miff", "-resize", "300%", "-despeckle", "out.miff"]],
     {_POLICY: _policy('<policy domain="system" name="max-memory-request" value="64KiB"/>')}),
    ("policy shreds memory and temporary files",
     [["-limit", "memory", "0", "-limit", "map", "0", "{C}/rose.miff", "-resize", "300%",
       "out.miff"]],
     {_POLICY: _policy('<policy domain="system" name="shred" value="2"/>')}),
]
# type.c (Mac): a type.xml of the case's own, found the same way. Glyph paths relative to
# the case directory and to type.xml's own directory (both reach the corpus font), one
# that does not exist (the entry is dropped), a stealth entry and an include
_TYPE_XML = """<typemap>
  <type name="Case-Sans" fullname="Case Sans" family="CaseFamily" foundry="Case" style="Italic"
    stretch="Condensed" weight="Bold" format="truetype" encoding="AppleRoman" face="0"
    glyphs="{C}/Generic.ttf" metrics="{C}/Generic.ttf"/>
  <type name="Case-Light" family="CaseFamily" weight="300" glyphs="../../{C}/Generic.ttf"/>
  <type name="Case-Missing" family="CaseFamily" glyphs="nowhere.ttf"/>
  <type name="Case-Hidden" stealth="True" glyphs="{C}/Generic.ttf"/>
  <include file="more.xml"/>
</typemap>
"""
_TYPE_FILES = {".config/ImageMagick/type.xml": _TYPE_XML,
               ".config/ImageMagick/more.xml":
                   '<typemap>\n  <type name="Case-More" family="MoreFamily" '
                   'glyphs="../../{C}/Generic.ttf"/>\n</typemap>\n'}
# type.c: a type.xml with a DOCTYPE holding brackets and a quoted '>', and comments with a
# '>' in them, which LoadTypeCache skips by hand
_TYPE_DOCTYPE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE typemap [
  <!ELEMENT typemap (type)+>
  <!ATTLIST type name CDATA #REQUIRED family CDATA "x]y>z" glyphs CDATA #IMPLIED>
]>
<!-- a comment before the map, with a > inside -->
<typemap>
  <!-- and one inside -->
  <type name="Doc-Sans" family="DocFamily" glyphs="{C}/Generic.ttf"/>
</typemap>
"""
GAP_STEP_CASES += [
    ("type.xml of the case's own, listed", [["-list", "font"]], _TYPE_FILES),
    ("type.xml with a DOCTYPE and comments, listed and used",
     [["-list", "font"], ["-family", "DocFamily", "-pointsize", "12", "label:Ab", "out.miff"]],
     {".config/ImageMagick/type.xml": _TYPE_DOCTYPE_XML}),

    ("type.xml fonts by name, family and weight, and from an include",
     [["-font", "Case-Sans", "-pointsize", "12", "label:Ab", "a.miff"],
      ["-family", "CaseFamily", "-weight", "300", "-pointsize", "12", "label:Ab", "b.miff"],
      ["-family", "CaseFamily", "-style", "Italic", "-stretch", "Condensed", "-pointsize", "12",
       "label:Ab", "c.miff"],
      ["-family", "MoreFamily", "-pointsize", "12", "label:Ab", "d.miff"],
      ["-font", "Case-Missing", "-pointsize", "12", "label:Ab", "e.miff"],
      ["a.miff", "b.miff", "c.miff", "d.miff", "e.miff", "-append", "out.miff"]], _TYPE_FILES),
]
# annotate.c, second round: rotated multi-line text for every gravity (a line index
# times a unit scale hides a * turned into /), a virtual canvas, a gray image, text
# density, hinting off, UTF-8 text
GAP_COMMANDS += [
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity None -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity NorthWest -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity North -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity West -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity Center -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity East -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthWest -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity South -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity SouthEast -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -gravity NorthEast -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -affine 1.3,0.2,0.1,0.8,0,0 -annotate +3+10 'one\\ntwo'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -annotate 20x10+3+4 'one\\ntwo\\nthree'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -repage 100x80+5+7 -annotate +3+10 'Page'",
    "{C}/gray16.miff -font {C}/Generic.ttf -pointsize 11 -fill red -annotate +3+10 'Gray'",
    "-density 144 -font {C}/Generic.ttf -pointsize 16 label:Hi",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -set type:hinting off -annotate +5+20 'Hint'",
    "{C}/rose.miff -font {C}/Generic.ttf -pointsize 11 -annotate +5+20 'café ✓'",
]
# vision.c, second round: an area range whose ends are object areas, reversed id
# ranges, ';' in colour lists, sort order with a sort, CMYK mean colours, merging
# small objects under 4-connectivity
GAP_COMMANDS += [
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:area-threshold=110-141 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep=11-9 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:sort=area -define connected-components:sort-order=decreasing -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:remove-ids=11-9 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:keep-colors=white;gray -connected-components 8",
    "{C}/cmyk.miff -define connected-components:verbose=true -define connected-components:mean-color=true -define connected-components:area-threshold=20 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define connected-components:verbose=true -define connected-components:area-threshold=10-200 -connected-components 4",
    "{C}/rose.miff -define connected-components:area-threshold=16 -connected-components 4",
]
# utility.c: wildcards in input names, base64 via inline: (GIF: no dates to hide in
# the base64), paper sizes
GAP_COMMANDS += [
    "'{C}/ros*.miff' -append",
    "'{C}/r?se.miff' -flip",
    "'{C}/[rt]*.miff' -append",
    "{C}/tiny.miff -write inline:gif:-",
    "{C}/rose.miff -resize 5x3 -write inline:gif:-",
    "{C}/rose.miff -resize 4x4! -write inline:gif:-",
    "{C}/rose.miff -page A4",
    "{C}/rose.miff -page Letter+10+10",
]
# vision.c, third round: every shape metric over a range that keeps every object, printed at 17 digits, and each sort key
GAP_COMMANDS += [
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:angle-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:major-axis-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:minor-axis-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:eccentricity-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:circularity-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:perimeter-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:diameter-threshold=0-1000 -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:sort=area -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:sort=width -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:sort=height -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:sort=x -connected-components 8",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -define connected-components:verbose=true -define connected-components:sort=y -connected-components 8",
]
# layer.c: a five-frame animation with offsets, a duplicate, partial transparency and a zero delay, through every -layers method under each dispose method
GAP_COMMANDS += [
    "-dispose None -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce",
    "-dispose None -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers dispose",
    "-dispose None -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers optimize",
    "-dispose None -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce -layers optimize-plus",
    "-dispose Background -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce",
    "-dispose Background -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers dispose",
    "-dispose Background -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers optimize",
    "-dispose Background -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce -layers optimize-plus",
    "-dispose Previous -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce",
    "-dispose Previous -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers dispose",
    "-dispose Previous -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers optimize",
    "-dispose Previous -size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce -layers optimize-plus",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers optimize-transparency",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers remove-dups",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers remove-zero",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers compare-any",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers compare-clear",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers compare-overlay",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers merge",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers flatten",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers mosaic",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers trim-bounds",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) -layers coalesce -layers optimize-frame",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) null: ( -size 4x4 xc:white ) -gravity center -layers composite",
    "-size 20x16 xc:red -delay 10 ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 8x8 xc:blue -repage 20x16+3+2 ) ( -size 6x6 xc:#00ff0080 -repage 20x16+9+7 ) -delay 0 ( -size 4x4 xc:yellow -repage 20x16+1+10 ) null: ( -size 4x4 xc:white -repage +2+2 ) -compose multiply -layers composite",
]
# compress.c: fax encoding (HuffmanEncodeImage) to stdout
GAP_COMMANDS += [
    "{C}/bilevel.miff -write fax:-",
    "{C}/rose.miff -monochrome -write fax:-",
]
# attribute.c: Floyd-Steinberg depth reduction, and the minimum-bounding-box properties with each orientation
GAP_COMMANDS += [
    "{C}/rose.miff -define dither=FloydSteinberg -depth 4",
    "{C}/rose_alpha.miff -define dither=FloydSteinberg -depth 2",
    "{C}/gray16.miff -define dither=FloydSteinberg -depth 3",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -precision 17 -format '%[minimum-bounding-box] %[minimum-bounding-box:area] %[minimum-bounding-box:width] %[minimum-bounding-box:height] %[minimum-bounding-box:angle] %[minimum-bounding-box:unrotate]\\n' -write info:",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define minimum-bounding-box:orientation=landscape -precision 17 -format '%[minimum-bounding-box] %[minimum-bounding-box:area] %[minimum-bounding-box:width] %[minimum-bounding-box:height] %[minimum-bounding-box:angle] %[minimum-bounding-box:unrotate]\\n' -write info:",
    "-size 40x30 xc:black -fill white -draw 'circle 10,10 10,4' -draw 'rectangle 22,5 35,12' -fill gray -draw 'ellipse 20,22 12,4 20,340' -draw 'line 2,27 12,20' -define minimum-bounding-box:orientation=portrait -precision 17 -format '%[minimum-bounding-box] %[minimum-bounding-box:area] %[minimum-bounding-box:width] %[minimum-bounding-box:height] %[minimum-bounding-box:angle] %[minimum-bounding-box:unrotate]\\n' -write info:",
    "{C}/rose.miff -fuzz 20% -precision 17 -format '%[minimum-bounding-box] %[minimum-bounding-box:area] %[minimum-bounding-box:width] %[minimum-bounding-box:height] %[minimum-bounding-box:angle] %[minimum-bounding-box:unrotate]\\n' -write info:",
]
# type.c: font lookup by family, weight, style and stretch (the result depends on the machine's fonts, the same on both sides of one run)
GAP_COMMANDS += [
    "{C}/rose.miff -family Helvetica -pointsize 12 -annotate +5+20 Fam",
    "{C}/rose.miff -family Helvetica -weight Bold -pointsize 12 -annotate +5+20 Fam",
    "{C}/rose.miff -family Helvetica -style Italic -pointsize 12 -annotate +5+20 Fam",
    "{C}/rose.miff -family 'Nonexistent Family' -pointsize 12 -annotate +5+20 Fam",
    "{C}/rose.miff -family 'Times,Courier' -pointsize 12 -annotate +5+20 Fam",
]
# transform.c: tile crops (@) with overlap, offset and gravity, and trims of bordered images with -fuzz and the trim: defines
GAP_COMMANDS += [
    "{C}/rose.miff -crop 3x2@ +repage",
    "{C}/rose.miff -crop 2x2@",
    "{C}/rose.miff -gravity center -crop 3x3@ +repage",
    "{C}/rose.miff -crop 3x2-2-2@ +repage",
    "{C}/rose.miff -crop 3x2+3+2@ +repage",
    "{C}/rose.miff -crop 25x20 +repage",
    "{C}/rose.miff -crop 50%x40%",
    "{C}/rose.miff -bordercolor white -border 5 -trim",
    "{C}/rose.miff -bordercolor white -border 5 -fuzz 15% -trim +repage",
    "{C}/rose.miff -bordercolor white -border 3x6 -define trim:percent-background=50% -trim",
    "{C}/rose.miff -bordercolor white -border 5 -define trim:edges=north,east -trim",
    "{C}/rose_alpha.miff -bordercolor none -border 4 -trim",
]
# compare.c: every metric with a read mask of exactly QuantumRange/2 on one image
# only (the utility masks both, and the test ORs the two masks)
GAP_COMMANDS += [
    "-size 70x46 " + images + " -metric " + metric +
    " -compare -precision 17 -print %[distortion]"
    for metric in ("AE", "DPC", "DSSIM", "Fuzz", "MAE", "MEPP", "MSE", "NCC", "PAE", "PDC",
                   "PHASE", "PHASH", "PSNR", "RMSE", "SSIM")
    for images in ("{C}/rose.miff -read-mask xc:gray(50%) {C}/rose_blur.miff",
                   "{C}/rose.miff ( {C}/rose_blur.miff -read-mask xc:gray(50%) )")]
# vision.c, fourth round: lines of both slopes and a tall rectangle, so every angle quadrant of the ellipse fit is taken
GAP_COMMANDS += [
    "-size 44x30 xc:black -fill white -stroke white -strokewidth 2 -draw 'line 2,2 15,12' -draw 'line 26,12 40,2' -stroke none -draw 'rectangle 18,14 21,28' -draw 'rectangle 26,20 40,23' -draw 'line 4,26 12,18' -precision 17 -define connected-components:verbose=true -define connected-components:angle-threshold=0-1000 -connected-components 8",
    "-size 44x30 xc:black -fill white -stroke white -strokewidth 2 -draw 'line 2,2 15,12' -draw 'line 26,12 40,2' -stroke none -draw 'rectangle 18,14 21,28' -draw 'rectangle 26,20 40,23' -draw 'line 4,26 12,18' -precision 17 -define connected-components:verbose=true -define connected-components:angle-threshold=0-1000 -connected-components 4",
    "-size 44x30 xc:black -fill white -stroke white -strokewidth 2 -draw 'line 2,2 15,12' -draw 'line 26,12 40,2' -stroke none -draw 'rectangle 18,14 21,28' -draw 'rectangle 26,20 40,23' -draw 'line 4,26 12,18' -precision 17 -define connected-components:verbose=true -define connected-components:sort=y -define connected-components:sort-order=decreasing -connected-components 8",
]
# layer.c, second round: frames at negative and oversized page offsets under each dispose method, -layers merge, mosaic and flatten with offsets, webp:mux-blend, and -layers composite with null: in each position
GAP_COMMANDS += [
    "-size 20x16 xc:none ( +clone -fill blue -draw \"rectangle 2,2 8,8\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 10,6 16,12\" ) ( -size 20x16 xc:none -fill red -draw \"rectangle 1,9 5,14\" ) ( -size 20x16 xc:none -fill red -draw \"rectangle 1,9 5,14\" -fill green -draw \"rectangle 12,1 18,4\" ) ( -size 20x16 xc:none ) -delete 0 -layers optimize-plus",
    "-size 20x16 xc:none ( +clone -fill blue -draw \"rectangle 2,2 8,8\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 10,6 16,12\" ) ( -size 20x16 xc:none -fill red -draw \"rectangle 1,9 5,14\" ) ( -size 20x16 xc:none -fill red -draw \"rectangle 1,9 5,14\" -fill green -draw \"rectangle 12,1 18,4\" ) ( -size 20x16 xc:none ) -delete 0 -layers optimize-plus -layers coalesce",
    "-size 20x16 xc:none ( +clone -fill blue -draw \"rectangle 12,8 18,14\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 1,1 6,5\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 0,0 19,15\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 0,0 3,3\" ) -delete 0 -layers optimize-plus",
    "-size 20x16 xc:none ( +clone -fill blue -draw \"rectangle 12,8 18,14\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 1,1 6,5\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 0,0 19,15\" ) ( -size 20x16 xc:none -fill blue -draw \"rectangle 0,0 3,3\" ) -delete 0 -layers remove-dups",
    "-dispose None -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 8x8 xc:#0000ff80 -repage 20x16+15+12 ) ( -size 30x30 xc:green -repage 20x16-5-5 ) -layers merge",
    "-dispose None -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 8x8 xc:#0000ff80 -repage 20x16+15+12 ) ( -size 30x30 xc:green -repage 20x16-5-5 ) -layers mosaic",
    "-dispose None -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 8x8 xc:#0000ff80 -repage 20x16+15+12 ) ( -size 30x30 xc:green -repage 20x16-5-5 ) -layers trim-bounds",
    "-dispose Background -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 8x8 xc:#0000ff80 -repage 20x16+15+12 ) ( -size 30x30 xc:green -repage 20x16-5-5 ) -layers coalesce",
    "-dispose Background -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 8x8 xc:#0000ff80 -repage 20x16+15+12 ) ( -size 30x30 xc:green -repage 20x16-5-5 ) -layers optimize-transparency",
    "-size 8x6 xc:red -set webp:mux-blend AtopBackgroundAlphaBlend ( -size 4x4 xc:#0000ff80 -set webp:mux-blend AtopBackgroundAlphaBlend -repage +1+1 ) -coalesce",
    "-size 8x6 xc:red -repage +3+2 ( -size 6x4 xc:blue -repage +5+4 ) ( -size 3x3 xc:green -repage +1+7 ) -layers merge",
    "-size 10x8 xc:red null: ( -size 4x4 xc:#ffff0080 -repage +2+2 ) ( -size 3x3 xc:white -repage +5+1 ) -layers composite",
    "-size 10x8 xc:red ( -size 10x8 xc:blue ) null: ( -size 4x4 xc:#ffff0080 -repage +2+2 ) ( -size 3x3 xc:white -repage +5+1 ) ( -size 2x2 xc:black -repage +1+5 ) -layers composite",
]
# transform.c, second round: trim:minSize under each gravity, chop, crop and shave at the edges and beyond, splice under each gravity, flip and transverse of a page offset
GAP_COMMANDS += [
    "{C}/rose.miff -bordercolor white -border 8 -repage +4+3 -define trim:minSize=200x200 -trim",
    "{C}/rose.miff -bordercolor white -border 8 -repage +4+3 -define trim:minSize=20x60 -gravity East -trim",
    "{C}/rose.miff -chop 10x5+70+46",
    "{C}/rose.miff -chop 30x20-5-3",
    "{C}/rose.miff -chop 20x10-20-10",
    "{C}/rose.miff -repage 100x80+10+5 -crop 40x30+50+40",
    "{C}/rose.miff -crop 3x2-2-3@ +repage -append",
    "{C}/rose.miff -crop 30x0 +repage -append",
    "{C}/rose.miff -crop 0x20 +repage -append",
    "{C}/rose.miff -repage 90x60+3+2 -flip",
    "{C}/rose.miff -repage 90x60+3+2 -transverse",
    "{C}/rose.miff -repage +3+2 -shave 5x4",
    "{C}/rose.miff -shave 35x10",
    "{C}/rose.miff -shave 10x23",
    "{C}/rose.miff -background blue -gravity NorthWest -splice 10x6",
    "{C}/rose.miff -background blue -gravity North -splice 10x6",
    "{C}/rose.miff -background blue -gravity West -splice 10x6",
    "{C}/rose.miff -background blue -gravity Center -splice 10x6",
    "{C}/rose.miff -background blue -gravity East -splice 10x6",
    "{C}/rose.miff -background blue -gravity South -splice 10x6",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity NorthWest -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity North -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 50,30 57,37\" -gravity North -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity West -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 50,30 57,37\" -gravity West -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity Center -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity East -define trim:minSize=21x15 -trim",
    "-size 60x40 xc:white -fill red -draw \"rectangle 25,15 32,22\" -gravity South -define trim:minSize=21x15 -trim",
    "{C}/rose.miff -repage 120x90+30+20 -crop 50x40+80+50",
    "{C}/rose.miff -crop 3x2+0-3@ +repage -append",
    "{C}/rose.miff -crop 25x20-3-2 -append",
]
# attribute.c, second round: trim:edges, Floyd-Steinberg depth on the alpha channel, -type on CMYK and palette images
GAP_COMMANDS += [
    "-size 30x20 xc:white -fill black -draw 'rectangle 0,0 4,19' -draw 'rectangle 25,0 29,19' -draw 'rectangle 0,0 29,3' -draw 'rectangle 0,16 29,19' -fill red -draw 'rectangle 12,8 16,11' -define trim:edges=north -trim",
    "{C}/rose_alpha.miff -define dither=FloydSteinberg -channel A -depth 2",
    "{C}/rose.miff -colorspace CMYK -type TrueColor",
    "{C}/rose.miff -colorspace CMYK -type TrueColorAlpha",
    "{C}/rose.miff -colors 16 -type TrueColor",
    "{C}/rose.miff -colors 16 -type TrueColorAlpha",
    "{C}/rose.miff -define dither=None -type PaletteBilevelAlpha",
]
# compress.c, second round: fax runs of 1792 pixels and more, which need an image wider than that
GAP_COMMANDS += [
    "-size 3000x6 xc:white -fill black -draw \"point 2900,1\" -draw \"line 0,3 1900,3\" -draw \"point 5,5\" -write fax:-",
]
# effect.c: -local-contrast on images large enough that its window is wider than one pixel, and -adaptive-sharpen on one channel, a gray image and a larger sigma
GAP_COMMANDS += [
    "{C}/rose.miff -adaptive-sharpen 5x2",
    "{C}/rose.miff -channel R -adaptive-sharpen 3x1",
    "{C}/gray16.miff -adaptive-sharpen 5x2",
    "{C}/rose.miff -resize 400x260! -local-contrast 20x40",
    "{C}/rose.miff -resize 120x500! -local-contrast 100x30",
]
# fourier.c: -complex over four images (two complex numbers) with and without complex:snr, and -fft -ift with and without the phase image
GAP_COMMANDS += [
    "{C}/rose.miff {C}/rose_blur.miff ( {C}/gray16.miff -resize 70x46! ) ( {C}/rose_patch.miff -resize 70x46! ) -complex add",
    "{C}/rose.miff {C}/rose_blur.miff ( {C}/gray16.miff -resize 70x46! ) ( {C}/rose_patch.miff -resize 70x46! ) -complex divide",
    "{C}/rose.miff {C}/rose_blur.miff ( {C}/gray16.miff -resize 70x46! ) ( {C}/rose_patch.miff -resize 70x46! ) -define complex:snr=0.25 -complex divide",
    "{C}/rose.miff -fft -ift",
    "{C}/rose.miff -fft +delete -ift",
]
# list.c: reversed clone ranges, frames:step, and a swap with negative indexes
GAP_COMMANDS += [
    "{C}/seq.miff ( -clone -1-0 ) -append",
    "{C}/seq.miff -swap -1,-5 -append",
    "{C}/seq.miff -define frames:step=2 ( -clone 0-4 ) -append",
]
# fourier.c, list.c (ERDC's runs): -ift on two images, which reaches the FFTW stub of
# InverseFourierTransformImage (the oracle builds without FFTW, so -fft never makes
# the pair); -delete of a range ending at 0; -insert at index 0 (PrependImageToList)
GAP_COMMANDS += [
    "{C}/rose.miff {C}/rose_blur.miff -ift",
    "{C}/seq.miff -delete 0-0 -append",
    "{C}/seq.miff -delete 2-0 -append",
    "{C}/seq.miff {C}/rose.miff -insert 0 -append",
]
# geometry.c (ERDC's runs): the separators x, X, the multiplication sign and ':'
# (aspect ratios, also under -gravity), the resize flags ^ < @ with one side only,
# five values with spaces and negative signs (cmyka colours, -colorize in CMYK),
# page sizes with % and >, scene lists, -affine with seven values, and geometries of
# exactly MagickPathExtent-1 characters, which both parsers reject
GAP_COMMANDS += [
    "{C}/rose.miff -resize 30×20",
    "{C}/rose.miff -resize 30X20",
    "{C}/rose.miff -gravity center -crop 16:9 +repage",
    "{C}/rose.miff -gravity center -crop 1:2 +repage",
    "{C}/rose.miff -gravity center -crop 16:9^ +repage",
    "{C}/rose.miff -gravity center -extent 1:1",
    "{C}/rose.miff -resize 2:1",
    "{C}/rose.miff -resize 1:3",
    "{C}/rose.miff -resize 40^",
    "{C}/rose.miff -resize x40^",
    "{C}/rose.miff -resize 200x200<",
    "{C}/rose.miff -resize 120x20<",
    "{C}/rose.miff -resize 500@",
    "{C}/rose.miff -resize 50000@",
    "-size 4x3 xc:cmyka(10%,20%,30%,40%,0.5)",
    "-size 4x3 xc:cmyka(10%,20%,30%,40%,-0.25)",
    "-size 4x3 'xc:cmyka( 10% , 20% , 30% , 40% , 0.5 )'",
    "-size 4x3 xc:cmyka(10%,20%,30%,-40%,0.5)",
    "{C}/rose.miff -colorspace cmyk -fill red -colorize 10,20,30,40,50",
    "{C}/rose.miff -page 50%",
    "{C}/rose.miff -page 300x200>",
    "{C}/seq.miff[0,2] -append",
    "{C}/seq.miff[99999999999999999999] -append",
    "-size 30x20 xc:white -affine 1,0.3,0,1,0,0 -draw 'rectangle 2,2 10,8'",
    "-size 30x20 xc:white -affine 1,0.3,0,1,2,3,4 -draw 'rectangle 2,2 10,8'",
    "{C}/rose.miff -resize " + "0" * 4093 + "10",
    "{C}/rose.miff -blur " + "0" * 4093 + "x2",
]
# image.c (ERDC's runs): settings given before a read (-extract, -density with two values,
# -delay with > < and x), chromaticity and unit settings synced before an operator,
# -repage with offsets, appends of images that differ in depth, type and colorspace
# (bilevel too), +smush over transparent columns, scene ranges, raw RGB by extension
GAP_COMMANDS += [
    "-extract 30x20+5+3 {C}/rose.miff",
    "-extract 30x20 {C}/rose.miff",
    "-density 150x75 {C}/rose.miff",
    "-density 150 {C}/rose.miff",
    "-delay 5> {C}/seq.miff",
    "-delay 500< {C}/seq.miff",
    "-delay 20x50 {C}/seq.miff",
    "{C}/rose.miff -blue-primary 0.15,0.06 -green-primary 0.3,0.6 -red-primary 0.64,0.33 "
    "-white-point 0.3127,0.329 -resize 50%",
    "{C}/rose.miff -blue-primary 0.15 -green-primary 0.3 -red-primary 0.64 -white-point 0.31 "
    "-resize 50%",
    "{C}/rose.miff -density 300 -units PixelsPerInch -resize 50% -units PixelsPerCentimeter "
    "-resize 50%",
    "{C}/rose.miff -density 100 -units PixelsPerCentimeter -resize 50% -units PixelsPerInch "
    "-resize 50%",
    "{C}/rose.miff -repage +5+3",
    "{C}/rose.miff -repage 100x80-4+6",
    "{C}/rose.miff {C}/gray16.miff -append",
    "{C}/rose.miff ( {C}/rose.miff -colorspace cmyk ) -append",
    "{C}/bilevel.miff {C}/bilevel.miff -append",
    "{C}/rose.miff {C}/gray16.miff +append",
    "{C}/rose_alpha.miff {C}/rose_alpha.miff +smush 3",
    "{C}/rose_alpha.miff {C}/rose_alpha.miff +smush -5",
    "{C}/seq.miff[3-1] -append",
    "{C}/seq.miff[1-99] -append",
]
GAP_STEP_CASES += [
    ("filename patterns %d %03d %x %o %% %5d and malformed ones, written and read back",
     [["{C}/seq.miff", "-scene", "9", "a%d.miff"], ["{C}/seq.miff", "-scene", "9", "b%03d.miff"],
      ["{C}/seq.miff", "-scene", "9", "c%x.miff"], ["{C}/seq.miff", "-scene", "9", "d%o.miff"],
      ["{C}/seq.miff", "-scene", "9", "e%%d.miff"], ["{C}/seq.miff", "-scene", "9", "h%5d.miff"],
      ["{C}/seq.miff", "-scene", "9", "k%00d.miff"], ["{C}/seq.miff", "-scene", "9", "m%q.miff"],
      ["{C}/seq.miff", "-set", "filename:t", "z", "g%[filename:t].miff"],
      ["-define", "filename:literal=true", "e%d.miff", "k%00d-9.miff", "m%q-9.miff", "+append",
       "lit.miff"],
      ["a9.miff", "b013.miff", "cd.miff", "d11.miff", "h   12.miff", "gz.miff", "lit.miff",
       "-append", "out.miff"]], {}),
    ("raw rgb chosen by extension", [["{C}/rose.miff", "-depth", "8", "x.rgb"],
                                     ["-size", "70x46", "-depth", "8", "x.rgb", "out.miff"]], {}),
    ("jpeg sampling factor through a cloned image_info",
     [["-sampling-factor", "2x1", "{C}/rose.miff", "x.jpg"], ["x.jpg", "out.miff"]], {}),
]
# enhance.c, threshold.c (statement deletion): -modulate under each modulate:colorspace on a
# palette image, whose colormap is modulated on its own; -color-threshold on images in each
# colour space ColorThresholdImage converts its start and stop colours into
GAP_CASES += [("palette modulate:colorspace=%s" % cs, ["-define", "modulate:colorspace=" + cs,
                                                       "-modulate", "110/100/95"], ["palette"])
              for cs in ("HCL", "HCLp", "HSB", "HSI", "HSV", "HWB", "LCHab", "LCHuv")]
GAP_COMMANDS += ["{C}/rose.miff -colorspace %s -color-threshold 'sRGB(10,20,30)-sRGB(200,210,220)'"
                 % cs for cs in ("HCL", "HSB", "HSL", "HSV", "HWB", "Lab")]
# ranges that select pixels in each model: every converted component of the start colour
# below the stop colour's, so a start colour left unconverted (far above any pixel) shows
GAP_COMMANDS += ["{C}/rose.miff -colorspace %s -color-threshold '%s'" % cs_range for cs_range in (
    ("HCL", "sRGB(60,20,20)-sRGB(255,0,200)"), ("HSB", "sRGB(60,20,20)-sRGB(255,0,200)"),
    ("HSL", "sRGB(60,20,20)-sRGB(255,0,200)"), ("HSV", "sRGB(60,20,20)-sRGB(255,0,200)"),
    ("Lab", "sRGB(10,40,10)-sRGB(255,140,40)"))]  # no HWB range tried selected any pixel
# compress.c (statement deletion): a fax read back and resized, so the decoded pixels'
# colours are read, not only their colormap indexes
GAP_STEP_CASES += [("fax read back and resized",
                    [["{C}/bilevel.miff", "b.fax"], ["fax:b.fax", "-resize", "50%", "out.miff"]], {})]
# identify.c: pixel locations (identify:locate, identify:limit) on RGB, CMYK, gray and alpha
# images, a 16-bit image under -verbose, masks and a meta channel in verbose info, and an
# image read smaller than stored (jpeg:size), which plain identify prints as WxH=>
GAP_COMMANDS += [
    "identify -define identify:locate=maximum -define identify:limit=2 {C}/rose.miff",
    "identify -define identify:locate=minimum {C}/cmyk.miff",
    "identify -define identify:locate=mean {C}/gray16.miff",
    "identify -define identify:locate=maximum {C}/rose_alpha.miff",
    "identify -verbose {C}/gray16.miff",
    "{C}/rose.miff -channel-fx 'red=>meta' -verbose -write info: +verbose",
    "{C}/rose.miff -read-mask {C}/bilevel.miff -verbose -write info: +verbose",
    "{C}/rose.miff -write-mask {C}/bilevel.miff -verbose -write info: +verbose",
]
# cipher.c: passphrases of 48 and 64 characters, whose second halves are 24- and 32-byte
# keys, exactly the 192- and 256-bit sizes SetAESKey chooses between (the catalogue's
# passphrase gives 18 bytes, so only the 128-bit schedule ran)
GAP_STEP_CASES += [
    ("image read smaller than stored, identified",
     [["{C}/rose.miff", "x.jpg"], ["identify", "-define", "jpeg:size=20x13", "x.jpg"]], {}),
    ("encipher with a 192-bit key", [["{C}/rose.miff", "-encipher", "pass.txt", "out.miff"]],
     {"pass.txt": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL"}),
    ("encipher with a 256-bit key", [["{C}/rose.miff", "-encipher", "pass.txt", "out.miff"]],
     {"pass.txt": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ!?"}),
    ("encipher with a 184-bit key", [["{C}/rose.miff", "-encipher", "pass.txt", "out.miff"]],
     {"pass.txt": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ"}),
]
# compare.c, visual-effects.c, resize.c, channel.c: -metric PHASH per channel; subimage
# searches with a metric where higher is better (NCC) and with similarity and
# dissimilarity thresholds; -polaroid with a caption set as a property (the -caption
# setting is not what PolaroidImage reads), under a gravity; -thumbnail of an image
# with an ICC profile, which a thumbnail keeps; semi-transparent backgrounds for
# -alpha remove and background, through FlattenPixelInfo
GAP_COMMANDS += [
    "compare -metric PHASH -verbose -precision 17 {C}/rose.miff {C}/rose_blur.miff",
    "compare -metric NCC -subimage-search {C}/rose.miff ( {C}/rose.miff -crop 20x20+10+10 +repage )",
    "compare -metric RMSE -subimage-search -similarity-threshold 0.5 {C}/rose.miff "
    "( {C}/rose.miff -crop 20x20+10+10 +repage )",
    "compare -metric NCC -subimage-search -similarity-threshold 0.5 {C}/rose.miff "
    "( {C}/rose.miff -crop 20x20+10+10 +repage )",
    "compare -metric RMSE -subimage-search -dissimilarity-threshold 0.01 {C}/rose.miff "
    "( {C}/rose_blur.miff -crop 20x20+10+10 +repage )",
    "{C}/rose.miff -font {C}/Generic.ttf -set caption 'A rose' -polaroid 5",
    "{C}/rose.miff -font {C}/Generic.ttf -gravity south -set caption 'A rose' -polaroid 5",
    _UHDR_JPG + " -thumbnail 30x20",
    "{C}/rose_alpha.miff -background 'rgba(255,0,0,0.5)' -alpha remove",
    "{C}/rose_alpha.miff -background 'rgba(255,0,0,0.5)' -alpha background",
]
# statistic.c: a single-colour image, whose one histogram bin makes MagickSafeReciprocalLD
# take 0 (log2 of one bin) when the entropy is computed
GAP_COMMANDS += ["identify -verbose -precision 17 -size 4x4 xc:red"]
# string.c: a label with a control character, which StringToStrings lays out as a hex dump;
# IsStringFalse's false, off, no and 0 through exif:sync-image, on a JPEG whose EXIF block
# is rewritten with an orientation (read back as Undefined when the define is false)
GAP_COMMANDS += ["-font {C}/Generic.ttf -pointsize 8 label:'A\x01B'"]  # label: measures through StringToStrings
# compare.c: a PHASH subimage search (GetPHASHSimilarity serves only the search), against an
# exact patch and a blurred one, whose best match is not perfect
GAP_COMMANDS += [
    "compare -metric PHASH -subimage-search {C}/rose.miff ( {C}/rose.miff -crop 20x20+10+10 +repage )",
    "compare -metric PHASH -subimage-search {C}/rose.miff ( {C}/rose_blur.miff -crop 20x20+30+20 +repage )",
    "compare -metric RMSE -subimage-search {C}/rose.miff ( {C}/rose_blur.miff -crop 20x20+30+20 +repage )",
]
# identify.c, second round: locations and moments on a Lab image (the default branches of
# the colourspace switches; features on Lab take minutes, so they are left out), the convex
# hull, a montage's tile directory, a property longer than 80 characters
GAP_COMMANDS += [
    "{C}/rose.miff -colorspace Lab -define identify:locate=maximum -write info: +define identify:locate",
    "{C}/rose.miff -colorspace Lab -define identify:moments=true -verbose -write info: +verbose",
    "{C}/rose.miff -define identify:convex-hull=true -verbose -write info: +verbose",
    "{C}/rose.miff -set comment " + "7" * 100 + " -verbose -write info: +verbose",
]
# draw.c: square line caps (TraceSquareLinecap), and an image primitive under an affine
# transform and a rotation (DrawAffineImage, AffineEdge, InverseAffineMatrix). Gradients'
# reflect and repeat spreads are API-only (gradient: always pads, MVG has no spread), and
# draw:render-bounding-rectangles aborts (exit 134), so neither has a case
GAP_COMMANDS += [
    "-size 60x40 xc:white -stroke blue -strokewidth 6 -draw 'stroke-linecap square line 10,10 50,30'",
    "-size 80x60 xc:white -draw \"affine 1,0.3,0,1,0,0 image over 5,5 40,30 '{C}/rose.miff'\"",
    "-size 80x60 xc:white -draw \"rotate 20 image over 10,5 40,30 '{C}/rose.miff'\"",
]
# property.c: the profile property readers, which no case asked for: every EXIF property
# and named tags of a JPEG whose EXIF block was rewritten, the ICC properties, an IPTC
# dataset and 8BIM resources of the JPEG with those profiles, and XMP values (read by tag
# name once %[xmp:...] has parsed them; only the element form yields values)
GAP_COMMANDS += [
    "identify -format '%[icc:*]' " + _UHDR_JPG,
    "identify -format '%[IPTC:2:120]|%[8BIM:1028,1028]|%[8BIM:1000,2000]|%[8BIM:*]' " + _UHDR_JPG,
]
GAP_STEP_CASES += [
    ("exif properties of a JPEG, all and by name",
     [["{C}/rose.miff", "-profile", "APP1:exif.bin", "-density", "300", "-orient", "BottomLeft",
       "x.jpg"],
      ["identify", "-format", "%[exif:*]%[exif:Orientation]|%[exif:XResolution]|%[exif:Bogus]\\n",
       "x.jpg"]], {"exif.bin": EXIF_BLOCK}),
    ("xmp properties, element and attribute forms",
     [["{C}/rose.miff", "-profile", "e.xmp", "xe.miff"], ["{C}/rose.miff", "-profile", "a.xmp", "xa.miff"],
      ["identify", "-format", "%[xmp:load][%[tiff:Orientation]][%[tiff:XResolution]]\\n", "xe.miff",
       "xa.miff"]], {"e.xmp": XMP_ELEMENTS, "a.xmp": XMP_ATTRIBUTES}),
]
# channel.c: +combine at the channel-count boundaries of each target colour space (sRGB
# with a meta channel, gray with alpha and a meta channel, CMYK with alpha and a meta
# channel), an undefined target (the gamma test), images of different widths;
# identify.c: minimum locations on an image with no zero-valued pixel
GAP_COMMANDS += [
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff -combine",
    "{C}/gray8.miff {C}/gray8.miff +combine gray",
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff +combine gray",
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff +combine cmyk",
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff {C}/gray8.miff +combine cmyk",
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff +combine undefined",
    "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff -set gamma 1.0 +combine undefined",
    "{C}/wide.miff {C}/gray8.miff {C}/gray8.miff -combine",
    "identify -define identify:locate=minimum {C}/rose.miff",
]
# attribute.c: a uniform border, so the corner pixels decide the background, under a
# virtual-pixel method other than Edge, so a corner read one pixel too far would differ
GAP_COMMANDS += [
    "{C}/rose.miff -bordercolor white -border 5 -virtual-pixel Black -trim +repage",
    "{C}/rose.miff -bordercolor white -border 5 -virtual-pixel Black -set bbox %@ "
    "-define trim:edges=north,east -trim +repage",
]
# transform.c: crops on a virtual canvas with negative and positive offsets, crops that run
# off the image or start exactly at its edge, tile crops (@) with negative and positive
# offsets
GAP_COMMANDS += [
    "{C}/rose.miff -repage 100x80-10-5 -crop 30x20+0+0",
    "{C}/rose.miff -repage 100x80+10+5 -crop 40x30+60+40",
    "{C}/rose.miff -crop 3x2-4-3@ +repage -append",
    "{C}/rose.miff -crop 3x2+4+3@ +repage -append",
    "{C}/rose.miff -crop 20x20+65+40",
    "{C}/rose.miff -crop 20x20+70+0",
    "{C}/rose.miff -repage 0x0+5+5 -crop 10x10+0+0",
]
# layer.c: frames lying partly off the canvas (a negative offset, and one past the right
# and bottom edges) under coalesce, dispose (first frame off-canvas: DisposeImages only
# reads the first frame's offsets) and optimize-transparency; -layers composite with
# compose:clip-to-self=false
GAP_COMMANDS += [
    "-dispose Background -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) "
    "( -size 8x8 xc:green -repage 20x16+15+12 ) -layers coalesce",
    "-dispose Background ( -size 8x8 xc:blue -repage 20x16-3-2 ) ( -size 20x16 xc:red ) "
    "( -size 8x8 xc:green -repage 20x16+15+12 ) -layers dispose",
    "-dispose Previous -size 20x16 xc:red ( -size 8x8 xc:blue -repage 20x16-3-2 ) "
    "( -size 8x8 xc:green -repage 20x16+15+12 ) -layers optimize-transparency",
    "-size 20x16 xc:red ( -size 8x8 xc:blue -repage +15+12 ) null: ( -size 20x16 xc:yellow ) "
    "-define compose:clip-to-self=false -layers composite",
]
# colormap.c: PALM files below 8 bits per pixel written to the compared output itself,
# so the colormap SortColormapByIntensity orders is in the bytes (read back, any order
# decodes to the same pixels)
# compare.c: phash:normalize, which GetPHASHSimilarity's per-channel square roots need
GAP_COMMANDS += ["compare -metric PHASH -define phash:normalize=true -verbose -precision 17 "
                 "{C}/rose.miff {C}/rose_blur.miff"]
GAP_STEP_CASES += [
    ("palm at 4 bits, the file itself", [["{C}/palette.miff", "-colors", "12", "palm:out.miff"]], {}),
    ("palm at 2 bits, the file itself", [["{C}/gray8.miff", "-colors", "4", "palm:out.miff"]], {}),
]
# draw.c: an MVG file with every keyword no case used: named classes and macros
# (push class "x", push graphic-context "x", class, use), a named mask, a symbol, scale,
# the clip, compliance, density and encoding settings, the antialias switches, and the
# font and text settings (stretch, style, weight, direction, spacings, kerning, align, anchor)
_MVG_ALL_KEYWORDS = """viewbox 0 0 120 80
push defs
  push class "warm"
    fill orange stroke brown stroke-width 2
  pop class
  push graphic-context "blob"
    circle 10,10 10,16
  pop graphic-context
  push mask "m1"
    fill white rectangle 0,0 60,80
  pop mask
pop defs
push symbol
  rectangle 0,0 5,5
pop symbol
push graphic-context
  border-color red
  clip-rule evenodd
  clip-units userSpaceOnUse
  compliance SVG
  density 72
  encoding UTF-8
  stroke-antialias false
  text-antialias false
  scale 1.1,0.9
  class "warm"
  rectangle 5,5 40,30
  use "blob"
  font '{C}/Generic.ttf'
  font-stretch condensed
  font-style italic
  font-weight bold
  direction right-to-left
  interline-spacing 2
  interword-spacing 3
  kerning 1
  letter-spacing 1
  text-align center
  text-anchor middle
  fill navy
  text 60,60 'Ab cd'
pop graphic-context
"""
GAP_STEP_CASES += [("mvg with every keyword no case used",
                    [["-size", "120x80", "xc:white", "-draw", "@all.mvg", "out.miff"]],
                    {"all.mvg": _MVG_ALL_KEYWORDS})]
# draw.c: stroke joins on a polyline that turns both ways along horizontal and vertical
# segments, and on a closed acute triangle, under each join with miter limits of 1 and 10
# (TraceStrokePolygon's left and right turns, axis-aligned slopes, closed paths)
GAP_COMMANDS += ["-size 60x50 xc:white -fill none -stroke navy -strokewidth 5 -draw "
                 "\"stroke-linejoin %s stroke-miterlimit %d polyline 10,10 50,10 50,40 20,40 20,20 35,25 "
                 "path 'M 10,45 L 30,5 L 50,45 Z'\"" % (join, limit)
                 for join in ("miter", "round", "bevel") for limit in (1, 10)]
# draw.c: dash offsets in the same graphic context as the pattern (the catalogue set the
# offset in a separate -draw, so it never applied), inside the first dash, past it and past
# the whole pattern, and a pattern of odd length (a zero entry is rejected as nonconforming)
GAP_COMMANDS += ["-size 60x40 xc:white -fill none -stroke black -strokewidth 2 -draw "
                 "'%s polyline 5,5 55,5 55,35 5,35'" % dash for dash in (
                     "stroke-dasharray 6 3", "stroke-dasharray 6 3 stroke-dashoffset 2",
                     "stroke-dasharray 6 3 stroke-dashoffset 8", "stroke-dasharray 6 3 stroke-dashoffset 20",
                     "stroke-dasharray 5 2 1")]
# draw.c: the alpha primitive's methods (only floodfill had a case), a single-point path,
# and a numeric font weight (GetDrawInfo's fallback when the weight is not a name)
GAP_COMMANDS += ["{C}/rose.miff -fill '#ff000080' -draw 'alpha 10,10 %s'" % method
                 for method in ("point", "replace", "filltoborder", "reset")]
GAP_COMMANDS += [
    "{C}/rose_alpha.miff -fill '#ff000080' -draw 'path \"M 10,10 Z\"'",
    "-size 80x30 xc:white -font {C}/Generic.ttf -weight 650 -pointsize 14 -annotate +5+20 Ab",
]
# draw.c: degenerate primitives whose polygon has no edges (DrawPolygonPrimitive draws a
# point), and the settings GetDrawInfo copies from the command line, which reach it only
# through a draw info made afresh, as label: and caption: make them (-draw's comes from
# the command line directly)
GAP_COMMANDS += ["{C}/rose.miff -fill red -stroke none -draw '%s'" % primitive for primitive in (
    "line 10,10 10,10", "polygon 10,10 10,10 10,10", "polyline 10,10 10,10", 'path "M 10,10 L 10,10"')]
GAP_COMMANDS += [
    "-font {C}/Generic.ttf -pointsize 14 -kerning 2 -interword-spacing 6 -stroke red -strokewidth 1 "
    "-undercolor yellow -style italic -weight bold label:'Ab cd'",
    "-font {C}/Generic.ttf -pointsize 14 -weight 650 -density 150 label:'Ab cd'",
    "-font {C}/Generic.ttf -pointsize 14 -word-break break-all -size 40x caption:'Abcdefgh ijk'",
]
# property.c: the property names GetMagickProperty knows that no case printed (some are
# unknown for one image and known for the other), and the properties SetImageProperty maps
# onto image fields, which -set had never set
_PROPERTY_FORMAT = "%[bounding-box]|%[convex-hull:extreme-points]|%[height]|%[interlace]|%[mime:type]|%[page]|%[profile:icm]|%[printsize.x]|%[printsize.y]|%[profiles]|%[quality]|%[width]\\n"
GAP_COMMANDS += ["identify -format '" + _PROPERTY_FORMAT + "' {C}/rose.miff",
                 "identify -format '" + _PROPERTY_FORMAT + "' " + _UHDR_JPG]
GAP_COMMANDS += ["{C}/rose.miff -set compose Over -set compress Zip -set delay 20x50 -set density 150x100 "
                 "-set dispose Background -set gravity Center -set intensity Rec709Luma -set intent Perceptual "
                 "-set interpolate Bilinear -set kurtosis 1 -set opaque true -set rendering-intent Saturation "
                 "-set type TrueColor -set units PixelsPerInch"]
# property.c: InterpretImageProperties' rarer paths: a format read from a file with CRLF
# lines, the &lt; &gt; &amp; entities, globs over options, artifacts and properties (not
# date:*, whose date:timestamp is the time of the run), a backslash inside %[...], and a
# name longer than the 64-character pattern buffer
GAP_COMMANDS += [
    "identify -define case:one=1 -define case:two=2 -format '%[option:case:*]|' {C}/rose.miff",
    "{C}/rose.miff -define art:x=7 -format '%[artifact:art:*]|' -write info: +define art:x",
    "identify -format '&lt;%w&gt; &amp; %h\\n' {C}/rose.miff",
    "{C}/rose.miff -set case:a 1 -set case:b 2 -format '%[case:*]|' -write info:",
    "identify -format '%[fx:w\\*2]|%[" + "a" * 70 + "]\\n' {C}/rose.miff",
]
GAP_STEP_CASES += [("format read from a file with CRLF lines",
                    [["identify", "-format", "@fmt.txt", "{C}/rose.miff"]],
                    {"fmt.txt": "%wx%h\r\n%[case:a]\r\n"})]
# image.c: smush gaps, which count only fully transparent pixels (rose_alpha has none at its
# edges, so the gap was always 0): transparent margins, and triangles whose margins vary
# from row to row, so the gap is the minimum over rows, across and down
GAP_COMMANDS += [
    "( {C}/rose.miff -bordercolor none -border 6x0 ) ( {C}/rose.miff -bordercolor none -border 4x0 ) +smush 2",
    "( {C}/rose.miff -bordercolor none -border 0x6 ) ( {C}/rose.miff -bordercolor none -border 0x4 ) -smush 2",
    "( -size 30x20 xc:none -fill red -draw 'polygon 0,0 24,10 0,19' ) "
    "( -size 30x20 xc:none -fill blue -draw 'polygon 29,0 5,10 29,19' ) +smush 0",
    "( -size 20x30 xc:none -fill red -draw 'polygon 0,0 10,24 19,0' ) "
    "( -size 20x30 xc:none -fill blue -draw 'polygon 0,29 10,5 19,29' ) -smush 0",
]
# image.c: AcquireImage's settings and default colours on images no reader overwrites
# (the MIFF reader sets delay, density and the colours from its header, so the -delay and
# -density cases on MIFF files could not show them): xc: images with -delay x, > and <,
# -density with two values, and operators that use the default background, border and
# matte colours
GAP_COMMANDS += [
    "-delay 20x50 -size 8x8 xc:red",
    "-delay 5> -size 8x8 xc:red",
    "-delay 500< -size 8x8 xc:red",
    "-density 150x75 -size 8x8 xc:red",
    "-size 20x20 xc:red -rotate 30",
    "-size 20x20 xc:red -border 2",
    "-size 20x20 xc:red -frame 3",
]
# string.c: StringToArgv's quoted arguments, through an @list of files with double-quoted,
# single-quoted and bare names (the catalogue's list quotes nothing), and a font family
# list with a quoted name that the case's type.xml defines
GAP_STEP_CASES += [
    ("@list of files with quoted names",
     [["@list.txt", "-append", "out.miff"]],
     {"list.txt": '"{C}/rose.miff" \'{C}/granite.miff\' {C}/rose_blur.miff\n'}),
    ("a font family list with a quoted name",
     [["-family", '"Case Missing", CaseFamily', "-pointsize", "12", "label:Ab", "out.miff"]],
     _TYPE_FILES),
]
# string.c: CopyMagickString's return value, which the HDR writer uses as its header lengths;
# the round trips compare the decoded image, so the file itself is the output here
GAP_STEP_CASES += [("hdr file itself", [["{C}/rose.miff", "hdr:out.miff"]], {})]
# utility.c: ExpandFilenames' full path, which only runs when an argument holds a wildcard:
# globs with options that take values before and after them (whose values it copies),
# a dotted name read with a subimage spec, and an explicit format prefix with a directory
GAP_STEP_CASES += [
    ("glob among options with values",
     [["{C}/seq.miff", "f%d.miff"], ["-define", "case:x=1", "f*.miff", "-resize", "50%", "-append", "out.miff"]], {}),
    ("glob range among options with values",
     [["{C}/seq.miff", "f%d.miff"], ["-define", "case:x=1", "f[0-2].miff", "-resize", "50%", "+append", "out.miff"]], {}),
    ("dotted name with a subimage spec",
     [["{C}/rose.miff", "a.b.c.miff"], ["a.b.c.miff[0]", "out.miff"]], {}),
    ("format prefix with a directory",
     [["{C}/rose.miff", "miff:sub.d/x.y"], ["miff:sub.d/x.y", "out.miff"]], {"sub.d/keep.txt": "kept\n"}),
]
# draw.c: shapes aligned exactly with pixel centres, so GetFillAlpha's real-valued
# distances come out exactly 0 or 1 at some pixels, where its < and <= differ
GAP_COMMANDS += ["-size 40x30 xc:white -fill navy -stroke %s -draw '%s'" % (stroke, shape)
                 for stroke, shape in (
                     ("none", "rectangle 10.5,10.5 30.5,20.5"), ("none", "rectangle 10,10 30,20"),
                     ("none", "circle 20,15 20,25"), ("red -strokewidth 1", "line 5.5,5 5.5,25"),
                     ("red -strokewidth 1", "line 5,5.5 35,5.5"), ("red -strokewidth 2", "rectangle 10.5,10.5 30.5,20.5"),
                     ("none +antialias", "polygon 10.5,10.5 30.5,10.5 20.5,25.5"))]
# image.c: SyncImageSettings with chromaticity points other than sRGB's own (the earlier case
# used sRGB's values, which the image already had), with one value and with two; unit
# conversions on images whose resolution comes from the file, with -units but no -density
# (a -density option sets the resolution again after the conversion); -background on an
# image that carries its own
GAP_COMMANDS += [
    "{C}/rose.miff -blue-primary 0.2,0.1 -green-primary 0.25,0.65 -red-primary 0.6,0.3 "
    "-white-point 0.32,0.34 -resize 50%",
    "{C}/rose.miff -blue-primary 0.2 -green-primary 0.25 -red-primary 0.6 -white-point 0.32 -resize 50%",
    "{C}/rose.miff -background red -rotate 15",
]
GAP_STEP_CASES += [
    ("resolution in inches converted to centimetres",
     [["{C}/rose.miff", "-density", "300", "-units", "PixelsPerInch", "x.miff"],
      ["x.miff", "-units", "PixelsPerCentimeter", "-resize", "50%", "out.miff"]], {}),
    ("resolution in centimetres converted to inches",
     [["{C}/rose.miff", "-density", "100", "-units", "PixelsPerCentimeter", "x.miff"],
      ["x.miff", "-units", "PixelsPerInch", "-resize", "50%", "out.miff"]], {}),
]
# image.c: a filename pattern %[name] filled from a -define (InterpretImageFilename looks
# up the image's properties, then artifacts, then the options; the earlier case used -set,
# a property). property.c: an EXIF block with text tags (Make, Model, Software, Artist; the
# catalogue's block holds only numbers), read back whole, by name and by tag number
def _exif_text_block():
    entries = [(0x010F, 2, b"CaseMake\0"), (0x0110, 2, b"M1\0"), (0x0131, 2, b"Oracle\0"),
               (0x013B, 2, b"A\0"), (0x0213, 3, struct.pack("<H", 1))]
    data_at = 8 + 2 + 12 * len(entries) + 4
    ifd, data = struct.pack("<H", len(entries)), b""
    for tag, kind, value in entries:
        count = len(value) if kind == 2 else 1
        if len(value) <= 4:
            ifd += struct.pack("<HHI", tag, kind, count) + value.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, kind, count, data_at + len(data))
            data += value
    block = b"Exif\0\0II*\0" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + data
    assert max(block) < 128  # case files are text
    return block.decode("latin-1")


GAP_STEP_CASES += [
    ("filename pattern filled from a -define",
     [["{C}/rose.miff", "-define", "case:t=zz", "g%[case:t].miff"], ["gzz.miff", "out.miff"]], {}),
    ("exif text tags, whole, by name and by tag number",
     [["{C}/rose.miff", "-profile", "APP1:exif.bin", "x.jpg"],
      ["identify", "-format", "%[exif:*]|%[exif:#010F]|%[exif:#010f]|%[exif:@010F]|%[exif:Make]\\n",
       "x.jpg"]], {"exif.bin": _exif_text_block()}),
]
# The image's depth, class and type, printed before the floating-point write: every _op
# case writes with FLOAT_OUT (-depth 32), which overwrites the depth an operator set, so no
# case could see it (AppendImages' depth, -depth, -type, -colors, -monochrome, -separate,
# -combine, and GetImageDepth and SetImageDepth behind them)
_DEPTH_FORMAT = "-format '%z %r %[type]\\n' -write info:"
GAP_COMMANDS += [cmd + " " + _DEPTH_FORMAT for cmd in (
    "{C}/rose.miff {C}/gray16.miff -append", "{C}/gray16.miff {C}/rose.miff +append",
    "{C}/bilevel.miff {C}/bilevel.miff -append", "{C}/rose.miff -depth 4",
    "{C}/rose.miff -type Palette", "{C}/rose.miff -colors 8", "{C}/rose.miff -monochrome",
    "{C}/rose.miff -separate", "{C}/gray8.miff {C}/gray8.miff {C}/gray8.miff -combine",
    "{C}/rose.miff -type GrayscaleAlpha", "{C}/rose.miff -type TrueColorAlpha")]
# attribute.c: SetImageDepth's and GetImageDepth's colormap paths, which quantize a palette
# image's colormap channel by channel under the channel mask
GAP_COMMANDS += ["{C}/palette.miff " + ops for ops in (
    "-depth 4", "-channel R -depth 2 +channel", "-channel RG -depth 3 +channel")]
GAP_COMMANDS += ["identify -verbose -channel R {C}/palette.miff"]
# attribute.c: IsImageOpaque scans pixels only when the image has an alpha channel: %[opaque]
# on an image with transparency and on one whose added alpha channel is fully opaque
GAP_COMMANDS += ["identify -format '%[opaque]\\n' {C}/rose_alpha.miff",
                 "{C}/rose.miff -alpha set -format '%[opaque]\\n' -write info:"]
# attribute.c: GetImageQuantumDepth rounds a depth of 33 to 64 up to 64 and leaves one
# above 64 alone; the FITS writer asks for it unconstrained and writes it as BITPIX
GAP_STEP_CASES += [("-depth %d written as FITS" % depth,
                    [["{C}/rose.miff", "-depth", str(depth), "fits:out.miff"]], {})
                   for depth in (48, 65)]
# attribute.c: SetImageDepth on a palette image with an alpha channel scales the
# colormap's alpha too; -cycle copies the colormap back into the pixels
GAP_COMMANDS += ["{C}/rose_alpha.miff -colors 16 -depth 2 -write histogram:info:- -alpha extract"]
GAP_COMMANDS += ["{C}/rose_alpha.miff -colors 16 -depth 2 -cycle %d" % n for n in (0, 1)]
# attribute.c: GetImageBoundingBox reads the four corners as the background to trim; on a
# bordered image under a black virtual pixel a corner read from outside the image differs,
# and an image whose one corner differs from the rest drives the corner rule
_BBOX = " -format '%@\\n' -write info: -trim"
GAP_COMMANDS += ["{C}/rose.miff -bordercolor white -border 5 -virtual-pixel black" + _BBOX]
GAP_COMMANDS += ["-size 12x10 xc:white -fill %s -draw 'point %s' -fill black "
                 "-draw 'rectangle 4,3 7,6'" % corner + _BBOX
                 for corner in (("lime", "11,9"), ("red", "11,0"), ("blue", "0,9"))]
# a 2x4 image whose bottom-left pixel is the only one of its colour: a lower row may not
# shrink the box's height again
GAP_COMMANDS += ["-size 1x1 ( xc:white xc:red +append ) ( xc:blue xc:red +append ) "
                 "( xc:white xc:red +append ) ( xc:white xc:blue +append ) -append" + _BBOX]
# attribute.c: GetImageDepth on a palette image checks red, green and blue in turn (a colour
# whose green, or blue, alone needs 8 bits), and an image with alpha by its pixels: two
# colours at 1 bit under a 16-bit alpha
GAP_COMMANDS += ["-size 1x1 xc:black xc:%s +append -type Palette -format '%%[bit-depth]\\n' "
                 "-write info:" % colour for colour in ("rgb(0,37,0)", "rgb(0,0,91)")]
GAP_COMMANDS += ["-size 13x1 gradient:black-white -threshold 50% ( -size 13x1 gradient: ) -alpha off "
                 "-compose copy_opacity -composite -type PaletteAlpha -format '%[bit-depth]\\n' -write info:"]
# attribute.c: the pixel scans read their rows through the virtual pixel method, so a scan one
# row too far shows only when the row below the image is not a copy of the last one
_VP_BG = " -virtual-pixel background -background "
GAP_COMMANDS += ["{C}/rose.miff -alpha set -virtual-pixel transparent -format '%[opaque]\\n' -write info:",
                 "{C}/rose.miff -depth 8" + _VP_BG + "#123456789abc -format '%[bit-depth]\\n' -write info:",
                 "-size 4x4 xc:gray50" + _VP_BG + "red -type palette -format '%[type]\\n' -write info:"]
GAP_STEP_CASES += [("a black canvas as PDB under a red background virtual pixel",
                    [["-size", "4x4", "xc:black", "-virtual-pixel", "background", "-background", "red",
                      "pdb:out.miff"]], {})]
# attribute.c: GetEdgeBackgroundColor reads the corners (through the virtual pixel method) unless
# convex-hull:background-color, or -background, names the colour
GAP_COMMANDS += ["{C}/rose.miff -bordercolor white -border 3 " + extra + " -format '%[convex-hull]\\n' -write info:"
                 for extra in ("-virtual-pixel black", "-define convex-hull:background-color=red")]
# attribute.c: SetImageType to the palette, colour-separation and truecolor types from CMYK
GAP_COMMANDS += ["{C}/cmyk.miff " + ops for ops in (
    "-type PaletteBilevelAlpha", "-type PaletteAlpha", "-colors 8 -type ColorSeparationAlpha",
    "-colors 8 -type TrueColor")]
# the colour-separation types keep a CMYK image's colormap unless they make it DirectClass:
# a CMYK palette image (remapped onto itself), written as plain MIFF
GAP_STEP_CASES += [("a CMYK palette image -type %s as plain MIFF" % kind,
                    [["{C}/cmyk.miff", "+dither", "-remap", "{C}/cmyk.miff", "-type", kind, "out.miff"]], {})
                   for kind in ("ColorSeparation", "ColorSeparationAlpha")]
# paint.c: GradientImage's gradient:direction for every gravity, each gradient:extent of a
# radial gradient, and a gradient:bounding-box, on a non-square canvas (columns != rows)
GAP_COMMANDS += ["-size 60x40 -define gradient:direction=%s gradient:red-blue" % d for d in (
    "NorthWest", "North", "NorthEast", "West", "SouthWest", "South", "SouthEast")]
GAP_COMMANDS += ["-size 60x40 -define gradient:extent=%s radial-gradient:red-blue" % e for e in (
    "Circle", "Diagonal", "Ellipse", "Maximum", "Minimum")]
GAP_COMMANDS += ["-size 60x40 -define gradient:bounding-box=30x20+10+5 gradient:red-blue",
                 "-size 60x40 -define gradient:bounding-box=30x20+10+5 radial-gradient:red-blue"]
# paint.c: FloodfillPaintImage from seeds on each edge of the image and from outside it,
# and through a serpentine region (the scanline fill turns back on itself), filling to a
# border and with fuzz
_SERPENT = ("-size 30x20 xc:white -fill black -draw 'line 5,0 5,15' -draw 'line 15,5 15,19' "
            "-draw 'line 25,0 25,15' -fill red ")
GAP_COMMANDS += ["{C}/rose.miff -fill red -floodfill %s white" % seed for seed in (
    "+0+10", "+69+10", "+10+0", "+10+45", "+70+10", "+10+46")]
GAP_COMMANDS += [_SERPENT + "-floodfill +0+0 white", _SERPENT + "-floodfill +29+19 white",
                 _SERPENT + "-bordercolor black -draw 'color 10,10 filltoborder'",
                 _SERPENT + "-draw 'color 20,2 floodfill'",
                 "{C}/rose.miff -fuzz 30% -fill red -floodfill +35+20 red"]
# paint.c: OilPaintImage copies the channels the channel mask leaves out from the centre pixel
GAP_COMMANDS += ["{C}/rose.miff -channel R -paint 2 +channel",
                 "{C}/rose_alpha.miff -channel RGB -paint 3 +channel"]
# type.c: GetTypeInfoByFamily scores a family's entries by style, weight and stretch. The glyphs
# alternate between the two corpus fonts, Generic.ttf and the condensed Narrow.ttf, so which
# entry the scorer picked shows directly in the rendered glyphs (a single font would render the
# same whichever entry won). The families resolve within themselves, so the output does not
# depend on the machine's installed fonts.
_TYPE_SCORE_XML = "<typemap>\n" + "".join(
    '  <type name="Score-%s" family="ScoreFamily" style="%s" weight="%s" stretch="%s" glyphs="{C}/%s"/>\n'
    % (name, style, weight, stretch, font)
    for name, style, weight, stretch, font in (
        ("A", "Normal", 400, "Normal", "Generic.ttf"), ("B", "Italic", 400, "Normal", "Narrow.ttf"),
        ("C", "Oblique", 700, "Condensed", "Generic.ttf"), ("D", "Normal", 900, "Expanded", "Narrow.ttf"),
        ("E", "Normal", 100, "UltraCondensed", "Generic.ttf"), ("F", "Italic", 300, "SemiExpanded", "Narrow.ttf"),
        ("G", "Normal", 600, "Normal", "Narrow.ttf"), ("H", "Normal", 400, "Condensed", "Narrow.ttf"))) + (
    '  <type name="Score-Helvetica" family="Helvetica" glyphs="{C}/Narrow.ttf"/>\n'
    "</typemap>\n")
# label: takes its font from image options, where -style and -stretch do not go (they set the
# command line's draw state), and magick rejects -stretch: -annotate and MVG reach them all
_SCORE_CANVAS = ["-size", "40x20", "xc:white", "-pointsize", "12"]
GAP_STEP_CASES += [("type.xml scoring: -family %s %s, annotated" % (family, query),
                    [_SCORE_CANVAS + ["-family", family] + query.split() + ["-annotate", "+2+14", "Ab",
                                                                            "out.miff"]],
                    {".config/ImageMagick/type.xml": _TYPE_SCORE_XML})
                   for family, query in (
                       ("ScoreFamily", "-style Normal -weight 400"), ("ScoreFamily", "-style Italic"),
                       ("ScoreFamily", "-style Oblique"), ("ScoreFamily", "-style Italic -weight 700"),
                       ("ScoreFamily", "-style Oblique -weight 300"), ("ScoreFamily", "-style Any -weight 650"),
                       ("ScoreFamily", "-weight 900"), ("ScoreFamily", "-weight 100"),
                       ("ScoreFamily", "-weight 550"), ("Arial", "-weight 400"), ("Helvetica", "-style Italic"))]
GAP_STEP_CASES += [("type.xml scoring in MVG: %s" % mvg,
                    [_SCORE_CANVAS + ["-draw", "font-family ScoreFamily %s text 2,14 'Ab'" % mvg, "out.miff"]],
                    {".config/ImageMagick/type.xml": _TYPE_SCORE_XML})
                   for mvg in ("font-stretch condensed", "font-stretch expanded font-weight 800",
                               "font-stretch ultra-condensed", "font-stretch semi-expanded font-style italic",
                               "font-stretch normal font-weight 350", "font-stretch extra-condensed font-style oblique")]
GAP_STEP_CASES += [("type.xml scoring in MVG: an exact match by stretch",
                    [_SCORE_CANVAS + ["-draw", "font-family ScoreFamily font-style normal font-weight 400 "
                                      "font-stretch condensed text 2,14 'Ab'", "out.miff"]],
                    {".config/ImageMagick/type.xml": _TYPE_SCORE_XML})]
# type.c: LoadTypeCache skips <!...> declarations and comments by hand. A <type> hidden where
# only a broken skip would find it: in a quoted string of the DOCTYPE (with "]>" before it),
# in a comment; and a stray "]" in a DOCTYPE without an internal subset
_HIDDEN_TYPE = "<type name='Ghost-%s' family='GhostFamily' glyphs='{C}/Generic.ttf'/>"
_REAL_TYPE = '  <type name="Real-%s" family="RealFamily" glyphs="{C}/Generic.ttf"/>\n'
GAP_STEP_CASES += [("type.xml skipped by hand: %s, listed" % name, [["-list", "font"]],
                    {".config/ImageMagick/type.xml": xml})
                   for name, xml in (
                       ("a type inside a quoted doctype string",
                        '<?xml version="1.0"?>\n<!DOCTYPE typemap [\n  <!ENTITY e "x]> %s y">\n]>\n'
                        "<typemap>\n%s</typemap>\n" % (_HIDDEN_TYPE % "Quote", _REAL_TYPE % "Quote")),
                       ("a stray bracket in the doctype",
                        '<?xml version="1.0"?>\n<!DOCTYPE typemap SYSTEM "t" ]>\n'
                        "<typemap>\n%s</typemap>\n" % (_REAL_TYPE % "Bracket")),
                       ("a type inside a comment",
                        "<typemap>\n  <!-- %s -->\n%s</typemap>\n" % (_HIDDEN_TYPE % "Comment",
                                                                      _REAL_TYPE % "Comment")))]
# transform.c: tile crops in the overlap form (@!), with positive, negative and mixed
# offsets; more tiles than pixels; tiles of an image with a page offset
GAP_COMMANDS += ["{C}/rose.miff %s-crop %s +repage" % (pre, geo) for pre, geo in (
    ("", "3x2+2+2@!"), ("", "3x2-2-2@!"), ("", "3x2-3+1@!"), ("", "4x3+1-2@!"),
    ("", "100x60@"), ("-repage +5+3 ", "3x2@"), ("-repage +5+3 ", "3x2+2+1@!"))]
# transform.c: CropImage against the virtual canvas: offset and negative pages, crops that
# overhang it or miss it, a crop of exactly the image, and a zero width or height
GAP_COMMANDS += ["{C}/rose.miff %s-crop %s" % (pre, geo) for pre, geo in (
    ("-repage 100x80+10+5 ", "30x20+5+5"), ("-repage 100x80+10+5 ", "40x30+80+60"),
    ("-repage 100x80-10-5 ", "40x30+0+0"), ("-repage 100x80-10-5 ", "30x20-5-5"),
    ("", "50x30-10-5"), ("", "30x30+60+40"), ("", "100x100"), ("", "70x46+0+0"),
    ("", "0x20+0+5"), ("", "20x0+5+0"), ("-repage 100x80+10+5 ", "200x200-20-20"))]
# transform.c: trim:minSize smaller than, equal to and larger than the trimmed box, and
# larger than the image, under several gravities
GAP_COMMANDS += ["{C}/rose.miff -bordercolor white -border 5 %s-define trim:minSize=%s -trim" % (grav, size)
                 for grav, size in (("", "60x40"), ("", "70x46"), ("", "75x46"), ("", "80x50"),
                                    ("", "90x70"), ("-gravity center ", "80x52"),
                                    ("-gravity southeast ", "78x50"), ("-gravity north ", "76x54"),
                                    ("-gravity west ", "74x50"))]
# transform.c: ExtentImage moves the 8BIM clip path of a JPEG that has one; SpliceImage
# copies alpha, under each gravity
GAP_STEP_CASES += [("-extent %s on a JPEG with an 8BIM clip path" % geo,
                    [[_UHDR_JPG, "-extent", geo, "-write", "8bim:clip.8bim", "out.miff"]], {})
                   for geo in ("300x300", "120x80+10+10")]
# transform.c: that JPEG holds no clip path, so ExtentImage's Update8BIMClipPath had nothing to
# move. A hand-made 8BIM resource does: id 2048 and one subpath of three knots, every byte
# below 0x80 so that it survives the case's text file
_CLIP_8BIM = ("8BIM\x08\x00\x00\x00\x00\x00\x00\x68" + "\x00\x00\x00\x03" + "\x00" * 22
              + "".join("\x00\x01" + ("\x00" + chr(y) + "\x00\x00\x00" + chr(x) + "\x00\x00") * 3
                        for y, x in ((0x20, 0x20), (0x60, 0x30), (0x40, 0x70))))
GAP_STEP_CASES += [("-extent %s of an image with a clip path" % geo,
                    [["{C}/rose.miff", "-profile", "clip.8bim", "-extent", geo,
                      "-write", "8bim:out.8bim", "out.miff"]], {"clip.8bim": _CLIP_8BIM})
                   for geo in ("120x80+10+10", "60x40-5-5")]
# string.c: PrintStringInfo, which identify -verbose calls for each profile when the image's
# debug flag is set (-define debug=true sets it without turning event logging on): binary
# profiles as hex rows, a text profile (XMP) as text, and a profile of exactly two rows
GAP_STEP_CASES += [
    ("verbose with debug: binary profiles in hex",
     [[_UHDR_JPG, "-define", "debug=true", "-colorspace", "gray", "-verbose", "info:"]], {}),
    ("verbose with debug: an XMP profile as text",
     [["{C}/rose.miff", "-profile", "meta.xmp", "-define", "debug=true", "-verbose", "info:"]],
     {"meta.xmp": XMP_ELEMENTS}),
    ("verbose with debug: a 40-byte profile, two full hex rows",
     [["{C}/rose.miff", "-profile", "APP1:x.bin", "-define", "debug=true", "-verbose", "info:"]],
     {"x.bin": "".join(chr(1 + i % 7) for i in range(40))}),
]
# string.c: StripMagickString, through MSL's <comment> and <label>: surrounding blanks and
# quotes, a lone quote pair, a quote followed by blanks, and a newline (as &#10;: ReadMSLImage
# turns the file's own line ends into spaces before the parser sees them)
_MSL_COMMENT = """<?xml version="1.0" encoding="UTF-8"?>
<image>
  <read filename="{C}/rose.miff" />
  <comment>%s</comment>
  <label>%s</label>
  <write filename="out.miff" />
</image>
"""
GAP_STEP_CASES += [("MSL comment and label %r" % text,
                    [["msl:s.msl", "out.miff", "-format", "[%c|%l]\\n", "info:"]],
                    {"s.msl": _MSL_COMMENT % (text, text)})
                   for text in ('  "quoted text"  ', "'\"", "line one&#10;line two", '"   ')]
# string.c: InterpretSiPrefixValue at the bottom of its letter range, E (10^18), with no B after it: a
# width limit of 100 that the 70-pixel rose passes
GAP_STEP_CASES += [("a width limit with an E prefix",
                    [["-limit", "width", "0.0000000000000001E", "{C}/rose.miff", "-format", "%w\\n", "info:"]], {})]
# string.c: FileToString strips a leading @ only from a name longer than one character: a
# color correction file named just "@" is read under that name
GAP_STEP_CASES += [("-cdl from a file named @", [["{C}/rose.miff", "-cdl", "@", "out.miff"]], {"@": CDL})]
# annotate.c: AnnotateImage's text-align offsets for the second and later lines: rotated text
# (affine.ry is 0 without a rotation) of three lines, under each alignment
GAP_STEP_CASES += [("rotated three-line text, aligned %s" % align,
                    [["-size", "120x120", "xc:white", "-font", "{C}/Generic.ttf", "-pointsize", "14", "-draw",
                      "rotate 20 text-align %s text 60,40 'ab\\ncd\\nef'" % align, "out.miff"]], {})
                   for align in ("left", "center", "right")]
# annotate.c: RenderFreetype's two other pixel paths. A transparent fill (-fill none) punches
# the glyphs out of the alpha channel instead of compositing; a BDF bitmap font (plain text, so
# it fits a case file) gives FreeType's monochrome bitmaps, one byte per row for the 8-pixel A
# and two for the 16-pixel W
_BDF_FONT = 'STARTFONT 2.1\nFONT -misc-case-medium-r-normal--8-80-75-75-c-80-iso10646-1\nSIZE 8 75 75\nFONTBOUNDINGBOX 16 8 0 -1\nSTARTPROPERTIES 2\nFONT_ASCENT 7\nFONT_DESCENT 1\nENDPROPERTIES\nCHARS 2\nSTARTCHAR A\nENCODING 65\nSWIDTH 500 0\nDWIDTH 8 0\nBBX 8 8 0 -1\nBITMAP\n18\n24\n42\n42\n7E\n42\n42\n00\nENDCHAR\nSTARTCHAR W\nENCODING 87\nSWIDTH 1000 0\nDWIDTH 16 0\nBBX 16 8 0 -1\nBITMAP\n8001\n8001\n8181\n4242\n4242\n2424\n1818\n0000\nENDCHAR\nENDFONT\n'
GAP_STEP_CASES += [
    ("text with a transparent fill over an image with alpha",
     [["{C}/rose.miff", "-alpha", "set", "-font", "{C}/Generic.ttf", "-pointsize", "18", "-fill", "none",
       "-annotate", "+5+22", "Hole Ab", "out.miff"]], {}),
    ("text with a transparent fill over half-transparent blue",
     [["-size", "90x30", "xc:#0000ff80", "-font", "{C}/Generic.ttf", "-pointsize", "18", "-fill", "none",
       "-annotate", "+5+22", "Half Ab", "out.miff"]], {}),
    ("text in a BDF bitmap font",
     [["-size", "40x16", "xc:white", "-font", "f.bdf", "-pointsize", "8", "-annotate", "+2+10", "AW", "out.miff"]],
     {"f.bdf": _BDF_FONT}),
]
# property.c: Get8BIMProperty and the clip path tracers (TraceSVGClippath, TracePSClippath),
# through a hand-made 8BIM profile whose every byte is below 0x80 (it lives in a text case file):
# a plain resource, an unnamed path with stray, unknown and nested records, closed and open
# subpaths and real curves, two named paths (an even and an odd name length), and a path whose
# knots give each of TracePSClippath's forms (c, v, l, y, and closes by v and by y). Another
# profile starts with an empty path; ids 1999 and 2999, whose bytes are not 7-bit, come from
# ImageMagick's own 8BIMTEXT format.
def _8bim_long(v):
    return v.to_bytes(4, "big")
def _8bim_record(selector, body=b""):
    return selector.to_bytes(2, "big") + body.ljust(24, b"\0")
def _8bim_knot(selector, points):
    return _8bim_record(selector, b"".join(_8bim_long(y) + _8bim_long(x) for y, x in points))
def _8bim_subpath(selector, knots):
    return _8bim_record(selector, knots.to_bytes(2, "big"))
def _8bim_resource(rid, name, data):
    name = bytes([len(name)]) + name
    return b"8BIM" + rid.to_bytes(2, "big") + name + b"\0" * (len(name) % 2) + _8bim_long(len(data)) + data
def _8bim_pt(y, x):  # 8.24 fixed point, every byte below 0x80
    return (y << 16, x << 16)
_8BIM_PATH1 = (_8bim_record(6) + _8bim_record(8) + _8bim_knot(1, [_8bim_pt(0x10, 0x10)] * 3)
               + _8bim_subpath(0, 3)
               + _8bim_knot(1, [(0x201000, 0x180000), (0x200000, 0x200000), (0x203000, 0x280000)])
               + _8bim_knot(2, [(0x600000, 0x304000), (0x602000, 0x380000), (0x604000, 0x400000)])
               + _8bim_knot(1, [_8bim_pt(0x40, 0x70)] * 3)
               + _8bim_subpath(3, 2) + _8bim_knot(4, [_8bim_pt(0x08, 0x08), _8bim_pt(0x0c, 0x0c), _8bim_pt(0x10, 0x10)])
               + _8bim_subpath(0, 5) + _8bim_knot(5, [_8bim_pt(0x50, 0x08), _8bim_pt(0x54, 0x0c), _8bim_pt(0x58, 0x10)])
               + _8bim_record(9))
_8BIM_PATH2 = _8bim_subpath(0, 2) + _8bim_knot(1, [_8bim_pt(0x30, 0x30)] * 3) + _8bim_knot(2, [_8bim_pt(0x50, 0x50)] * 3)
def _8bim_curves():
    A, A2, B0, B = _8bim_pt(0x10, 0x10), _8bim_pt(0x14, 0x18), _8bim_pt(0x20, 0x30), _8bim_pt(0x24, 0x34)
    C0, C, D, D2, E = _8bim_pt(0x40, 0x20), _8bim_pt(0x44, 0x24), _8bim_pt(0x50, 0x50), _8bim_pt(0x54, 0x58), _8bim_pt(0x60, 0x40)
    return (_8bim_subpath(0, 5) + b"".join(_8bim_knot(2, k) for k in ([A, A, A2], [B0, B, B], [C0, C, C], [D, D, D2], [E, E, E]))
            + _8bim_subpath(0, 2) + _8bim_knot(2, [A2, A, A]) + _8bim_knot(2, [B, B, B])
            + _8bim_subpath(0, 2) + _8bim_knot(2, [C, C, C]) + _8bim_knot(2, [D, D, D2]))
_8BIM_RICH = (_8bim_resource(0x0430, b"", b"plain resource text") + _8bim_resource(0x0800, b"", _8BIM_PATH1)
              + _8bim_resource(0x0801, b"Path A", _8BIM_PATH2) + _8bim_resource(0x0802, b"Odd", _8BIM_PATH2)
              + _8bim_resource(0x0803, b"Curves", _8bim_curves())).decode("ascii")
_8BIM_EMPTY_FIRST = (_8bim_resource(0x0800, b"", b"") + _8bim_resource(0x0801, b"", _8BIM_PATH2)).decode("ascii")
def _8bim_format(fmt, profile=None):
    return ("8BIM properties %r" % fmt, [["{C}/rose.miff", "-profile", "clip.8bim", "-format", fmt, "info:"]],
            {"clip.8bim": profile or _8BIM_RICH})
GAP_STEP_CASES += [
    _8bim_format("%[8BIM:1999,2998:#1]"), _8bim_format("%[8BIM:1999,2998:#1\nPS]"),
    _8bim_format("%[8BIM:1999,2998:#2]|%[8BIM:1999,2998:#3\nPS]"),
    _8bim_format("%[8BIM:1999,2998:Path A\nPS]|%[8BIM:1999,2998:Odd]"),
    _8bim_format("[%[8BIM:1000,1100]][%[8BIM:1999,2998:Nope]][%[8BIM:3000,3001]][%[8BIM:1999,2998:#9]]"),
    _8bim_format("%[8BIM:1999,2998:Curves\nPS]"), _8bim_format("%[8BIM:1999,2998:Curves]"),
    _8bim_format("[%[8BIM:1999,2998:#1]][%[8BIM:1999,2998:#2\nPS]]", _8BIM_EMPTY_FIRST),
    ("8BIM clip path, -clip", [["{C}/rose.miff", "-profile", "clip.8bim", "-clip", "-fill", "red", "-colorize", "50", "out.miff"]],
     {"clip.8bim": _8BIM_RICH}),
    ("8BIM clip path, -clip-path by name", [["{C}/rose.miff", "-profile", "clip.8bim", "-clip-path", "Path A", "-fill", "red",
                                              "-colorize", "50", "out.miff"]], {"clip.8bim": _8BIM_RICH}),
    ("8BIM clip path, verbose", [["{C}/rose.miff", "-profile", "clip.8bim", "-verbose", "info:"]], {"clip.8bim": _8BIM_RICH}),
    ("8BIM resources 1999 and 2999 from 8BIMTEXT",
     [["{C}/rose.miff", "-profile", "8bimtext:t.txt", "-format", "[%[8BIM:1999,1999]] [%[8BIM:2999,2999]]\\n", "info:"]],
     {"t.txt": '8BIM#1999="low edge"\n8BIM#2999="high edge"\n'}),
]
# ... and a profile that ends right after a resource's name (4 zero bytes and an x), which a
# length test one off would read as a zero-length resource
GAP_STEP_CASES += [_8bim_format("[%[8BIM:1999,2998:#1]]", "8BIM\x08\x00\x05\x00\x00\x00\x00x")]
# property.c: GetEXIFProperty over a hand-made little-endian EXIF block, in a 4x4 JPEG passed
# inline as base64 (its tag numbers have bytes above 0x7f, so no text case file can hold it):
# IFD0 points to an Exif IFD and a GPS IFD and on to IFD1; the Exif IFD points to an Interop IFD,
# which points back to the Exif IFD (a loop); values come in every TIFF format. A tag looked up
# by number (#hex, @hex for GPS) is stored under an empty name, so it shows only as a warning,
# one per command; exif:! stores every tag as #hex or @hex, read back in the same format.
_TINY_JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/wAALCAAEAAQBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAAf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AH//Z")
def _exif_block(byte_order="<"):
    BYTE, ASCII, SHORT, LONG, RATIONAL, SBYTE, UNDEF, SSHORT, SLONG, SRATIONAL, FLOAT, DOUBLE = range(1, 13)
    ifds = {
        "0": [(0x0100, SHORT, 1, struct.pack(byte_order + "H", 70)), (0x0101, SHORT, 1, struct.pack(byte_order + "H", 46)),
              (0x010F, ASCII, 8, b"CaseCam\0"), (0x0112, SHORT, 1, struct.pack(byte_order + "H", 6)),
              (0x011A, RATIONAL, 1, struct.pack(byte_order + "II", 300, 1)), (0x0128, SHORT, 1, struct.pack(byte_order + "H", 2)),
              (0x8769, LONG, 1, "exif"), (0x8825, LONG, 1, "gps")],
        "exif": [(0x9000, UNDEF, 4, b"0230"), (0x9286, UNDEF, 16, b"ASCII\0\0\0hello!!"),
                 (0x9201, SRATIONAL, 1, struct.pack(byte_order + "ii", -7, 3)), (0x920A, RATIONAL, 1, struct.pack(byte_order + "II", 50, 1)),
                 (0xA002, LONG, 1, struct.pack(byte_order + "I", 70)), (0x9204, SSHORT, 1, struct.pack(byte_order + "h", -2)),
                 (0x9205, SLONG, 1, struct.pack(byte_order + "i", -40000)), (0x9206, FLOAT, 1, struct.pack(byte_order + "f", 2.5)),
                 (0x9207, DOUBLE, 1, struct.pack(byte_order + "d", -1.25)), (0x9208, SBYTE, 2, struct.pack(byte_order + "bb", -3, 4)),
                 (0xA005, LONG, 1, "interop")],
        "gps": [(0x0000, BYTE, 4, bytes([2, 3, 0, 0])), (0x0001, ASCII, 2, b"N\0"),
                (0x0002, RATIONAL, 3, struct.pack(byte_order + "IIIIII", 55, 1, 42, 1, 30, 1))],
        "interop": [(0x0001, ASCII, 4, b"R98\0"), (0x0002, UNDEF, 4, b"0100"), (0x8769, LONG, 1, "exif")],
        "1": [(0x0103, SHORT, 1, struct.pack(byte_order + "H", 6))],
    }
    order = ["0", "exif", "gps", "interop", "1"]
    offsets, pos = {}, 8
    for name in order:  # each IFD, then the values that do not fit in its entries
        offsets[name] = pos
        pos += 2 + 12 * len(ifds[name]) + 4 + sum(len(v) + len(v) % 2 for _, _, _, v in ifds[name]
                                                   if not isinstance(v, str) and len(v) > 4)
    out = bytearray((b"II*\0" if byte_order == "<" else b"MM\0*") + struct.pack(byte_order + "I", offsets["0"]))
    for name in order:
        entries, data = bytearray(struct.pack(byte_order + "H", len(ifds[name]))), bytearray()
        data_at = offsets[name] + 2 + 12 * len(ifds[name]) + 4
        for tag, fmt, count, v in ifds[name]:
            if isinstance(v, str):
                field = struct.pack(byte_order + "I", offsets[v])
            elif len(v) <= 4:
                field = v.ljust(4, b"\0")
            else:
                field = struct.pack(byte_order + "I", data_at + len(data))
                data += v + b"\0" * (len(v) % 2)
            entries += struct.pack(byte_order + "HHI", tag, fmt, count) + field
        out += entries + struct.pack(byte_order + "I", offsets["1"] if name == "0" else 0) + data
    return bytes(out)
def _exif_jpeg_uri(byte_order="<"):
    app1 = b"Exif\0\0" + _exif_block(byte_order)
    jpeg = _TINY_JPEG[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + _TINY_JPEG[2:]
    return "inline:data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
GAP_STEP_CASES += [("EXIF properties %r" % fmt, [[_exif_jpeg_uri(), "-format", fmt + "\\n", "info:"]], {})
                   for fmt in ["%[exif:*]",
                               "%[exif:!][%[#0112]][%[@0000]][%[@0001]][%[#9000]][%[#0001]][%[unknown]]",
                               "%[exif:GPSLatitudeRef]|%[exif:InteroperabilityIndex]|%[exif:Make]"]
                   + ["%%[exif:%s]" % key for key in ("#a002", "#A002", "#010f", "#010F", "#9000", "@0001",
                                                     "#00g0", "#12345", "#1234", "")]]
GAP_STEP_CASES += [("EXIF properties, big-endian", [[_exif_jpeg_uri(">"), "-format", "%[exif:*]\\n", "info:"]], {})]
# image.c: SetImageRegionMask through -region (a region inside the image, one centred by gravity
# and lifted again by +region, and one larger than the image), and GetImageMask through the
# clip: coder, written and read, with the 8BIM clip paths above
GAP_STEP_CASES += [
    ("-region inside the image", [["{C}/rose.miff", "-region", "30x20+10+5", "-negate", "out.miff"]], {}),
    ("-region by gravity, then +region", [["{C}/rose.miff", "-gravity", "center", "-region", "30x20+3-2", "-negate",
                                           "+region", "-flop", "out.miff"]], {}),
    ("-region larger than the image", [["{C}/rose.miff", "-region", "100x100-10-10", "-negate", "out.miff"]], {}),
    ("clip: written from an 8BIM clip path", [["{C}/rose.miff", "-profile", "clip.8bim", "clip:m.miff"]],
     {"clip.8bim": _8BIM_RICH}),
    ("clip: read back", [["{C}/rose.miff", "-profile", "clip.8bim", "m.miff"], ["clip:m.miff", "out.miff"]],
     {"clip.8bim": _8BIM_RICH}),
    ("clip: written from a named 8BIM clip path", [["{C}/rose.miff", "-profile", "clip.8bim", "-clip-path", "Path A",
                                                    "clip:m.miff"]], {"clip.8bim": _8BIM_RICH}),
]
# draw.c: round line caps (DrawRoundLinecap) on a line and an open polyline, and a composite mask
# from a named MVG macro (push mask "m1" ... mask m1: the name must be quoted to become a macro)
_MVG_MASK = ('push graphic-context\n  push mask "m1"\n    fill white\n    circle 35,23 35,5\n  pop mask\n'
             '  mask m1\n  fill red\n  rectangle 0,0 70,46\npop graphic-context\n')
GAP_STEP_CASES += [
    ("round line caps on a line", [["-size", "70x46", "xc:white", "-draw",
                                    "stroke blue stroke-width 7 stroke-linecap round line 10,10 60,30", "out.miff"]], {}),
    # round caps on a polyline fail, filled or not: the command ends in a non-conforming
    # primitive error and writes nothing (a line, above, draws them)
    ("round line caps on an open polyline", [["-size", "70x46", "xc:white", "-draw",
        "fill none stroke blue stroke-width 5 stroke-linecap round polyline 5,40 20,5 35,40 50,5", "out.miff"]], {}),
    ("an MVG composite mask", [["{C}/rose.miff", "-draw", "@m.mvg", "out.miff"]], {"m.mvg": _MVG_MASK}),
    ("an MVG composite mask, its red channel", [["{C}/rose.miff", "-draw", "@m.mvg", "-format",
                                                 "%[fx:mean.r] %[fx:maxima.r]\\n", "info:"]], {"m.mvg": _MVG_MASK}),
]
# draw.c: DrawGradientImage's stop lookup where a pixel's offset lands exactly on two stops of
# the same offset (0 and 0.5 on a 101-pixel ramp, x/100) and on a stop beyond 1; and an
# elliptical radial gradient at an angle (GetStopColorOffset's rotation)
_MVG_DUP_STOPS = ("push defs\n  push gradient g1 linear 0,0 100,0\n"
                  "    stop-color red 0\n    stop-color lime 0\n    stop-color blue 0.5\n    stop-color yellow 0.5\n"
                  "    stop-color black 1.5\n  pop gradient\npop defs\nfill url(#g1) rectangle 0,0 100,9\n")
GAP_STEP_CASES += [
    ("a gradient with stops sharing an offset", [["-size", "101x10", "xc:white", "-draw", "@g.mvg", "out.miff"]],
     {"g.mvg": _MVG_DUP_STOPS}),
]
# property.c: GetXMPProperty, listed after a lookup has parsed the profile: simple elements, an
# exif: name (renamed xmp:), names ending in :* (skipped, with and without children, and the
# two-character ":*"), a two-character name, nested elements, two rdf:Description blocks; and
# the same profile behind junk, which the scan for "<x" skips
_XMP_PROPS = '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n<rdf:Description rdf:about=""><xmp:Rating>5</xmp:Rating><ab>two</ab><exif:FNumber>28/10</exif:FNumber><c:*>star</c:*><q:>colon</q:><:*>tiny</:*><g:*><h>kid</h></g:*><:*><i>kid2</i></:*>\n<dc:subject><rdf:Bag><rdf:li>one</rdf:li><rdf:li>two</rdf:li></rdf:Bag></dc:subject>\n<dc:title><rdf:Alt><rdf:li xml:lang="x-default">A title</rdf:li></rdf:Alt></dc:title><d:*><rdf:li>skip</rdf:li></d:*><e><f>child</f></e></rdf:Description>\n<rdf:Description rdf:about=""><tiff:Make>CaseCam</tiff:Make></rdf:Description>\n</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>\n'
GAP_STEP_CASES += [("XMP properties listed%s" % label,
                    [["{C}/rose.miff", "-profile", "p.xmp", "-set", "comment", "%[xmp:Rating]", "-verbose", "info:"]],
                    {"p.xmp": prefix + _XMP_PROPS}) for label, prefix in (("", ""), (", behind junk", "JUNK x Kx <y "))]
# property.c: GetIPTCProperty over hand-made IPTC records (all bytes below 0x80): junk before the
# first marker, a dataset found twice (joined by ;), a record whose declared length runs past the
# end, a first match that is empty (which hides the property), and IPTC inside an 8BIM profile
def _iptc(dataset, record, data, declared=None):
    n = len(data) if declared is None else declared
    return "\x1c" + chr(dataset) + chr(record) + chr(n >> 8) + chr(n & 0xff) + data
_IPTC = ("junk" + _iptc(2, 120, "first caption") + _iptc(2, 25, "kw1") + _iptc(2, 25, "kw2") + _iptc(2, 5, "Title")
         + _iptc(2, 120, "second") + _iptc(2, 90, "Lund", 9))
GAP_STEP_CASES += [
    ("IPTC properties", [["{C}/rose.miff", "-profile", "iptc:p.iptc", "-format",
                          "[%[IPTC:2:120]][%[IPTC:2:25]][%[IPTC:2:5]][%[IPTC:2:90]][%[IPTC:2:7]]\\n", "info:"]],
     {"p.iptc": _IPTC}),
    ("IPTC property whose first record is empty", [["{C}/rose.miff", "-profile", "iptc:p.iptc", "-format",
                                                    "[%[IPTC:2:120]]\\n", "info:"]],
     {"p.iptc": _iptc(2, 120, "") + _iptc(2, 120, "after empty")}),
    ("IPTC property inside an 8BIM profile", [["{C}/rose.miff", "-profile", "8bim:p.8bim", "-format",
                                               "[%[IPTC:2:105]]\\n", "info:"]],
     {"p.8bim": "8BIM\x04\x04\x00\x00\x00\x00\x00\x14" + _iptc(2, 105, "from 8BIM")}),
]
# property.c: SetImageProperty's image attributes through -set: a valid value, Undefined (0) and an
# unknown name for compress, intent and interpolate; a non-default value then Undefined for dispose,
# gravity, interpolate and units; each written out (verbose, an interpolative resize, a MIFF
# header). And -set delay with > and < (where < takes the delay from sigma) at its boundaries.
_SET_TAIL = ["-verbose", "-write", "info:", "+verbose", "-interpolative-resize", "50%", "out.miff"]
GAP_STEP_CASES += [("-set %s %s" % (key, value), [["{C}/rose.miff", "-set", key, value] + _SET_TAIL], {})
                   for key, values in (("compress", ("RLE", "Undefined", "NoSuch")),
                                       ("intent", ("Saturation", "Undefined", "NoSuch")),
                                       ("interpolate", ("Nearest",)))
                   for value in values]
GAP_STEP_CASES += [("-set %s %s, then Undefined" % (key, value),
                    [["{C}/rose.miff", "-set", key, value, "-set", key, "Undefined"] + _SET_TAIL], {})
                   for key, value in (("dispose", "Background"), ("gravity", "South"), ("interpolate", "Nearest"),
                                      ("units", "PixelsPerCentimeter"))]
GAP_STEP_CASES += [("-set delay %s, then %s" % (first, second),
                    [["{C}/rose.miff", "-set", "delay", first, "-set", "delay", second, "-format", "%T\\n", "info:"]], {})
                   for first, second in (("50", "10>"), ("5", "30x20<"), ("40", "30x20<"), ("20", "20x30<"),
                                         ("29", "30x7<"))]
# image.c: SmushImages under gravity, with images of different sizes (each image's gravity offset
# and the larger width or height), and margins that step from row to row (the gap is their minimum)
GAP_COMMANDS += [
    "-gravity center ( -size 30x20 xc:none -fill red -draw 'polygon 0,0 24,10 0,19' ) ( -size 30x40 xc:none -fill blue -draw 'polygon 29,0 5,20 29,39' ) +smush 0",
    "-gravity center ( -size 30x40 xc:none -fill blue -draw 'polygon 29,0 5,20 29,39' ) ( -size 30x20 xc:none -fill red -draw 'polygon 0,0 24,10 0,19' ) +smush 1",
    "-gravity south ( -size 30x20 xc:none -fill red -draw 'polygon 0,0 24,10 0,19' ) ( -size 30x40 xc:none -fill blue -draw 'polygon 29,0 5,20 29,39' ) +smush 0",
    "-gravity center ( -size 20x30 xc:none -fill red -draw 'polygon 0,0 10,24 19,0' ) ( -size 40x30 xc:none -fill blue -draw 'polygon 0,29 20,5 39,29' ) -smush 0",
    "-gravity center ( -size 40x30 xc:none -fill blue -draw 'polygon 0,29 20,5 39,29' ) ( -size 20x30 xc:none -fill red -draw 'polygon 0,0 10,24 19,0' ) -smush 1",
    "( -size 20x20 xc:none -fill red -draw 'rectangle 0,0 18,9' -draw 'rectangle 0,10 15,19' ) ( -size 20x20 xc:none -fill blue -draw 'rectangle 1,0 19,9' -draw 'rectangle 4,10 19,19' ) +smush 0",
    "( -size 20x20 xc:none -fill red -draw 'rectangle 0,0 15,9' -draw 'rectangle 0,10 18,19' ) ( -size 20x20 xc:none -fill blue -draw 'rectangle 4,0 19,9' -draw 'rectangle 1,10 19,19' ) +smush 0",
    "( -size 20x20 xc:none -fill red -draw 'rectangle 0,0 9,18' -draw 'rectangle 10,0 19,15' ) ( -size 20x20 xc:none -fill blue -draw 'rectangle 0,1 9,19' -draw 'rectangle 10,4 19,19' ) -smush 0",
    "( -size 20x20 xc:none -fill red -draw 'rectangle 0,0 9,15' -draw 'rectangle 10,0 19,18' ) ( -size 20x20 xc:none -fill blue -draw 'rectangle 0,4 9,19' -draw 'rectangle 10,1 19,19' ) -smush 0",
]
# image.c: SetImageInfo turning adjoin off for a format that holds one frame: two images to a
# JPEG name become out-0.jpg and out-1.jpg
GAP_STEP_CASES += [("two images to a single-frame format", [["{C}/rose.miff", "{C}/rose.miff", "out.jpg"]], {})]
# layer.c: OptimizeLayerFrames where a frame clears pixels outside the previous frame's change, so
# a plain background disposal fails and its area must grow to cover them: cleared areas to the
# right and above, left and below, left and above, right and below, and inside, under each of
# optimize-frame, optimize-plus (which may add frames) and optimize
def _clear_outside(square, hole):
    (x0, y0, x1, y1), (hx, hy, hw, hh) = square, hole
    return ("-size 40x40 xc:red -alpha set ( +clone -fill blue -draw 'rectangle %d,%d %d,%d' ) "
            "( +clone ( -size %dx%d xc:none ) -geometry +%d+%d -compose Copy -composite ) " % (x0, y0, x1, y1, hw, hh, hx, hy))
GAP_COMMANDS += [_clear_outside(square, hole) + "-layers " + op + " -format '%p %D %g %wx%h|' -write info:"
                 for square, hole in (((20, 20, 30, 30), (25, 2, 11, 9)), ((20, 20, 30, 30), (2, 25, 9, 11)),
                                      ((20, 20, 30, 30), (2, 2, 9, 9)), ((5, 5, 15, 15), (25, 25, 11, 11)),
                                      ((10, 10, 30, 30), (12, 12, 6, 6)))
                 for op in ("optimize-frame", "optimize-plus", "optimize")]
# draw.c: a clip path in objectBoundingBox units, which scales to the bounds of what the using
# context has drawn (a rectangle and a circle; a polygon and a circle)
_MVG_BBOX_CLIP = 'push defs\n push clip-path "cp"\n  push graphic-context\n   clip-units objectBoundingBox\n   rectangle 0.2,0.2 0.8,0.8\n  pop graphic-context\n pop clip-path\npop defs\npush graphic-context\n clip-path url(#cp)\n fill red rectangle 10,10 60,40\n fill blue circle 30,25 30,12\npop graphic-context\n'
GAP_STEP_CASES += [("clip path in objectBoundingBox units%s" % label,
                    [["-size", "70x46", "xc:white", "-draw", "@m.mvg", "out.miff"]],
                    {"m.mvg": _MVG_BBOX_CLIP.replace("rectangle 10,10 60,40", shape)})
                   for label, shape in (("", "rectangle 10,10 60,40"), (", polygon", "polygon 60,40 10,35 20,10 55,5"))]
# draw.c: the MVG opacity keyword outside SVG compliance: a fraction, a percentage, with no fill
# (the stroke takes it), after compliance SVG, and inside a clip path (where it is ignored)
GAP_STEP_CASES += [("MVG opacity: %s" % draw, [["-size", "70x46", "xc:white", "-draw", draw, "out.miff"]], {})
                   for draw in ['fill red opacity 0.5 rectangle 5,5 30,30', 'fill red opacity 50% circle 40,20 40,5', 'fill none stroke blue stroke-width 3 opacity 0.4 rectangle 5,5 60,40', 'compliance SVG fill red opacity 0.5 rectangle 5,5 30,30']]
GAP_STEP_CASES += [("MVG opacity inside a clip path", [["-size", "70x46", "xc:white", "-draw", "@m.mvg", "out.miff"]],
                    {"m.mvg": 'push defs\n push clip-path "c"\n  push graphic-context\n   opacity 0.3\n   rectangle 10,10 50,35\n  pop graphic-context\n pop clip-path\npop defs\npush graphic-context\n clip-path url(#c)\n fill red rectangle 0,0 69,45\npop graphic-context\n'})]
# draw.c: a macro used twice (the expansion counter), transforms stacked on a rotation (the affine
# composition), and stop colours outside any gradient, one (no gradient) and two (a gradient over
# the whole image)
GAP_STEP_CASES += [
    ("an MVG macro used twice", [["-size", "70x46", "xc:white", "-draw", "@m.mvg", "out.miff"]],
     {"m.mvg": 'push graphic-context "dot"\n  fill red circle 10,10 10,5\npop graphic-context\nuse dot\n'
               'translate 30,10\nuse dot\n'}),
] + [("MVG: %s" % draw, [["-size", "70x46", "xc:white", "-draw", draw, "out.miff"]], {})
     for draw in ("rotate 20 rotate 15 fill red rectangle 10,10 40,30",
                  "skewX 10 rotate 15 fill red rectangle 10,10 40,30",
                  "stop-color red 0", "stop-color red 0 stop-color blue 1")]
# image.c: StripImage on an image that has profiles (8BIM, ICC, IPTC, MPF): -strip removes them
GAP_STEP_CASES += [("-strip of a JPEG with profiles", [[_UHDR_JPG, "-strip", "-format", "%[profiles]|%c\\n", "info:"]], {}),
                   ("-strip of a JPEG with profiles, written", [[_UHDR_JPG, "-strip", "out.miff"]], {})]
# draw.c: an image primitive under rotations and flips that turn the inverse transform's terms
# negative or zero (DrawAffineImage, AffineEdge's sign branches), some reaching past the canvas
GAP_STEP_CASES += [("MVG image primitive: %s" % draw, [["-size", "80x60", "xc:white", "-draw", draw, "out.miff"]], {})
                   for draw in ["translate 40,30 rotate 90 image over -15,-10 30,20 '{C}/rose.miff'", "translate 40,30 rotate 180 image over -15,-10 30,20 '{C}/rose.miff'", "translate 40,30 rotate 270 image over -15,-10 30,20 '{C}/rose.miff'", "translate 40,30 rotate 135 image over -15,-10 30,20 '{C}/rose.miff'", "translate 40,30 rotate -45 image over -15,-10 30,20 '{C}/rose.miff'", "affine -1,0,0,1,60,0 image over 5,5 40,30 '{C}/rose.miff'", "affine 1,0,0,-1,0,55 image over 5,5 40,30 '{C}/rose.miff'", "translate 70,0 rotate 30 image over -20,-5 50,30 '{C}/rose.miff'"]]
# draw.c: an image primitive with alpha, rotated over a half-transparent canvas, and a half-transparent
# rose from mpr: (DrawAffineImage composites each pixel over what is already there)
GAP_STEP_CASES += [("MVG translucent image primitive %d" % i, [argv[:-1] + ["out.miff"]], {})
                   for i, argv in enumerate([['-size', '80x60', 'xc:#00ff0080', '-draw', "translate 40,30 rotate 30 image over -15,-10 30,20 '{C}/rose_alpha.miff'", '-depth', '16', 'X'], ['-size', '80x60', 'xc:#00ff0080', '-draw', "translate 40,30 rotate 90 image over -15,-10 30,20 '{C}/rose_alpha.miff'", '-depth', '16', 'X'], ['-size', '80x60', 'xc:white', '(', '{C}/rose.miff', '-alpha', 'set', '-channel', 'A', '-evaluate', 'set', '50%', '+channel', '-write', 'mpr:half', '+delete', ')', '-draw', "translate 40,30 rotate 30 image over -15,-10 30,20 'mpr:half'", '-depth', '16', 'X']])]
# draw.c: DrawPolygonPrimitive with a one-point polyline, a tiled fill (-tile, whose offset follows
# the polygon's extent) on a polygon and a point, and a pattern stroke
GAP_STEP_CASES += [("polygon primitive %d" % i, [spec["argv"][:-1] + ["out.miff"]], spec["files"])
                   for i, spec in enumerate([{'files': {}, 'argv': ['-size', '40x30', 'xc:white', '-fill', 'red', '-draw', 'polyline 10,10', '-depth', '8', 'rgb:-']}, {'files': {}, 'argv': ['-size', '40x30', 'xc:white', '-tile', '{C}/granite.miff', '-draw', 'polygon 5,3 35,8 20,27', '-depth', '8', 'rgb:-']}, {'files': {}, 'argv': ['-size', '40x30', 'xc:white', '-tile', '{C}/granite.miff', '-draw', 'polyline 12,9', '-depth', '8', 'rgb:-']}, {'files': {'m.mvg': 'push defs\n push pattern p 0,0 6,6\n  fill blue rectangle 0,0 2,2\n  fill yellow rectangle 3,3 5,5\n pop pattern\npop defs\nfill none stroke url(#p) stroke-width 4 polygon 5,3 35,8 20,27\n'}, 'argv': ['-size', '40x30', 'xc:white', '-draw', '@m.mvg', '-depth', '8', 'rgb:-']}])]
# draw.c: TraceStrokePolygon's joins on a thick stroke with sharp and blunt turns both ways and
# horizontal and vertical runs: miter (limits 1, 4, 10), round (several arc segments) and bevel,
# open and closed, and round joins with round caps
_STROKE_PTS = "10,70 40,15 52,70 80,20 100,20 100,55 70,62"
GAP_STEP_CASES += [("stroke joins: %s" % draw, [["-size", "110x80", "xc:white", "-draw", draw, "out.miff"]], {})
                   for draw in (["fill none stroke blue stroke-width 12 stroke-linejoin %s stroke-miterlimit %s polyline %s"
                                 % (join, limit, _STROKE_PTS) for join in ("miter", "round", "bevel") for limit in ("1", "4", "10")]
                                + ["fill none stroke blue stroke-width 12 stroke-linejoin %s polygon %s" % (join, _STROKE_PTS)
                                   for join in ("miter", "round", "bevel")]
                                + ["fill none stroke blue stroke-width 9 stroke-linejoin round stroke-linecap round "
                                   "polyline 10,40 60,40 60,10 20,70"])]
# image.c: CloneImage of a montage (its montage and directory strings are copied), and of an
# offset image scaled by exactly 3 across and 1 down (or the reverse): a scale difference of
# exactly 2 keeps the page offsets scaled apart
GAP_STEP_CASES += [
    ("a montage cloned and written", [["montage", "{C}/rose.miff", "{C}/rose.miff", "-geometry", "+2+2", "m.miff"],
                                      ["m.miff", "(", "+clone", ")", "-delete", "0", "out.miff"]], {}),
    ("an offset image scaled 3 by 1", [["{C}/rose.miff", "-repage", "+10+5", "-resize", "210x46!", "-format", "%g\\n", "info:"]], {}),
    ("an offset image sampled 1 by 3", [["{C}/rose.miff", "-repage", "+10+5", "-sample", "70x138!", "-format", "%g\\n", "info:"]], {}),
]
# draw.c: RenderMVGContent's keywords at their edges: an unbalanced pop, drawing inside defs (not
# rendered), fill-opacity with no fill and as a percentage, stroke-opacity, zero entries in a dash
# array, zero and negative stroke widths, and skewY (alone and after skewX)
GAP_STEP_CASES += [("MVG keyword: %s" % draw, [["-size", "70x46", "xc:white", "-draw", draw, "out.miff"]], {})
                   for draw in ['pop graphic-context', 'push defs rectangle 5,5 20,20 pop defs fill red rectangle 25,5 40,20', 'fill none fill-opacity 0.5 stroke red stroke-width 3 rectangle 5,5 30,20', 'fill red fill-opacity 50% rectangle 5,5 30,20', 'stroke blue stroke-opacity 0.4 stroke-width 5 line 5,5 60,40', 'stroke blue stroke-width 4 stroke-dasharray 0 4 line 5,20 60,20', 'stroke blue stroke-width 4 stroke-dasharray 5 0 3 line 5,20 60,20', 'stroke blue stroke-width 0 line 5,5 30,30', 'stroke blue stroke-width -1 line 5,5 30,30', 'skewY 20 fill red rectangle 10,5 40,20', 'fill red skewX 15 skewY -10 rectangle 10,5 40,20']]
# draw.c: RenderMVGContent's checks on degenerate primitives: zero corner radii, zero width and
# height, zero ellipse radii, too few points for a polyline, polygon or bezier, a closed two-point
# path, a circle of radius 0 and a zero-size stroked rectangle
GAP_STEP_CASES += [("MVG degenerate: %s" % draw, [["-size", "70x46", "xc:white", "-draw", draw, "out.miff"]], {})
                   for draw in ['fill red roundrectangle 5,5 40,30 0,0', 'fill red roundrectangle 5,5 5,30 3,3', 'fill red roundrectangle 5,5 40,5 3,3', 'fill red ellipse 30,20 0,10 0,360', 'fill red ellipse 30,20 10,0 0,360', 'fill red arc 5,5 40,30 0,90', 'fill red polyline 10,10', 'fill red polygon 5,5 30,30', 'fill red polygon 5,5 30,30 10,25', 'fill red bezier 5,5 30,30', 'fill red bezier 5,5 30,30 50,5', "fill red path 'M 10,10 L 30,30 Z'", 'fill red circle 30,20 30,20', 'stroke blue fill none rectangle 5,5 5,5']]
# policy.c: IsRightsAuthorizedByName's canonical forms of a path. sub/./new.miff does not exist
# yet, so only its real directory joined to its name matches */sub/new.miff; a policy on */sub
# matches the real directory; sub/./in.miff, once written, matches by its full real path; and a
# deny on */sub/* is sticky against a later allow written as the raw path
GAP_STEP_CASES += [
    ("policy on a new file's canonical name", [["{C}/rose.miff", "sub/./new.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="read" pattern="*/sub/new.miff"/>'), "sub/keep.txt": "x"}),
    ("policy on a file's canonical directory", [["{C}/rose.miff", "sub/./x.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="none" pattern="*/sub"/>'), "sub/keep.txt": "x"}),
    ("policy on a file's canonical path", [["{C}/rose.miff", "sub/in.miff"], ["sub/./in.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="write" pattern="*/sub/in.miff"/>'), "sub/keep.txt": "x"}),
    ("a canonical deny is sticky", [["{C}/rose.miff", "sub/./ok.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="none" pattern="*/sub/*"/>',
                       '<policy domain="path" rights="read|write" pattern="sub/./ok.miff"/>'), "sub/keep.txt": "x"}),
]
# policy.c: LoadPolicyCache's DOCTYPE skipping: a quoted string holding "]>" and a ghost policy
# (denying GIF) that must stay inside the string, and a stray "]" before the real GIF deny
GAP_STEP_CASES += [("policy.xml with %s" % label, [["{C}/rose.miff", "x.gif"], ["{C}/rose.miff", "y.bmp"]], {_POLICY: xml})
                   for label, xml in (("a quoted doctype string", '<?xml version="1.0"?>\n<!DOCTYPE policymap [\n  <!ENTITY e "x]> <policy domain=\'coder\' rights=\'none\' pattern=\'GIF\'/> y">\n]>\n<policymap>\n  <policy domain="coder" rights="none" pattern="BMP"/>\n</policymap>\n'), ("a stray doctype bracket", '<?xml version="1.0"?>\n<!DOCTYPE policymap SYSTEM "t" ]>\n<policymap>\n  <policy domain="coder" rights="none" pattern="GIF"/>\n</policymap>\n'))]
# policy.c: GetPolicyInfo's domain filter: system-domain policies named area and width, ahead of
# the resource-domain ones that resource:area and resource:width must find
GAP_STEP_CASES += [("policies of the same name in two domains", [["-list", "resource"], ["{C}/rose.miff", "out.miff"]],
                    {_POLICY: _policy('<policy domain="system" name="area" value="1KP"/>',
                                      '<policy domain="resource" name="area" value="10MP"/>',
                                      '<policy domain="system" name="width" value="9"/>',
                                      '<policy domain="resource" name="width" value="1000"/>')})]
# draw.c: GetMVGMacros with an empty named macro after a full one (its body has length 0, so
# nothing is stored, and using it draws nothing)
GAP_STEP_CASES += [("an empty MVG macro used", [["-size", "40x30", "xc:white", "-draw", "@m.mvg", "out.miff"]],
                    {"m.mvg": 'push graphic-context "a"\n  fill red circle 10,10 10,5\npop graphic-context\n'
                              'push graphic-context "e"\npop graphic-context\nuse e\n'})]
# draw.c: GetDrawInfo reading -direction for a label (label: builds its own draw info)
GAP_STEP_CASES += [("label right to left", [["-direction", "right-to-left", "-font", "{C}/Generic.ttf", "-pointsize", "14",
                                             "label:abc def", "out.miff"]], {})]
# profile.c: SyncExifProfile rewriting resolution and orientation in the hand-made EXIF block (both
# byte orders, with Exif, GPS and Interop directories to walk) as a JPEG or MIFF is written; and
# the 8BIM profile's clip paths through -extent to PSD and through -crop
GAP_STEP_CASES += [("EXIF synced on write, %s, %s" % ("little-endian" if order == "<" else "big-endian", out),
                    [[_exif_jpeg_uri(order)] + opts + [out], [out, "-format", "%[exif:*]\\n", "info:"]], {})
                   for order in ("<", ">")
                   for opts, out in ((["-density", "150x75", "-units", "PixelsPerInch", "-orient", "RightTop"], "out.jpg"),
                                     (["-density", "50x60", "-units", "PixelsPerCentimeter", "-orient", "BottomLeft"], "out.miff"),
                                     (["-resize", "50%"], "out.jpg"))]
GAP_STEP_CASES += [
    ("8BIM clip path through -extent to PSD", [["{C}/rose.miff", "-profile", "clip.8bim", "-extent", "90x60-5-5", "-density", "100",
                                                "out.psd"], ["out.psd", "-format", "%[8BIM:1999,2998:#1]\\n", "info:"]],
     {"clip.8bim": _8BIM_RICH}),
    ("8BIM clip path through -crop", [["{C}/rose.miff", "-profile", "clip.8bim", "-crop", "40x30+5+5", "+repage", "out.miff"],
                                       ["out.miff", "-format", "%[8BIM:1999,2998:#1]\\n", "info:"]], {"clip.8bim": _8BIM_RICH}),
]
# policy.c: a delegate policy without the execute right: the SVG reader's svg:decode delegate is
# refused before any program runs (IsRightsAuthorizedByName's execute test), and MSVG renders it
GAP_STEP_CASES += [("SVG with delegates not executable", [["{C}/draw.svg", "-format", "%wx%h\\n", "info:"]],
                    {_POLICY: _policy('<policy domain="delegate" rights="read" pattern="*"/>')})]
# profile.c: an 8BIM profile carrying IPTC (0x0404), XMP (0x0424, padded so its length bytes stay
# below 0x80) and a small 7-bit EXIF block (0x0422), which GetProfilesFromResourceBlock lifts out
# as profiles of their own; read back directly and after a MIFF round trip
_8BIM_EMBEDDED = (_8bim_resource(0x0404, b"", _IPTC.encode("latin-1"))
                  + _8bim_resource(0x0424, b"", _XMP_PROPS.encode("ascii").ljust(0x500, b" "))
                  + _8bim_resource(0x0422, b"", b"Exif\0\0II*\0" + struct.pack("<IH", 8, 2)
                                   + struct.pack("<HHIHH", 0x0112, 3, 1, 3, 0) + struct.pack("<HHI", 0x0131, 2, 4)
                                   + b"ABC\0" + b"\0" * 4)).decode("ascii")
GAP_STEP_CASES += [
    ("8BIM with embedded profiles", [["{C}/rose.miff", "-profile", "8bim:r.8bim", "-format",
                                      "%[profiles]|%[IPTC:2:120]|%[xmp:Rating]|%[exif:Orientation]|%[exif:Software]\\n", "info:"]],
     {"r.8bim": _8BIM_EMBEDDED}),
    ("8BIM with embedded profiles, written", [["{C}/rose.miff", "-profile", "8bim:r.8bim", "out.miff"],
                                              ["out.miff", "-format", "%[profiles]\\n", "info:"]], {"r.8bim": _8BIM_EMBEDDED}),
]
# profile.c: Sync8BimProfile rewriting the PSD's resolution resource (0x03ED) for a new density in
# centimetres, x and y apart, written to PSD again and read back from the 8BIM profile
GAP_STEP_CASES += [("psd 8bim resolution rewritten per centimetre",
                    [["{C}/rose.miff", "-density", "150", "-units", "PixelsPerInch", "r.psd"],
                     ["r.psd", "-density", "300x200", "-units", "PixelsPerCentimeter", "out.psd"],
                     ["out.psd", "-format", "%x %y %U|%[8BIM:1005,1005]\\n", "info:"]], {})]
# annotate.c: GetMultilineTypeMetrics through multi-line labels (the widest line sets the width,
# whichever line it is), interline spacing, and a caption fitted to a size
GAP_STEP_CASES += [("multi-line text metrics: %s" % args[-3], [["-font", "{C}/Generic.ttf"] + args], {})
                   for args in (["-pointsize", "14", "label:a\\nbbbbbbbbbbb\\ncc", "-format", "%wx%h\\n", "info:"],
                                ["-pointsize", "14", "label:wwwwwwwwwww\\nb", "-format", "%wx%h\\n", "info:"],
                                ["-size", "120x60", "caption:aaa bbbbbbbbbbbbbb cc dd", "-format", "%wx%h %[caption:pointsize]\\n", "info:"],
                                ["-pointsize", "14", "-interline-spacing", "5", "label:a\\nbbbb\\ncc", "-format", "%wx%h\\n", "info:"])]
# annotate.c: a label whose glyphs reach below the baseline and past their advance (j, g, _), for
# RenderFreetype's glyph bounds
GAP_STEP_CASES += [("label with descenders", [["-font", "{C}/Generic.ttf", "-pointsize", "20", "label:Ajg_", "-format",
                                               "%wx%h\\n", "info:"]], {})]
# image.c: InterpretImageFilename copying an invalid specifier (%q) literally before a valid one
GAP_STEP_CASES += [("output name with an invalid specifier before %d",
                    [["{C}/rose.miff", "{C}/rose.miff", "-scene", "3", "o_%q_%d.miff"]], {})]
GAP_COMMANDS += ["-size 60x40 -define gradient:angle=30 -define gradient:radii=25,10 radial-gradient:red-blue",
                 "-size 60x40 -define gradient:angle=120 -define gradient:radii=8,20 -define gradient:center=20,15 "
                 "radial-gradient:yellow-navy"]
# transform.c: CropImage at the edges of the virtual canvas: a crop ending exactly where the
# image's page offset begins (in x, and in y with x inside), a negative crop of an offset image,
# and pages with a zero width or height, where the crop's page comes from the image size
GAP_COMMANDS += ["{C}/rose.miff %s -crop %s" % (page, geo) for page, geo in (
    ("-repage +10+5", "10x10+0+0"), ("-repage +10+5", "80x5+0+0"), ("-repage +10+5", "30x20-5-3"),
    ("-repage 0x46", "30x20+5+0"), ("-repage 70x0", "30x20+0+5"))]
# transform.c: CropImageToTiles: an overlap tile crop at y offset -1 (the one value its
# "< -1" test separates), a single crop in the aspect form (!), tiles a full column or row
# wide, and fixed-size tiles of an image whose page has no width or height
GAP_COMMANDS += ["{C}/rose.miff %s-crop %s" % (pre, geo) for pre, geo in (
    ("", "3x2+0-1@!"), ("", "30x20+5+5!"), ("", "70x20"), ("", "30x46"),
    ("+repage ", "30x20"), ("-repage 0x46 ", "30x20"))]
# layer.c: a persistent first frame (dispose None) under frames with Background dispose that
# overhang the canvas on each side, followed by full frames: the region a disposal clears
# shows in coalesce and in optimize-transparency (with every frame disposed to background,
# the whole canvas is cleared and the difference falls on transparent pixels)
_LAYERS_OVERHANG = ("-dispose None -size 20x16 xc:red -dispose Background ( -size 8x8 xc:blue -repage 20x16%s ) "
                    "-dispose None ( -size 20x16 xc:red ) -dispose Background ( -size 8x8 xc:lime -repage 20x16%s ) "
                    "-dispose None ( -size 20x16 xc:red ) ")
GAP_COMMANDS += [_LAYERS_OVERHANG % offsets + op for offsets in (("-3-2", "+15+12"), ("+2+3", "+10+6"), ("+0+0", "+12+8"))
                 for op in ("-layers coalesce", "-layers optimize-transparency")]
# in coalesce the cleared region must stay visible: a small frame follows the disposals
GAP_COMMANDS += ["-size 20x16 xc:red -dispose Background ( -size 8x8 xc:blue -repage 20x16%s ) "
                 "( -size 8x8 xc:lime -repage 20x16%s ) -dispose None ( -size 4x4 xc:yellow -repage 20x16+8+6 ) "
                 "-layers coalesce" % offsets for offsets in (("-3-2", "+15+12"), ("+2+3", "+10+6"))]
# layer.c: -layers composite with compose:outside-overlay either way, under Copy; and the
# comparisons at exactly half alpha (HDRI holds 0.5 exactly), in compare-clear and -overlay
GAP_COMMANDS += ["-size 10x8 xc:red null: ( -size 14x4 xc:#ffff0080 -repage -2+2 ) -compose Copy "
                 "-define compose:outside-overlay=%s -layers composite" % v for v in ("false", "true")]
GAP_COMMANDS += ["-size 10x8 xc:rgba(0,0,255,0.5) ( -size 10x8 xc:none -fill rgba(0,0,255,0.5) -draw 'point 2,2' ) "
                 "( -size 10x8 xc:rgba(0,0,255,0.5) ) -layers %s" % m for m in ("compare-clear", "compare-overlay")]
# layer.c: MergeImageLayers with offsets in one direction at a time, negative and past the
# first frame, under each merge method; and frames without a page size
_MERGE_FRAMES = ("-size 10x8 xc:red -repage %s ( -size 6x4 xc:blue -repage %s ) "
                 "( -size 3x3 xc:green -repage %s ) ")
GAP_COMMANDS += [_MERGE_FRAMES % offsets + "-layers " + method
                 for offsets in (("+0+3", "+0-2", "+0+9"), ("+3+0", "-2+0", "+9+0"), ("+4+3", "+1+1", "+2+5"))
                 for method in ("merge", "mosaic", "flatten", "trim-bounds")]
GAP_COMMANDS += ["-size 10x8 xc:red +repage ( -size 6x4 xc:blue +repage -page +12+3 ) -layers " + method
                 for method in ("merge", "mosaic")]
# a mosaic on a page wider than every frame, and mosaic and merge from a first frame whose page
# has no size but a negative offset (it does not cover the canvas its size implies)
GAP_COMMANDS += ["-size 10x8 xc:red -repage 30x20+0+0 ( -size 6x4 xc:blue -repage +1+1 ) -layers mosaic",
                 "-size 10x8 xc:red -repage 0x0-3-2 ( -size 6x4 xc:blue -repage +1+1 ) -layers mosaic",
                 "-size 10x8 xc:red -repage 0x0-3-2 ( -size 6x4 xc:blue -repage -5-4 ) -layers merge"]
# layer.c: OptimizeLayerFrames on sequences that grow, shrink back (needing a background or
# previous disposal), repeat a frame (DupDispose) and clear to transparency, for optimize,
# optimize-plus (which may add frames) and optimize-frame
_OPT_SEQ = ("-size 20x16 xc:red ( -size 20x16 xc:red -fill blue -draw 'rectangle 2,2 15,12' ) "
            "( -size 20x16 xc:red -fill blue -draw 'rectangle 5,5 8,8' ) ( -size 20x16 xc:red ) "
            "( -size 20x16 xc:red ) ( -size 20x16 xc:none -fill lime -draw 'rectangle 0,0 3,3' ) ")
GAP_COMMANDS += [_OPT_SEQ + "-layers " + m for m in ("optimize", "optimize-plus", "optimize-frame")]
GAP_COMMANDS += ["-size 12x10 xc:none ( -size 12x10 xc:none -fill blue -draw 'rectangle 1,1 10,8' ) "
                 "( -size 12x10 xc:none -fill blue -draw 'rectangle 4,4 6,6' ) ( -size 12x10 xc:none ) -layers " + m
                 for m in ("optimize-plus", "optimize-frame")]
# layer.c: OptimizeLayerFrames refuses frames of different sizes and pages not coalesced
GAP_COMMANDS += ["-size 10x8 xc:red -size 6x4 xc:blue -layers optimize-frame",
                 "-size 10x8 xc:red ( -size 10x8 xc:blue -repage +1+1 ) -layers optimize-frame",
                 "-size 10x8 xc:red ( -size 10x8 xc:blue -repage 12x8 ) -layers optimize-plus"]
# geometry.c: ParseGravityGeometry's aspect ratios with '#' (the larger of the two fits), its
# '<' and '>' tests on sizes and ratios either side of the image, and offset-only geometries on
# a page with a size, where the region takes the page size
GAP_COMMANDS += ["{C}/rose.miff %s %s -format '%%wx%%h%%O\\n' -write info:" % (op, geo)
                 for geo in ("16:9#", "9:16#", "70:46#", "9:16<", "30x20<", "30x80<", "100x80>", "100x30>")
                 for op in ("-crop", "-extent")]
GAP_COMMANDS += ["{C}/rose.miff -repage 100x80 %s+5+5 -format '%%wx%%h%%O %%g\\n' -write info:" % op
                 for op in ("-extent ", "-gravity center -crop ")]
# geometry.c: ParseGeometry's separators, signs and spacing in up to six values, through
# operators that use each value (-colorize and the thresholds read all five as channels; the
# -alpha set ones make the fifth visible); chosen from 500 random strings as the smallest
# set that kills what any of them killed
GAP_COMMANDS += [
    "'{C}/rose.miff' -fill blue -colorize 25x-10:10X5x+10 -depth 16",
    "'{C}/rose.miff' -fill blue -colorize '2,+2,0.5x+2+2+-40 ' -depth 16",
    "'{C}/rose.miff' -fill blue -colorize -25x-2,2-+10 -depth 16",
    "'{C}/rose.miff' -fill blue -colorize ' 40-+10+-5' -depth 16",
    "'{C}/rose.miff' -fill blue -colorize -5x-0+-2 -depth 16",
    "'{C}/rose.miff' -fill blue -colorize '+0 10:0.5' -depth 16",
    "'{C}/rose.miff' -alpha set -fill 'rgba(0,0,255,0.5)' -black-threshold -0-+2-+25++80+60% -depth 16",
    "'{C}/rose.miff' -alpha set -fill 'rgba(0,0,255,0.5)' -white-threshold +2x-10-+60x+80X40% -depth 16",
    "'{C}/rose.miff' -alpha set -bilateral-blur '10/2+40 3-+5%'",
    "'{C}/rose.miff' -alpha set -bilateral-blur 5:10%",
    "'{C}/rose.miff' -alpha set -shadow 1:10+3++2x10",
    "'{C}/rose.miff' -resize '(3)x(4)'",
]
# utility.c: ExpandFilename's "~" (HOME is the case directory; magick expands it only in a glob)
# and "~user", and ExpandFilenames
# on @lists holding options with arguments, lists of directories only, and globs over files
# the case wrote, with and without a subimage
GAP_STEP_CASES += [
    ("a file read back through a glob under ~/", [["{C}/rose.miff", "f.miff"], ["~/f*.miff", "-negate", "out.miff"]], {}),
    # the glob's head is "~/d", not "~": ExpandFilename's "~/" test and its $HOME lookup, seen
    # in the directory the file was found in ($HOME/d, or ./d when $HOME is not substituted)
    ("a glob under ~/ in a subdirectory, with its directory",
     [["{C}/rose.miff", "d/f.miff"], ["~/d/f*.miff", "-format", "%d|%f %wx%h\\n", "info:"]],
     {"d/keep.txt": "x"}),
    ("a file under ~root", [["~root/no-such-file.miff", "out.miff"]], {}),
    ("a glob under ~root (the user's home is looked up)", [["~root/no-such-*.miff", "out.miff"]], {}),
    ("a glob under ~ of no such user", [["~no-such-user-x/no-such-*.miff", "out.miff"]], {}),
    ("an @list with options and their arguments", [["@opts.txt", "out.miff"]],
     {"opts.txt": "-resize 50% {C}/rose.miff -negate\n"}),
    ("an @list of directories only", [["@dirs.txt", "{C}/rose.miff", "out.miff"]], {"dirs.txt": ". ..\n"}),
    ("an @list mixing a directory, an option and images", [["@mix.txt", "-append", "out.miff"]],
     {"mix.txt": ". -flip {C}/rose.miff {C}/granite.miff\n"}),
    ("a glob over files the case wrote", [["{C}/rose.miff", "a1.miff"], ["{C}/granite.miff", "a2.miff"],
                                          ["a*.miff", "-append", "out.miff"]], {}),
    ("a glob with a subimage", [["{C}/rose.miff", "{C}/granite.miff", "b1.miff"], ["{C}/rose.miff", "b2.miff"],
                                ["b*.miff[0]", "-append", "out.miff"]], {}),
]
# utility.c: AppendImageFormat's branch for a compressed name (.gz and the like), which keeps
# the compression suffix last: a raw RGB file interlaced by partition, one file per channel
GAP_STEP_CASES += [("rgb by partition to a .gz name",
                    [["{C}/rose.miff", "-depth", "8", "-interlace", "partition", "out.rgb.gz"]], {})]
# geometry.c: ParseMetaGeometry's area form with a shrink-only flag; ParseAffineGeometry's
# determinant (a matrix that inverts, and one that does not); IsSceneGeometry at the limits of a
# 64-bit scene number
GAP_COMMANDS += ["{C}/rose.miff -resize 5000@> -format '%wx%h\\n' -write info:",
                 "-size 30x20 xc:white -affine 2,0.5,0.25,1,3,4 -draw 'rectangle 2,2 10,8'",
                 "-size 30x20 xc:white -affine 1,2,2,4,0,0 -draw 'rectangle 2,2 10,8'",
                 "{C}/rose.miff {C}/rose.miff -delete 9223372036854775807 -format '%s\\n' -write info:",
                 "{C}/rose.miff {C}/rose.miff -delete -9223372036854775808 -format '%s\\n' -write info:"]
# policy.c: path policies matched against the literal and the canonical path: a symlink policy
# read through a doubled slash, a path rule naming the corpus file as the case names it, and a
# read-only rule on the corpus directory itself
GAP_STEP_CASES += [
    ("a symlink policy, read through a doubled slash", [["{C}//rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="system" name="symlink" rights="none" pattern="follow"/>')}),
    ("a path policy on the corpus file as the case names it", [["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="none" pattern="{C}/rose.miff"/>')}),
    ("a read-only path policy on the corpus directory", [["{C}/rose.miff", "out.miff"]],
     {_POLICY: _policy('<policy domain="path" rights="read" pattern="*/corpus"/>')}),
]
# configure.c: AcquireConfigureCache loads only the first configure.xml that parses (the
# build's own), so a case's configure.xml is searched for and never read: listed, it must not
# appear
GAP_STEP_CASES += [("a configure.xml of the case's own, shadowed by the build's", [["-list", "configure"]],
                    {".config/ImageMagick/configure.xml":
                         '<configuremap>\n  <configure name="CASE-ENTRY" value="x"/>\n</configuremap>\n'})]
# locale.c: a case's own locale.xml is read (listed with -list locale): the hand-skipping of
# <!...> and comments, the include and the nesting of messages. (A case's log.xml is read too,
# but -list log orders it by path among the build's own, so which build lists it first, and
# which one governs logging, depends on where the build lives: no log case can be compared.)
_LOCALE = ".config/ImageMagick/locale.xml"
def _localemap(body):
    return '<?xml version="1.0"?>\n<localemap>\n  <locale name="C">\n' + body + '  </locale>\n</localemap>\n'
_LOCALE_FILES = {
    "nested messages": _localemap('    <Exception>\n      <Message name="CaseOne">first text</Message>\n'
                                  '      <Case>\n        <Message name="CaseTwo">  spaced   text  </Message>\n      </Case>\n'
                                  '    </Exception>\n'),
    "a quoted doctype string": '<?xml version="1.0"?>\n<!DOCTYPE localemap [\n  <!ENTITY e "x]> <Message name=\'Ghost\'>g</Message> y">\n]>\n'
                               '<localemap>\n  <locale name="C">\n    <Message name="Real">r</Message>\n  </locale>\n</localemap>\n',
    "a stray bracket": '<?xml version="1.0"?>\n<!DOCTYPE localemap SYSTEM "t" ]>\n<localemap>\n  <locale name="C">\n'
                       '    <Message name="Real">r</Message>\n  </locale>\n</localemap>\n',
    "a comment": _localemap('    <!-- <Message name="Ghost">g</Message> -->\n    <Message name="Real">r</Message>\n'),
    "another locale": '<?xml version="1.0"?>\n<localemap>\n  <locale name="xx_XX">\n    <Message name="Other">o</Message>\n'
                      '  </locale>\n  <locale name="C">\n    <Message name="Real">r</Message>\n  </locale>\n</localemap>\n',
}
GAP_STEP_CASES += [("locale.xml of the case's own: %s, listed" % name, [["-list", "locale"]], {_LOCALE: xml})
                   for name, xml in _LOCALE_FILES.items()]
GAP_STEP_CASES += [("locale.xml with an include, listed", [["-list", "locale"]],
                    {_LOCALE: '<localemap>\n  <include locale="C" file="more.xml"/>\n  <locale name="C">\n'
                              '    <Message name="Real">r</Message>\n  </locale>\n</localemap>\n',
                     ".config/ImageMagick/more.xml": _localemap('    <Message name="More">m</Message>\n')}),
                   ("locale.xml including itself, listed", [["-list", "locale"]],
                    {_LOCALE: '<localemap>\n  <include locale="C" file="locale.xml"/>\n  <locale name="C">\n'
                              '    <Message name="Self">s</Message>\n  </locale>\n</localemap>\n'})]
# annotate.c: FormatMagickCaption wraps at a multi-byte space (ReplaceSpaceWithNewline's other
# branch): ideographic, no-break and em spaces in a narrow caption
GAP_COMMANDS += ["-font {C}/Generic.ttf -pointsize 12 -size 40x caption:'%s'" % t for t in (
    "word\u3000word\u3000word\u3000word", "word\u00a0word\u00a0word", "longword\u2003longword\u2003x")]
# transform.c: SpliceImage on an image without alpha under a transparent background: the
# splice image gains an alpha channel the source lacks, which only the explicit SetPixelAlpha
# after each channel loop sets (the loop skips a channel the source does not have)
GAP_COMMANDS += ["{C}/rose.miff -background none %s-splice 5x4+10+8" % grav
                 for grav in ("", "-gravity center ", "-gravity southeast ")]
GAP_COMMANDS += ["{C}/rose_alpha.miff -background none %s-splice 5x4+10+8" % grav
                 for grav in ("", "-gravity center ", "-gravity southeast ")]
# type.c: LoadFontConfigFonts sorts each fontconfig font into ImageMagick's width and weight
# buckets. The case's own fonts.conf (fontconfig reads $HOME/.config/fontconfig, and HOME is
# the case directory) adds the corpus directory and, at scan time, gives its font an exact
# bucket boundary: every width and weight threshold the function compares against.
# A plain file at .cache/fontconfig keeps fontconfig from writing its cache into the case
# directory: whether it writes one there depends on the shared caches other runs left in
# Homebrew's cache directory, so the file came and went between baseline and mutant runs
def _fonts_conf(width, weight, style):
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            '  <dir prefix="relative">../../{C}</dir>\n'
            '  <match target="scan">\n'
            '    <test name="file" compare="contains"><string>Generic.ttf</string></test>\n'
            '    <edit name="width" mode="assign"><int>%d</int></edit>\n'
            '    <edit name="weight" mode="assign"><int>%d</int></edit>\n'
            '    <edit name="style" mode="assign"><string>%s</string></edit>\n'
            '  </match>\n</fontconfig>\n' % (width, weight, style))
GAP_STEP_CASES += [("fontconfig font at width %d, weight %d, style %s, listed" % (width, weight, style),
                    [["-list", "font"]], {".config/fontconfig/fonts.conf": _fonts_conf(width, weight, style),
                     ".cache/fontconfig": ""})
                   for width, weight, style in (
                       (30, 0, "Regular"), (50, 40, "Italic"), (63, 50, "Bold"), (75, 75, "Regular"),
                       (87, 80, "Oblique"), (100, 100, "Regular"), (113, 180, "Italic"),
                       (125, 200, "Regular"), (150, 205, "Bold Italic"), (200, 210, "Regular"))]
# attribute.c: the minimum bounding box's orientation: a rectangle at 30 degrees, axis-aligned
# rectangles (angle 0) under each orientation and an unknown one, a square (equal lengths) and
# a diamond (two corners equally near the origin)
_MBB = (" -precision 17 -format '%[minimum-bounding-box] %[minimum-bounding-box:angle]\\n' -write info:")
GAP_COMMANDS += ["-size 60x60 xc:black -fill white -draw '%s'%s" % (shape, orient) + _MBB
                 for shape, orients in (
                     ("polygon 19,23 43,29 41,37 17,31", ("landscape", "portrait")),
                     ("rectangle 10,20 40,30", ("landscape", "portrait", "other")),
                     ("rectangle 20,10 30,40", ("landscape", "portrait", "other")),
                     ("rectangle 10,10 40,40", ("landscape", "portrait")),
                     ("polygon 30,10 50,30 30,50 10,30", ("",)))
                 for orient in [(" -define minimum-bounding-box:orientation=" + o) if o else ""
                                for o in orients]]
GAP_STEP_CASES += [("a montage's tile directory under identify -verbose",
                    [["montage", "{C}/rose.miff", "{C}/rose.miff", "-geometry", "+2+2", "m.miff"],
                     ["identify", "-verbose", "m.miff"]], {})]
GAP_STEP_CASES += [("exif:sync-image=%s on a JPEG with EXIF" % value,
                    [["{C}/rose.miff", "-profile", "APP1:exif.bin", "-density", "300", "-orient",
                      "BottomLeft", "x.jpg"],
                     ["-define", "exif:sync-image=" + value, "x.jpg", "out.miff"]],
                    {"exif.bin": EXIF_BLOCK})
                   for value in ("false", "off", "no", "0", "true")]
# channel.c: the -alpha methods the catalogue lacked (activate, associate, disassociate, discrete, off-if-opaque, on) on images with and without alpha
GAP_COMMANDS += [
    "{C}/rose.miff -alpha activate",
    "{C}/rose_alpha.miff -alpha associate",
    "{C}/rose_alpha.miff -alpha disassociate",
    "{C}/rose_alpha.miff -alpha discrete",
    "{C}/rose_alpha.miff -alpha off-if-opaque",
    "{C}/rose_alpha.miff -alpha on",
    "{C}/rose.miff -alpha set -alpha off-if-opaque",
]
# magic.c: format detection of a file with no extension, written by -format and info: and read back: SVG with spaces after the <, and one that ends where the pattern does
GAP_COMMANDS += [
    "-size 1x1 xc:red -format \"<  svg width='4' height='4'/>\" -write info:t.dat +delete t.dat",
    "-size 1x1 xc:red -format \"<svg\" -write info:t.dat +delete t.dat",
]
# compress.c, third round: fax and Group 4 written and read back in one command
GAP_COMMANDS += [
    "-size 3000x6 xc:white -fill black -draw \"point 2900,1\" -draw \"line 0,3 1900,3\" -draw \"point 5,5\" -write fax:t.fax +delete fax:t.fax",
    "-size 100x6 xc:white -fill black -draw \"line 0,1 99,1\" -draw \"line 50,3 99,3\" -draw \"point 99,5\" -write fax:t.fax +delete fax:t.fax",
]
# Commands whose output must not be converted to floating point: -stegano hides
# the watermark in the low-order bits, which a float output does not keep.
GAP_PLAIN_COMMANDS = [
    "composite -stegano 5 {C}/gray8.miff {C}/rose.miff",
    "composite -stegano 0 {C}/logo.miff {C}/rose.miff",
]
# Through mogrify.c, whose -gamma is GammaImage (`magick -gamma` uses EvaluateImage).
GAP_CONVERT_CASES = [
    ("convert palette -gamma", ["-gamma", "1.6"], "palette"),
    # `magick -perceptible` fails: the option is missing from MagickCore/option.c
    ("convert palette -perceptible", ["-perceptible", "0.1"], "palette"),
    ("convert hdri -perceptible", ["-perceptible", "0.1"], "hdri"),
    # epsilon is in quantum units: 0.1 changes almost nothing
    ("convert palette -perceptible 30000", ["-perceptible", "30000"], "palette"),
    ("convert rose_alpha colors -perceptible 30000",
     ["-colors", "16", "-channel", "RGBA", "-perceptible", "30000"], "rose_alpha"),
]


def _gap_cases():
    yield from _gap_image_cases(GAP_CASES)
    yield from _gap_plain_cases()
    yield from _gap_image_cases(REACH_CASES)
    yield from _gap_cdl_cases()
    yield from _gap_command_cases()
    yield from _gap_convert_cases()
    yield from _gap_step_cases()


def _gap_image_cases(entries):
    for label, args, names in entries:
        yield _op("gaps", label, [img(n) for n in names], args)


def _gap_plain_cases():
    for command in GAP_PLAIN_COMMANDS:
        yield _op_to("gaps", command.replace("{C}/", ""), _fmt(command), "out.miff")


def _gap_cdl_cases():
    for name in CDL_INPUTS:
        yield _with_inputs(_op("gaps", name + " -cdl", [img(name)], ["-cdl", "cc.xml"]),
                           files={"cc.xml": CDL})


def _gap_command_cases():
    for command in GAP_COMMANDS:
        label = command.replace("{C}/", "")
        if command.startswith("identify "):  # prints, writes nothing
            yield _case("gaps", label, [_fmt(command)], [])
        else:
            yield _op("gaps", label, [], _fmt(command))


def _gap_step_cases():
    for label, steps, files in GAP_STEP_CASES:
        yield _with_inputs(_case("gaps", label, steps, ["out.miff"]), files=files or None)


def _gap_convert_cases():
    for label, args, name in GAP_CONVERT_CASES:
        yield _case("gaps", label, [["convert", img(name)] + args + FLOAT_OUT + ["out.miff"]],
                    ["out.miff"])


def _unique(cases):
    """Identical argv from different families: keep the first."""
    seen, unique = set(), []
    for c in cases:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)
    return unique


def generate(lists, writable_formats):
    """All cases. `lists` maps an option list name to its values
    (`magick -list <name>`); `writable_formats` is the set of lowercase
    format names this build can write."""
    families = (
        _unary_cases(), _convert_cases(), _mogrify_cases(), _stream_cases(),
        # resize.c
        _magnify_cases(), _palette_filter_cases(), _msl_cases(), _one_dimension_cases(),
        _write_mask_cases(), _thumbnail_cases(), _filter_curve_cases(lists),
        _filter_define_cases(),
        _draw_cases(), _text_cases(), _generator_cases(),
        # enumerated families
        _colorspace_cases(lists), _compose_cases(lists), _distort_cases(lists),
        _filter_cases(lists), _interpolate_cases(lists), _virtual_pixel_cases(lists),
        _morphology_cases(lists), _morphology_arg_cases(), _evaluate_cases(lists),
        _statistic_cases(lists),
        _noise_cases(lists), _dither_cases(lists), _layers_cases(lists),
        _complex_cases(lists), _intensity_cases(lists), _sparse_color_cases(lists),
        _type_cases(lists), _preview_cases(lists),
        _multi_cases(), _sequence_cases(), _compare_cases(lists), _text_output_cases(),
        _montage_cases(), _encode_cases(writable_formats), _raw_cases(writable_formats),
        _quantum_cases(writable_formats), _quantum_gap7_cases(writable_formats), _pixel_jxl_cases(writable_formats),
        _constitute_cases(), _glob_cases(), _read_blob_string_cases(), _blob_path_cases(), _distort_poly_cases(), _fx_gap_cases(), _composite_gap_cases(), _compose_colorspace_gap_cases(), _feature_cases(), _resample_cases(), _sparse_color_gap_cases(), _meta_channel_gap_cases(), _exception_gap_cases(), _auto_level_gap_cases(), _matrix_gap_cases(), _stream_gap_cases(), _signature_gap_cases(), _quantize_gap_cases(), _resource_gap_cases(), _quantize_gap2_cases(), _distort_gap_cases(), _fx_gap2_cases(), _cache_gap_cases(), _xml_gap_cases(), _color_gap_cases(), _texture_gap_cases(), _distort_args_gap_cases(), _fx_gap3_cases(), _matrix_gap2_cases(), _quantize_gap3_cases(), _quantize_gap4_cases(), _montage_gap_cases(), _compose_over_gap_cases(), _seamless_gap_cases(), _fx_gap4_cases(), _opacity_line_gap_cases(), _opacity_line_gap2_cases(), _signature_gap2_cases(), _histogram_gap3_cases(), _stream_gap2_cases(), _color_gap2_cases(), _timer_gap_cases(), _monitor_gap_cases(), _montage_gap2_cases(), _morph_gap_cases(), _morph_gap2_cases(), _morph_gap3_cases(), _morph_gap4_cases(), _quantize_gap5_cases(), _quantize_gap6_cases(), _quantize_gap7_cases(), _quantize_gap8_cases(), _quantize_gap9_cases(), _quantize_gap10_cases(), _cache_gap2_cases(), _fx_gap5_cases(), _fx_gap6_cases(), _fx_gap7_cases(), _fx_gap8_cases(), _fx_gap9_cases(), _fx_gap10_cases(), _fx_gap11_cases(), _matrix_gap3_cases(), _resample_gap_cases(), _blob_gap_cases(), _fx_gap12_cases(), _cache_gap3_cases(), _token_gap_cases(), _quantum_gap8_cases(), _fx_gap13_cases(), _quantum_gap9_cases(), _quantum_gap10_cases(), _morph_gap5_cases(), _fx_gap14_cases(), _color_gap3_cases(), _quantize_gap11_cases(), _windrv_cases(),
        _decode_cases(lists),
        _infra_cache_cases(), _infra_blob_cases(), _infra_filename_cases(),
        _infra_property_cases(),
        _cipher_cases(), _info_cases(), _mvg_cases(), _gap_cases(),
    )
    return _unique(c for family in families for c in family)


MSL_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<image>
  <read filename="%s" />
  %s
  <write filename="out.miff" />
</image>
"""
MSL_OPS = [
    '<resize geometry="50x30" />', '<scale geometry="150%" />', '<sample geometry="40x40" />',
    '<blur radius="0" sigma="1.5" />', '<sharpen radius="0" sigma="1" />',
    '<rotate degrees="30" />', '<shear geometry="10x5" />', '<flip />', '<flop />',
    '<crop geometry="30x20+5+5" />', '<border geometry="4x4" fill="red" />',
    '<frame geometry="6x6+2+2" />', '<modulate brightness="110" saturation="80" hue="90" />',
    '<negate />', '<normalize />', '<equalize />', '<despeckle />', '<emboss radius="1" />',
    '<edge radius="1" />', '<implode amount="0.5" />', '<swirl degrees="60" />',
    '<wave geometry="4x20" />', '<solarize threshold="50%" />', '<threshold threshold="40%" />',
    '<raise geometry="4x4" />', '<roll geometry="+10+5" />',
    '<charcoal radius="0" sigma="1" />', '<paint radius="1" />', '<shade azimuth="30" elevation="30" />',
    '<gamma gamma="1.7" />', '<level levels="10%,90%" />', '<magnify />', '<minify />',
    '<trim />', '<transparent color="white" />', '<colorize fill="red" blend="30%" />',
    '<contrast sharpen="true" />', '<enhance />', '<quantize colors="8" />',
    '<segment cluster-threshold="1" smoothing-threshold="1.5" />',
    '<draw primitive="circle" points="20,20 30,30" fill="blue" />',
    '<set background="red" /><extent geometry="90x60" />',
    '<affine xx="1" rx="0.3" ry="0" yy="1" tx="0" ty="0" />',
]

MVG = """viewbox 0 0 120 90
push graphic-context
  fill '#eeeeff' rectangle 0,0 120,90
  stroke navy stroke-width 2 fill none
  path 'M 10 80 Q 40 10 60 45 T 110 20'
  fill-opacity 0.6 fill red circle 30,30 30,12
  stroke-dasharray 4 2 line 5,85 115,60
  push graphic-context
    translate 80,60 rotate 25 fill green roundrectangle -20,-10 20,10 5,5
  pop graphic-context
  push defs
    push gradient g1 linear 0,0 120,0
      stop-color yellow 0% stop-color purple 100%
    pop gradient
  pop defs
  fill url(#g1) ellipse 60,15 30,8 0,360
  stroke-linejoin bevel stroke-width 4 stroke black fill none
  polyline 10,50 25,40 40,55 55,35
  font-size 10 fill black text 8,70 'mvg text'
pop graphic-context
"""

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90" viewBox="0 0 120 90">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f00"/><stop offset="1" stop-color="#00f"/>
    </linearGradient>
    <radialGradient id="r"><stop offset="0" stop-color="white"/>
      <stop offset="1" stop-color="black"/></radialGradient>
    <clipPath id="c"><circle cx="60" cy="45" r="35"/></clipPath>
  </defs>
  <rect width="120" height="90" fill="url(#g)"/>
  <g clip-path="url(#c)" transform="rotate(10 60 45)">
    <ellipse cx="60" cy="45" rx="40" ry="20" fill="url(#r)" opacity="0.7"/>
  </g>
  <path d="M10 80 C 30 10, 90 10, 110 80 Z" fill="none" stroke="green"
        stroke-width="3" stroke-linecap="round" stroke-dasharray="6 3"/>
  <polygon points="10,10 30,5 25,25" fill="orange" fill-rule="evenodd"/>
  <polyline points="80,80 90,60 100,80 110,60" fill="none" stroke="black"/>
  <line x1="0" y1="89" x2="119" y2="0" stroke="purple" stroke-opacity="0.5"/>
  <text x="15" y="50" font-size="12" fill="black">svg text</text>
</svg>
"""
# string.c: StringToArgv counts a quoted argument as one, through the closing quote, before it
# splits the text; an @file list (ExpandFilenames) whose file name holds a space is split by it,
# in double and in single quotes
GAP_STEP_CASES += [("@file list with a %s-quoted name holding a space" % kind,
                    [["{C}/rose.miff", "-resize", "20x20", "a b.miff"],
                     ["{C}/rose.miff", "-resize", "10x10", "c.miff"],
                     ["@list.txt", "-append", "-format", "%w %h %n\\n", "info:"]],
                    {"list.txt": "%sa b.miff%s c.miff\n" % (q, q)})
                   for kind, q in (("double", '"'), ("single", "'"))]
# profile.c: ProfileImage's colour transforms. The corpus holds no ICC profile, so the cases
# build their own: a matrix/TRC display profile (RGB) or a kTRC one (GRAY), ICC v2, with every
# byte below 0x80 so it fits a text case file (fixed-point values, tag offsets and the size are
# chosen for it). Little CMS accepts them; two RGB profiles that differ only in gamma make a
# real transform, two of the same length that differ only in their description make
# CompareStringInfo (string.c) tell them apart
def _icc_s15(v):
    b = struct.pack(">i", int(round(v * 65536)))
    assert all(x < 0x80 for x in b), v
    return b
def _icc(name, gamma256=0x0100, gray=False):
    xyz = lambda x, y, z: b"XYZ " + b"\0" * 4 + _icc_s15(x) + _icc_s15(y) + _icc_s15(z)
    curv = b"curv" + b"\0" * 4 + struct.pack(">IH", 1, gamma256) + b"\0\0"
    text = name.encode() + b"\0"
    desc = b"desc" + b"\0" * 4 + struct.pack(">I", len(text)) + text + b"\0" * 78
    tags = [(b"desc", desc), (b"wtpt", xyz(1.0, 1.0, 1.0))]
    if gray:
        tags += [(b"kTRC", curv)]
    else:
        tags += [(b"rXYZ", xyz(0.4375, 0.25, 0.0625)), (b"gXYZ", xyz(0.3125, 0.4375, 0.125)),
                 (b"bXYZ", xyz(0.25, 0.3125, 0.4375)), (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv)]
    off = 128 + 4 + 12 * len(tags); table = b""; data = b""
    for sig, body in tags:  # every offset, length and the size with each byte below 0x80
        body += b"\0" * (-len(body) % 4)
        while ((off + len(data)) & 0xff) + len(body) > 0x7f or (off + len(data)) & 0x8080:
            data += b"\0" * 4
        table += sig + struct.pack(">II", off + len(data), len(body)); data += body
    while (off + len(data)) & 0x8080:
        data += b"\0" * 4
    header = (struct.pack(">I", off + len(data)) + b"lcms" + bytes([2, 0x10, 0, 0]) + b"mntr"
              + (b"GRAY" if gray else b"RGB ") + b"XYZ " + b"\0" * 12 + b"acspAPPL").ljust(128, b"\0")
    out = header + struct.pack(">I", len(tags)) + table + data
    assert all(x < 0x80 for x in out)
    return out.decode("ascii")
_ICC = {"a.icc": _icc("tiny"), "b.icc": _icc("tiny", 0x0200), "z.icc": _icc("tinz"),
        "g.icc": _icc("gray", 0x0200, gray=True), "h.icc": _icc("grey", gray=True)}
def _icc_case(label, args, src="rose", out=("out.miff",)):
    return ("ICC " + label, [["{C}/%s.miff" % src] + args + list(out)], _ICC)
GAP_STEP_CASES += [
    _icc_case("assigned", ["-profile", "a.icc"]),
    _icc_case("RGB to RGB", ["-profile", "a.icc", "-profile", "b.icc"]),
    _icc_case("the same profile twice", ["-profile", "a.icc", "-profile", "a.icc"]),
    _icc_case("same length, other description", ["-profile", "a.icc", "-profile", "z.icc"]),
    _icc_case("black-point compensation", ["-profile", "a.icc", "-black-point-compensation", "-profile", "b.icc"]),
    _icc_case("RGB to RGB with alpha", ["-profile", "a.icc", "-profile", "b.icc"], "rose_alpha"),
    _icc_case("RGB to RGB at depth 16", ["-depth", "16", "-profile", "a.icc", "-profile", "b.icc"]),
    _icc_case("RGB to RGB in floating point", ["-define", "quantum:format=floating-point", "-depth", "32",
                                               "-profile", "a.icc", "-profile", "b.icc"]),
    _icc_case("removed, then another", ["-profile", "a.icc", "+profile", "icc", "-profile", "b.icc"]),
    _icc_case("CMYK image, RGB profiles", ["-colorspace", "cmyk", "-profile", "a.icc", "-profile", "b.icc"]),
    _icc_case("RGB there and back", ["-profile", "a.icc", "-profile", "b.icc", "-profile", "a.icc"]),
    _icc_case("RGB to gray", ["-profile", "a.icc", "-profile", "g.icc"]),
    _icc_case("RGB to gray with alpha", ["-profile", "a.icc", "-profile", "g.icc"], "rose_alpha"),
    _icc_case("gray to RGB", ["-colorspace", "gray", "-profile", "g.icc", "-profile", "a.icc"]),
    _icc_case("gray to RGB with alpha", ["-colorspace", "gray", "-profile", "g.icc", "-profile", "a.icc"], "rose_alpha"),
    _icc_case("gray to gray", ["-colorspace", "gray", "-profile", "g.icc", "-profile", "h.icc"]),
    _icc_case("RGB to gray, type", ["-profile", "a.icc", "-profile", "g.icc", "-format", "%[type]\\n"], out=("info:",)),
    _icc_case("RGB to gray with alpha, type", ["-profile", "a.icc", "-profile", "g.icc", "-format", "%[type]\\n"],
              "rose_alpha", out=("info:",)),
]
# ... a profile that is not ICC at all (Little CMS's error reaches stderr through the handler
# ProfileImage installs), on an image without and with a profile, and a transform under
# -monitor (its progress lines)
_ICC_BAD = dict(_ICC, **{"x.icc": "A" * 200})
GAP_STEP_CASES += [
    ("ICC not a profile", [["{C}/rose.miff", "-profile", "x.icc", "out.miff"]], _ICC_BAD),
    ("ICC not a profile, after one", [["{C}/rose.miff", "-profile", "a.icc", "-profile", "x.icc", "out.miff"]], _ICC_BAD),
    _icc_case("RGB to RGB under -monitor", ["-profile", "a.icc", "-monitor", "-profile", "b.icc"]),
    _icc_case("RGB to gray under -monitor", ["-profile", "a.icc", "-monitor", "-profile", "g.icc"]),
]
# ... and profiles built on lut16 tables (A2B0 and B2A0, two grid points, every table value at
# most 0x7F7F so its bytes stay below 0x80): CMYK (an output profile), Lab and XYZ (colour space
# profiles). They reach ProfileImage's CMYK, Lab and XYZ branches as source and as target, and
# make black-point compensation matter (the matrix profiles' black is already zero)
def _icc_lut16(nin, nout, rows):
    body = b"mft2" + b"\0" * 4 + bytes([nin, nout, 2, 0])
    body += b"".join(struct.pack(">i", 65536 if i == j else 0) for i in range(3) for j in range(3))
    body += struct.pack(">HH", 2, 2) + struct.pack(">HH", 0, 0x7F7F) * nin
    body += b"".join(struct.pack(">H", v) for row in rows for v in row)
    return body + struct.pack(">HH", 0, 0x7F7F) * nout
def _icc_corners(nin, f):
    rows = []
    for k in range(2 ** nin):
        bits = [(k >> (nin - 1 - i)) & 1 for i in range(nin)]
        row = [min(0x7F7F, max(0, int(v))) & 0x7F7F for v in f(bits)]
        rows.append([v if (v & 0xFF) < 0x80 else (v & 0x7F00) | 0x7F for v in row])
    return rows
def _icc_with_luts(name, space, pcs, cls, a2b, b2a):
    text = name.encode() + b"\0"
    desc = b"desc" + b"\0" * 4 + struct.pack(">I", len(text)) + text + b"\0" * 78
    white = b"XYZ " + b"\0" * 4 + _icc_s15(1.0) * 3
    tags = [(b"desc", desc), (b"wtpt", white), (b"A2B0", a2b), (b"B2A0", b2a)]
    off = 128 + 4 + 12 * len(tags); table = b""; data = b""
    for sig, body in tags:
        body += b"\0" * (-len(body) % 4)
        while len(body) & 0x8080:  # trailing zeros after a tag's content are ignored
            body += b"\0" * 4
        while (off + len(data)) & 0x8080:
            data += b"\0" * 4
        table += sig + struct.pack(">II", off + len(data), len(body)); data += body
    while (off + len(data)) & 0x8080:
        data += b"\0" * 4
    header = (struct.pack(">I", off + len(data)) + b"lcms" + bytes([2, 0x10, 0, 0]) + cls + space + pcs
              + b"\0" * 12 + b"acspAPPL").ljust(128, b"\0")
    out = header + struct.pack(">I", len(tags)) + table + data
    assert all(x < 0x80 for x in out)
    return out.decode("ascii")
def _icc_cmyk():
    a2b = _icc_lut16(4, 3, _icc_corners(4, lambda b: [0x7F7F * (1 - b[0]) * (1 - b[3]) * (0.75 + 0.25 * (1 - b[1])),
                                                       0x7F7F * (1 - b[1]) * (1 - b[3]) * (0.75 + 0.25 * (1 - b[2])),
                                                       0x7F7F * (1 - b[2]) * (1 - b[3]) * (0.75 + 0.25 * (1 - b[0]))]))
    b2a = _icc_lut16(3, 4, _icc_corners(3, lambda b: [0x7F7F * (1 - b[0]), 0x7F7F * (1 - b[1]), 0x7F7F * (1 - b[2]),
                                                       0x2020 * (1 - max(b))]))
    return _icc_with_luts("cmyk", b"CMYK", b"XYZ ", b"prtr", a2b, b2a)
def _icc_space(name, sig):
    rows = _icc_corners(3, lambda b: [0x7F7F * b[0], 0x4040 + 0x1010 * b[1], 0x4040 + 0x2020 * b[2]])
    return _icc_with_luts(name, sig, sig, b"spac", _icc_lut16(3, 3, rows), _icc_lut16(3, 3, rows))
_ICC_LUT = dict(_ICC, **{"c.icc": _icc_cmyk(), "l.icc": _icc_space("lab", b"Lab "), "x.icc": _icc_space("xyz", b"XYZ ")})
def _icc_lut_case(label, profiles, src="rose", out=("out.miff",), extra=()):
    return ("ICC " + label, [["{C}/%s.miff" % src] + list(extra) + [a for p in profiles for a in ("-profile", p)]
                             + list(out)], _ICC_LUT)
GAP_STEP_CASES += [
    _icc_lut_case("RGB to CMYK", ["a.icc", "c.icc"]),
    _icc_lut_case("RGB to CMYK and back", ["a.icc", "c.icc", "a.icc"]),
    _icc_lut_case("RGB to CMYK with alpha", ["a.icc", "c.icc"], "rose_alpha"),
    _icc_lut_case("RGB to CMYK, black-point compensation", ["a.icc", "c.icc"], extra=("-black-point-compensation",)),
    _icc_lut_case("RGB to Lab", ["a.icc", "l.icc"]),
    _icc_lut_case("RGB to Lab and back", ["a.icc", "l.icc", "a.icc"]),
    _icc_lut_case("RGB to XYZ", ["a.icc", "x.icc"]),
    _icc_lut_case("RGB to XYZ and back", ["a.icc", "x.icc", "a.icc"]),
    _icc_lut_case("RGB to CMYK, type", ["a.icc", "c.icc"], out=("-format", "%[type]\\n", "info:")),
    _icc_lut_case("RGB to CMYK with alpha, type", ["a.icc", "c.icc"], "rose_alpha", out=("-format", "%[type]\\n", "info:")),
]
# profile.c: an 8BIM block holding an IPTC record and an ICC profile (the hand-built one).
# Reading it gives the image both profiles (GetProfilesFromResourceBlock); a new ICC profile,
# or one removed, rewrites the 8BIM resource in place (WriteTo8BimProfile), padding an
# odd-length profile to an even one
def _8bim_with_icc(icc):
    return (_8bim_resource(0x0404, b"", b"\x1c\x02\x78\x00\x05hello")
            + _8bim_resource(0x040F, b"", icc)).decode("ascii")
_ICC_ODD = _icc("tiny") + "\0"  # one byte past the declared size
_ICC_8BIM = dict(_ICC, **{"x.8bim": _8bim_with_icc(_ICC["a.icc"].encode()),
                          "o.8bim": _8bim_with_icc(_ICC_ODD.encode()), "o.icc": _ICC_ODD})
GAP_STEP_CASES += [("8BIM with ICC: %s" % label, [["{C}/rose.miff", "-profile", load] + args], _ICC_8BIM)
                   for label, load, args in (
                       ("profiles listed", "x.8bim", ["-format", "%[profiles]|%[icc:description]\\n", "info:"]),
                       ("converted", "x.8bim", ["-profile", "b.icc", "-write", "8bim:out.8bim", "out.miff"]),
                       ("ICC removed", "x.8bim", ["+profile", "icc", "8bim:out.8bim"]),
                       ("IPTC removed", "x.8bim", ["+profile", "iptc", "8bim:out.8bim"]),
                       ("odd-length ICC, converted", "o.8bim", ["-profile", "b.icc", "8bim:out.8bim"]),
                       ("odd-length ICC set", "x.8bim", ["-profile", "o.icc", "8bim:out.8bim"]),
                       ("the same ICC set", "x.8bim", ["-profile", "a.icc", "8bim:out.8bim"]))]
# profile.c: Sync8BimProfile rewrites the 8BIM resolution resource (0x03ED) from the image's
# density as the image is written. The resource id has a byte above 0x7F, so the 8BIM comes
# from a PSD the first step writes (the PSD writer adds the resource; the reader keeps the
# block as the image's 8BIM profile); the density is then changed per inch and per centimetre
GAP_STEP_CASES += [("8BIM resolution from a PSD, new density %s" % units,
                    [["{C}/rose.miff", "-units", "PixelsPerInch", "-density", "72", "a.psd"],
                     ["a.psd[0]", "-units", units, "-density", density, "8bim:out.8bim"]], {})
                   for units, density in (("PixelsPerInch", "150x100"), ("PixelsPerCentimeter", "40x30"))]
# profile.c: SyncExifProfile's limits, with small hand-made IFDs in a JPEG resized (so the sync
# rewrites ImageWidth): an IFD that exactly fits the block, and entries before ImageWidth that
# a bound one off would stop at (a DOUBLE and a FLOAT, the last two formats; no components)
def _exif_ifd0(entries, tail=b""):
    return (b"II*\0" + struct.pack("<IH", 8, len(entries)) + b"".join(entries) + struct.pack("<I", 0) + tail)
def _exif_entry(tag, fmt, count, field):
    return struct.pack("<HHI", tag, fmt, count) + field
def _exif_uri(block):
    app1 = b"Exif\0\0" + block
    jpeg = _TINY_JPEG[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + _TINY_JPEG[2:]
    return "inline:data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
_EXIF_W = _exif_entry(0x0100, 3, 1, struct.pack("<HH", 70, 0))
_EXIF_H = _exif_entry(0x0101, 3, 1, struct.pack("<HH", 46, 0))
GAP_STEP_CASES += [("EXIF sync, %s" % label, [[_exif_uri(block), "-resize", "50%", "out.jpg"]], {})
                   for label, block in (
                       ("an IFD that exactly fits", _exif_ifd0([_EXIF_W, _EXIF_H])),
                       ("a DOUBLE before the width",
                        _exif_ifd0([_exif_entry(0x0110, 12, 1, struct.pack("<I", 50)), _EXIF_W, _EXIF_H],
                                   struct.pack("<d", 1.5))),
                       ("a FLOAT before the width",
                        _exif_ifd0([_exif_entry(0x0110, 11, 1, struct.pack("<f", 1.5)), _EXIF_W, _EXIF_H])),
                       ("no components before the width",
                        _exif_ifd0([_exif_entry(0x010F, 2, 0, b"\0" * 4), _EXIF_W, _EXIF_H])))]
# image.c: AppendImages under gravity (GravityAdjustGeometry offsets the smaller image across
# the stack, which way depending on -append or +append), and CopyImagePixels through -copy:
# a region with a source offset, one that overruns the right or the bottom edge (refused), one
# at the corner, and one under -monitor
GAP_STEP_CASES += [("rose and half a rose, -gravity %s %sappend" % (grav, sign),
                    [["{C}/rose.miff", "(", "{C}/rose.miff", "-resize", "50%", ")", "-gravity", grav,
                      sign + "append", "out.miff"]], {})
                   for grav, sign in (("center", "-"), ("southeast", "+"), ("east", "-"), ("south", "+"))]
GAP_STEP_CASES += [("-copy %s %s%s" % (geometry, offset, " under -monitor" if monitor else ""),
                    [["{C}/rose.miff", "(", "{C}/rose.miff", "-negate", ")"] + (["-monitor"] if monitor else [])
                     + ["-copy", geometry, offset, "out.miff"]], {})
                   for geometry, offset, monitor in (("20x10+5+7", "+30+20", False), ("20x10+5+7", "+60+20", False),
                                                     ("20x10+5+7", "+30+40", False), ("20x10+5+7", "+30+20", True),
                                                     ("20x10", "+50+36", False))]
# image.c: SetImageInfoFromExtension, with a PNG written under extensions that say otherwise:
# .edit and .show (in its table of explicit formats with no coder: the extension is trusted
# and the read fails), .rgb (trust withdrawn: often SGI) and .gray (an explicit raw format)
GAP_STEP_CASES += [("a PNG named %s, read" % name,
                    [["{C}/rose.miff", "-resize", "8x6", "png:" + name], read + [name, "-format", "%m %w %h\\n", "info:"]], {})
                   for name, read in (("x.edit", []), ("a.show", []), ("x.rgb", []), ("x.gray", ["-size", "8x6"]))]
# annotate.c: RenderFreetype takes the vertical resolution from -density's second value
GAP_STEP_CASES += [("label at -density 72x144", [["-font", "{C}/Generic.ttf", "-density", "72x144", "-pointsize", "20",
                                                  "label:Hi", "out.miff"]], {})]
# image.c: SetImageMask with a write mask smaller than the image: past the mask's last column
# and row the image is left unmasked, where a bound one off would read the mask's edge
GAP_STEP_CASES += [("write mask smaller than the image, %s" % colour,
                    [["-size", "60x40", "xc:" + colour, "m.miff"],
                     ["{C}/rose.miff", "-write-mask", "m.miff", "-negate", "+write-mask", "out.miff"]], {})
                   for colour in ("white", "black")]
# image.c: ResetImagePage with a relative offset (-repage ...!), which adds to the page offset
GAP_STEP_CASES += [("-repage %s after 100x80+10+5" % g,
                    [["{C}/rose.miff", "-repage", "100x80+10+5", "-repage", g, "-format", "%g\\n", "info:"]], {})
                   for g in ("+3+2!", "+3!")]
# image.c: IsValidFormatSpecifier refuses a %0d (a lone zero is no width) in an output name
# written frame by frame; SetImageAlpha under a write mask of exactly one half (only a mask
# above one half lets the alpha through)
GAP_STEP_CASES += [
    ("two frames to o_%0d.miff, +adjoin", [["{C}/rose.miff", "{C}/rose.miff", "+adjoin", "o_%0d.miff"]], {}),
    ("alpha set under a write mask of one half",
     [["-size", "70x46", "xc:gray(50%)", "h.miff"],
      ["{C}/rose.miff", "-write-mask", "h.miff", "-alpha", "set", "-channel", "A", "-evaluate", "set", "50%",
       "+channel", "+write-mask", "out.miff"]], {}),
]
# Cases that call the API through imdriver (tools/oracle/driver: the owner allowed a C driver,
# 2026-10-03), for code the command line cannot reach. draw.c: GradientImage with each spread
# method (every caller in the library passes PadSpread), linear and radial, with a short
# vector or radii so the spread matters, an angle, an extent and a centre. image.c: the read,
# write and composite masks under four operations, GetImageMask of each, and AcquireImage
# from ImageInfo fields the command line overwrites. Policy, locale and mime lists, and a
# mime lookup (the driver sorts the mime list: GetMimeList's order varies between runs)
def _driver(*args):
    return [["@driver"] + list(args)]
_DRIVER_CASES = []
for _drv_type, _drv_art in (("linear", "gradient:vector=10,5,20,8"), ("radial", "gradient:radii=6,4")):
    for _drv_spread in ("pad", "reflect", "repeat"):
        _DRIVER_CASES.append(("driver gradient %s %s, %s" % (_drv_type, _drv_spread, _drv_art),
                              _driver("gradient", _drv_type, _drv_spread, "40x20", _drv_art, "red:0.0", "yellow:0.4",
                                      "blue:1.0", "out.miff")))
_DRIVER_CASES += [
    ("driver gradient linear reflect at 30 degrees",
     _driver("gradient", "linear", "reflect", "40x20", "gradient:angle=30", "red:0.2", "blue:0.7", "out.miff")),
    ("driver gradient radial repeat, maximum extent, off centre",
     _driver("gradient", "radial", "repeat", "40x20", "gradient:extent=Maximum", "gradient:center=10,8",
             "red:0.1", "blue:0.5", "out.miff")),
    ("driver gradient radial reflect, diagonal extent, equal stops",
     _driver("gradient", "radial", "reflect", "40x20", "gradient:extent=Diagonal", "red:0.3", "green:0.3",
             "blue:0.9", "out.miff")),
]
for _drv_kind in ("read", "write", "composite"):
    for _drv_op in ("negate", "blur", "composite", "colorize"):
        _DRIVER_CASES.append(("driver %s mask, %s" % (_drv_kind, _drv_op),
                              _driver("mask", _drv_kind, "{C}/rose.miff", "{C}/bilevel.miff", _drv_op, "out.miff")))
    _DRIVER_CASES.append(("driver %s mask, GetImageMask" % _drv_kind,
                          _driver("getmask", _drv_kind, "{C}/rose.miff", "{C}/bilevel.miff", "out.miff")))
_DRIVER_CASES += [
    ("driver AcquireImage, size, page, density, depth, quality, units, extract, interlace",
     _driver("acquire", "size=30x20+2+3", "page=100x80+5+6", "density=72x96", "depth=8", "quality=90",
             "units=PixelsPerInch", "extract=10x10+1+1", "interlace=Plane")),
    ("driver AcquireImage, per centimetre, options",
     _driver("acquire", "size=30x20", "page=+5+6", "density=150", "units=PixelsPerCentimeter", "dither=false",
             "ping=1")),
    ("driver AcquireImage, extract and page alone, colour options",
     _driver("acquire", "extract=10x10", "page=100x80", "background=red", "border-color=blue",
             "matte-color=green", "delay=5", "dispose=Background")),
    ("driver AcquireImage, odd geometries", _driver("acquire", "size=30", "extract=50%", "page=A4")),
]
_DRIVER_CASES += [("driver %s list %r" % (kind, pattern), _driver("list", kind, pattern))
                  for kind, pattern in (("policy", "*"), ("policy", "system*"), ("locale", "*"),
                                        ("locale", "Magick/*"), ("mime", "*"), ("mime", "image/*"), ("mime", "*nope*"))]
_DRIVER_CASES += [("driver mime of %s" % name, _driver("mime", "{C}/%s" % name)) for name in ("rose.miff", "bilevel.miff")]
GAP_STEP_CASES += [(label, steps, {}) for label, steps in _DRIVER_CASES]


# Windows files through imdriver (2026-10-04). pixel.c: ExportImagePixels and ImportImagePixels
# with every storage type, over the maps with a fast path (RGB, BGR, RGBA, BGRA, RGBP, BGRP, I)
# and the generic loop (ARGB, OIP; CMYK, CMYKA and KYMC on a CMYK image), into and from a region,
# plus the refusals (an unknown channel, CMYK of an RGB image, a region outside the image).
# linked-list.c and splay-tree.c: scripts of every operation (the driver interns its strings, so a
# removal by value finds what was stored); a 1100-node ascending chain makes the splay tree
# balance itself past depth 1024. InsertValueInLinkedList at a middle index drops the new element
# but counts it (upstream bug), after which RemoveLastElementFromLinkedList walks off the list,
# so a middle insertion is only ever a script's last step. cache-view.c: the one-pixel getters,
# with each virtual pixel method but Random, inside and outside the image.
_WINDRV_TYPES = ("char", "short", "long", "longlong", "float", "double", "quantum")
_WINDRV_MAPS = [("-", m) for m in ("RGB", "BGR", "RGBA", "BGRA", "RGBP", "BGRP", "I", "ARGB", "OIP",
                                    "BGRO", "RGBO")] + \
               [("CMYK", m) for m in ("CMYK", "CMYKA", "KYMC")]


def _windrv(label, args, outputs=()):
    return _case("windrv", label, _driver(*args), list(outputs))


def _windrv_cases():
    for t in _WINDRV_TYPES:
        for cs, m in _WINDRV_MAPS:
            yield _windrv("export %s %s%s" % (m, t, "" if cs == "-" else " of a CMYK image"),
                          ("pixels", "export", "{C}/rose_alpha.miff", cs, m, t, "4x3+20+15"))
            yield _windrv("import %s %s%s" % (m, t, "" if cs == "-" else " into a CMYK image"),
                          ("pixels", "import", "{C}/rose_alpha.miff", cs, m, t, "4x3+20+15", "out.miff"),
                          ["out.miff"])
        yield _windrv("export RGB %s of the whole image" % t,
                      ("pixels", "export", "{C}/tiny.miff", "-", "RGB", t, "1x1"))
    for direction in ("export", "import"):
        extra = ["out.miff"] if direction == "import" else []
        for label, cs, m, geometry in (("an unknown channel", "-", "RGBX", "2x2"),
                                       ("CMYK of an RGB image", "-", "CMYK", "2x2"),
                                       ("a region outside the image", "-", "RGB", "4x3+68+44"),
                                       ("a gray image as I", "-", "I", "3x2+1+1")):
            yield _windrv("%s refused or not: %s" % (direction, label),
                          tuple(["pixels", direction, "{C}/gray16.miff" if "gray" in label else "{C}/rose.miff",
                                 cs, m, "char", geometry] + extra), extra)
    for label, ops in (
            ("append, iterate, get and remove at each end",
             "3 append:a append:b append:c append:d get:0 get:2 get:5 next next reset next removeat:0 "
             "removeat:1 removeat:7 removelast removelast removelast removelast"),
            ("insert at the head and the tail, remove by value",
             "0 insert:0:b insert:0:a insert:2:c insert:9:x remove:b remove:zz remove:a remove:c remove:a"),
            ("sorted insertion with replacement, array, clear",
             "0 sorted:m sorted:c sorted:x sorted:c sorted:a sorted:z array clear array append:q array"),
            ("iterator across removals", "0 append:a append:b append:c next remove:b next next reset "
                                         "next removeat:0 next removelast next"),
            ("removal of the iterator's element", "0 append:a append:b append:c next next remove:b next "
                                                  "reset next next removelast next"),
            ("a middle insertion, last", "0 append:a append:b append:c insert:1:m"),
            ("a middle insertion further in, last", "0 append:a append:b append:c append:d insert:3:m"),
            ("empty list operations", "0 get:0 next removelast removeat:0 remove:a array clear"),
    ):
        yield _windrv("linked list: %s" % label, tuple(["linkedlist"] + ops.split()))
    for label, ops in (
            ("add, get, delete and remove", "add:m=1 add:c=2 add:x=3 add:a=4 add:z=5 add:c=6 get:c get:q "
                                            "delete:x delete:q remove:a remove:q removevalue:5 removevalue:9 "
                                            "deletevalue:1 deletevalue:9 values clone reset values"),
            ("removal by value of an inner node", "add:d=1 add:b=2 add:f=3 add:a=4 add:c=5 add:e=6 add:g=7 "
                                                  "removevalue:2 deletevalue:6 removevalue:1 values"),
            ("a chain deep enough to balance", "quiet addrange:1100 loud get:k0000 get:k0550 get:k1099 "
                                               "quiet delete:k0001 removevalue:v0002 remove:k0003 loud get:k0004"),
            ("a balanced tree, deleted by value", "quiet addrange:1100 get:k0000 deletevalue:v0500 "
                                                  "removevalue:v1099 loud remove:k0000 get:k0001"),
            ("an empty tree", "get:a delete:a remove:a removevalue:a deletevalue:a values clone reset"),
    ):
        yield _windrv("splay tree: %s" % label, tuple(["splaytree"] + ops.split()))
    # second wave (2026-10-04, after the first round): iterator checks after each kind of change,
    # a middle get and removal, trees with relinquish functions. Not kept: keys compared by address
    # (their order follows heap addresses, which varied in one of four runs) and -debug pixel logs
    # (LogPixelChannels; stable by hand with -log %e, not under the oracle)
    for label, ops in (
            ("iterator at the head, then an insertion at the head", "0 append:a append:b reset insert:0:z next next"),
            ("iterator at the end, then an append and a tail insertion",
             "0 append:a next next insert:1:b next insert:2:c next"),
            ("middle get and removal", "0 append:a append:b append:c append:d append:e get:1 get:3 removeat:2 "
                                       "removeat:2 get:2 removeat:1"),
            ("iterator on the removed head, by value and by index",
             "0 append:a append:b append:c reset remove:a next reset removeat:0 next"),
            ("iterator on a removed middle element", "0 append:a append:b append:c append:d next next "
                                                     "removeat:1 next next"),
            ("iterator on the removed tail", "0 append:a append:b next next removelast next append:c next"),
    ):
        yield _windrv("linked list: %s" % label, tuple(["linkedlist"] + ops.split()))
    for mode in ("free",):
        for label, ops in (
                ("add, delete and remove", "add:m=1 add:c=2 add:x=3 add:a=4 add:c=5 delete:x remove:a "
                                           "removevalue:5 deletevalue:1 deletevalue:9 removevalue:9 values"),
                ("reset of a tree with inner nodes", "add:d=1 add:b=2 add:f=3 add:a=4 add:c=5 add:e=6 add:g=7 "
                                                     "get:a get:g reset values add:q=8"),
                ("remove the root and leaves", "add:d=1 add:b=2 add:f=3 remove:d remove:b get:f deletevalue:3 "
                                               "add:k=4 removevalue:4 clone"),
        ):
            yield _windrv("splay tree, %s: %s" % (mode, label), tuple(["splaytree", "mode:" + mode] + ops.split()))
    # trees without a compare function, as profile.c and property.c make them (keys compared as
    # pointers; here small integers, so the order is the same every run)
    for mode in ("int", "freeint"):
        for label, ops in (
                ("add, delete and remove", "add:50=m add:20=c add:90=x add:10=a add:20=r delete:90 remove:10 "
                                           "removevalue:r deletevalue:m deletevalue:q removevalue:q get:20 values"),
                ("reset of a tree with inner nodes", "add:40=d add:20=b add:60=f add:10=a add:30=c add:50=e "
                                                     "add:70=g get:10 get:70 reset values add:80=q"),
                ("remove the root and leaves", "add:40=d add:20=b add:60=f remove:40 remove:20 get:60 "
                                               "deletevalue:f add:11=k removevalue:k get:99 delete:99 remove:99 clone"),
                ("a chain deep enough to balance", "quiet addrange:1100 loud get:0 get:550 quiet delete:1 "
                                                   "removevalue:v0002 remove:3 deletevalue:v0004 loud get:5"),
        ):
            yield _windrv("splay tree, %s: %s" % (mode, label), tuple(["splaytree", "mode:" + mode] + ops.split()))
    # pixel.c: SortImagePixels (-sort-pixels)
    for name in ("rose", "rose_alpha", "gray16", "cmyk", "tiny", "palette"):
        yield _op("windrv", "%s -sort-pixels" % name, [img(name)], ["-sort-pixels"])
    for name, x, y in (("rose", 5, 5), ("rose_alpha", -3, 100), ("palette", 69, 45), ("cmyk", 100, -20),
                       ("gray16", 2, 2), ("tiny", 0, 0), ("bilevel", -1, -1)):
        yield _windrv("cache view of %s at %d,%d" % (name, x, y), ("cacheview", "{C}/%s.miff" % name, str(x), str(y)))
# delegate.c: PostScript read back through Ghostscript (the owner allowed external programs,
# 2026-10-03; gs from Homebrew, on the oracle's PATH), and PostScript written as EPS. Where gs is
# missing the read fails alike in every run. Inkscape's SVG output and Graphviz's (dot) vary
# between runs, so no case uses them.
GAP_STEP_CASES += [
    ("PostScript through Ghostscript, read back", [["{C}/rose.miff", "a.ps"], ["a.ps", "out.miff"]], {}),
    ("PostScript through Ghostscript, as EPS", [["{C}/rose.miff", "a.ps"], ["a.ps", "b.eps"], ["b.eps", "out.miff"]], {}),
]
