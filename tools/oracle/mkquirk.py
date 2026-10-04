#!/usr/bin/env python3
"""Derive Quirk.ttf from PerlMagick/t/Generic.ttf: the same glyphs with three properties the corpus
fonts lack, each one a branch of annotate.c's RenderFreetype or ComplexTextLayout that no case can
otherwise take:

  - only a Macintosh Roman character map (the Unicode ones removed) and no glyph names (post
    format 3, so FreeType cannot synthesise a Unicode map from them), so selecting the Unicode
    encoding fails and RenderFreetype falls back to the font's first character map;
  - a zero ascender and descender (hhea and OS/2), the "buggy" metrics RenderFreetype sanitises
    by deriving ascent and descent from the em size;
  - an old-style 'kern' table (format 0) with a few pairs, which FT_Get_Kerning reads (it ignores
    GPOS), so ComplexTextLayout adjusts advances.

Derived from Generic.ttf, so it carries the same licence. Deterministic; needs fontTools
(/usr/bin/python3 -m pip install --user fonttools). Run from the repo root:

    python3 tools/oracle/mkquirk.py
"""
import os
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "PerlMagick/t/Generic.ttf")
DST = os.path.join(ROOT, "tools/oracle/Quirk.ttf")

f = TTFont(SRC)
f["cmap"].tables = [t for t in f["cmap"].tables if (t.platformID, t.platEncID) == (1, 0)]
f["post"].formatType = 3.0
f["hhea"].ascent = f["hhea"].descent = 0
f["OS/2"].sTypoAscender = f["OS/2"].sTypoDescender = 0
f["OS/2"].usWinAscent = f["OS/2"].usWinDescent = 0
cmap = f["cmap"].tables[0].cmap
pairs = {}
for left, right, value in (("A", "V", -300), ("V", "A", -300), ("T", "o", -200), ("A", "T", -150),
                           ("W", "a", -120), ("L", "T", -250)):
    if ord(left) in cmap and ord(right) in cmap:
        pairs[(cmap[ord(left)], cmap[ord(right)])] = value
kern = newTable("kern")
kern.version = 0
sub = KernTable_format_0()
sub.version, sub.length, sub.coverage, sub.format = 0, None, 1, 0
sub.kernTable = pairs
kern.kernTables = [sub]
f["kern"] = kern
for rec in f["name"].names:
    if rec.nameID in (1, 4, 16):
        rec.string = "Generic Quirk"
    elif rec.nameID == 6:
        rec.string = "GenericQuirk"
f.save(DST)
print("saved", DST, "with", len(pairs), "kerning pairs")
