# M04 - refactor `MagickCore/morphology.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **1.53** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 4765 lines |
| Functions with findings | 12 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/morphology.c
```

The score must read 1.53. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 3 |
| Bumpy Road Ahead | 11 |
| Deep, Nested Complexity | 7 |
| Overall Code Complexity | file |
| Complex Method | 9 |
| Complex Conditional | 2 |
| Excess Number of Function Arguments | 3 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `AcquireKernelBuiltIn` | 962 | 294 | 5 | 25 | public | - | 2290 | 28 of 34 |
| 2 | `MorphologyPrimitiveDirect` | 3216 | 75 | 8 | 14 | static | 2 | 84 | 8 of 10 |
| 3 | `MorphologyPrimitive` | 2540 | - | 9 | 17 | static | 4 | 2279 | 10 of 11 |
| 4 | `RotateKernelInfo` | 4232 | 45 | 4 | 5 | static | - | 1378 | 3 of 6 |
| 5 | `MorphologyApply` | 3608 | - | 6 | 10 | public | - | 2363 | 8 of 9 |
| 6 | `ParseKernelArray` | 219 | 38 | - | 5 | static | - | 1053 | 1 of 1 |
| 7 | `ParseKernelName` | 380 | 39 | - | 2 | static | - | 2290 | 2 of 2 |
| 8 | `MorphologyImage` | 4103 | - | 4 | 4 | public | - | 2363 | 2 of 3 |
| 9 | `AcquireKernelInfo` | 497 | 12 | - | 3 | public | - | 2415 | 1 of 1 |
| 10 | `ScaleKernelInfo` | 4545 | 13 | - | 2 | public | - | 568 | 0 of 2 |
| 11 | `SameKernelInfo` | 2370 | 11 | - | - | static | - | 336 | 1 of 1 |
| 12 | `ShowKernelInfo` | 4632 | 9 | 4 | 2 | public | - | 0 | - |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `AcquireKernelBuiltIn` (line 962)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 25 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 1067, `ne_to_eq`: `else if ( (type != DoGKernel) || (sigma >= sigma2) )`
  - line 1582, `lt_to_le`: `if ( args->rho < 1.0 || args->sigma < 1.0 )`
  - line 1606, `lt_to_le`: `if (args->rho < 1.0)`
  - line 1705, `mul_to_div`: `kernel->width = CastDoubleToSizeT(args->rho)*2+1;`
- 2 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/morphology.c): simplify AcquireKernelBuiltIn`

#### Step 2: `MorphologyPrimitiveDirect` (line 3216)

- **Recipe G (guard clauses)** - nesting is 8, target is under 4.
- **Recipe E (extract function)** - 14 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 3530, `lt_to_le`: `if (((double) pixels[i]+(*k)) < pixel)`
  - line 3571, `sub_to_add`: `if (fabs(pixel-(double) q[i]) > MagickEpsilon)`

Commit message: `refactor(MagickCore/morphology.c): simplify MorphologyPrimitiveDirect`

#### Step 3: `MorphologyPrimitive` (line 2540)

- **Recipe G (guard clauses)** - nesting is 9, target is under 4.
- **Recipe E (extract function)** - 17 nested blocks; each bump is a missing function.
- **Recipe A (parameter object)** - 6 arguments; the function is `static`, so check that its address is never taken.
- Contains 4 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 3036, `lt_to_le`: `if ((double) pixels[i] < minimum)`

Commit message: `refactor(MagickCore/morphology.c): simplify MorphologyPrimitive`

#### Step 4: `RotateKernelInfo` (line 4232)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4245, `lt_to_le`: `if ( angle < 0 )`
  - line 4276, `le_to_lt`: `if ( 135.0 < angle && angle <= 225.0 )`
  - line 4286, `le_to_lt`: `if ( 22.5 < fmod(angle,90.0) && fmod(angle,90.0) <= 67.5 )`

Commit message: `refactor(MagickCore/morphology.c): simplify RotateKernelInfo`

### Wave 2

#### Step 5: `MorphologyApply` (line 3608)

- **Recipe G (guard clauses)** - nesting is 6, target is under 4.
- **Recipe E (extract function)** - 10 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/morphology.c): simplify MorphologyApply`

#### Step 6: `ParseKernelArray` (line 219)

- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/morphology.c): simplify ParseKernelArray`

#### Step 7: `ParseKernelName` (line 380)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/morphology.c): simplify ParseKernelName`

#### Step 8: `MorphologyImage` (line 4103)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4184, `lt_to_le`: `if ( parse < 0 )`

Commit message: `refactor(MagickCore/morphology.c): simplify MorphologyImage`

### Wave 3

#### Step 9: `AcquireKernelInfo` (line 497)

- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/morphology.c): simplify AcquireKernelInfo`

#### Step 10: `ScaleKernelInfo` (line 4545)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 4592, `ge_to_lt`: `kernel->minimum *= (kernel->minimum >= 0.0) ? pos_scale : neg_scale;`
  - line 4595, `lt_to_ge`: `if ( scaling_factor < MagickEpsilon ) {`

Commit message: `refactor(MagickCore/morphology.c): simplify ScaleKernelInfo`

#### Step 11: `SameKernelInfo` (line 2370)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.

Commit message: `refactor(MagickCore/morphology.c): simplify SameKernelInfo`

#### Step 12: `ShowKernelInfo` (line 4632)

- **No oracle case executes this function. Do not change it.** Report it so cases can be added.

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/morphology.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/morphology.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/morphology.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
