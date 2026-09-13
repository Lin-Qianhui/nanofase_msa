# Phase 7 WaterBody Migration

## Summary

Phase 7 is complete. WaterBody now owns its four model settings, six fallback
constants, and six effective error codes. A fallback constant supplies a value when
the corresponding input is absent. Scientific calculations and public science
types and procedures are unchanged, and every original code comment was retained.

Verification on 12 September 2026 passed all 21 focused tests and 14 exact
scientific comparisons against a fresh Phase 6 executable. Four expected failures
retained their exit status and meaningful error text. Batch operation and checkpoint
save/reinstate also passed. The next domain is **Phase 8: Reactor**.

## What Changed

### WaterBody owns its configuration

Added `src/WaterBody/WaterBodyConfigModule.f90`. Its public interface consists of
`WaterBodyConfigType`, the shared `waterBodyConfig` object, its
`init(configFilePath)` procedure, and the six constants listed below. The shared
object holds the settings used throughout a running model.

| Setting | Number or value type | Default |
| --- | --- | --- |
| `minStreamSlope` | default `real` | `0.0001` |
| `minEstuaryTimestep` | `integer` | `3600` seconds |
| `includeEstuary` | `logical` | true |
| `includeBankErosion` | `logical` | true |

The initializer reads the optional `/water/` group in the model configuration file.
A namelist is a named group of settings in a Fortran input file. All four group
members are optional too. The initializer assigns the existing defaults before
each read, opens the supplied file with an available file-unit number, preserves the
old two-read/status-check sequence, closes the file, and stores the settings.

The old reading sequence first reads with a status result, rewinds, and repeats the
read without a status argument when that first status is nonnegative. A missing
group therefore leaves defaults in place. This phase adds no new validation or
numeric conversions. In particular, minimum slope remains default `real`, and
estuary timestep divisions remain integer divisions where they were before.

### Constants moved; the constants-file reader stayed in place

| Constant | Existing type and value |
| --- | --- |
| `defaultSlope` | `real(dp)`, `0.0005_dp` |
| `defaultBankErosionAlpha` | `real(dp)`, `1.0e-9_dp` |
| `defaultBankErosionBeta` | `real(dp)`, `1.0_dp` |
| `defaultMinWaterTemperature` | default `real`, `4.0` |
| `defaultMaxWaterTemperature` | default `real`, `21.0` |
| `defaultMinWaterTemperatureDayOfYear` | `integer`, `32` |

`real(dp)` is the model's double-precision number type. Default `real` has lower
precision in the tested build. Keeping these types, including the default-real
local bank-erosion buffers in DataInput, preserves existing rounding.

DataInput still reads the different `/water/` group in the constants input file.
Its declarations, reading order, temperature calculations, assignments, and rules
giving spatial values priority were not changed. It now imports the moved constants
from WaterBody. Reach imports `defaultSlope` from that same owner. Deposition
constants remain in BedSediment; reaction constants remain for the Reactor phase.

### Startup and the remaining shared object

The relevant startup order is now:

1. Read model dimensions and general model settings, then initialise the shared
   error handler.
2. Initialise Soil, followed by BedSediment.
3. Copy general model settings into `C` for older consumers.
4. Initialise WaterBody and register its six effective errors.
5. Copy dimensions into `C` using the private `syncModelDimensionsToGlobals` helper.
6. Continue the existing model audit, Source, logger, input-data, and construction
   steps.

The four WaterBody fields were removed from `GlobalsType`, along with their old
defaults and assignments into `C`. Bootstrap no longer reads any domain namelist.
The former `initLegacyGlobalsFacade` helper became the dimension-copying helper;
the separate model-copying helper remains. Both are private, so Bootstrap's public
`bootstrap(env)` interface is unchanged.

### WaterBody owns six registered errors

Codes 401, 402, 403, 404, 500, and 501 moved with their exact messages and status.
Code 500 remains a warning; the other five remain critical errors. No new science
error-raising site was introduced, and existing logging and error handling were not
reordered.

The original code-405 assignment is deliberately retained in a private six-element
list, where code 500 overwrites it before registration. Only the final six entries
are registered, using the named `error=` argument. Code 405 therefore remains absent.

The shared legacy array now has nine positions. Its blank positions 4 and 5 remain;
codes 901 to 903 occupy positions 7 to 9. The effective counts are:

| Initialisation completed | Registered errors |
| --- | --- |
| Shared handler | 18 |
| Soil | 19 |
| BedSediment | 20 |
| WaterBody | 26 |

### Science modules read settings from their owners

Removed direct `GlobalsModule` imports and all `C%` reads from WaterBodyModule,
FlowModule, ReachModule, RiverReachModule, and EstuaryReachModule. They now obtain
precision and physical functions from Kernel, array sizes and particle properties
from ModelDimensions, run settings from ModelConfig, and WaterBody settings from
WaterBodyConfig. Required date types, results, errors, and the shared handler are
imported directly where needed.

DataInput's `includeEstuary` access also uses the new owner. Existing connections to
Source, BedSediment, Reactor, Biota, utilities, and input data remain. This phase
removes WaterBody's direct use of the shared `C` object; it does not claim that the
science has become independent of all other domains.

## Original Comments and Preserved Behaviour

Every original comment and TODO was retained verbatim. Field, default, namelist,
and error-category comments moved with their code. Comments describing the former
owner remain, accompanied by separate `Phase 7 note` comments explaining the move.

A comment-count comparison covered all changed existing Fortran files and the new
configuration module, including repeated comments. Each of the five science files
also retained its original comment order. CMake's original comments were checked
in order too.

A separate source comparison removed imports and comments, then applied only the
planned owner-reference substitutions to the original science files. All five
matched their changed versions apart from trailing whitespace. This checks that
existing types, procedures, array shapes, and calculations were not rewritten.

All shipped configuration and data-file hashes were unchanged. Earlier phase
reports were left unchanged. The pre-existing `vendor/nanofase-data` workspace
state was preserved.

## Verification

### Reference build and evidence

The reference executable was built from unchanged Phase 6 revision:

```text
55928ee0c6408174c6d08438c17b3e65a756fc96
```

The build used the existing Debug CMake configuration and gfortran-14. Before any
science edits, the original files and their hashes were saved, CMake configuration
and build passed, all five pre-phase CTest cases passed, and the reference executable
was copied. Reference results were then captured before the source migration.

Local evidence is under:

```text
/private/tmp/nanofase_phase7_qlbfdmsi
```

`original/`, `original_hashes.json`, `revision.txt`, `reference_CMakeCache.txt`, and
`reference_nanofase` record the starting state. `checks/inputs/` holds generated
inputs. `checks/reference/` and `checks/candidate/` hold commands, results, logs,
and the evidence that each scenario exercises its intended behaviour. Input and
executable hashes are recorded in `checks/provenance.json` and the stage-specific
`executable.json` files.

These large local evidence files are temporary. Repeating the tests uses the source
runner and fixtures described below; it does not require the old Phase 6 temporary
directory, which was no longer available during this phase.

### Build and focused tests

The following commands were run from the repository root:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the saved VersionModule.f90 contents before building.
cmake --build build-debug -j2
ctest --test-dir build-debug --output-on-failure
```

The final build passed and CTest passed **21/21** cases. Build warnings included
existing number conversions, unused variables and arguments, continued strings,
and version-text truncation. The new configuration and slope test executables have
separate directories for compiled Fortran module files.

Tests cover explicit settings; empty, absent, and partially supplied Water groups;
each individually omitted member; all defaults and constant types; all six error
messages and statuses; the 18/19/20/26 counts; missing code 405; warnings enabled and
suppressed; and critical errors with output enabled and disabled.

The interior-reach slope test covers flat, uphill, and steep terrain, missing
terrain, and both headwater and non-headwater geometry. It calls the existing
procedure on a small terrain array with its neighbours inside the array.

One initial malformed-input fixture ended immediately after `/water/` and therefore
did not produce the expected rejection. The old Phase 6 reader was compiled and
checked separately: it also returned successfully with default settings for that
fixture. With a following `/sources/` group, it failed with exit 2. The tests now
cover both existing outcomes, rather than imposing a new validation rule.

Final build and test logs are `final_build.log` and `final_ctest.log`. The final
model executable's hash was identical to the executable used for the exact
comparisons, so the last test-list update did not invalidate those comparisons.

### Exact scientific comparisons

The actual capture and comparison commands were:

```sh
python3 verification/verify_waterbody.py capture \
  --exe /private/tmp/nanofase_phase7_qlbfdmsi/reference_nanofase \
  --work-dir /private/tmp/nanofase_phase7_qlbfdmsi/checks

python3 verification/verify_waterbody.py compare \
  --exe build-debug/nanofase \
  --work-dir /private/tmp/nanofase_phase7_qlbfdmsi/checks
```

| Scenario | Result |
| --- | --- |
| `river` | exact match |
| `missing_water` | exact match; also reproduces canonical CSV results |
| `empty_water` | exact match; also reproduces canonical CSV results |
| `partial_water` | exact match; also reproduces the bank-disabled CSV results |
| `bank_off` | exact match |
| `estuary` | exact match |
| `estuary_as_river` | exact match |
| `estuary_1800` | exact match |
| `estuary_bed_off` | exact match |
| `constants_fallback` | exact match |
| `bank_explicit` | exact match |
| `constants_explicit` | exact match |
| `spatial_bank` | exact match |
| `spatial_bank_changed_constants` | exact match |

All three CSV files were byte-identical in every before/after comparison.
`summary.md` matched after removing only its `Simulation datetime` line. The
`ncdump` text of `output.nc` matched after removing only its `history` metadata.
Raw NetCDF file bytes are not required to match because that metadata changes.

The reference comparisons confirmed that bank erosion, estuary treatment, estuary
timestep, temperature defaults, and explicit bank constants affect results. The
generated spatial bank values affect results but make subsequent changes to bank
constants ineffective, confirming that the spatial values still take priority.
Both original datasets were checked to lack spatial bank coefficients and terrain
heights, so those inputs cannot silently hide the fallback tests.

### Expected failures, batch, and checkpoints

| Scenario | Before and after |
| --- | --- |
| Terrain heights added at the river outlet | exit 2; terrain-array index exceeds its upper bound |
| River with bed sediment disabled | exit 1; unset deposit result cannot be returned as `REAL(DP)` |
| Unknown Water setting | exit 2; cannot match `unknown_water_setting` |
| Invalid integer followed by another group | exit 2; cannot match `'invalid'` |
| Batch run | exit 0; 3 batches and 31 timesteps |
| Checkpoint save after warm-up | exit 0; 404,908-byte file |
| Checkpoint reinstate with timestep preservation | exit 0 |

Expected-failure comparisons check exit status and meaningful text, excluding
changing source locations and runtime addresses. Checkpoint checks show that saving
and loading complete; they do not prove identical continuation from a saved state.

### Repeating the checks

Build Phase 6 revision `55928ee0c6408174c6d08438c17b3e65a756fc96` in a separate
checkout with the same compiler and build settings, retaining its original version
file. Save that executable, then run the capture command with its path and a new
work directory. Run compare with the changed executable and that same directory.
Build the current checkout and run CTest for the focused tests.

The runner creates all scenario inputs from the shipped examples using Python's
standard library, `ncdump`, and `ncgen`. It saves copies of the input files and
checks their hashes before comparison. It invokes `verify_refactor.py --exact` for
every successful scenario. Reusing an existing reference or candidate output
directory is rejected; choose a fresh work directory for a new verification run.

### Source and workspace checks

```sh
rg -n 'use[[:space:]]+GlobalsModule|\bC%' src/WaterBody
rg -n -i 'C%(minStreamSlope|minEstuaryTimestep|includeEstuary|includeBankErosion)([^A-Za-z0-9_]|$)' src
rg -n -i 'namelist[[:space:]]*/water/' src
git diff --check
shasum -a 256 src/VersionModule.f90
```

The first two searches returned no matches. The Water declarations remain only in
the new configuration reader and the separate DataInput constants reader. Comment,
science-source, shipped-input, earlier-report, and whitespace checks passed.

CMake rewrote the version file during configuration. Its exact saved contents were
restored before each build. Its final SHA-256 is unchanged:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

## Remaining Work

1. Phase 8: migrate Reactor defaults and its assigned error without changing
   reaction calculations.
2. Phase 9: migrate Biota, including the current Soil-to-Biota relationship.
3. Migrate the remaining `C` readers in data, output, logging, utilities, checkpoint
   code, and other consumers. WaterBody still uses some of these modules indirectly.
4. Correct the blank error entries, missing code 405, code 901 ownership, and the
   other unassigned owners in a separate tested change. Code 405 now resides in
   WaterBody's overwritten list position, not the shared legacy list.
5. Define and repair river behaviour with bed sediment disabled, covering deposition,
   resuspension, nanomaterial transfers, and water-depth effects.
6. Define and repair terrain-height access when a reach's outflow is outside the
   terrain array. Preserve interior-reach behaviour while testing both outlet types.
7. Resolve warm-up/reinstatement timing and prove exact checkpoint continuation.
8. Stop CMake from rewriting the tracked version file during configuration.
9. Remove `C`, its copying helpers, and the empty legacy error list only after their
   remaining consumers and error owners have migrated.
10. If optional Water input validation is tightened later, test it as a separate
    behaviour change. Phase 7 intentionally retains the EOF-sensitive malformed
    input behaviour described above.
