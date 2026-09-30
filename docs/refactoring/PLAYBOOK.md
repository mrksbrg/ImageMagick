# Refactoring Playbook

This is a **closed catalogue**. If a change you want to make is not one of the recipes
below, you are not allowed to make it as part of this campaign. Stop and report instead.

Every recipe here is *behaviour-preserving*: it moves code around without changing what
the program computes. That property is what makes the campaign safe to run at scale, and
the oracle ([`ORACLE.md`](ORACLE.md)) is what checks it, byte for byte.

The recipes come from the Street Fighter III: 3rd Strike campaign, where they took every
scored file to Code Health 10.00. Each one is adapted here for what ImageMagick is: a
published library, parallelised with OpenMP, compiled differently on every platform.
Recipes that 3SX found and measured but that this catalogue does not yet hold can be
proposed for addition when a file plateaus without them.

---

## The three rules

1. **One recipe, one function, one commit.** A commit may apply the same recipe several
   times to one function - four blocks extracted from one loop is one commit - but it
   must not mix two recipes, and it must not span two functions. The point is that one
   step can be reverted on its own.
2. **Re-measure after every commit.** If the score improved, keep it. If it did not, run
   `python3 tools/ch.py --review <file>` and keep the change only when the function you
   targeted left a smell category or its complexity dropped. Otherwise revert. See
   *A flat score does not mean a failed refactor* below.
3. **When in doubt, stop and report.** An unfinished task is fine. A silently changed
   image library is not.

---

## Absolutely forbidden

These change behaviour, or change what other programs can rely on, and must never appear
in a campaign commit:

- Changing any numeric literal, string literal, character constant, or enum value.
- Changing arithmetic (`+ - * / %`), bit operations, shifts, or the grouping of
  floating-point operations. Floating-point addition and multiplication are not
  associative: `a*b*c` is `(a*b)*c`, and rewriting it as `a*(b*c)` changes the last bit,
  which the oracle compares.
- Changing a comparison operator, including `<` to `<=`.
- Reordering statements that have side effects (assignment, I/O, function calls,
  exceptions thrown).
- Changing types: signedness, width, `float` versus `double`, `MagickRealType` versus
  `double`, `Quantum` versus anything else. Under HDRI these are not the same.
- "Fixing" a bug you spot. **Report it, leave it.**
- Deleting code that looks dead. It may be reached by another format, another platform,
  another build configuration, or a program calling the API.
- Touching a `static const` data table.
- **Changing anything public.** Every function that is not `static` is part of the API or
  of the library's internal ABI: do not rename it, change its signature, change its
  linkage, or move it to another file. The same goes for struct layouts, macros and
  anything else in a header.

### OpenMP regions

About 380 loops in MagickCore run under `#pragma omp parallel for`. The oracle builds
with OpenMP disabled, so it cannot see a data race or a change in what is shared between
threads. Therefore:

- **Never add, remove, move, or edit a `#pragma omp` line or its clauses**, and never
  move code into, out of, or across the region it governs.
- A block **inside** a parallel loop body may be extracted (Recipe E) into a `static`
  function called from the same place, **provided the block writes no variable declared
  outside the loop body** - not directly, and not by passing its address. Reading outer
  variables, which become parameters passed by value, is fine; writing through pointers
  the block already uses for pixel data (`p`, `q`) is fine. Moving a statement into a
  callee does not change which thread runs it; changing which variables it writes would.
- Code under `#pragma omp critical` or `#pragma omp atomic` stays exactly where it is,
  including the progress-monitor blocks at the end of most loops.

### Preprocessor branches

Code inside `#if defined(...)` branches that this build does not compile - X11,
OpenCL, Windows, a delegate library that is not installed - cannot be compiled, run or
measured here. Do not change it, even when the change looks identical to one you made in
a compiled branch. When a recipe would need to, skip the function and report it.

This stands until `tools/oracle/build.sh` can build the X11, OpenCL and Windows code in
one command ([`VERIFICATION.md`](VERIFICATION.md), step 5). Then that code becomes
guard-verified, below, in the build that compiles it.

---

## Two levels of evidence

The oracle only proves what its cases reach and check. Before starting on a function,
find out which level it is at, and say in the commit message which one verified it
(`Verified: oracle` or `Verified: guard`).

**Oracle-verified.** The function passes the readiness gate:

```bash
python3 tools/oracle/casemap.py <Function>              # some case executes it
python3 tools/oracle/mutate.py --file <file> --function <Function> --max-cases 0
python3 tools/oracle/gate.py build-oracle/work/mutation-<name>.json --file <file>.c
```

A verdict of **ready** (90% or more of the killable mutants killed) allows every recipe
in this catalogue. **Careful** (75-90%) allows them too, but read the unmatched and
unreached survivors of the function first (`classify.py ... --kind unmatched`) and keep
clear of the lines they sit on, or add a case that kills them.

**Guard-verified.** The function is **not ready**, or no case executes it. It may still
be refactored, as 3SX refactored a program with no tests at all, but only with the
recipes whose guard fingerprint is exact: **E, G, P, R and X**. The proof is the build
and `refactor_guard.py` reporting `OK` with `--calls`; a `WARN` stops the commit.
Recipes D, C, A and S fold code together or move it, the guard cannot follow them, and
they need the oracle.

The guard has two blind spots: reordered statements, which the prohibitions already
forbid, and **transposed arguments**. For every call the step adds, check by reading
that each argument is passed in the position of the parameter it fills. Where the
machine-code comparison applies (`VERIFICATION.md`, step 3), identical optimised code is
a proof that covers both.

---

## Recipe E - Extract Function

**Use when:** CodeScene reports *Bumpy Road Ahead* (a function with several separate
blocks of nested logic). Each bump is a missing function.

**How:**

1. Find one nested block. It usually already has a comment or a blank line around it.
2. Cut it into a new `static` function directly above the current one.
3. Pass in every variable it reads as a parameter. Return the single value it produces.
4. If the block writes to more than one outer **local** variable, **skip it** and move to
   the next bump. Do not invent an out-parameter struct to carry results back. Writing
   fields through a pointer the block already has (`image->`, `q[...]`) is not what this
   rule is about; that is safe.
5. If the block is inside an OpenMP loop, check the rule above before you cut.
6. If the block can throw - `ThrowBinaryException`, `ThrowImageException` and friends
   expand to a `return` - the new function must return a status the caller checks, and
   the caller must `return` exactly what the macro returned. If you cannot see what the
   macro expands to, skip the block.

**Before:**

```c
static MagickBooleanType ApplyLevel(Image *image,const double black,
  const double white,ExceptionInfo *exception)
{
  ...
  for (x=0; x < (ssize_t) image->columns; x++)
  {
    if (GetPixelWriteMask(image,q) > (QuantumRange/2))
      {
        for (i=0; i < (ssize_t) GetPixelChannels(image); i++)
        {
          PixelChannel channel = GetPixelChannelChannel(image,i);
          PixelTrait traits = GetPixelChannelTraits(image,channel);
          if ((traits & UpdatePixelTrait) != 0)
            q[i]=ClampToQuantum(LevelPixel(black,white,(double) q[i]));
        }
      }
    q+=(ptrdiff_t) GetPixelChannels(image);
  }
  ...
}
```

**After:**

```c
static void LevelPixelChannels(const Image *image,const double black,
  const double white,Quantum *q)
{
  ssize_t
    i;

  for (i=0; i < (ssize_t) GetPixelChannels(image); i++)
  {
    PixelChannel channel = GetPixelChannelChannel(image,i);
    PixelTrait traits = GetPixelChannelTraits(image,channel);
    if ((traits & UpdatePixelTrait) != 0)
      q[i]=ClampToQuantum(LevelPixel(black,white,(double) q[i]));
  }
}
...
    if (GetPixelWriteMask(image,q) > (QuantumRange/2))
      LevelPixelChannels(image,black,white,q);
```

Name the new function for **what it does**, in ImageMagick's style: CamelCase, a verb
first, `static`, and declarations at the top of the block as the surrounding code does.

---

## Recipe G - Guard Clauses

**Use when:** CodeScene reports *Deep, Nested Complexity* (nesting depth 4 or more).

**How:** invert the outermost condition and return early - or, inside a loop, `continue`.
Repeat until the main body sits at one level of indentation.

**Before:**

```c
if (image != (Image *) NULL)
  {
    if (image->alpha_trait != UndefinedPixelTrait)
      {
        if (GetImageArtifact(image,"verbose") != (const char *) NULL)
          ReportAlpha(image);
      }
  }
```

**After:**

```c
if (image == (Image *) NULL)
  return;
if (image->alpha_trait == UndefinedPixelTrait)
  return;
if (GetImageArtifact(image,"verbose") == (const char *) NULL)
  return;
ReportAlpha(image);
```

**Careful:**

- If the function returns a value, every guard must return the value the original would
  have produced by falling through. Read the end of the function first. In ImageMagick
  that is often `status`, or an image pointer that must also be destroyed on the way out;
  if the fall-through path frees anything, the guard must too, and then the recipe does
  not apply - skip the function.
- Inverting `a < b` gives `a >= b`, never `a > b`. Inverting `x != (T *) NULL` gives
  `x == (T *) NULL`. Write the inverse out; do not wrap the original in `!(...)` unless
  that is clearer, and never both.
- Inside an OpenMP loop the early exit is `continue`, and it must not skip a
  `#pragma omp critical` or `atomic` block that the original ran on that path.

---

## Recipe P - Named Predicate

**Use when:** CodeScene reports *Complex Conditional*, or *Complex Method* driven by
compound boolean expressions.

**How:** move the expression into a `static` function whose name states the intent,
returning `MagickBooleanType`. This is the safest recipe in the catalogue.

**Before:**

```c
if ((image->alpha_trait != UndefinedPixelTrait) &&
    (image->colorspace != CMYKColorspace) && (image->columns > 1))
  ...
```

**After:**

```c
static inline MagickBooleanType IsBlendableImage(const Image *image)
{
  return(((image->alpha_trait != UndefinedPixelTrait) &&
    (image->colorspace != CMYKColorspace) && (image->columns > 1)) ?
    MagickTrue : MagickFalse);
}
...
if (IsBlendableImage(image) != MagickFalse)
  ...
```

Copy the expression **character for character**. Do not simplify the boolean algebra, and
do not reorder the operands: `&&` short-circuits, so reordering can change which calls run
and can dereference a null pointer the original never touched.

---

## Recipe D - Deduplicate

**Use when:** CodeScene reports *Code Duplication*.

**How:** only when the blocks are **identical or differ by a single value**. Extract one
`static` helper and pass the differing value as a parameter. If they differ in two or
more places, leave them alone - forcing a shared abstraction over near-miss duplicates is
how subtle behaviour gets broken.

The per-colorspace and per-channel blocks in `colorspace.c`, `quantum-import.c` and
`quantum-export.c` often *look* identical and differ in one scale factor or one channel
index. That is exactly one value, and D applies; two, and it does not.

---

## Recipe C - Extract Common Part

**Use when:** CodeScene reports *Code Duplication* and the blocks share a **contiguous
identical run** - a prefix, a suffix or a middle - but differ elsewhere, so Recipe D does
not apply.

This is the mirror image of Recipe D, and it is safer. D moves the *difference* into the
helper as a parameter. C moves only the *identical* part, and every difference stays at
the call site, visible and unchanged.

**How:**

1. Find the longest run of lines that is identical in both blocks, character for
   character. Whitespace may differ; nothing else may.
2. Move exactly that run into a `static` helper. Do not tidy it on the way.
3. Leave everything else at the call sites, in its original order.
4. If the shared run ends inside control flow - the callers need to know whether to carry
   on - the helper returns `MagickTrue` or `MagickFalse` and each caller branches on it.
   Return nothing else.

**Careful:** this does **not** license merging near-miss blocks by parameterising two or
more differences. That is what Recipe D forbids, and it stays forbidden.

`refactor_guard.py` reports this shape as a WARN - copies removed, returns added -
because the call sites lose the run's literals while the helper brings its own returns.

---

## Recipe X - Split Dispatch

**Use when:** CodeScene reports *Complex Method* on a function whose complexity is mostly
its own `switch` - a dispatch over methods, colorspaces, compose operators or options
with more arms than the threshold allows. Recipe E does not help: there is no nested bump
to lift out, only arms.

**How:**

1. Choose a contiguous group of later arms that belong together.
2. Move them to a `static` helper that switches on **the same expression**.
3. Reach the helper from the original `default:` arm.

**Preconditions, all of them:**

- **Case labels are never changed.** The helper keeps the original enum labels.
- If the original switch already had a `default:`, that body moves to the helper's
  `default:`, unchanged, and the original's `default:` only calls the helper.
- Anything that ran after the switch stays in the caller, after the switch.
- An arm that falls through into the next keeps its neighbour in the same function. Never
  cut between two arms joined by a fall-through.
- If the switch sits inside an OpenMP loop, the helper is called from the same place and
  the OpenMP rule above applies to what the arms write.

---

## Recipe A - Parameter Object

**Use when:** CodeScene reports *Excess Number of Function Arguments* (more than four for
C) on a **`static`** function.

**Never on a function that is not `static`.** A public function's signature is the API.
This is the biggest difference from the 3SX version of this recipe, which was authorised
for public signatures there.

**How:**

1. Declare a `struct` in the same `.c` file, just above the function, whose fields are
   the function's parameters **in the same order** with **exactly the same types**.
2. Change the function to take one `const Struct *`, and read each parameter as a field.
3. Rewrite every call site - all in the same file, since the function is `static` - to
   fill the struct from its **original argument list**, in order, without reformatting
   the arguments.

**Preconditions:**

- The function is never referenced other than as a direct call. A `static` function
  whose address is taken - stored in a table, passed as a callback, handed to
  `qsort` - cannot take a new signature.
- `refactor_guard.py` must report **OK**, not WARN: the argument lists are copied
  verbatim, so the literal fingerprint cannot move.

---

## Recipe R - Resolve a Goto Chain

**Use when:** CodeScene reports *Complex Method* on a function whose complexity is mostly
`goto`. CodeScene counts each `goto` as a branch, and no other recipe reaches it.

**How:**

1. Check the preconditions. If any fails, stop - this is not the shape.
2. Replace each `goto L;` with a **verbatim copy** of the statements under `L`, which must
   end in `return`.
3. Delete every label that is now unreferenced, together with what stood beneath it.
4. A label that was also reached by falling off the end of the code above keeps its
   statements, unlabelled, as the function's tail.

**Preconditions, all of them:**

- **Every label in the chain ends in a `return`** and holds at most one or two statements
  before it. A longer tail - the resource cleanup at the end of most coders - is not this
  shape: copying it would duplicate the cleanup, and a missed copy would leak. Leave those
  `goto`s alone.
- **No label can be reached by falling into it** from another label's body.
- **Every `goto` jumps forward** and stays inside the same construct.
- **The conditions are not touched.**
- **Nothing else references the labels.**

This is control flow: run the whole catalogue (`oracle.py run`), not only the function's
cases, before committing.

---

## Recipe S - Split File

**Use when:** CodeScene reports *Lines of Code in a Single File*, after the functions in
it have been simplified.

**This recipe needs the project owner's go-ahead per file.** ImageMagick lists its
sources explicitly in `MagickCore/Makefile.am` (and in the separate Windows build
configuration), so a new file means editing the build system and regenerating
`Makefile.in`. That is outside the other recipes' guarantee, and the owner decides when it
is worth it.

When approved:

1. Move a group of `static` functions that share a theme, together with the one public
   function that uses them, to a new `.c` file beside the original.
2. No function may change linkage: a `static` stays `static` and must travel with every
   caller. A split that would need one widened is refused.
3. The public function keeps its declaration in the header it already has.

---

## A flat score does not mean a failed refactor

The file score is one aggregate over every function in the file. In a 5,000-line file
with a hundred functions, fixing one function can move it by less than the score's
resolution. So when the score does not move, run the review and ask the sharper question:
**did the smell I targeted go away?**

```bash
python3 tools/ch.py --review <file>
```

- The function **left** a category it was in, or its complexity dropped: keep the change.
- The function is still listed with the same numbers: revert.

Score is the campaign-level signal. Per step, the review is the signal.

### When the score falls

A correct transformation sometimes *lowers* the score: decomposing one function makes it
resemble a sibling, and the duplication detector prices that above the complexity
removed. `tools/codescene_precommit.py` refuses such a commit. Do not bypass it; stop and
report the case, with the review before and after, and the project owner decides.

---

## Known plateaus

None recorded on this branch. When a file stops improving and no recipe in this
catalogue applies, record it here: the file, its score, the smells left, and which 3SX
recipe might reach them.

A refactoring pilot, run by Claude on 2026-09-29/30 before the campaign's conditions
were settled, is kept on the branch `night1-refactoring`: 41 commits on eight
MagickCore files, 0 divergences across the catalogue. Its playbook records the
plateaus it met and the patterns that worked. The points below are what it taught
about the harness and the recipes themselves.

### Practical points

- **Put a helper directly before the function it came from**, not before the
  function's comment banner: ImageMagick often defines static helpers (`url_encode`,
  the `Modulate*` family) between the banner and the function, and a helper placed
  above them fails to compile.
- **Macros defined inside a function** (`LevelizeValue`, `ScaledSig`, `Colorize`) are
  file-scope from their `#define` onwards; the preprocessor ignores function scope.
  To extract code that expands one, move the `#define` above the helper and give the
  helper parameters of the names the macro reads. Say so in the commit.
- **CodeScene's start line** for a function often includes the comment block above it
  (it reported `AcquireImageColormap` at line 40, not 105). Use the compiler's view of
  where a function starts; `tools/make_task.py` does.
- **A score can fall when two extractions resemble each other.** Extracting
  `ContrastStretchImage`'s histogram pass made it resemble `EqualizeImage`'s, and the
  duplication finding cost more than the complexity saved (1.61 -> 1.60); leaving
  that block in place gave 1.65. The pre-commit gate is what catches this.
- `refactor_guard.py --calls` fails on a renamed function until the rename is declared
  (`--renamed OLD=NEW`); that is legal only for a file-local static, and in practice
  only for a helper this campaign created.

### Proposed amendment: moving a complete parallel region (needs the owner's decision)

The OpenMP rule forbids moving a `#pragma omp` line, even together with the whole loop
it governs. That blocks the two largest functions in MagickCore (`colorspace.c`, cc 142
and 151), whose `switch` arms each hold a complete parallel region, and several Brain
Methods. A narrower rule would still guarantee that nothing a thread shares changes:

> A complete parallel region - the pragma, its clauses unchanged, and the loop it
> governs - may be moved into a `static` helper, provided every variable named in its
> clauses (`shared`, `private`, `reduction`, ...) is either declared inside the helper
> or passed to it by pointer exactly as the region used it, and the helper returns any
> value the region left in a caller variable (typically `status`).

Not applied. The oracle cannot check threading, so this rule's safety rests on reading
alone; an OpenMP-enabled build with `-fsanitize=thread` on the moved functions would be
the check to add first.


---

## The verification loop

After every commit, as [`AGENTS.md`](../../AGENTS.md) sets out:

1. `tools/oracle/build.sh cand`
2. `python3 tools/refactor_guard.py <file>` (with `--calls` after Recipe E, C, X or S;
   always with `--calls` at the guard-verified level)
3. `python3 tools/oracle/oracle.py run --function <Function>` (at the guard-verified
   level too: it cannot prove the step, but it can still catch one)
4. `python3 tools/ch.py --review <file>`

Before pushing a branch: `python3 tools/oracle/oracle.py run`, the whole catalogue.
