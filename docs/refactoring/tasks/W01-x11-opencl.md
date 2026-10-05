# W01 - make the X11 and OpenCL files measurable (Windows desktop, WSL)

Tasked by the project owner, 2026-10-05. Harness phase: **no changes to ImageMagick's
sources**, only builds, oracle support, cases, mutation runs and verdicts.

| Files | What they need at run time |
| --- | --- |
| `xwindow.c`, `display.c`, `animate.c`, `widget.c` | an X server (no display here, so a virtual one: Xvfb) |
| `accelerate.c`, `opencl.c` | an OpenCL device (no GPU in WSL, so a CPU implementation: pocl) |

`nt-base.c`, `nt-feature.c`, `vms.c` and `distribute-cache.c` stay written off (owner,
2026-10-04).

## What is known already

- **The builds work.** `build.sh wide` (WSL) configures `--with-x --enable-opencl`. The Mac
  built the same today (`build-oracle/x11cl`, Homebrew libX11 and Apple's OpenCL framework).
- **X11 without a server.** `display`, `animate`, `import` and the `x:` format stop with
  `UnableToOpenXServer`. The XWD format reads and writes without one.
- **OpenCL is off by default.** `AcquireMagickCLEnv` enables it only when `MAGICK_OCL_DEVICE`
  is `true`, `GPU` or `CPU`. The oracle sets none, so no case reaches the accelerated paths.
- **pocl 5.0 aborts** compiling ImageMagick's kernels on Ubuntu 24.04
  (`VERIFICATION.md`, item 6).
- **Likely upstream bug** (`MUTATION.md`, *OpenCL never binds when the header is found*). In
  `BindOpenCLFunctions`, the `MAGICKCORE_HAVE_OPENCL_CL_H` branch binds the functions
  directly but never sets `openCL_library->library`. The following
  `if (openCL_library->library == NULL) return(MagickFalse)` then reads uninitialised
  memory. On the Mac it is NULL: OpenCL itself reports the M1 Pro GPU, ImageMagick lists 0
  devices, and its output equals the CPU path. On WSL the kernels were compiled, so the
  build there either took the other branch (no header: `lt_dlopen("libOpenCL.so")`) or met
  non-zero garbage. **Find out which**, in `build-oracle/wide/config/config.h`
  (`HAVE_CL_CL_H`): it decides whether the WSL figures are reproducible.

## Steps

1. **Xvfb.** `sudo apt install xvfb` (plus `x11-apps` for `xwd` if useful). Give the oracle
   a way to run a case with an X server:
   - either one Xvfb per run on a fixed display with a fixed screen
     (`-screen 0 640x480x24`), with `DISPLAY` in `env_for` for wide builds;
   - or one per case.

   It must be deterministic: no window manager, a fixed geometry, `selfcheck --repeat 4`
   clean.
2. **X11 cases.** Non-interactive paths first:
   - `x:` output to a window, then `import -window root` back from the virtual screen;
   - `display -window root`;
   - `animate` with a fixed `-delay` and `-loop 1`;
   - X resources (`-xrm`, the resource database code in `xwindow.c`), which may not need a
     window at all.

   Interactive widgets (`widget.c`, the menus in `display.c`) need synthetic events
   (`xdotool`). Measure how far plain cases get before spending on that, and write down
   what stays out of reach, with the reason.
3. **OpenCL.**
   - Try a newer pocl (6.x), from source or a PPA, CPU device only. If kernels still abort,
     record it and stop there.
   - Switch OpenCL on per case: a per-case environment variable in the oracle, or an
     imdriver command calling `SetOpenCLEnabled` / `SetOpenCLDeviceEnabled`. Pin the
     device: the default choice benchmarks the devices, which is timing-dependent.
   - Keep the kernel cache and the device profile (`ImagemagickOpenCLDeviceProfile.xml`)
     out of the comparison. `MAGICK_OPENCL_CACHE_DIR` in the case directory, fixed or
     removed.
   - Base and candidate both run the accelerated path, so float differences against the
     CPU path do not matter. Run-to-run differences do: `selfcheck` decides.
4. **Mutation runs.**
   - Build a Mull variant of the wide build for these six files (`build.sh mull` with their
     regex and a new name).
   - Rebuild the case map with the wide coverage build, run `mutate.py`, read the
     survivors, and write verdicts as for every other file.
   - A kill that only this platform gives goes into `tools/oracle/platform-kills/` (see its
     README).
5. **Report** in `MUTATION.md`: per file the reach, the figures, and what stays out of
   reach. Update the dashboard (*Harness Status*).

## Rules that apply

- Pull right before every commit.
- Add cases to the `GAP_*` lists.
- Keep `verdicts.json` sorted.
- Bump `HARNESS_VERSION` if normalisation or execution changes.
- After a Homebrew or apt upgrade of a library the builds link, rebuild the baseline and
  candidate together (`MUTATION.md`, *Build drift*).
- The `wide` build is not an oracle build yet. Make it one only once `selfcheck` is clean.
