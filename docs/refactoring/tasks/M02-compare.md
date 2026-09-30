# M02 - refactor `MagickCore/compare.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.46** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 4988 lines |
| Functions with findings | 37 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/compare.c
```

The score must read 1.46. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 1 |
| Bumpy Road Ahead | 26 |
| Deep, Nested Complexity | 24 |
| Overall Code Complexity | file |
| Complex Method | 31 |
| Complex Conditional | 3 |
| Code Duplication | 23 |
| Excess Number of Function Arguments | 10 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `GetSSIMSimularity` | 2076 | 35 | 6 | 6 | static | 2 | 20 | 74 of 77 |
| 2 | `GetDPCSimilarity` | 452 | 29 | 4 | 7 | static | 3 | 10 | 33 of 37 |
| 3 | `GetNCCSimilarity` | 1229 | 29 | 4 | 7 | static | 3 | 10 | 33 of 37 |
| 4 | `GetPHASESimilarity` | 1698 | 37 | 4 | 5 | static | 2 | 11 | 49 of 58 |
| 5 | `GetMEPPSimilarity` | 933 | 27 | 4 | 5 | static | 2 | 66 | 36 of 42 |
| 6 | `GetAESimilarity` | 307 | 26 | 4 | 5 | static | 2 | 11 | 37 of 38 |
| 7 | `GetFUZZSimilarity` | 648 | 25 | 4 | 5 | static | 2 | 10 | 37 of 39 |
| 8 | `GetMAESimilarity` | 791 | 25 | 4 | 5 | static | 2 | 10 | 35 of 36 |
| 9 | `GetMSESimilarity` | 1088 | 25 | 4 | 5 | static | 2 | 34 | 35 of 36 |
| 10 | `GetPASimilarity` | 1426 | 24 | 4 | 4 | static | 2 | 10 | 29 of 36 |
| 11 | `GetPDCSimilarity` | 1548 | 22 | 4 | 4 | static | 2 | 10 | 31 of 33 |
| 12 | `SimilarityImage` | 4712 | - | 4 | 7 | public | 2 | 3 | 26 of 33 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `GetSSIMSimularity` (line 2076)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 6 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetSSIMSimularity`

#### Step 2: `GetDPCSimilarity` (line 452)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 7 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 3 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetDPCSimilarity`

#### Step 3: `GetNCCSimilarity` (line 1229)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 7 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 3 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetNCCSimilarity`

#### Step 4: `GetPHASESimilarity` (line 1698)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1897, `sub_to_add`: `pearson=(fabs(image_sum[j]-reconstruct_sum[j]) < MagickEpsilon) ?`
- 8 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetPHASESimilarity`

### Wave 2

#### Step 5: `GetMEPPSimilarity` (line 933)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 6 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetMEPPSimilarity`

#### Step 6: `GetAESimilarity` (line 307)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetAESimilarity`

#### Step 7: `GetFUZZSimilarity` (line 648)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetFUZZSimilarity`

#### Step 8: `GetMAESimilarity` (line 791)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetMAESimilarity`

### Wave 3

#### Step 9: `GetMSESimilarity` (line 1088)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetMSESimilarity`

#### Step 10: `GetPASimilarity` (line 1426)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 7 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetPASimilarity`

#### Step 11: `GetPDCSimilarity` (line 1548)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify GetPDCSimilarity`

#### Step 12: `SimilarityImage` (line 4712)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 7 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 3 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 4892, `ge_to_gt`: `if (similarity >= channel_info.similarity)`
  - base line 4951, `ne_to_eq`: `if (similarity_threshold != DefaultSimilarityThreshold)`
  - base line 4954, `lt_to_le`: `if (channel_info.similarity < similarity_info.similarity)`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes, or read by hand and found equivalent; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/compare.c): simplify SimilarityImage`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/compare.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/compare.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/compare.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
