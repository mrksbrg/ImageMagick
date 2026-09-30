# M12 - refactor `MagickCore/fourier.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **3.08** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 1627 lines |
| Functions with findings | 11 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/fourier.c
```

The score must read 3.08. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Bumpy Road Ahead | 8 |
| Deep, Nested Complexity | 2 |
| Overall Code Complexity | file |
| Complex Method | 9 |
| Complex Conditional | 4 |
| Excess Number of Function Arguments | 6 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `ComplexImages` | 134 | 35 | 4 | 3 | public | 2 | 7 | 32 of 37 |
| 2 | `ForwardFourierTransformImage` | 913 | 19 | - | 2 | public | 6 | 0 | - |
| 3 | `InverseFourierTransformImage` | 1504 | 16 | - | - | public | 6 | 0 | - |
| 4 | `InverseFourier` | 1115 | 34 | - | 8 | not compiled | - | - | - |
| 5 | `ForwardFourier` | 506 | 30 | - | 6 | not compiled | - | - | - |
| 6 | `InverseFourierTransform` | 1320 | 20 | 4 | 3 | not compiled | - | - | - |
| 7 | `ForwardFourierTransform` | 694 | 23 | - | 5 | not compiled | - | - | - |
| 8 | `RollFourier` | 415 | 10 | - | 2 | not compiled | - | - | - |
| 9 | `ForwardFourierTransformChannel` | 855 | 11 | - | - | not compiled | - | - | - |
| 10 | `ForwardQuadrantSwap` | 461 | - | - | 2 | not compiled | - | - | - |
| 11 | `InverseFourierTransformChannel` | 1472 | - | - | - | not compiled | - | - | - |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `ComplexImages` (line 134)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 7 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 227, `ne_to_eq`: `(images->next->next->next != (Image *) NULL))`
  - base line 314, `add_to_sub`: `cr=MagickSafeReciprocal(br*br+bi*bi+snr)*(ar*br+ai*bi);`
  - base line 332, `sub_to_add`: `cr=ar*cos(2.0*MagickPI*(ai-0.5));`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/fourier.c): simplify ComplexImages`

#### Step 2: `ForwardFourierTransformImage` (line 913)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

#### Step 3: `InverseFourierTransformImage` (line 1504)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

#### Step 4: `InverseFourier` (line 1115)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

### Wave 2

#### Step 5: `ForwardFourier` (line 506)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

#### Step 6: `InverseFourierTransform` (line 1320)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

#### Step 7: `ForwardFourierTransform` (line 694)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

#### Step 8: `RollFourier` (line 415)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

### Wave 3

#### Step 9: `ForwardFourierTransformChannel` (line 855)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

#### Step 10: `ForwardQuadrantSwap` (line 461)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

#### Step 11: `InverseFourierTransformChannel` (line 1472)

- **This function is not compiled in this build** (it sits in a preprocessor branch for a platform or a library that is not present). Nothing can check it here. Do not change it.

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/fourier.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/fourier.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/fourier.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
