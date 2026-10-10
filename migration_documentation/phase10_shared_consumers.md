# Phase 10 Shared-Consumer Migration

## Summary

Phase 10 is complete. The remaining running-model code now reads settings and
array sizes directly from the modules that own them. A module is a named group of
Fortran code and values. Model-wide defaults now live beside model configuration.

The old `C` object, its copying procedures, and Bootstrap's startup copies remain
for final cleanup, as agreed. Production code no longer reads those copies after
startup. The old defaults module exposes the same defaults object as the new owner;
it does not hold a second copy.

Verification on 6 October 2026 passed a clean build, **33 CTest cases**, and
**47 exact model-output comparisons** against a fresh Phase 9 reference. Biota's
50 direct concentration records and 7,500 concentrations recorded inside the model
also matched. Logging, changing batch inputs, simulation masks, expected failures,
and checkpoint checks passed. All original source comments were preserved.

The next migration phase is the **separate diagnostic-registry correction**:
decide ownership and correct the remaining error-list defects with dedicated tests.
Removing the compatibility code remains the final cleanup phase.

## What Changed

### Settings and dimensions come from their owners

| Code area | Change |
| --- | --- |
| Util | Tolerance and model version come from ModelConfig; array sizes come from ModelDimensions; number precision comes from Kernel. |
| Logger | Color selection comes from ModelConfig and the reset sequence comes from Kernel. The unused broad utility import was removed. |
| AbstractGridCell and Crop | Number precision and procedure result sizes use Kernel and ModelDimensions, including imports inside abstract procedure declarations. |
| DataInput | Paths, simulation masks, and current chunk length come from ModelConfig. Pi, colors, precision, and the constants-file unit come from Kernel. The error handler comes directly from ErrorHandling. |
| DataOutput and both NetCDF writers | Output choices and timing come from ModelConfig, sizes from ModelDimensions, and file units/precision from Kernel. |
| Checkpoint | Grid comparison tolerance comes from ModelConfig, the file unit from Kernel, and the handler from ErrorHandling. |
| ModelAssembly | The existing shared handler is imported directly from ErrorHandling. |

Two previously indirect imports needed explicit owners: `i64` in the main program
now comes from `mo_types`, and `NcGroup` in AbstractBedSedimentLayer comes from
`mo_netcdf`. The latter name is used by an existing abstract procedure declaration;
its declaration and comments were retained.

No science equations, operation order, public science types or procedure arguments,
input-reading rules, output layouts, or checkpoint records were changed. Existing
file-unit numbers and file-opening behavior were retained.

### Model defaults have one owner

Added `src/ModelConfig/ModelDefaultsModule.f90`. It exposes the existing
`ConfigDefaultsType` and shared `configDefaults` object. The entire declaration
block moved verbatim, including values, number precision, text lengths, comments,
and the original spelling of names and comments.

ModelConfig imports this object directly. DefaultsModule remains a compatibility
module exposing the same type/object and Kernel's file-unit constants. A direct
test changes the defaults through each import and observes the same object through
the other import. No new settings group or default policy was introduced.

### Runtime updates no longer need copies

DataInput still selects the new batch chunk before reading its constants and data.
Checkpoint still sets `modelConfig%t0` only when timestep preservation is requested.
Their calls to `syncRuntimeModelConfigToGlobals()` were removed after all active
readers moved. Neither operation now needs to update `C`.

Globals and Bootstrap were left byte-for-byte unchanged. Their retained startup
copies are no longer the source of current runtime settings. The runtime-copy
procedure remains available for final cleanup and the existing historical test.

`BiotaScienceTest.f90` and `BiotaIntegrationTest.f90` were also left unchanged.
The science test deliberately sets both old and new values so it can still run
against older phases. Its Globals dependency is the named test exception, not a
production dependency. The new direct tests do not write `C`.

Standalone utility callers must initialise their owning settings before use.
ModelConfig intentionally has neutral values before initialisation, including zero
tolerance. The Reactor mass-loss test now calls `modelConfig%clear()` before setting
its test values; its calculations and known-defect expectations remain unchanged.

## Original Comments and Source Checks

All **1,330 original comment occurrences** in changed production files and the moved
defaults block remain verbatim, in their original order within each retained/moved
block. This includes inline comments, TODOs, repeated comments, and commented-out
code. All **36 original CMake comment lines** remain in order. Original comments in
existing test files were checked too.

The 33 comments associated with model-default declarations moved with the exact
declaration block. Historical comments were retained; separate Phase 10 notes
explain where the current owner or copying behavior differs from their old wording.

After excluding imports, comments, continuation formatting, and the two removed
runtime-copy calls, each changed existing production file matches its original
after applying only the planned owner substitutions. This checks calculations and
procedure declarations as well as comments.

Case-insensitive checks distinguish code from comments. They confirm:

- no active `C%` reference outside retained Globals/Bootstrap code;
- no production Globals import outside Bootstrap;
- no active DefaultsModule reader outside retained Globals;
- no production runtime-copy calls;
- no new test Globals imports; BiotaScienceTest remains the historical exception;
- unchanged Globals, Bootstrap, error registry, Biota comparison sources, shipped
  input files, earlier phase reports, and saved version-file contents.

`git diff --check` passed. The pre-existing `vendor/nanofase-data` workspace state
was preserved. Generated evidence was kept outside tracked source directories.

## Verification

### Reference and build

The fresh reference was built from unchanged Phase 9 production source at:

```text
78d9c61e74f19b0d453af2ff1f0228d6d6b96582
```

Evidence is saved at:

```text
/private/tmp/nanofase_phase10_kxy83w_f
```

The directory contains original source copies and hashes, revision/workspace status,
saved reference executables, CMake caches, compiler flags, generated inputs, commands,
logs, and comparison results. Reference and candidate use the same gfortran-14
Debug configuration and identical flags, including the existing runtime checks.

The reference passed a clean build and all 29 pre-existing tests. The new integration
program was then built against unchanged Phase 9 production code. Reference outputs
were captured before production edits. Both builds use the identical integration
program and unchanged Biota test programs.

The final build commands were:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the exact saved src/VersionModule.f90 contents before building.
cmake --build build-debug --clean-first -j2
ctest --test-dir build-debug --output-on-failure
```

The final candidate passed **33/33 CTest cases**. Four additions cover direct owner
access/defaults and missing required `/data/`, `/output/`, and `/run/` groups. The
required-group checks retain exit 2 and the existing end-of-file failure.

The direct owner test checks repeated configuration reads, omitted optional groups
and values, explicit values, tolerance boundaries and overrides, division/zeroing,
two array shapes, abstract GridCell results, and logger colors without updating `C`.
It also checks that defaults imported through the compatibility module are the same
object. The existing error counts remain 16/17/18/24/25/26 through startup.

CMake still rewrites the tracked version file during configuration. Its exact saved
contents were restored before building, and its final SHA-256 remains:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

Final build/test logs are `candidate_configure_final.log`,
`candidate_build_final.log`, and `candidate_ctest.log`. Existing compiler/linker
warnings remain. An initial build exposed the indirect `NcGroup` import; adding
its explicit owner resolved it before the final clean build.

### Expanded shared-consumer checks

Added `verification/verify_shared_consumers.py`. It checks the complete expected
output-file set, including files that must be absent. It uses existing exact
comparison helpers without changing the older runners' interfaces or tolerances.

The final capture and comparison used:

```sh
python3 -B verification/verify_shared_consumers.py capture \
  --exe /private/tmp/nanofase_phase10_kxy83w_f/reference_nanofase \
  --probe-exe /private/tmp/nanofase_phase10_kxy83w_f/reference_shared_consumer_integration_test \
  --work-dir /private/tmp/nanofase_phase10_kxy83w_f/shared_checks4
python3 -B verification/verify_shared_consumers.py compare \
  --exe build-debug/nanofase \
  --probe-exe build-debug/shared_consumer_integration_test \
  --work-dir /private/tmp/nanofase_phase10_kxy83w_f/shared_checks4
```

| Checks | Actual result |
| --- | --- |
| Both NetCDF writing modes and aggregated/per-waterbody layouts | Four exact output comparisons; expected water dimensions confirmed |
| Full/minimal detail, output selection, suffix, units, steady state | Eight exact comparisons; expected files/columns checked |
| File logging with colors enabled/disabled | Two exact output comparisons and matching logs after removing only timestamps and measured durations |
| One-headwater simulation mask | Exact outputs; one selected cell confirmed in loaded state |
| Batch updates in both NetCDF modes | Two exact comparisons; three chunks reload distinct paths, constants, dates, and 10/11/10-step evaporation arrays |
| End-of-run checkpoint save | Exact ordinary outputs and unchanged defined checkpoint values/layout |
| Warning enabled/suppressed, error output disabled, invalid NetCDF mode | Existing status and diagnostic behavior retained |
| Six checkpoint load/tolerance cases | Restored timestep 10 or retained timestep 1 as requested; inside-tolerance differences accepted and outside differences rejected |

These are **18 complete model-output comparisons**, four startup diagnostic cases,
and six checkpoint cases. CSV files are byte-identical, summaries exclude only
`Simulation datetime`, and NetCDF dumps exclude only `history`. File and console
logs run at identical paths in both stages so no path filtering is needed.

The final column checks explicitly require enabled layer/state, erosion, sediment
flux, and sediment-size columns, and reject them when disabled. They also check
metadata on/off and the exact soil concentration-unit label. Both archived stages
passed these strengthened checks again; results are in `output_column_recheck.log`.
The sediment writer already emits both concentration units regardless of its unit
setting. The checks preserve this existing behavior rather than claiming that the
setting changes sediment output.

Checkpoint files retain six records with payload lengths 24, 4, 6,816, 20,736,
303,360, and 73,920 bytes, for a 404,908-byte file including record markers. Grid,
timestep, soil state, and zero-initialised water arrays compare in full. Water
volume, bed area, and sediment values compare for every existing reach: 5,418
double-precision values in those spatial arrays.

The existing writer does not initialise some positions for nonexistent reaches.
The fixture has ten such positions in its rectangular reach arrays. Raw checkpoint
comparison initially found 2,148 differing unused sediment values and **no differing
values for existing reaches**. The final check excludes only those known unused
positions. Additional checks deliberately changed an existing-reach value, water
state, and the grid header; each change was rejected. Changing only an unused
position was accepted. The production checkpoint writer/format was not repaired.

Both builds load the same pre-phase checkpoint. Tolerance fixtures use a copy with
two grid-header values set to zero, allowing small differences to survive the
existing default-real precision. They preserve the normal model tolerance during
construction. An earlier fixture used a large tolerance and disrupted startup;
it was replaced before completing verification. Failed attempts remain in
`shared_checks`, `shared_checks2`, and `shared_checks3`; final passing evidence is
in `shared_checks4`.

### Existing regression suites

WaterBody, Reactor, and Biota were captured and compared using their existing
`capture`/`compare` commands and the same fresh Phase 9 reference executable.
Their work directories are `waterbody_checks`, `reactor_checks`, and `biota_checks`
under the evidence directory. Capture used the saved `reference_biota_science_test`
and `reference_biota_integration_test`; comparison used the corresponding
`build-debug` programs. Exact commands are saved by each runner, and results are
in the corresponding `*_capture.log` and `*_compare.log` files.

All **14 WaterBody**, **nine Reactor**, and **six Biota** ordinary output comparisons
passed, bringing the phase total to **47**. Biota also retained 50 exact direct
records, 7,500 exact concentration records inside the model, and the existing
organism-count checks. Source-hash protections were unchanged.

The four established WaterBody failure cases retained their exit statuses and
meaningful messages. Existing batch and checkpoint save/load checks passed. These
checks remain separate from claims of correct checkpoint continuation.

The comment/source checks are saved as `check_source.py` and `source_checks.json`
beside the evidence. Temporary evidence may eventually disappear; the tracked
programs, fixtures, runners, and [verification instructions](../verification/README.md)
allow the model checks to be repeated from the reference revision.

## Preserved Limitations and Remaining Work

1. Correct the remaining diagnostic list separately: blank entries, missing code
   405, and ownership of 110/200/201/300/901. Those five codes currently have no
   production raising sites; ownership must be decided from their meaning rather
   than inferred from nonexistent calls. ErrorHandling already owns the list and
   does not require Globals.
2. Remove Globals, its fields and copying helpers, Bootstrap's startup copying,
   DefaultsModule's compatibility export, and historical test compatibility writes
   in final cleanup. Preserve their original comments when code is moved/removed.
3. Correct checkpoint continuation separately. The main loop still starts at 1
   without reading restored `t0`; warm-up/reinstatement timing remains unresolved;
   Biota concentrations are not saved. Restoring a nonzero field proves only that
   field was loaded, not that simulation continuation is correct.
4. Decide separately whether to initialise unused checkpoint slots. They contain
   no live reach state and cannot be used as stable numeric reference values.
5. Implement compartment statistics separately if needed. Enabling the option
   currently creates an empty CSV because its writer is a commented-out stub.
6. Preserve the existing `heteroaggregatedNM` utility behavior unless separately
   corrected. It sums across particle sizes. For the new three-size fixture both
   original Phase 9 and Phase 10 return `[9, 12, 15]`; the initial new test had
   expected a sum across states and was corrected against the original procedure.
   The comparison source/result are saved in `utility_reference`. This utility has
   no current production callers, and no science change was made here.
7. Keep the documented river-disabled, terrain-outlet, Reactor mass-loss, Biota
   harvest/invalid-input, and other science repairs in their separate tested work.
8. Stop CMake from rewriting the tracked version file in a separate build change.

The main plan and verification guide now describe Phase 10, its compatibility
exceptions, stronger output/state checks, and these limitations. Earlier phase
reports were left unchanged. Each future phase must likewise record what changed,
what actually passed, and what remains in this folder, while retaining original
code comments.
