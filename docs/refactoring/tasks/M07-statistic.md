# M07 - refactor `MagickCore/statistic.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.92** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 3159 lines |
| Functions with findings | 19 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/statistic.c
```

The score must read 1.92. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 2 |
| Bumpy Road Ahead | 12 |
| Deep, Nested Complexity | 8 |
| Overall Code Complexity | file |
| Complex Method | 11 |
| Complex Conditional | 1 |
| Code Duplication | 5 |
| Excess Number of Function Arguments | 3 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `EvaluateImages` | 478 | 68 | 6 | 14 | public | 4 | 46 | 87 of 102 |
| 2 | `GetImageStatistics` | 2026 | 53 | 6 | 15 | public | - | 328 | 114 of 132 |
| 3 | `PolynomialImage` | 2421 | 29 | 5 | 6 | public | 2 | 2 | 33 of 43 |
| 4 | `GetImageMoments` | 1441 | 28 | 4 | 6 | public | - | 27 | 212 of 235 |
| 5 | `EvaluateImage` | 828 | 18 | 4 | 3 | public | 2 | 207 | 17 of 19 |
| 6 | `StatisticImage` | 2919 | - | 6 | 4 | public | 2 | 113 | 54 of 59 |
| 7 | `GetImageRange` | 1841 | 15 | 4 | 2 | public | 2 | 101 | 15 of 21 |
| 8 | `ApplyEvaluateOperator` | 241 | 45 | - | - | static | - | 243 | 54 of 58 |
| 9 | `FunctionImage` | 1069 | - | 4 | 3 | public | 2 | 70 | 14 of 16 |
| 10 | `GetMedianPixel` | 1961 | 14 | - | 3 | static | - | 328 | 22 of 30 |
| 11 | `GetImagePerceptualHash` | 1728 | 11 | - | 2 | public | - | 27 | 17 of 19 |
| 12 | `ApplyFunction` | 971 | 21 | - | - | static | - | 70 | 46 of 47 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `EvaluateImages` (line 478)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 14 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 4 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 15 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify EvaluateImages`

#### Step 2: `GetImageStatistics` (line 2026)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 15 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2138, `gt_to_le`: `if (cs->depth > channel_statistics[CompositePixelChannel].depth)`
  - base line 2205, `gt_to_ge`: `if (cs->area > 1.0)`
  - base line 2218, `gt_to_ge`: `if (cs->area > 1.0)`
  - base line 2274, `div_to_mul`: `channel_statistics[CompositePixelChannel].entropy+=((double) entropy/`
- 14 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify GetImageStatistics`

#### Step 3: `PolynomialImage` (line 2421)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 6 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 2 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- 10 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify PolynomialImage`

#### Step 4: `GetImageMoments` (line 1441)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 6 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1632, `ge_to_gt`: `if (fabs(M20[c]-M02[c]) >= 0.0)`
  - base line 1634, `lt_to_le`: `if ((M20[c]-M02[c]) < 0.0)`
- 21 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify GetImageMoments`

### Wave 2

#### Step 5: `EvaluateImage` (line 828)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify EvaluateImage`

#### Step 6: `StatisticImage` (line 2919)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 5 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify StatisticImage`

#### Step 7: `GetImageRange` (line 1841)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 6 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify GetImageRange`

#### Step 8: `ApplyEvaluateOperator` (line 241)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify ApplyEvaluateOperator`

### Wave 3

#### Step 9: `FunctionImage` (line 1069)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify FunctionImage`

#### Step 10: `GetMedianPixel` (line 1961)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1977, `add_to_sub`: `l = low+1,`
  - base line 2000, `lt_to_le`: `if (h < l)`
  - base line 2005, `le_to_lt`: `if (h <= median)`
  - base line 2007, `ge_to_gt`: `if (h >= median)`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify GetMedianPixel`

#### Step 11: `GetImagePerceptualHash` (line 1728)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify GetImagePerceptualHash`

#### Step 12: `ApplyFunction` (line 971)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe A (parameter object)** - 5 arguments; the function is `static`, so check that its address is never taken.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/statistic.c): simplify ApplyFunction`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/statistic.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/statistic.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/statistic.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
