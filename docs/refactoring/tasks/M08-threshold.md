# M08 - refactor `MagickCore/threshold.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.89** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 2649 lines |
| Functions with findings | 15 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/threshold.c
```

The score must read 1.89. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 2 |
| Bumpy Road Ahead | 14 |
| Deep, Nested Complexity | 11 |
| Overall Code Complexity | file |
| Complex Method | 13 |
| Complex Conditional | 4 |
| Excess Number of Function Arguments | 2 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `OrderedDitherImage` | 1893 | 35 | 4 | 7 | public | 2 | 72 | 6 of 8 |
| 2 | `ColorThresholdImage` | 1217 | 27 | 4 | 4 | public | 2 | 12 | 2 of 2 |
| 3 | `BlackThresholdImage` | 927 | 26 | 4 | 4 | public | 2 | 12 | 7 of 9 |
| 4 | `WhiteThresholdImage` | 2518 | 26 | 4 | 4 | public | 2 | 12 | 4 of 5 |
| 5 | `PerceptibleImage` | 2092 | 19 | 4 | 4 | public | 2 | 3 | 3 of 3 |
| 6 | `KapurThreshold` | 392 | 17 | 4 | 4 | static | - | 12 | 9 of 11 |
| 7 | `ClampImage` | 1087 | 16 | 4 | 4 | public | 2 | 117 | 2 of 3 |
| 8 | `RandomThresholdImage` | 2231 | 19 | 4 | 3 | public | 2 | 12 | 3 of 4 |
| 9 | `BilevelImage` | 805 | 18 | 4 | 3 | public | 2 | 138 | 2 of 2 |
| 10 | `AdaptiveThresholdImage` | 182 | - | 5 | 5 | public | 2 | 12 | 8 of 8 |
| 11 | `TriangleThreshold` | 570 | 15 | - | 5 | static | - | 12 | 11 of 11 |
| 12 | `RangeThresholdImage` | 2377 | - | 4 | 3 | public | 2 | 12 | 5 of 7 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `OrderedDitherImage` (line 1893)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 7 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify OrderedDitherImage`

#### Step 2: `ColorThresholdImage` (line 1217)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/threshold.c): simplify ColorThresholdImage`

#### Step 3: `BlackThresholdImage` (line 927)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 980, `ne_to_eq`: `if ((flags & ChiValue) != 0)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify BlackThresholdImage`

#### Step 4: `WhiteThresholdImage` (line 2518)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify WhiteThresholdImage`

### Wave 2

#### Step 5: `PerceptibleImage` (line 2092)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 3 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.

Commit message: `refactor(MagickCore/threshold.c): simplify PerceptibleImage`

#### Step 6: `KapurThreshold` (line 392)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 452, `gt_to_ge`: `if (histogram[i] > epsilon)`
  - line 461, `gt_to_ge`: `if ((1.0-cumulative_histogram[j]) > epsilon)`

Commit message: `refactor(MagickCore/threshold.c): simplify KapurThreshold`

#### Step 7: `ClampImage` (line 1087)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify ClampImage`

#### Step 8: `RandomThresholdImage` (line 2231)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 2315, `mul_to_div`: `threshold=((double) QuantumRange*`

Commit message: `refactor(MagickCore/threshold.c): simplify RandomThresholdImage`

### Wave 3

#### Step 9: `BilevelImage` (line 805)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/threshold.c): simplify BilevelImage`

#### Step 10: `AdaptiveThresholdImage` (line 182)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/threshold.c): simplify AdaptiveThresholdImage`

#### Step 11: `TriangleThreshold` (line 570)

- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/threshold.c): simplify TriangleThreshold`

#### Step 12: `RangeThresholdImage` (line 2377)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 2449, `ge_to_gt`: `if ((pixel >= low_black) && (pixel < low_white))`
  - line 2456, `le_to_lt`: `if ((pixel > high_white) && (pixel <= high_black))`

Commit message: `refactor(MagickCore/threshold.c): simplify RangeThresholdImage`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/threshold.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/threshold.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/threshold.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
