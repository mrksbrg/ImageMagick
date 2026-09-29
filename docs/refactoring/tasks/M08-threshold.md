# M08 - refactor `MagickCore/threshold.c`

| Field | Value |
| --- | --- |
| Baseline Code Health | **2.06** / 10 |
| Exit target | **plateau** - no legal recipe raises the score further; record it |
| Hand-off point | **4.00** leaves the Red band. A small model stops there and hands on |
| File size | 2674 lines |
| Functions with findings | 17 |
| Measured with | `cs-mcp` 1.5.6, `cs` 1.0.46 |

## 1. Read these first

- [`../../../AGENTS.md`](../../../AGENTS.md) - the contract, including the verification sequence.
- [`../PLAYBOOK.md`](../PLAYBOOK.md) - the only transformations you may apply, and the rules for OpenMP regions and public functions.
- [`../README.md`](../README.md) - campaign rules and the definition of done.

## 2. Record the baseline before touching anything

```bash
python3 tools/ch.py --review MagickCore/threshold.c
```

The score must read 2.06. If it does not, this file changed after the task was written: stop and report that instead of proceeding.

## 3. What CodeScene flags here

| Smell | Functions |
| --- | ---: |
| Lines of Code in a Single File | file |
| Brain Method | 1 |
| Bumpy Road Ahead | 14 |
| Deep, Nested Complexity | 10 |
| Overall Code Complexity | file |
| Complex Method | 15 |
| Complex Conditional | 4 |
| Excess Number of Function Arguments | 4 |
| Overall Function Size | file |

## 4. Target functions, highest leverage first

| # | Function | Line | Cyclomatic | Nesting | Bumps | Linkage | OpenMP | Cases | Mutants killed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `OrderedDitherImage` | 1893 | 35 | 4 | 7 | public | 2 | 72 | 54 of 65 |
| 2 | `ColorThresholdImage` | 1217 | 27 | 4 | 4 | public | 2 | 12 | 18 of 22 |
| 3 | `BlackThresholdImage` | 927 | 26 | 4 | 4 | public | 2 | 12 | 22 of 28 |
| 4 | `WhiteThresholdImage` | 2518 | 26 | 4 | 4 | public | 2 | 12 | 22 of 28 |
| 5 | `PerceptibleImage` | 2092 | 19 | 4 | 4 | public | 2 | 3 | 12 of 16 |
| 6 | `KapurThreshold` | 392 | 17 | 4 | 4 | static | - | 12 | 37 of 43 |
| 7 | `ClampImage` | 1087 | 16 | 4 | 4 | public | 2 | 117 | 13 of 19 |
| 8 | `RandomThresholdImage` | 2231 | 19 | 4 | 3 | public | 2 | 12 | 15 of 23 |
| 9 | `BilevelImage` | 805 | 18 | 4 | 3 | public | 2 | 156 | 17 of 20 |
| 10 | `AdaptiveThresholdImage` | 182 | - | 5 | 5 | public | 2 | 12 | 58 of 63 |
| 11 | `TriangleThreshold` | 570 | 15 | - | 5 | static | - | 12 | 33 of 48 |
| 12 | `GetThresholdMapFile` | 1526 | 25 | - | 2 | static | - | 72 | 26 of 31 |

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
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1933, `ne_to_eq`: `(*p != '\0'))`
  - base line 1939, `ge_to_gt`: `if ((p-threshold_map) >= (MagickPathExtent-1))`
  - base line 1960, `post_inc_to_post_dec`: `for (i=0; (*p != '\0') && (i < MaxPixelChannels); i++)`
  - base line 1969, `ge_to_gt`: `if (fabs(levels[i]) >= 1)`
  - base line 2013, `lt_to_le`: `if (fabs(levels[n]) < MagickEpsilon)`
- 6 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify OrderedDitherImage`

#### Step 2: `ColorThresholdImage` (line 1217)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1256, `ne_to_eq`: `if (artifact != (const char *) NULL)`
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify ColorThresholdImage`

#### Step 3: `BlackThresholdImage` (line 927)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 970, `ne_to_eq`: `if ((flags & SigmaValue) != 0)`
  - base line 976, `eq_to_ne`: `if (threshold.colorspace == CMYKColorspace)`
  - base line 980, `ne_to_eq`: `if ((flags & ChiValue) != 0)`
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify BlackThresholdImage`

#### Step 4: `WhiteThresholdImage` (line 2518)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 3 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2561, `ne_to_eq`: `if ((flags & SigmaValue) != 0)`
  - base line 2567, `eq_to_ne`: `if (threshold.colorspace == CMYKColorspace)`
  - base line 2571, `ne_to_eq`: `if ((flags & ChiValue) != 0)`
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify WhiteThresholdImage`

### Wave 2

#### Step 5: `PerceptibleImage` (line 2092)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- Only 3 oracle case(s) execute this function, so the oracle sees little of it. Consider adding cases before a structural change.
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify PerceptibleImage`

#### Step 6: `KapurThreshold` (line 392)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 6 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 448, `gt_to_ge`: `if (cumulative_histogram[j] > epsilon)`
  - base line 452, `gt_to_ge`: `if (histogram[i] > epsilon)`
  - base line 461, `gt_to_ge`: `if ((1.0-cumulative_histogram[j]) > epsilon)`
  - base line 461, `sub_to_add`: `if ((1.0-cumulative_histogram[j]) > epsilon)`
  - base line 465, `gt_to_ge`: `if (histogram[i] > epsilon)`
  - base line 474, `add_to_sub`: `maximum_entropy=black_entropy[0]+white_entropy[0];`

Commit message: `refactor(MagickCore/threshold.c): simplify KapurThreshold`

#### Step 7: `ClampImage` (line 1087)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 4 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 1 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1116, `lt_to_ge`: `for (i=0; i < (ssize_t) image->colors; i++)`
- 5 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify ClampImage`

#### Step 8: `RandomThresholdImage` (line 2231)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- The oracle missed 4 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 2309, `lt_to_le`: `if ((double) q[i] < min_threshold)`
  - base line 2312, `gt_to_ge`: `if ((double) q[i] > max_threshold)`
  - base line 2315, `mul_to_div`: `threshold=((double) QuantumRange*`
  - base line 2317, `le_to_lt`: `q[i]=(double) q[i] <= threshold ? 0 : QuantumRange;`
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify RandomThresholdImage`

### Wave 3

#### Step 9: `BilevelImage` (line 805)

- **Recipe G (guard clauses)** - nesting is 4, target is under 4.
- **Recipe E (extract function)** - 3 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 3 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify BilevelImage`

#### Step 10: `AdaptiveThresholdImage` (line 182)

- **Recipe G (guard clauses)** - nesting is 5, target is under 4.
- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- Recipe A does not apply: this function is public, and its signature is the API.
- Contains 2 OpenMP pragma(s): only blocks inside a loop body that write no variable declared outside it may be extracted. Never move or edit a pragma.
- Public function: its name and signature must not change.
- 5 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify AdaptiveThresholdImage`

#### Step 11: `TriangleThreshold` (line 570)

- **Recipe E (extract function)** - 5 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 11 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 626, `sub_to_add`: `if ((max-start) >= (end-max))`
  - base line 626, `ge_to_gt`: `if ((max-start) >= (end-max))`
  - base line 629, `sub_to_add`: `a=y1-y2;`
  - base line 631, `mul_to_div`: `c=(-1.0)*(a*x1+b*y1);`
  - base line 632, `div_to_mul`: `inverse_ratio=1.0/sqrt(a*a+b*b+c*c);`
  - base line 632, `mul_to_div`: `inverse_ratio=1.0/sqrt(a*a+b*b+c*c);`
  - and 5 more (`tools/oracle/mutate.py --function TriangleThreshold`)
- 4 further survivor(s) are of kinds the oracle cannot see by design (logging, loop bounds over padding, allocation sizes; see `tools/oracle/classify.py`).

Commit message: `refactor(MagickCore/threshold.c): simplify TriangleThreshold`

#### Step 12: `GetThresholdMapFile` (line 1526)

- **Recipe E (extract function)** - 2 nested blocks; each bump is a missing function.
- **Recipe P (named predicate)** - move compound conditions into named `MagickBooleanType` helpers.
- The oracle missed 5 sampled mutant(s) here that are not of a known harmless kind. Take extra care on these lines, and consider closing the gap first:
  - base line 1594, `ne_to_eq`: `if (attribute != (char *) NULL)`
  - base line 1597, `ne_to_eq`: `if (content != (char *) NULL)`
  - base line 1645, `lt_to_le`: `if (map->divisor < 2)`
  - base line 1677, `lt_to_le`: `if ((map->levels[i] < 0) || (map->levels[i] > map->divisor))`
  - base line 1677, `gt_to_ge`: `if ((map->levels[i] < 0) || (map->levels[i] > map->divisor))`

Commit message: `refactor(MagickCore/threshold.c): simplify GetThresholdMapFile`

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
