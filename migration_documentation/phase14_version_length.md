# Phase 14 Version-Length Correction

## Summary

Phase 14 is complete. The complete selected version label now reaches the version
constant, ModelConfig, console welcome text, simulation summary and NetCDF source
text, including its repository URL. Short labels retain the existing 16-character
output padding. Scientific calculations and numerical compiler settings are unchanged.

Verification on 13 October 2026 passed **58 CTest cases**, including an expanded
version test with **19 check groups**, **47 exact model-output comparisons**, and
**four long-label comparisons** covering both NetCDF layouts and writing modes.
CMake, Make, source-archive and fpm build routes passed. Earlier phase reports and
all original code comments were preserved.

## What Changed

CMake no longer cuts the selected label to 17 characters. Generated Fortran source
uses quoted pieces of at most 32 original characters, joined with continuation
lines. This preserves the whole label without exceeding ordinary source-line
limits. Double quotes are escaped within each piece. Existing handling of CMake
special characters, version selection and build refresh is unchanged.

The generated and tracked fallback `MODEL_VERSION` declarations now use
`character(len=*)`: their length comes from the complete literal. ModelConfig uses
`character(len=max(16, len(MODEL_VERSION)))`: enough room for the full label, with
the same padding as before for short labels. Before initialisation its value is
still blank; clearing or reading configuration restores the selected version.

The constant and field keep their names. Their lengths can change, so dependent
Fortran code must be rebuilt. No science procedure, input group, output variable,
checkpoint record, or numerical expression changed. Console/summary/NetCDF writers
needed no algorithm changes: they already use the model version field.

Version selection is still explicit override, then this checkout's Git description,
then the tracked `0.0.5` fallback. fpm compiles the fallback directly. No release
number or citation date was changed. The existing repository URL rule is retained;
an arbitrary override is not guaranteed to name a real repository page.

The two original CMake comments describing truncation moved verbatim to
[phase14_removed_version_comments.cmake](phase14_removed_version_comments.cmake),
a comment-only historical file that the build does not include. All 70 original
comment occurrences in the reviewed build and build-runner files remain. The
Phase 13 check still accounts for all 4,910 original application/test comments.

## Verification

### Reference and recorded evidence

Phase 13 was completed, verified and documented before Phase 14 began. Its source
and executables were then saved as the reference. Both phases are working-tree
changes in this implementation; there is no invented Phase 13 Git commit.

Evidence is under:

```text
/private/tmp/nanofase_phase13_14_iceq6cpq
```

`phase13-source` is the saved source; `phase13_snapshot_hashes.json` identifies its
files; `phase13.patch` records its tracked changes from Phase 12 revision
`125d8c55e6747b6efa9c5a2aa08d07b9e4b444a0`. The snapshot also contains the new
verification code and documentation. `phase13-build` contains the reference
executables. Fresh Phase 14 reference captures were made before changing version
production code, with unchanged Biota/shared-consumer test sources and hash checks.

For future reproduction from the completed tree, make an isolated copy retaining
Phase 13's cleanup and test changes. Restore `cmake/NanoFASEVersion.cmake`,
`cmake/VersionModule.f90.in`, `src/VersionModule.f90`, and the two build-version/route
runners from the Phase 12 revision above; change only ModelConfig's version length
back to 16. That reconstructs the pre-Phase-14 production version behavior. Keep
this reconstruction out of the working checkout.

All full model builds used GNU Fortran 14 and the same NetCDF installation and
numerical flags. The short-label build command form was:

```sh
cmake -S SOURCE -B BUILD -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_Fortran_COMPILER=gfortran-14 -DNANOFASE_VERSION=migration-check \
  -DNETCDF_INCLUDES=/opt/homebrew/Cellar/netcdf-fortran/4.6.2/include \
  '-DNETCDF_LIBRARIES_F90=-L/opt/homebrew/Cellar/netcdf-fortran/4.6.2/lib -lnetcdff -lnetcdf'
cmake --build BUILD -j2
ctest --test-dir BUILD --output-on-failure
```

The Phase 14 build is `phase14-build`. Its CTest result was **58/58 passed**.
Existing compiler/linker warnings remain. Complete commands are in saved
`*_command.json` files, with logs beside them; `numerical_flags.txt` records the
identical numerical settings for reference, candidate and both long-label builds.

### The new expectation failed before the correction

The expanded `verify_build_system.py` was first run with Phase 13 production code.
It failed with `ModelConfig version was truncated`, the intended defect, before
any version implementation changed. This is an expected failing test, not an
unresolved failure. Its log is `phase14_red_version.log` and its generated inputs
are in `phase14-red-version`.

The corrected implementation passed:

```sh
python3 -B verification/verify_build_system.py \
  --compiler /opt/homebrew/bin/gfortran-14 \
  --work-dir /private/tmp/nanofase_phase13_14_iceq6cpq/phase14-version-checks
```

Evidence is in `phase14-version-checks/version_93ywrv05`. The same runner passed
again through CTest. It compiles the real ModelConfig and checks neutral initial
state, clearing, configuration reads and repeated reads. It covers labels of
length 1, 15, 16, 17, 18 and 256, and long labels containing quotes, backslashes,
semicolons and literal CMake syntax. Generated lines must stay within 120 characters.

The retained checks cover override changes/clearing, Git commits/tags, unavailable
Git, missing tags, archives, a nested archive, a linked worktree, independent build
directories, unchanged builds, directly rebuilt secondary targets, old compiled
modules and source hashes. There are 19 passing check groups in total.

### Scientific output and complete version text

The four unchanged comparison suites ran through the saved helper:

```sh
python3 /private/tmp/nanofase_phase13_14_iceq6cpq/run_checks.py suites phase14 capture phase13
python3 /private/tmp/nanofase_phase13_14_iceq6cpq/run_checks.py suites phase14 compare phase14
```

All 14 WaterBody, nine Reactor, six Biota and 18 shared-consumer comparisons passed:
**47 exact output sets**. The common `migration-check` label preserves identical
version metadata. CSVs are byte-identical, summaries exclude only simulation
datetime and NetCDF text excludes only history. General filters and tolerances
were not changed. Biota's 50 direct and 7,500 running-model records matched.
Expected failures, logs, diagnostics, batch state and checkpoint checks passed.

Separate reference/candidate model builds used the same longer label:

```text
v0.0.5-phase14-full-version-label-123456789
```

The full-model check was:

```sh
python3 -B verification/verify_version_outputs.py \
  --reference-exe /private/tmp/nanofase_phase13_14_iceq6cpq/phase13-long-build/nanofase \
  --exe /private/tmp/nanofase_phase13_14_iceq6cpq/phase14-long-build/nanofase \
  --label v0.0.5-phase14-full-version-label-123456789 \
  --work-dir /private/tmp/nanofase_phase13_14_iceq6cpq/phase14-long-output-checks
```

All four combinations of `end`/`itr` writing and per-waterbody/aggregated layout
passed. The runner first requires the exact truncated reference text and complete
candidate text in console, summary and NetCDF source/URL. Only then does it exclude
those checked version fields, plus the existing datetime/history fields, to compare
all remaining content exactly. It checks the output file set too. Evidence is in
`phase14-long-output-checks/version_outputs_d7x9tj58`.

### Build routes and final source checks

`run_checks.py routes phase14` invoked the unchanged build-route command form with
the updated full-label expectations. Evidence is in `phase14-routes/routes_nqvc1zwl`.
Automatic CMake, Make Debug/Release/Fast, dry runs, clean/rebuild, archive CMake and
archive `fpm @install` all passed. Tracked-source hashes stayed unchanged throughout
these commands. The package install command was tested, not full Conda packaging.

`phase14_source_checks.json` confirms that the only existing production Fortran
changes since Phase 13 are the two version-length declarations. Scientific source,
integration programs, comparison filters, earlier reports and the existing data
submodule state remain unchanged. Original comment checks, Python syntax checks
and `git diff --check` passed. Main plan, current build/verification instructions
and CHANGELOG now describe the completed phases.

## What Remains

The ownership migration and version-length correction are complete. Scientific
correctness remains separate work: Reactor attachment mass conservation, complete
river-disabled behavior, terrain access at outlets, and Biota harvest/invalid-input
handling still need their planned fixes. Correct checkpoint continuation also needs
organism state, warm-up timing and use of the restored timestep to be resolved.
Existing checkpoint comparisons prove restoration only.

Unused checkpoint positions, empty compartment-statistics output and release/citation
metadata remain separate follow-ups. Full Conda-package creation and Intel/Windows
builds were not exercised by this macOS/GNU Fortran verification. Earlier phase
reports remain historical records and must not be rewritten as later work completes.
