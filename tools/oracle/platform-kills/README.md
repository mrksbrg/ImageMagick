# Platform kills

Mutation kills that only one platform makes, read by `gate.py` (`platform_kills()`) after
the merged reports. A kill here turns that mutant into a kill in every gate run, on every
machine. Each entry is a mutate.py-style result with `status: killed`, the killing case
(`killer`), and the `platform` it holds on. IDs are relative to the repository root; the gate
matches them by mutator and source position.

The owner decided this on 2026-10-05, for mutants whose effect depends on the C library. The
first such mutants are qsort comparators: BSD qsort reorders ties with seven or more
elements, glibc may not.

**Rule: a function trusted through a kill listed here must have its refactoring checked with
the oracle on that platform.**

| file | platform | functions |
|---|---|---|
| `macos-qsort.json` | macOS (BSD qsort) | draw.c StopInfoCompare, locale.c LocaleInfoCompare, log.c LogInfoCompare |
