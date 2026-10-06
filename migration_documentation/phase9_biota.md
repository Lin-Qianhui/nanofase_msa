# Phase 9 Biota Migration

## Summary

Phase 9 is complete. Biota now owns error 902, and all three Biota source files
obtain precision and timing from the modules that own those values. A module is
a named group of Fortran code and values. The calculations, public types and
procedures, input readers, and original comments were preserved.

Verification on 5 October 2026 passed a clean build and all **29 focused tests**.
Against a fresh Phase 8 reference, **50 direct concentration records**, **7,500
organism-state records**, and **29 ordinary model output comparisons** matched
exactly under the rules below. Four expected failures retained their exit status
and meaningful messages. Batch operation and checkpoint saving/loading passed.

The next migration is the **shared-consumer phase**: move remaining readers of the
older shared `C` object and model-wide defaults to the modules that own them.

## What Changed

### Biota owns its existing error

Added `src/Biota/BiotaConfigModule.f90`. Its only public procedure is
`registerBiotaErrors()`, which adds this existing critical error to the shared
error list:

```text
902: Invalid Biota index provided.
```

Critical means that triggering the error can stop the model when error output is
enabled. The procedure uses the existing named `error=ErrorInstance(...)` argument.
Bootstrap calls it immediately after Reactor error registration and before copying
dimensions into `C` for older consumers.

Only code 902 was removed from the shared list. Its array now has seven positions;
blank positions 4 and 5 and code 901 in position 7 remain. The registered counts are:

| Initialisation completed | Registered errors |
| --- | ---: |
| Shared handler | 16 |
| Soil | 17 |
| BedSediment | 18 |
| WaterBody | 24 |
| Reactor | 25 |
| Biota | 26 |

The final total is unchanged. Code 405 remains absent, and the blank code-1 message
and other messages and severity settings remain unchanged. Code 902 has no current
science call that raises it. None was added, and the separate invalid-uptake-form
message was not replaced by 902.

### Inputs still come from the same files

Biota has no settings group in `config.nml`, no fallback constants to move, and no
domain-specific fields to remove from `C`. The new module therefore has no
configuration object, file reader, defaults, or file-path argument.

Organism inputs already exist in the separate constants file as `/n_biota_grp/`
and `/biota/`. These are named groups of input values. DataInput still reads them,
stores their values, and reloads input during batch changes in its original order.
Its source was unchanged. No new required values, defaults, or validation were added.

### Biota reads shared values from their owners

`AbstractBiotaModule`, `BiotaSoilModule`, and `BiotaWaterModule` now import precision
directly from Kernel. The two concrete organism classes read `startDate` and
`timeStep` from `modelConfig` on each update. They explicitly import the result and
error types, input data, date operations, and `str`/`isZero` helpers they use.

No direct `GlobalsModule` import or `C%` read remains under `src/Biota/`. The
existing `isZero` utility still obtains its default tolerance through `C`; changing
that utility remains work for the shared-consumer phase. The timing fields also
remain in `C` for other consumers that have not migrated.

The three public Biota types, their components, procedure bindings and arguments,
array shapes, number precision, expressions, and operation order are unchanged.
SoilLayer, RiverReach, and EstuaryReach still select, create, and update organisms
in the same places. Those consumers required no source changes.

## Original Comments and Source Checks

All **82 original comment occurrences** across the ten changed existing Fortran
files remain verbatim and in order, including repeated comments, TODOs, and
commented-out logging lines. All **33 original CMake comment lines** remain in
order. Added explanations did not replace any original comment.

A separate comparison removed import lines and applied only the planned changes
from `C%startDate`/`C%timeStep` to `modelConfig`. Each of the three Biota science
files then matched its original source exactly apart from trailing whitespace.
This checks the procedure declarations and calculations as well as their comments.

Source checks also confirmed one production registration site for 902, unchanged
shipped-input hashes, unchanged earlier phase reports, and unchanged Globals,
DataInput, DataOutput, Checkpoint, and Util sources. The pre-existing
`vendor/nanofase-data` state was preserved. `git diff --check` passed.

## Verification

### Reference, build, and saved evidence

The fresh reference was built from unchanged Phase 8 revision:

```text
c1e73e0fc41bc1b3568864366933e4638c387812
```

Evidence is outside tracked source directories at:

```text
/private/tmp/nanofase_phase9_zby5x4se
```

`original/`, `original_hashes.json`, `revision.txt`, and `status.txt` record the
starting files and workspace. Saved CMake caches and compiler flags identify both
builds; the compiler flags match exactly. `reference_nanofase` and the two
`reference_biota_*_test` executables are the saved reference programs. The original
test sources and reference test-build definition are also saved there.

Both builds used the existing Debug configuration and gfortran-14. Before any
production edits, the clean Phase 8 build and its 25 tests passed. The two new
concentration test programs were then compiled against the unchanged production
source, and all reference scenarios were captured before the migration.

The build commands were:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the exact saved src/VersionModule.f90 contents before building.
cmake --build build-debug --clean-first -j2
ctest --test-dir build-debug --output-on-failure
```

For the reference test programs, the additional build command was:

```sh
cmake --build build-debug --target biota_science_test biota_integration_test -j2
```

The final candidate passed **29/29 CTest cases**. The four additions cover direct
Biota calculations, the full error-registration sequence, enabled critical error
output, and disabled error output. Existing tests now check the changed intermediate
counts and leave registration of 902 to Biota. The critical-error tests disable
warnings to establish that this does not suppress a critical error.

CMake rewrote the version file during configuration. Its exact saved contents were
restored before each build. Its final SHA-256 remains:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

Build and test logs are `reference_build.log`, `reference_ctest.log`,
`reference_probes_build.log`, `candidate_build.log`, and `candidate_ctest.log`.
Existing compiler and linker warnings did not prevent either build.

### Direct organism calculations

`test/BiotaScienceTest.f90` calls the real Biota procedures and emits both active
and stored concentrations at full precision. The identical source was compiled
against Phase 8 and Phase 9; all **50 records** matched exactly.

The test checks copied creation inputs, initial concentrations, all six supported
uptake spellings, soil and water's different attachment positions, and pristine,
transformed, and dissolved material separately and together. It also covers zero,
intermediate, and full storage fractions; positive and zero combined growth/death;
daily and half-day timesteps; harvest-month transitions; and a changed start date
without recreating the organism. Assertions establish that intended differences
occur and that equivalent uptake spellings agree.

The test deliberately sets both the new timing owner and the older `C` copy so
that the same program can run on Phase 8. This is test compatibility code, not a
new production dependency. No unstable invalid-form numeric values are used as
reference expectations.

### Organisms inside the running model

`test/BiotaIntegrationTest.f90` uses the normal Bootstrap and Environment procedures
and follows the normal warm-up, update, and batch-switch sequence. It records
organism counts, selected input indices, and concentrations after construction and
updates. It adds no production output fields.

| Case | Organisms created | Concentration records | Before/after result |
| --- | ---: | ---: | --- |
| No Biota inputs | 0 | 0 | exact counts and ordinary outputs |
| Soil only | 72 | 936 | exact match |
| Water only | 28 | 364 | exact match |
| Mixed soil and river organisms | 100 | 1,300 | exact match |
| Mixed soil and estuary organisms | 100 | 1,300 | exact match |
| Three batch chunks | 100 | 3,600 | exact match |

All **7,500 concentration records** and **101 count records** matched. Checks
confirmed the correct input indices and changes to organism concentrations in each
applicable compartment. The estuary fixture contains estuary reaches throughout;
it does not contain river reaches. An initial fixture expectation assumed both
types, and was corrected before production changes. That first attempt is retained
in `biota_checks_attempt1`; the complete reference and candidate are in `biota_checks`.

The batch starts its chunks on 25 January, 4 February, and 1 March. It exercises
harvesting across a month boundary, checks 1,100 zero-concentration records in the
February chunk, and confirms recovery in both soil and water in March.

The actual Biota runner commands were:

```sh
python3 -B verification/verify_biota.py capture \
  --exe /private/tmp/nanofase_phase9_zby5x4se/reference_nanofase \
  --science-exe /private/tmp/nanofase_phase9_zby5x4se/reference_biota_science_test \
  --integration-exe /private/tmp/nanofase_phase9_zby5x4se/reference_biota_integration_test \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/biota_checks
python3 -B verification/verify_biota.py compare \
  --exe build-debug/nanofase \
  --science-exe build-debug/biota_science_test \
  --integration-exe build-debug/biota_integration_test \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/biota_checks
```

The runner saves generated inputs, input and executable hashes, commands, logs,
state records, and evidence that the intended behaviour was exercised. It refuses
to overwrite existing results and checks that test sources and inputs have not
changed between capture and comparison.

### Ordinary outputs, expected failures, and checkpoint checks

All six Biota model output sets matched exactly, including the batch case. The
nine Reactor and fourteen successful WaterBody scenarios were also captured and
compared against the same fresh reference:

```sh
python3 -B verification/verify_reactor.py capture \
  --exe /private/tmp/nanofase_phase9_zby5x4se/reference_nanofase \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/reactor_checks
python3 -B verification/verify_reactor.py compare \
  --exe build-debug/nanofase \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/reactor_checks
python3 -B verification/verify_waterbody.py capture \
  --exe /private/tmp/nanofase_phase9_zby5x4se/reference_nanofase \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/waterbody_checks
python3 -B verification/verify_waterbody.py compare \
  --exe build-debug/nanofase \
  --work-dir /private/tmp/nanofase_phase9_zby5x4se/waterbody_checks
```

For all **29 ordinary output comparisons**, CSV files were byte-identical.
`summary.md` matched after removing only `Simulation datetime`; NetCDF text from
`ncdump` matched after removing only `history` metadata. Raw NetCDF bytes are not
required to match because their metadata records when the run occurred.

| Additional check | Result |
| --- | --- |
| Terrain at river outlet | unchanged exit 2 and out-of-bounds terrain message |
| River with bed sediment disabled | unchanged exit 1 and unset deposit-result message |
| Unknown Water setting | unchanged exit 2 and unknown-setting message |
| Invalid Water integer followed by another group | unchanged exit 2 and invalid-input message |
| Biota error 902, output enabled | exit 1 and unchanged critical message |
| Biota error 902, output disabled | exit 0 without the critical message |
| Existing batch check | exit 0; three chunks and 31 timesteps |
| Checkpoint save after warm-up | exit 0; 404,908-byte file |
| Checkpoint load with timestep preservation | exit 0 |

Expected-failure comparisons exclude changing source-line numbers and runtime
addresses. Checkpoint checks establish only that saving and loading complete.
They do not prove correct continuation of either model timing or Biota state.

Temporary evidence may eventually be removed. The tracked test programs, runner,
and instructions in [verification/README.md](../verification/README.md) make the
checks repeatable without depending on this particular temporary directory.

## Preserved Limitations and Remaining Work

1. Move the remaining shared-`C` readers in data, output, logging, utilities,
   checkpoint code, and other consumers to their owners. Move model-wide defaults
   into the model configuration area before removing `DefaultsModule`.
2. Add checkpoint saving and restoration of both concentrations for soil and water
   organisms, with tests for compatibility with existing checkpoint files. The
   current checkpoint code saves neither concentration. Resolve the existing
   warm-up/reinstatement timing as well before proving exact continuation.
3. Define harvesting for non-daily timesteps and whether it should happen once or
   throughout the selected month. Current code advances the harvest date one day
   per step and resets concentrations on every update in that month. Phase 9
   deliberately retains these results, including the half-day case.
4. Handle invalid uptake forms before calculations use unset concentration sums.
   Current code records a message and continues. That repair needs a separate
   error-behaviour test; undefined numeric values are not meaningful reference data.
5. The existing zero combined growth/death branch leaves stored concentration
   unchanged even with positive uptake. The direct test preserves this current
   result; any science change needs its own review and tests.
6. Correct Reactor attachment mass loss, the incomplete river-disabled behaviour,
   and terrain access at outlets in their separately tested changes.
7. Correct the blank error entries, missing 405, code-901 ownership, and remaining
   unassigned error owners separately from ownership migration.
8. Stop CMake configuration from rewriting the tracked version file.
9. Remove the remaining `C` object, its copying helpers, unused fields such as
   `C%T`, and the old error list only after their consumers and error owners have
   migrated. Input-data and utility dependencies remain explicit follow-up work.

The main plan now records Phase 9 completion, the distinction between model-config
and constants-file Biota inputs, direct-state verification, and the additional
checkpoint limitation. Earlier phase reports were left unchanged. Each future
phase must likewise preserve original code comments and record what changed,
what actually passed, and what remains in this documentation folder.
