# M06 - refactor `MagickCore/colorspace.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **2.57** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 2900 lines |
| Functions with findings | 9 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/colorspace.c
```

The score must read 2.57. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Bumpy Road Ahead | 2 |
| Deep, Nested Complexity | 2 |
| Overall Code Complexity | file |
| Complex Method | 5 |
| Complex Conditional | 3 |
| Code Duplication | 4 |
| Excess Number of Function Arguments | 4 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `TransformsRGBImage` | 1828 | 151 | 4 | 19 | static | 14 | 371 | 32 of 35 |
| 2 | `sRGBTransformImage` | 727 | 142 | 4 | 16 | static | 13 | 732 | 35 of 37 |
| 3 | `ConvertRGBToGeneric` | 416 | 30 | - | - | public | - | 448 | - |
| 4 | `ConvertGenericToRGB` | 127 | 30 | - | - | public | - | 218 | - |
| 5 | `ConvertHSLToRGB` | 312 | 9 | - | - | public | - | 34 | 6 of 7 |
| 6 | `SetImageColorspace` | 1567 | - | - | - | public | - | 2796 | - |
| 7 | `SetImageGray` | 1647 | - | - | - | public | - | 20 | 2 of 2 |
| 8 | `SetImageMonochrome` | 1704 | - | - | - | public | - | 132 | 2 of 2 |
| 9 | `ConvertRGBToHSL` | 602 | - | - | - | public | - | 81 | 5 of 5 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `TransformsRGBImage` (line 1828)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 19 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 14 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 2233, `eq_to_ne`: `if (SetImageColorspace(image,sRGBColorspace,exception) == MagickFalse)`
  - line 2511, `eq_to_ne`: `if (SetImageColorspace(image,sRGBColorspace,exception) == MagickFalse)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/colorspace.c): simplify TransformsRGBImage`

#### Step 2: `sRGBTransformImage` (line 727)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 16 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 13 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 901, `eq_to_ne`: `if (SetImageColorspace(image,colorspace,exception) == MagickFalse)`
- 1 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/colorspace.c): simplify sRGBTransformImage`

#### Step 3: `ConvertRGBToGeneric` (line 416)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify ConvertRGBToGeneric`

#### Step 4: `ConvertGenericToRGB` (line 127)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify ConvertGenericToRGB`

### Wave 2

#### Step 5: `ConvertHSLToRGB` (line 312)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 328, `le_to_lt`: `if (lightness <= 0.5)`

Commit message: `refactor(MagickCore/colorspace.c): simplify ConvertHSLToRGB`

#### Step 6: `SetImageColorspace` (line 1567)

- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify SetImageColorspace`

#### Step 7: `SetImageGray` (line 1647)

- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify SetImageGray`

#### Step 8: `SetImageMonochrome` (line 1704)

- **Recipe D or C** - duplication: D only if the blocks differ in one value, C for an identical contiguous run.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify SetImageMonochrome`

### Wave 3

#### Step 9: `ConvertRGBToHSL` (line 602)

- Recipe A does not apply: this function is public, and its signature is the API.
- Public function: its name and signature must not change.

Commit message: `refactor(MagickCore/colorspace.c): simplify ConvertRGBToHSL`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/colorspace.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/colorspace.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/colorspace.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
