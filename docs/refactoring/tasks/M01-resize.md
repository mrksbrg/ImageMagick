# M01 - refactor `MagickCore/resize.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.39** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 4705 lines |
| Functions with findings | 25 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/resize.c
```

The score must read 1.39. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 3 |
| Bumpy Road Ahead | 11 |
| Deep, Nested Complexity | 6 |
| Overall Code Complexity | file |
| Complex Method | 17 |
| Complex Conditional | 17 |
| Excess Number of Function Arguments | 12 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `ScaleImage` | 4114 | 98 | 7 | 23 | public | - | 56 | 171 of 208 |
| 2 | `AcquireResizeFilter` | 804 | 69 | - | 11 | public | 1 | 949 | 60 of 73 |
| 3 | `MagnifyImage` | 2886 | 35 | 4 | 5 | public | 2 | 49 | 45 of 47 |
| 4 | `SampleImage` | 3925 | 26 | 4 | 5 | public | 1 | 68 | 32 of 34 |
| 5 | `HorizontalFilter` | 3337 | - | 5 | 5 | static | 2 | 611 | 83 of 86 |
| 6 | `VerticalFilter` | 3553 | - | 5 | 5 | static | 2 | 611 | 73 of 77 |
| 7 | `InterpolativeResizeImage` | 1750 | - | 4 | 3 | public | 2 | 44 | 23 of 28 |
| 8 | `ThumbnailImage` | 4599 | 19 | - | 3 | public | - | 78 | 20 of 26 |
| 9 | `Scale3X` | 2797 | 24 | - | 2 | static | - | 4 | 2 of 3 |
| 10 | `Fish2X` | 2445 | 31 | - | - | static | - | 4 | 8 of 12 |
| 11 | `CubicSpline` | 250 | 12 | - | 2 | static | - | 13 | 38 of 47 |
| 12 | `Epbx2X` | 2670 | 22 | - | - | static | - | 4 | 2 of 3 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `ScaleImage` (line 4114)

- **Recipe G (guard clauses)** - nesting is 7, target is under 4.
- **Recipe E (extract function)** - 23 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 15 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4249, `le_to_lt`: `if (GetPixelWriteMask(image,p) <= (QuantumRange/2))`
  - line 4278, `lt_to_le`: `(number_rows < (ssize_t) image->rows))`
  - line 4292, `le_to_lt`: `if (GetPixelWriteMask(image,p) <= (QuantumRange/2))`
  - line 4314, `post_inc_to_post_dec`: `number_rows++;`
  - line 4324, `lt_to_le`: `if ((next_row != MagickFalse) && (number_rows < (ssize_t) image->rows))`
  - line 4338, `le_to_lt`: `if (GetPixelWriteMask(image,p) <= (QuantumRange/2))`
  - and 9 more (`tools/oracle/mutate.py --function ScaleImage`)
- 22 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify ScaleImage`

#### Step 2: `AcquireResizeFilter` (line 804)

- **Recipe E (extract function)** - 11 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 1 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 12 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1032, `lt_to_le`: `if ((UndefinedFilter < option) && (option < SentinelFilter))`
  - line 1032, `lt_to_le`: `if ((UndefinedFilter < option) && (option < SentinelFilter))`
  - line 1099, `mul_to_div`: `resize_filter->coefficient[2]=MagickSafeReciprocal(Magick2PI*value*value);`
  - line 1099, `mul_to_div`: `resize_filter->coefficient[2]=MagickSafeReciprocal(Magick2PI*value*value);`
  - line 1101, `gt_to_ge`: `if ( value > 0.5 )`
  - line 1101, `gt_to_le`: `if ( value > 0.5 )`
  - and 6 more (`tools/oracle/mutate.py --function AcquireResizeFilter`)
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify AcquireResizeFilter`

#### Step 3: `MagnifyImage` (line 2886)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify MagnifyImage`

#### Step 4: `SampleImage` (line 3925)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 1 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4031, `le_to_lt`: `if (GetPixelWriteMask(sample_image,q) <= (QuantumRange/2))`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify SampleImage`

### Wave 2

#### Step 5: `HorizontalFilter` (line 3337)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 7 arguments; the function is `static`, so check that its address is never taken.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 3373, `lt_to_le`: `if (support < 0.5)`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify HorizontalFilter`

#### Step 6: `VerticalFilter` (line 3553)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 7 arguments; the function is `static`, so check that its address is never taken.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 3587, `lt_to_le`: `if (support < 0.5)`
  - line 3663, `sub_to_add`: `image->columns,(size_t) (contribution[n-1].pixel-contribution[0].pixel+1),`
  - line 3733, `mul_to_div`: `alpha=contribution[j].weight*QuantumScale*(double)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify VerticalFilter`

#### Step 7: `InterpolativeResizeImage` (line 1750)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1847, `eq_to_ne`: `if (status == MagickFalse)`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify InterpolativeResizeImage`

#### Step 8: `ThumbnailImage` (line 4599)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4635, `mul_to_div`: `x_factor=(ssize_t) (image->columns*MagickSafeReciprocal((double)`
  - line 4638, `gt_to_ge`: `if ((x_factor > 4) && (y_factor > 4))`
  - line 4638, `gt_to_ge`: `if ((x_factor > 4) && (y_factor > 4))`
  - line 4647, `gt_to_ge`: `if ((x_factor > 2) && (y_factor > 2))`
  - line 4692, `ne_to_eq`: `if (mime_type != (const char *) NULL)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify ThumbnailImage`

### Wave 3

#### Step 9: `Scale3X` (line 2797)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Only 4 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify Scale3X`

#### Step 10: `Fish2X` (line 2445)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Only 4 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 2495, `gt_to_ge`: `CopyPixels(pixels,(ssize_t) (intensities[0] > intensities[1] ? 0 : 1),result,`
  - line 2530, `gt_to_ge`: `if (ae && (!bd || intensities[1] > intensities[0]))`
  - line 2535, `gt_to_ge`: `if (bd && (!ae || intensities[0] > intensities[1]))`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify Fish2X`

#### Step 11: `CubicSpline` (line 250)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 9 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 257, `lt_to_le`: `if (x < 1.0)`
  - line 259, `lt_to_le`: `if (x < 2.0)`
  - line 268, `lt_to_le`: `if (x < 1.0)`
  - line 270, `lt_to_le`: `if (x < 2.0)`
  - line 272, `lt_to_le`: `if (x < 3.0)`
  - line 279, `lt_to_le`: `if (x < 1.0)`
  - and 3 more (`tools/oracle/mutate.py --function CubicSpline`)

Commit message: `refactor(MagickCore/resize.c): simplify CubicSpline`

#### Step 12: `Epbx2X` (line 2670)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Only 4 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/resize.c): simplify Epbx2X`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/resize.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/resize.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/resize.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
