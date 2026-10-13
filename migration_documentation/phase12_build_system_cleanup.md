# Phase 12 Build-System Cleanup

## Summary

Phase 12 is complete. CMake and the example Makefile now generate version source
inside the build directory instead of changing tracked source. The tracked
VersionModule remains valid Fortran and contains the fallback version `0.0.5`,
which fpm and the package recipe compile directly.

Verification on 11 October 2026 passed a clean build, **58 CTest cases**, and
**47 exact model-output comparisons** against a fresh Phase 11 reference. CTest is
the program that runs the project's automated tests. All 50 direct Biota records
and 7,500 organism-state records inside the running model matched. Make's three
build modes, clean/rebuild, a source archive, and the fpm install route also passed.
Original code comments were retained.

This separate build change was completed before final compatibility cleanup.
Removing Globals and its remaining copying procedures is now the next migration
step. Version-length and scientific corrections remain separate work.

## What Changed

### Builds select a version without editing source

| Build route | Selected version |
| --- | --- |
| CMake with non-empty `NANOFASE_VERSION` | The explicitly supplied label |
| CMake with no override, or an empty override | This checkout's `git describe --tags` when successful and non-empty |
| CMake without usable Git, tags, or history | The tracked `0.0.5` fallback |
| Example Makefile with `MODEL_VERSION` | The corresponding CMake override |
| fpm, including the package recipe | The tracked `0.0.5` fallback |

Git runs against the source directory explicitly. A source archive inside another
repository does not borrow that repository's version. Linked Git worktrees, which
use a `.git` file instead of a directory, also work. An automatically detected
version does not become a saved explicit override.

CMake generates `generated/VersionModule.f90` in each build directory and excludes
the tracked fallback from its source list. The model and all full-model test
programs compile exactly one version module. The version is selected during
configuration and checked again before compilation, so a new commit or tag can
update it without manual reconfiguration. Generated source is rewritten only when
its contents change; an unchanged build does not recompile it.

The public module and constant names are unchanged. The constant still holds 17
characters; ModelConfig and Globals still hold 16. A longer explicit or Git label
is subject to these existing limits. Quotes and other special characters are
handled when generating source and the refresh script.

The fallback change is intentional metadata maintenance, not a new release. It
matches `fpm.toml` and the package recipe. Citation metadata still says `0.0.4`
with its older date; this phase neither changes that date nor claims it is current.

### Make delegates to CMake

`make`, `make release`, `make fast`, and `make clean` remain available, either after
copying the example to `Makefile` or through `make -f Makefile.example`.

Debug and Release use the existing CMake settings. Fast selects GNU Fortran Release
with `-Ofast`. Compiler selection, NetCDF overrides, extra CMake options, the build
directory, job count, and an explicit version can be supplied on the command line.
CMake owns module dependency ordering; the obsolete manual object list is gone.

Each mode builds under its own `build/make-*` directory. The selected executable
is copied to `build/nanofase`, and `build/comp_meta` records compilation time,
commit, branch, label and configuration. Cleaning uses only those mode directories
and the wrapper's recorded published files; an unrelated fpm-cache test file
survived. Reading the Makefile or performing a dry run does not rewrite source.

### Compiled module files cannot supply stale versions

A compiled module file is a compiler-generated description that other Fortran
source files read during compilation. The main executable previously wrote these
files into the build root, whereas test programs used separate directories.

An extra check reproduced a real problem: after the main program compiled label
`first`, a separately built second program still printed `first` when built for
`second`. Adding an include directory did not fix it; GNU Fortran searched its
working directory first. These investigations are saved in `module_search.log`
and `module_search_include.log` beside the phase evidence.

The main executable now uses `nanofase-modules`, so all full-model executables
keep separate compiled modules. On reconfiguration of an older build, old root
module files move into `legacy-fortran-modules`. They are retained, but no longer
sit in the compiler's search path. An old build performed directly in the source
directory must instead be upgraded using a separate build directory.

The version test now checks a secondary target after a label change and upgrades
a fixture containing a deliberately stale compiled module. Numerical compiler
settings are unchanged; the added `-Jnanofase-modules` option changes only where
compiler-generated module files are placed.

### Original comments and preserved behavior

All **61 original comment occurrences** in changed existing code/build files remain
verbatim: 41 in CMake and 20 in the example Makefile. VersionModule had no comments.
The Makefile's obsolete implementation comments remain in a clearly marked
historical comment block with new explanations above it.

All scientific source, startup procedures, diagnostic definitions, input settings,
output layouts, checkpoint records and comparison-test sources are unchanged.
Only the version literal changed under `src/`. The 16-character fields were not
lengthened. Earlier phase reports and the pre-existing data-submodule workspace
state were preserved. The user's existing migration-plan additions were retained
and updated to describe the completed change.

## Verification

### Fresh reference and evidence

The reference used Phase 11 revision:

```text
99522f1f5a66789a9e1fac4b187071aa160f0d81
```

Evidence is saved under:

```text
/private/tmp/nanofase_phase12_b4bpmo77
```

It contains saved original files and hashes, initial working changes, dependency
revisions, isolated reference sources, build settings, reference executables,
scenario inputs, commands, logs and results. The builds used GNU Fortran 14.2.0,
CMake 4.3.4 and the existing NetCDF installation. The fpm install used fpm 0.10.1.

The old reference was extracted with its vendored source dependencies into an
isolated directory. Its original CMake build cannot accept a version override and
still rewrites the version file. After configuration, the saved original file was
restored and the build completed. Its hash was checked after compilation too:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

That procedure compiled `0.0.5-18-g163ae42`, reported as `0.0.5-18-g163ae4` by the
existing model fields. The reference passed all 57 existing tests. Its model,
shared-consumer integration and two Biota executables were saved before build edits.
All four reference scenario captures passed before implementation started.

The candidate commands were:

```sh
cmake -S . -B /private/tmp/nanofase_phase12_b4bpmo77/candidate-build \
  -DCMAKE_BUILD_TYPE=Debug -DCMAKE_Fortran_COMPILER=gfortran-14 \
  -DNANOFASE_VERSION=0.0.5-18-g163ae42 \
  -DNETCDF_INCLUDES=/opt/homebrew/Cellar/netcdf-fortran/4.6.2/include \
  '-DNETCDF_LIBRARIES_F90=-L/opt/homebrew/Cellar/netcdf-fortran/4.6.2/lib -lnetcdff -lnetcdf'
cmake --build /private/tmp/nanofase_phase12_b4bpmo77/candidate-build --clean-first -j2
ctest --test-dir /private/tmp/nanofase_phase12_b4bpmo77/candidate-build --output-on-failure
```

The paths identify the installation used for these results; they are not hard-coded
project requirements. After the compiled-module fix, the candidate was rebuilt
cleanly and all **58/58** tests passed. This includes one new build-version test
with **16 check groups**. Existing compiler and linker warnings remain.
Final logs are `candidate_build_final.log` and `candidate_ctest_final.log`.

### Build and package checks

The repeatable runners are:

```sh
python3 -B verification/verify_build_system.py \
  --compiler /opt/homebrew/bin/gfortran-14 \
  --work-dir /private/tmp/nanofase_phase12_b4bpmo77/build-version-checks
python3 -B verification/verify_build_routes.py \
  --compiler /opt/homebrew/bin/gfortran-14 \
  --work-dir /private/tmp/nanofase_phase12_b4bpmo77/build-route-checks-final
```

The final version checks also ran through CTest, with evidence under
`candidate-build/version-checks/version_kcegnt7x`. The standalone run before the
compiled-module additions passed 14 groups; the final CTest run passed all 16.

| Build checks | Actual result |
| --- | --- |
| Explicit labels with and without Git | Correct labels, quoting and existing 17/16-character limits |
| Clearing/changing overrides | Correct replacement in compiled executables |
| Automatic Git selection, new commits and tags | Correct labels, including refresh without reconfiguration |
| Git unavailable, no tags, archive, archive inside another repository | Non-empty `0.0.5` fallback |
| Linked worktree | Correct Git version with a `.git` file |
| Two build directories running concurrently | Independent labels and generated source |
| Unchanged build | Generated-file, object-file and executable times unchanged |
| Direct secondary target and legacy compiled modules | Correct new label; old module retained outside the search path |
| Make Debug, Release, Fast, dry runs and clean/rebuild | All completed; source and unrelated caches preserved |
| Full CMake automatic/source-archive models | Expected labels in console, summary and NetCDF source metadata |
| `fpm @install --prefix=<temporary directory>` from an archive | Compiled, installed and ran successfully with `0.0.5` |

Final full-route logs and commands are under
`build-route-checks-final/routes_ot1_09g3`; the summary is
`build_route_checks_final.log`.

The full-route runner copied the available fpm dependency cache into its disposable
source archive and used the existing package install command without changing any
manifest or dependency. It checked tracked-file hashes around every command and
checked the archive sources after both build routes. No network fetch was needed.
This verifies the recipe's install command, not construction or publication of a
Conda package through the separate packaging service.

An early version test failed because this Mac's older Make compared file timestamps
only to whole seconds: two rapid label changes landed in the same second. The test
now separates edits in time. The failed run remains in
`build-version-checks/version_gvq7kwe1`; the corrected run and final CTest evidence
are retained separately. This adjustment does not change compiler options or model
calculations.

### Exact model comparisons

The saved execution helper ran the unchanged scenario suites with:

```sh
python3 /private/tmp/nanofase_phase12_b4bpmo77/run_suites.py capture
python3 /private/tmp/nanofase_phase12_b4bpmo77/run_suites.py compare
```

Capture used the four saved Phase 11 executables. Compare used the corresponding
candidate-build executables. The complete per-suite commands are in
`*_capture_command.json` and `*_compare_command.json`, with logs beside them.

| Suite | Actual result |
| --- | --- |
| WaterBody | 14 exact output comparisons, four expected failures, batch and checkpoint save/load passed |
| Reactor | Nine exact comparisons including active rates and changed shear |
| Biota | Six exact output comparisons; 50 direct and 7,500 running-model records matched |
| Shared consumers | 18 exact comparisons, four diagnostic cases and six checkpoint cases passed |

All **47 output sets** matched using the same explicit version text and numerical
compiler flags. CSV files are byte-identical. Summaries exclude only simulation
time, and NetCDF text excludes only history. Version fields remain part of the
comparison. Biota and shared-consumer source-hash protections are unchanged.

After the compiled-module fix, all four comparisons passed again against the same
saved reference. Initial passing candidate results were retained as
`candidate_before_module_isolation` inside each suite's evidence directory.

Checkpoint checks retain the existing layout and defined-value comparisons,
excluding only previously documented unused reach positions. They prove that
saved state can be restored, not that the simulation resumes correctly.

### Final source checks

`python3 /private/tmp/nanofase_phase12_b4bpmo77/check_source.py` passed and saved
`source_checks_final.json`. It compares original file hashes, original comment
counts and order, numerical compiler flags, the retained version-field lengths,
earlier phase reports, and the expected working changes. `git diff --check` passed.
Only the version literal changed in existing Fortran source. The new fallback's
SHA-256 is:

```text
c6caca99e6e1741b32d2ba4ac388f2a90bbe851277735d016ca66a0d89f83188
```

Temporary evidence may eventually disappear. The tracked build-check runners,
unchanged scientific runners, reference revision and verification guide provide
the steps needed to repeat the checks in a fresh directory.

## What Remains

1. Complete final compatibility cleanup: remove Globals, its old fields/copying
   procedures, Bootstrap's copies, old defaults exports and historical test writes.
   Preserve original comments and the approved shared errors and blank code-1 message.
2. Correct version-label length separately. Check console welcome text, summary
   and NetCDF source metadata, including its repository URL; preserve numerical output.
3. Review citation metadata and the release checklist separately. Keep fallback,
   manifest and recipe versions consistent without inventing a release date.
4. Correct river behavior with bed sediment disabled and terrain access at outlets
   in their separately tested changes.
5. Correct Reactor attachment mass loss with tests that require conservation of mass.
6. Correct Biota harvest timing and invalid-input handling separately. Resolve missing
   checkpointed organism state, warm-up timing and the unused restored timestep
   before claiming correct checkpoint continuation.
7. Keep unused checkpoint positions and the empty compartment-statistics output as
   separate follow-up work. Intel/Windows builds and complete Conda-package creation
   were not exercised by this macOS/GNU Fortran verification.

The main plan, verification guide, build instructions and CHANGELOG were updated.
Earlier reports remain historical records. Every following phase must likewise
record what changed, what actually passed and what remains, using plain language
and retaining original code comments.
