#!/usr/bin/env python3
"""Derive Narrow.ttf from PerlMagick/t/Generic.ttf: the same glyph set scaled to 0.6 of its
width (outlines and advance widths), so the same text renders with visibly different metrics
and shapes. A second, visually distinct corpus font lets the oracle observe which TypeInfo
the font matcher selects (type.c GetTypeInfoByFamily, annotate.c), which a single glyph file
cannot. Derived from Generic.ttf, so it carries the same licence. Deterministic; needs
fontTools (pip install --user fonttools). Run from the repo root:

    python3 tools/oracle/mknarrow.py
"""
import os
from fontTools.ttLib import TTFont
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.misc.transform import Transform

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "PerlMagick/t/Generic.ttf")
DST = os.path.join(ROOT, "tools/oracle/Narrow.ttf")
SX = 0.6

f = TTFont(SRC)
glyf, hmtx, order, gs = f["glyf"], f["hmtx"], f.getGlyphOrder(), f.getGlyphSet()
new = {}
for name in order:
    pen = TTGlyphPen(gs)
    gs[name].draw(TransformPen(pen, Transform(SX, 0, 0, 1.0, 0, 0)))
    new[name] = pen.glyph()
for name in order:
    glyf[name] = new[name]
    aw, lsb = hmtx[name]
    hmtx[name] = (min(int(round(aw * SX)), 0xffff), int(round(lsb * SX)))
for rec in f["name"].names:
    if rec.nameID in (1, 4, 16):
        rec.string = "Generic Narrow"
    elif rec.nameID == 6:
        rec.string = "GenericNarrow"
    elif rec.nameID in (2, 17):
        rec.string = "Regular"
f.save(DST)
print("saved", DST)
