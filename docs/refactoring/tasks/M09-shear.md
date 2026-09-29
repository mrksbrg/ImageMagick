# M09 - refactor `MagickCore/shear.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **2.05** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 1831 lines |
| Functions with findings | 10 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/shear.c
```

The score must read 2.05. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 2 |
| Bumpy Road Ahead | 7 |
| Deep, Nested Complexity | 4 |
| Overall Code Complexity | file |
| Complex Method | 8 |
| Complex Conditional | 2 |
| Code Duplication | 2 |
| Excess Number of Function Arguments | 3 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `IntegralRotateImage` | 701 | 72 | 7 | 13 | public | 4 | 53 | 84 of 113 |
| 2 | `RadonProjection` | 217 | 37 | 5 | 4 | static | 1 | 12 | 67 of 75 |
| 3 | `RadonTransform` | 322 | 31 | - | 6 | static | 2 | 12 | 39 of 51 |
| 4 | `YShearImage` | 1361 | - | 4 | 5 | static | 2 | 26 | 37 of 46 |
| 5 | `XShearImage` | 1146 | - | 4 | 5 | static | 2 | 26 | 35 of 46 |
| 6 | `CropToFitImage` | 114 | 9 | - | 2 | static | - | 26 | 31 of 35 |
| 7 | `ShearImage` | 1581 | 16 | - | - | public | - | 26 | 19 of 27 |
| 8 | `DeskewImage` | 558 | 12 | - | - | public | - | 12 | 21 of 24 |
| 9 | `GetImageBackgroundColor` | 497 | 14 | - | 2 | static | - | 0 | - |
| 10 | `ShearRotateImage` | 1714 | 15 | - | - | public | - | 0 | - |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `IntegralRotateImage` (line 701)

- **Recipe G (guard clauses)** - nesting is 7, target is under 4.
- **Recipe E (extract function)** - 13 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 4 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 23 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 808, `gt_to_ge`: `if ((tile_width+(size_t) tile_x) > image->columns)`
  - line 808, `add_to_sub`: `if ((tile_width+(size_t) tile_x) > image->columns)`
  - line 808, `gt_to_le`: `if ((tile_width+(size_t) tile_x) > image->columns)`
  - line 812, `add_to_sub`: `if ((tile_height+(size_t) tile_y) > image->rows)`
  - line 812, `gt_to_ge`: `if ((tile_height+(size_t) tile_y) > image->rows)`
  - line 833, `add_to_sub`: `rotate_image->columns-(tile_y+(ssize_t) height),y+tile_x,height,`
  - and 17 more (`tools/oracle/mutate.py --function IntegralRotateImage`)
- 6 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify IntegralRotateImage`

#### Step 2: `RadonProjection` (line 217)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 1 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 256, `add_to_sub`: `if (GetMatrixElement(p,x+i+(ssize_t) step,y+i+1,&neighbor) == MagickFalse)`
  - line 259, `eq_to_ne`: `if (SetMatrixElement(q,x+2*i+1,y,&neighbor) == MagickFalse)`
  - line 271, `eq_to_ne`: `if (SetMatrixElement(q,x+2*i+1,y,&element) == MagickFalse)`
  - line 280, `eq_to_ne`: `if (SetMatrixElement(q,x+2*i+1,y,&element) == MagickFalse)`
  - line 302, `sub_to_add`: `for (y=0; y < (ssize_t) (GetMatrixRows(p)-1); y++)`
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify RadonProjection`

#### Step 3: `RadonTransform` (line 322)

- **Recipe E (extract function)** - 6 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 8 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 412, `lt_to_le`: `if (((MagickRealType) GetPixelRed(image,p) < threshold) ||`
  - line 413, `lt_to_le`: `((MagickRealType) GetPixelGreen(image,p) < threshold) ||`
  - line 414, `lt_to_le`: `((MagickRealType) GetPixelBlue(image,p) < threshold))`
  - line 426, `ne_to_eq`: `if (bit != 0)`
  - line 469, `lt_to_le`: `if (((MagickRealType) GetPixelRed(image,p) < threshold) ||`
  - line 470, `lt_to_le`: `((MagickRealType) GetPixelGreen(image,p) < threshold) ||`
  - and 2 more (`tools/oracle/mutate.py --function RadonTransform`)
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify RadonTransform`

#### Step 4: `YShearImage` (line 1361)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 7 arguments; the function is `static`, so check that its address is never taken.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1438, `gt_to_ge`: `if (displacement > 0.0)`
  - line 1483, `sub_to_add`: `for (i=0; i < (step-1); i++)`
  - line 1501, `add_to_sub`: `if ((size_t) (y_offset+(ssize_t) height+step-i) > image->rows)`
  - line 1501, `gt_to_ge`: `if ((size_t) (y_offset+(ssize_t) height+step-i) > image->rows)`
  - line 1514, `sub_to_add`: `for (i=0; i < (step-1); i++)`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify YShearImage`

### Wave 2

#### Step 5: `XShearImage` (line 1146)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 7 arguments; the function is `static`, so check that its address is never taken.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 6 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1223, `gt_to_ge`: `if (displacement > 0.0)`
  - line 1243, `gt_to_ge`: `if (step > x_offset)`
  - line 1248, `lt_to_le`: `if ((x_offset+i) < step)`
  - line 1267, `sub_to_add`: `for (i=0; i < (step-1); i++)`
  - line 1285, `add_to_sub`: `if ((size_t) (x_offset+(ssize_t) width+step-i) > image->columns)`
  - line 1297, `sub_to_add`: `for (i=0; i < (step-1); i++)`
- 5 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify XShearImage`

#### Step 6: `CropToFitImage` (line 114)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe A (parameter object)** - 7 arguments; the function is `static`, so check that its address is never taken.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 158, `gt_to_ge`: `if (min.x > extent[i].x)`
  - line 160, `gt_to_ge`: `if (min.y > extent[i].y)`
  - line 162, `lt_to_le`: `if (max.x < extent[i].x)`
  - line 164, `lt_to_le`: `if (max.y < extent[i].y)`

Commit message: `refactor(MagickCore/shear.c): simplify CropToFitImage`

#### Step 7: `ShearImage` (line 1581)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 7 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1604, `ne_to_eq`: `if ((x_shear != 0.0) && (fmod(x_shear,90.0) == 0.0))`
  - line 1606, `ne_to_eq`: `if ((y_shear != 0.0) && (fmod(y_shear,90.0) == 0.0))`
  - line 1616, `eq_to_ne`: `if ((shear.x == 0.0) && (shear.y == 0.0))`
  - line 1616, `eq_to_ne`: `if ((shear.x == 0.0) && (shear.y == 0.0))`
  - line 1631, `sub_to_add`: `image->rows)-image->columns)/2.0-0.5));`
  - line 1633, `sub_to_add`: `bounds.width)-image->rows)/2.0-0.5));`
  - and 1 more (`tools/oracle/mutate.py --function ShearImage`)
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify ShearImage`

#### Step 8: `DeskewImage` (line 558)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/shear.c): simplify DeskewImage`

### Wave 3

#### Step 9: `GetImageBackgroundColor` (line 497)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

#### Step 10: `ShearRotateImage` (line 1714)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/shear.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/shear.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/shear.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
