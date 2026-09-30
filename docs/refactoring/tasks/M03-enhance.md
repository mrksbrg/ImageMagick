# M03 - refactor `MagickCore/enhance.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.53** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 4597 lines |
| Functions with findings | 34 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/enhance.c
```

The score must read 1.53. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 3 |
| Bumpy Road Ahead | 20 |
| Deep, Nested Complexity | 10 |
| Overall Code Complexity | file |
| Complex Method | 17 |
| Complex Conditional | 3 |
| Code Duplication | 10 |
| Large Method | 19 |
| Excess Number of Function Arguments | 17 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `EqualizeImage` | 2053 | 45 | 4 | 12 | public | 2 | 38 | 74 of 84 |
| 2 | `ContrastStretchImage` | 1558 | 49 | 4 | 10 | public | 2 | 160 | 79 of 94 |
| 3 | `NegateImage` | 3953 | 38 | 5 | 8 | public | 2 | 80 | 25 of 28 |
| 4 | `GrayscaleImage` | 2487 | 33 | 4 | 5 | public | 2 | 46 | 31 of 33 |
| 5 | `GammaImage` | 2335 | 25 | 4 | 5 | public | 2 | 5 | 22 of 25 |
| 6 | `ModulateImage` | 3645 | 44 | - | 5 | public | 2 | 16 | 17 of 22 |
| 7 | `ClipCLAHEHistogram` | 303 | 15 | 4 | 4 | static | - | 12 | 29 of 32 |
| 8 | `CLAHEImage` | 620 | 30 | - | 4 | public | - | 12 | 44 of 54 |
| 9 | `SigmoidalContrastImage` | 4280 | - | 4 | 5 | public | 2 | 24 | 27 of 34 |
| 10 | `ClutImage` | 840 | 25 | - | 4 | public | 2 | 1 | 22 of 33 |
| 11 | `HaldClutImage` | 2699 | 30 | - | 3 | public | 2 | 1 | 43 of 50 |
| 12 | `WhiteBalanceImage` | 4448 | 22 | - | 4 | public | 2 | 12 | 23 of 26 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `EqualizeImage` (line 2053)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 12 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2142, `post_inc_to_post_dec`: `ClampToQuantum(intensity))+(size_t) i]++;`
  - base line 2202, `add_to_sub`: `ClampToQuantum(image->colormap[j].red))+channel];`
  - base line 2222, `ne_to_eq`: `if ((GetPixelAlphaTraits(image) & UpdatePixelTrait) != 0)`
- 7 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify EqualizeImage`

#### Step 2: `ContrastStretchImage` (line 1558)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 10 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 7 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1679, `gt_to_ge`: `if (intensity > black_point)`
  - base line 1687, `gt_to_ge`: `if (intensity > ((double) image->columns*image->rows-white_point))`
  - base line 1709, `lt_to_le`: `if (j < (ssize_t) black[i])`
  - base line 1710, `mul_to_div`: `stretch_map[(ssize_t) GetPixelChannels(image)*j+i]=(Quantum) 0;`
  - base line 1712, `gt_to_ge`: `if (j > (ssize_t) white[i])`
  - base line 1735, `add_to_sub`: `image->colormap[j].red))+(size_t) i];`
  - and 1 more (`tools/oracle/mutate.py --function ContrastStretchImage`)
- 8 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify ContrastStretchImage`

#### Step 3: `NegateImage` (line 3953)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 8 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify NegateImage`

#### Step 4: `GrayscaleImage` (line 2487)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify GrayscaleImage`

### Wave 2

#### Step 5: `GammaImage` (line 2335)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 5 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2376, `eq_to_ne`: `if (image->storage_class == PseudoClass)`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify GammaImage`

#### Step 6: `ModulateImage` (line 3645)

- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 3704, `ne_to_eq`: `if (artifact != (const char *) NULL)`
  - base line 3708, `ne_to_eq`: `if (artifact != (const char *) NULL)`
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify ModulateImage`

#### Step 7: `ClipCLAHEHistogram` (line 303)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 322, `gt_to_ge`: `if (histogram[i] > clip_limit)`
  - base line 362, `lt_to_le`: `if (step < 1)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify ClipCLAHEHistogram`

#### Step 8: `CLAHEImage` (line 620)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 669, `lt_to_le`: `if (tile_info.width < 2)`
  - base line 674, `lt_to_le`: `if (tile_info.height < 2)`
  - base line 740, `eq_to_ne`: `status=CLAHE(&clahe_info,&tile_info,&range_info,number_bins == 0 ?`
  - base line 749, `mul_to_div`: `n=clahe_info.width*(size_t) (tile_info.y/2);`
  - base line 790, `eq_to_ne`: `if (TransformImageColorspace(image,colorspace,exception) == MagickFalse)`
- 5 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify CLAHEImage`

### Wave 3

#### Step 9: `SigmoidalContrastImage` (line 4280)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 4314, `lt_to_le`: `if (contrast < MagickEpsilon)`
  - base line 4336, `ne_to_eq`: `if ((GetPixelAlphaTraits(image) & UpdatePixelTrait) != 0)`
  - base line 4352, `ne_to_eq`: `if ((GetPixelAlphaTraits(image) & UpdatePixelTrait) != 0)`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify SigmoidalContrastImage`

#### Step 10: `ClutImage` (line 840)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 9 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 871, `ne_to_eq`: `if ((IsGrayColorspace(image->colorspace) != MagickFalse) &&`
  - base line 872, `eq_to_ne`: `(IsGrayColorspace(clut_image->colorspace) == MagickFalse))`
  - base line 888, `mul_to_div`: `status=InterpolatePixelInfo(clut_image,clut_view,method,(double) i*`
  - base line 889, `sub_to_add`: `((double) clut_image->columns-adjust)/MaxMap,(double) i*`
  - base line 889, `div_to_mul`: `((double) clut_image->columns-adjust)/MaxMap,(double) i*`
  - base line 939, `ne_to_eq`: `if ((traits & UpdatePixelTrait) != 0)`
  - and 3 more (`tools/oracle/mutate.py --function ClutImage`)
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify ClutImage`

#### Step 11: `HaldClutImage` (line 2699)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2746, `ne_to_eq`: `if (image->colorspace != hald_image->colorspace)`
  - base line 2840, `ne_to_eq`: `if (((GetPixelBlackTraits(image) & UpdatePixelTrait) != 0) &&`
  - base line 2841, `eq_to_ne`: `(image->colorspace == CMYKColorspace))`
  - base line 2843, `ne_to_eq`: `if (((GetPixelAlphaTraits(image) & UpdatePixelTrait) != 0) &&`
  - base line 2844, `ne_to_eq`: `(image->alpha_trait != UndefinedPixelTrait))`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify HaldClutImage`

#### Step 12: `WhiteBalanceImage` (line 4448)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 4595, `ne_to_eq`: `return(status != 0 ? MagickTrue : MagickFalse);`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify WhiteBalanceImage`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/enhance.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/enhance.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/enhance.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
