# M10 - refactor `MagickCore/segment.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **2.30** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 1935 lines |
| Functions with findings | 9 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/segment.c
```

The score must read 2.30. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 3 |
| Bumpy Road Ahead | 8 |
| Deep, Nested Complexity | 5 |
| Overall Code Complexity | file |
| Complex Method | 4 |
| Complex Conditional | 4 |
| Excess Number of Function Arguments | 4 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `ConsolidateCrossings` | 703 | 28 | 5 | 7 | static | - | 26 | 3 of 5 |
| 2 | `Classify` | 246 | - | 5 | 11 | static | 3 | 26 | 10 of 10 |
| 3 | `OptimalTau` | 1509 | - | 4 | 5 | static | - | 26 | 2 of 3 |
| 4 | `InitializeIntervalTree` | 1343 | 10 | 5 | 2 | static | - | 26 | 3 of 3 |
| 5 | `ZeroCrossHistogram` | 1897 | 9 | - | 3 | static | - | 26 | 1 of 1 |
| 6 | `DefineRegion` | 820 | - | - | 2 | static | - | 26 | 1 of 1 |
| 7 | `ScaleSpace` | 1718 | - | - | 2 | static | - | 26 | 1 of 1 |
| 8 | `SegmentImage` | 1796 | 10 | - | - | public | - | 26 | 1 of 1 |
| 9 | `GetImageDynamicThreshold` | 933 | - | 4 | 8 | public | - | 0 | - |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `ConsolidateCrossings` (line 703)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 7 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 770, `post_inc_to_post_dec`: `count++;`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/segment.c): simplify ConsolidateCrossings`

#### Step 2: `Classify` (line 246)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 11 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe A (parameter object)** - 6 arguments; the function is `static`, so check that its address is never taken.
- Contains 3 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.

Commit message: `refactor(MagickCore/segment.c): simplify Classify`

#### Step 3: `OptimalTau` (line 1509)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 6 arguments; the function is `static`, so check that its address is never taken.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1651, `le_to_gt`: `for (x=node->left; x <= node->right; x++)`

Commit message: `refactor(MagickCore/segment.c): simplify OptimalTau`

#### Step 4: `InitializeIntervalTree` (line 1343)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/segment.c): simplify InitializeIntervalTree`

### Wave 2

#### Step 5: `ZeroCrossHistogram` (line 1897)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/segment.c): simplify ZeroCrossHistogram`

#### Step 6: `DefineRegion` (line 820)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.

Commit message: `refactor(MagickCore/segment.c): simplify DefineRegion`

#### Step 7: `ScaleSpace` (line 1718)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.

Commit message: `refactor(MagickCore/segment.c): simplify ScaleSpace`

#### Step 8: `SegmentImage` (line 1796)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/segment.c): simplify SegmentImage`

### Wave 3

#### Step 9: `GetImageDynamicThreshold` (line 933)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/segment.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/segment.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/segment.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
