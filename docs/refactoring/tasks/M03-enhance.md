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
| 1 | `EqualizeImage` | 2053 | 45 | 4 | 12 | public | 2 | 38 | 10 of 11 |
| 2 | `ContrastStretchImage` | 1558 | 49 | 4 | 10 | public | 2 | 160 | 10 of 12 |
| 3 | `NegateImage` | 3953 | 38 | 5 | 8 | public | 2 | 76 | 2 of 2 |
| 4 | `GrayscaleImage` | 2487 | 33 | 4 | 5 | public | 2 | 46 | - |
| 5 | `GammaImage` | 2335 | 25 | 4 | 5 | public | 2 | 5 | 3 of 3 |
| 6 | `ModulateImage` | 3645 | 44 | - | 5 | public | 2 | 16 | 3 of 3 |
| 7 | `ClipCLAHEHistogram` | 303 | 15 | 4 | 4 | static | - | 12 | 2 of 2 |
| 8 | `CLAHEImage` | 620 | 30 | - | 4 | public | - | 12 | 2 of 2 |
| 9 | `SigmoidalContrastImage` | 4280 | - | 4 | 5 | public | 2 | 24 | 3 of 4 |
| 10 | `ClutImage` | 840 | 25 | - | 4 | public | 2 | 1 | 1 of 2 |
| 11 | `HaldClutImage` | 2699 | 30 | - | 3 | public | 2 | 1 | 2 of 3 |
| 12 | `WhiteBalanceImage` | 4448 | 22 | - | 4 | public | 2 | 12 | 0 of 1 |

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
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify EqualizeImage`

#### Step 2: `ContrastStretchImage` (line 1558)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 10 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1709, `lt_to_le`: `if (j < (ssize_t) black[i])`
  - line 1735, `add_to_sub`: `image->colormap[j].red))+(size_t) i];`

Commit message: `refactor(MagickCore/enhance.c): simplify ContrastStretchImage`

#### Step 3: `NegateImage` (line 3953)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 8 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify NegateImage`

#### Step 4: `GrayscaleImage` (line 2487)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify GrayscaleImage`

### Wave 2

#### Step 5: `GammaImage` (line 2335)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 5 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.

Commit message: `refactor(MagickCore/enhance.c): simplify GammaImage`

#### Step 6: `ModulateImage` (line 3645)

- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify ModulateImage`

#### Step 7: `ClipCLAHEHistogram` (line 303)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/enhance.c): simplify ClipCLAHEHistogram`

#### Step 8: `CLAHEImage` (line 620)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify CLAHEImage`

### Wave 3

#### Step 9: `SigmoidalContrastImage` (line 4280)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4314, `lt_to_le`: `if (contrast < MagickEpsilon)`

Commit message: `refactor(MagickCore/enhance.c): simplify SigmoidalContrastImage`

#### Step 10: `ClutImage` (line 840)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 889, `sub_to_add`: `((double) clut_image->columns-adjust)/MaxMap,(double) i*`

Commit message: `refactor(MagickCore/enhance.c): simplify ClutImage`

#### Step 11: `HaldClutImage` (line 2699)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 2844, `ne_to_eq`: `(image->alpha_trait != UndefinedPixelTrait))`

Commit message: `refactor(MagickCore/enhance.c): simplify HaldClutImage`

#### Step 12: `WhiteBalanceImage` (line 4448)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

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
