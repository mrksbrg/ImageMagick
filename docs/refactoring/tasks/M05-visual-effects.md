# M05 - refactor `MagickCore/visual-effects.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.55** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 3790 lines |
| Functions with findings | 21 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/visual-effects.c
```

The score must read 1.55. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 3 |
| Bumpy Road Ahead | 18 |
| Deep, Nested Complexity | 12 |
| Overall Code Complexity | file |
| Complex Method | 15 |
| Complex Conditional | 8 |
| Excess Number of Function Arguments | 9 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `WaveletDenoiseImage` | 3511 | 41 | 4 | 9 | public | 2 | 12 | 7 of 8 |
| 2 | `MorphImages` | 1156 | 32 | 6 | 6 | public | 1 | 3 | 10 of 12 |
| 3 | `ColorMatrixImage` | 713 | 32 | 4 | 5 | public | 2 | 36 | 1 of 2 |
| 4 | `ImplodeImage` | 935 | 29 | 5 | 4 | public | 2 | 26 | 6 of 7 |
| 5 | `PlasmaImageProxy` | 1402 | - | 4 | 10 | static | - | 4 | 13 of 17 |
| 6 | `ColorizeImage` | 530 | 30 | 4 | 4 | public | 2 | 25 | 4 of 5 |
| 7 | `SwirlImage` | 2784 | 25 | 5 | 4 | public | 2 | 14 | 5 of 5 |
| 8 | `SolarizeImage` | 2335 | 21 | 4 | 4 | public | 2 | 14 | 5 of 7 |
| 9 | `AddNoiseImage` | 138 | 22 | 4 | 3 | public | 2 | 27 | 2 of 2 |
| 10 | `TintImage` | 2999 | 24 | - | 3 | public | 2 | 12 | 2 of 3 |
| 11 | `WaveImage` | 3298 | 21 | - | 3 | public | 2 | 13 | 4 of 4 |
| 12 | `SepiaToneImage` | 1871 | 20 | - | 3 | public | 2 | 12 | 1 of 1 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `WaveletDenoiseImage` (line 3511)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 9 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/visual-effects.c): simplify WaveletDenoiseImage`

#### Step 2: `MorphImages` (line 1156)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 6 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 1 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 3 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1348, `post_inc_to_post_dec`: `scene++;`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/visual-effects.c): simplify MorphImages`

#### Step 3: `ColorMatrixImage` (line 713)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 847, `gt_to_le`: `height=color_matrix->height > 6 ? 6UL : color_matrix->height;`

Commit message: `refactor(MagickCore/visual-effects.c): simplify ColorMatrixImage`

#### Step 4: `ImplodeImage` (line 935)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/visual-effects.c): simplify ImplodeImage`

### Wave 2

#### Step 5: `PlasmaImageProxy` (line 1402)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 10 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe A (parameter object)** - 9 arguments; the function is `static`, so check that its address is never taken.
- Only 4 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1429, `sub_to_add`: `if ((fabs(segment->x2-segment->x1) < MagickEpsilon) &&`
  - line 1478, `sub_to_add`: `if ((fabs(segment->x1-x_mid) >= MagickEpsilon) ||`
  - line 1531, `sub_to_add`: `if ((fabs(segment->x1-x_mid) >= MagickEpsilon) ||`
  - line 1610, `lt_to_le`: `(fabs(segment->y2-segment->y1) < 3.0))`

Commit message: `refactor(MagickCore/visual-effects.c): simplify PlasmaImageProxy`

#### Step 6: `ColorizeImage` (line 530)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 597, `ne_to_eq`: `if ((flags & PsiValue) != 0)`

Commit message: `refactor(MagickCore/visual-effects.c): simplify ColorizeImage`

#### Step 7: `SwirlImage` (line 2784)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/visual-effects.c): simplify SwirlImage`

#### Step 8: `SolarizeImage` (line 2335)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/visual-effects.c): simplify SolarizeImage`

### Wave 3

#### Step 9: `AddNoiseImage` (line 138)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/visual-effects.c): simplify AddNoiseImage`

#### Step 10: `TintImage` (line 2999)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 3082, `sub_to_add`: `color_vector.alpha=(double) (color_vector.alpha*tint->alpha/100.0-intensity);`

Commit message: `refactor(MagickCore/visual-effects.c): simplify TintImage`

#### Step 11: `WaveImage` (line 3298)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/visual-effects.c): simplify WaveImage`

#### Step 12: `SepiaToneImage` (line 1871)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/visual-effects.c): simplify SepiaToneImage`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/visual-effects.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/visual-effects.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/visual-effects.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
