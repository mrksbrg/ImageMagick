# M11 - refactor `MagickCore/decorate.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **5.78** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 902 lines |
| Functions with findings | 2 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/decorate.c
```

The score must read 5.78. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Bumpy Road Ahead | 2 |
| Deep, Nested Complexity | 2 |
| Complex Method | 2 |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `RaiseImage` | 628 | 63 | 4 | 14 | public | 6 | 26 | 112 of 118 |
| 2 | `FrameImage` | 169 | 67 | 5 | 11 | public | 2 | 82 | 222 of 237 |

Thresholds for C: cyclomatic complexity under 9, nesting depth under 4. **Cases** is how many oracle cases execute the function; **Mutants killed** counts the sampled mutants on lines the oracle executes. A function with no cases cannot be checked and is listed last: skip it and report it.

## 5. Steps

Work **one function at a time, in the order above**, and run the verification in section 6 after each commit. Re-run the review at the start of each wave: line numbers shift as earlier waves land.

### Wave 1 - start here

#### Step 1: `RaiseImage` (line 628)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 14 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 6 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 2 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 659, `le_to_lt`: `if ((image->columns <= (raise_info->width << 1)) ||`
  - line 660, `le_to_lt`: `(image->rows <= (raise_info->height << 1)))`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/decorate.c): simplify RaiseImage`

#### Step 2: `FrameImage` (line 169)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 11 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 11 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - line 214, `sub_to_add`: `x_offset=(ssize_t) frame_info->width-frame_info->x-(ssize_t) bevel_width;`
  - line 214, `sub_to_add`: `x_offset=(ssize_t) frame_info->width-frame_info->x-(ssize_t) bevel_width;`
  - line 215, `sub_to_add`: `y_offset=(ssize_t) frame_info->height-frame_info->y-(ssize_t) bevel_width;`
  - line 215, `sub_to_add`: `y_offset=(ssize_t) frame_info->height-frame_info->y-(ssize_t) bevel_width;`
  - line 235, `eq_to_ne`: `(frame_image->alpha_trait == UndefinedPixelTrait))`
  - line 257, `sub_to_add`: `accentuate.black=(QuantumScale*(((double) QuantumRange-(double)`
  - and 5 more (`tools/oracle/mutate.py --function FrameImage`)
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/decorate.c): simplify FrameImage`

## 6. Verification after every commit

```bash
tools/oracle/build.sh cand
python3 tools/refactor_guard.py MagickCore/decorate.c   # --calls after E, C, X
python3 tools/oracle/oracle.py run --function <Function>
python3 tools/ch.py --review MagickCore/decorate.c
```

Name the function you refactored in the oracle run, not a helper you extracted from it. If the guard fails or the oracle diverges, `git checkout -- MagickCore/decorate.c` and stop.

Before the branch is pushed: `python3 tools/oracle/oracle.py run`.

## 7. Report

For each function: the recipes applied, the score before and after, and the review lines that changed. For the file: where it plateaued, and which smells are left.
