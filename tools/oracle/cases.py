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

import hashlib
import itertools
import json

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


# Upstream bug (docs/refactoring/ORACLE.md, "Known upstream issues"): the
# Displace and Distort compose operators leave the canvas columns beyond the
# source's width uninitialised when the destination is wider than the source,
# so those outputs change from run to run. The oracle keeps them off that path.
DEST_WIDER_UNSTABLE = ("Displace", "Distort")

# Upstream bug (ORACLE.md): -scale 50% under a bilevel write mask leaves output
# pixels unwritten, so the image holds whatever memory held: under a parallel
# load 19 of 64 runs of the same command differed. selfcheck, which runs each
# case twice, missed it, and it counted as a kill in 155 mutation runs.
WRITE_MASK_UNSTABLE = ("-scale 50%",)


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
# compare.c: every metric with a read mask of exactly QuantumRange/2 on one image
# only (the utility masks both, and the test ORs the two masks)
GAP_COMMANDS += [
    "-size 70x46 " + images + " -metric " + metric +
    " -compare -precision 17 -print %[distortion]"
    for metric in ("AE", "DPC", "DSSIM", "Fuzz", "MAE", "MEPP", "MSE", "NCC", "PAE", "PDC",
                   "PHASE", "PHASH", "PSNR", "RMSE", "SSIM")
    for images in ("{C}/rose.miff -read-mask xc:gray(50%) {C}/rose_blur.miff",
                   "{C}/rose.miff ( {C}/rose_blur.miff -read-mask xc:gray(50%) )")]
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
