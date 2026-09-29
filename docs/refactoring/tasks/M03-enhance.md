# M03 - refactor `MagickCore/enhance.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **2.12** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 4738 lines |
| Functions with findings | 43 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/enhance.c
```

The score must read 2.12. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Bumpy Road Ahead | 23 |
| Deep, Nested Complexity | 6 |
| Overall Code Complexity | file |
| Complex Method | 26 |
| Complex Conditional | 3 |
| Code Duplication | 15 |
| Large Method | 17 |
| Excess Number of Function Arguments | 21 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `ContrastStretchImage` | 1558 | 39 | 4 | 8 | public | 2 | 160 | 10 of 12 |
| 2 | `EqualizeImage` | 2053 | 26 | 4 | 5 | public | 2 | 38 | 10 of 11 |
| 3 | `NegateImage` | 3953 | 24 | 4 | 5 | public | 2 | 80 | 2 of 2 |
| 4 | `ClipCLAHEHistogram` | 303 | 15 | 4 | 4 | static | - | 12 | 2 of 2 |
| 5 | `CLAHEImage` | 620 | 30 | - | 4 | public | - | 12 | 2 of 2 |
| 6 | `ClutImage` | 840 | 25 | - | 4 | public | 2 | 1 | 1 of 2 |
| 7 | `HaldClutImage` | 2699 | 30 | - | 3 | public | 2 | 1 | 2 of 3 |
| 8 | `ModulateImage` | 3645 | 22 | - | 4 | public | 2 | 16 | 3 of 3 |
| 9 | `GrayscaleImage` | 2487 | 19 | - | 4 | public | 2 | 46 | - |
| 10 | `WhiteBalanceImage` | 4448 | 20 | - | 3 | public | 2 | 12 | 0 of 1 |
| 11 | `EnhanceImage` | 1858 | 17 | - | 3 | public | 2 | 13 | 4 of 4 |
| 12 | `GammaImage` | 2335 | 17 | - | 3 | public | 2 | 5 | 3 of 3 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `ContrastStretchImage` (line 1558)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 8 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1709, `lt_to_le`: `if (j < (ssize_t) black[i])`
  - base line 1735, `add_to_sub`: `image->colormap[j].red))+(size_t) i];`

Commit message: `refactor(MagickCore/enhance.c): simplify ContrastStretchImage`

#### Step 2: `EqualizeImage` (line 2053)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify EqualizeImage`

#### Step 3: `NegateImage` (line 3953)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify NegateImage`

#### Step 4: `ClipCLAHEHistogram` (line 303)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/enhance.c): simplify ClipCLAHEHistogram`

### Wave 2

#### Step 5: `CLAHEImage` (line 620)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify CLAHEImage`

#### Step 6: `ClutImage` (line 840)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 889, `sub_to_add`: `((double) clut_image->columns-adjust)/MaxMap,(double) i*`

Commit message: `refactor(MagickCore/enhance.c): simplify ClutImage`

#### Step 7: `HaldClutImage` (line 2699)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 1 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2844, `ne_to_eq`: `(image->alpha_trait != UndefinedPixelTrait))`

Commit message: `refactor(MagickCore/enhance.c): simplify HaldClutImage`

#### Step 8: `ModulateImage` (line 3645)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify ModulateImage`

### Wave 3

#### Step 9: `GrayscaleImage` (line 2487)

- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify GrayscaleImage`

#### Step 10: `WhiteBalanceImage` (line 4448)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/enhance.c): simplify WhiteBalanceImage`

#### Step 11: `EnhanceImage` (line 1858)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/enhance.c): simplify EnhanceImage`

#### Step 12: `GammaImage` (line 2335)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 5 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.

Commit message: `refactor(MagickCore/enhance.c): simplify GammaImage`

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
