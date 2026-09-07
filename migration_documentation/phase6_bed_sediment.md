# Phase 6 BedSediment Migration

## Summary

Phase 6 is complete. BedSediment now owns its two model settings, seven sediment
fallback constants, and error code 904. A fallback constant is the value used when
that value is absent from the constants input file.

This phase reorganised the source code. The supported inputs, public science types
and procedures, calculation order, and scientific results remain unchanged. All
seven successful test scenarios matched their fresh Phase 5 reference results
exactly under the comparison rules below. All original code comments were retained
verbatim, including comments moved to the new owner.

The next domain is **Phase 7: WaterBody**.

## What Changed

### A BedSediment module now owns the settings

Added `src/BedSediment/BedSedimentConfigModule.f90`. Its public interface consists of
`BedSedimentConfigType`, the shared `bedSedimentConfig` object, its
`init(configFilePath)` procedure, and the seven constants listed below. The shared
object is one instance used throughout the running model.

It owns exactly these settings:

- `sedimentLayerDepth(:)`: the depth of each sediment layer, kept as default `real`;
- `includeBedSediment`: the existing logical on/off setting.

The initializer reads the `/sediment/` namelist group in the model configuration
file. A namelist is a named group of settings in a Fortran input file. It allocates
temporary arrays using the layer, size-class, and composition counts from
`ModelDimensionsModule`, opens the supplied file with an available file-unit number,
reads the group, closes the file, and stores the two owned settings.

Fortran requires the reader to declare every member that may appear in the group.
The new reader therefore also declares local `spm_size_classes` and
`sediment_particle_densities` arrays. These are temporary input buffers only. The
stored size classes, particle densities, and counts still belong to
`ModelDimensionsModule`, whose earlier read remains unchanged.

Neither setting gained a default or new validation. Both must still be supplied for
supported input. Missing individual values are not newly checked; a missing complete
group still fails at the required read. Keeping default `real` for layer depths is
intentional: increasing their precision could change rounding and results.

### Sediment constants moved, but their input readers stayed in place

The following public constants moved from `DefaultsModule` to the new module. Their
names, values, precision, and original comments are unchanged. `real(dp)` means the
model's double-precision real number type.

| Constant | Value | Constants-file group that uses it |
| --- | --- | --- |
| `defaultSedimentTransport_a` | `2.0e-9_dp` | `/soil/` |
| `defaultSedimentTransport_b` | `0.0_dp` | `/soil/` |
| `defaultSedimentTransport_c` | `0.2_dp` | `/soil/` |
| `defaultSedimentEnrichment_k` | `1.0_dp` | `/sediment/` |
| `defaultSedimentEnrichment_a` | `0.0_dp` | `/sediment/` |
| `defaultDepositionAlpha` | `38.1_dp` | `/water/` |
| `defaultDepositionBeta` | `0.93_dp` | `/water/` |

All seven remain `real(dp), parameter`, meaning double-precision constants.
`DataInputModule` imports them from their new owner. It still reads the same groups
from the separate constants file, in the same order, and stores the values in
`DATASET`. Its local deposition variables remain default `real`; their existing
conversions and the rule that spatial input values take priority are unchanged.

The model-configuration `/sediment/` group and constants-file `/sediment/` group are
different groups in different files. Phase 6 did not merge them or move the
constants-file reader.

### Startup and error registration

The relevant startup order is now:

1. Read shared model dimensions, including the first full `/sediment/` read.
2. Read general model settings and initialise the shared error handler.
3. Initialise Soil and register code 600.
4. Initialise BedSediment and register code 904.
5. Read the remaining legacy Water configuration and copy shared values into `C`
   for older consumers.
6. Continue the existing model audit, Source, logger, data, and construction steps.

The old sediment reader, temporary arrays, and assignments into `C` were removed
from Bootstrap. The two migrated fields were removed from `GlobalsType`. Copies of
shared dimensions remain for consumers that have not migrated yet.

This preserves the later Soil, Sediment, Water, then model-audit order. It does not
mean every sediment input error occurs after Soil: the first dimension read already
reads `/sediment/`, so a missing or malformed group can fail earlier.

Code 904 is registered after the new configuration read using the named
`error=ErrorInstance(...)` argument. Its message remains:

```text
Invalid BedSedimentLayer index provided.
```

It remains critical, meaning it can stop the model when triggered through the
enabled error handler. The remaining old error array shrank from 16 slots to 15. The effective
number of registered errors is 24 after shared-handler initialisation, 25 after
Soil, and 26 after BedSediment. The total after both domains is unchanged.

Codes 901 to 903 remain in legacy slots 13 to 15. The blank entries in slots 4 and 5
and overwritten code 405 remain unchanged. Code 904 currently has no raising site
in the sediment science implementation; this phase tests its registration without
inventing a new raising site. Existing inline sediment errors retain their messages
and handling.

### Science and other consumers

Removed direct `GlobalsModule` imports and all `C%` reads from the five existing
science files in `src/BedSediment/` and `src/BedSedimentLayer/`, including
`FineSedimentModule` and local abstract procedure declarations. Precision now comes
from `KernelModule`; counts and particle properties come from `ModelDimensionsModule`;
depths come from `BedSedimentConfigModule`. Error types and the shared handler are
imported explicitly where needed.

Other modules that read these settings also changed: Reach and EstuaryReach use the new
switch; GridCell and DataOutput use the new depth array. GridCell imports the error
handler directly and no longer directly imports Globals. DataInput's only change is
its import of the seven constants.

Existing types, procedure arguments and bindings, array shapes, equations, operation
order, construction, batch updates, and checkpoint layout were preserved. Removing
direct Globals access does not make sediment science fully independent: it still
uses shared utility and input-data code.

## Original Comments and Workspace Preservation

The original comment sequence was compared before and after in each of the five
sediment science files, the changed external consumers, the error module, and the
existing tests. Every sequence matched. The field comments, deposition references,
and two allocation-comment lines moved verbatim from Globals, Defaults, and Bootstrap
into the new configuration module. A separate count of the comments confirmed that none was lost,
including repeated comments. Existing CMake comments remain in place.

A separate source comparison removed import lines and reversed only the planned
owner-reference substitutions. All five science files then matched their original
code, apart from trailing whitespace. This checks that the calculations and existing
interfaces were not rewritten during the move.

All shipped configuration and data files retained their original SHA-256 hashes.
Earlier phase reports were left unchanged. The pre-existing `vendor/nanofase-data`
workspace state was preserved.

CMake configuration rewrote `src/VersionModule.f90`. Before each configuration its
original contents were saved, and those exact contents were restored before building.
Its final SHA-256 remains:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

## Verification

Verification was completed on 6 September 2026 using the existing Debug CMake setup
and gfortran-14. Fresh reference results came from an unchanged Phase 5 build made
before the source edits. The reference executable was also saved.

All generated inputs, reference results, candidate results, commands, and logs are
outside the tracked source directories under:

```text
/private/tmp/nanofase_phase6_zi4qfe3g
```

`pre/` contains the Phase 5 references. `post_final/` contains results from the final
Phase 6 executable. `original/` and `original_hashes.json` hold the original-file
evidence. The temporary runner and source-check script are retained there too; these
local evidence files are not added to the repository.

### Build and focused tests

The commands run from the repository root were:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the saved VersionModule.f90 contents before building.
cmake --build build-debug -j2
ctest --test-dir build-debug --output-on-failure
```

Both pre-change and post-change builds passed. Compiler warnings included existing
number conversions, unused variables/arguments, continued strings, and version-text
truncation. Four changed code lines had inherited trailing whitespace; it was removed
without altering comments or calculations, and the final executable was rebuilt and
all checks rerun. No further CMake configuration followed that final build.

CTest passed **5/5** cases: the shared registry, Soil configuration, BedSediment on,
BedSediment off, and the required missing BedSediment group. The new executable has
its own directory for compiled Fortran module files.

The BedSediment tests use three layers, two size classes, and four composition
fractions. They check unequal depths, both switch values, depth precision, all seven
constant values and precisions, the 24/25/26 error counts, and exactly one unchanged
critical code 904. The disabled fixture deliberately supplies different size classes
and densities to prove that the domain reader does not overwrite their shared owner.

The missing-group test loads dimensions and Soil from a valid fixture first. Its
wrapper checks that execution reached the BedSediment reader and then failed, so an
earlier dimensions failure cannot count as success.

The final build and test logs are `final_build.log` and `post_ctest.log` under the
evidence directory.

### Exact scientific result comparisons

The local runner was invoked with:

```sh
python3 /private/tmp/nanofase_phase6_zi4qfe3g/run_phase6_checks.py pre
python3 /private/tmp/nanofase_phase6_zi4qfe3g/run_phase6_checks.py post_final
```

For every successful case, it invokes the tracked verification script. For example:

```sh
python3 verification/verify_refactor.py \
  --exe build-debug/nanofase \
  --baseline /private/tmp/nanofase_phase6_zi4qfe3g/pre/canonical/output \
  --config /private/tmp/nanofase_phase6_zi4qfe3g/pre/canonical/config.nml \
  --run-dir /private/tmp/nanofase_phase6_zi4qfe3g/post_final/canonical \
  --exact
```

| Case | Input variation | Result |
| --- | --- | --- |
| `canonical` | River, sediment enabled, all seven constants omitted | passed |
| `estuary_on` | Estuary dataset, sediment enabled | passed |
| `estuary_off` | Estuary dataset, sediment disabled | passed |
| `unequal_depths` | Depths `0.02, 0.03, 0.04, 0.05` | passed |
| `reach_depths` | Same unequal depths, individual-reach output enabled | passed |
| `clay_defaults` | Clay enrichment enabled, constants omitted | passed |
| `explicit_constants` | Clay enrichment enabled, seven constants supplied | passed |

The explicit case supplies transport values `3.0e-9`, `1.0e-9`, and `0.3` in
constants-file `/soil/`; enrichment values `1.2` and `0.1` in `/sediment/`; and
deposition values `40.0` and `1.0` in `/water/`.

Before/after comparisons passed for all seven cases: each of the three CSV files was
byte-identical; `summary.md` matched after removing only `Simulation datetime`; and
the `ncdump` text of `output.nc` matched after removing only its `history` metadata.

The reference-run comparisons also confirmed useful coverage. Estuary on/off changed
water and sediment CSV results. Unequal depths changed sediment results. Enabling
clay enrichment changed all three CSV results. Explicit constants then changed water
and sediment results relative to the clay-enabled default case. Both input datasets
lack the spatial deposition and sediment-transport variables that would override
these constants. This evidence is recorded in `branch_evidence.json`.

Each exact-comparison log is in `post_final/<case>_verify.log`. Argument lists for
the model and verification commands are in `pre_commands.json` and
`post_final_commands.json`.

### Negative, batch, and checkpoint checks

The runner also invoked the executable directly for the following checks. Results
and selected diagnostics are recorded in `pre_results.json` and
`post_final_results.json`; complete logs are in each case's `run.log`.

| Case | Result before and after migration |
| --- | --- |
| River with bed sediment disabled | exit 1, unchanged unset deposit-result error |
| Missing configuration `/sediment/` group | exit 2, unchanged end-of-file error in the early dimensions read |
| First sediment depth set to zero | exit 1, unchanged `Layer capacity is zero` message and construction trace |
| First depth set to `0.0001` | exit 1, unchanged `Fine sediment volume exceeds capacity` message and construction trace |
| Existing batch configuration | exit 0, summary reports 3 batches and 31 timesteps |
| Checkpoint save after warm-up | exit 0, saved 404,908 bytes |
| Checkpoint reinstate with timestep preservation and no second warm-up | exit 0 |

Error comparisons excluded changing memory addresses in the runtime call stack,
which lists the procedures leading to the failure. These negative cases are
expected failures retained from Phase 5, not successful scientific runs. The
checkpoint checks show that saving and loading still execute; they do not prove that
a loaded run continues with exactly the same scientific results as an uninterrupted
run.

### Final source checks

The source-check script and these searches were run from the repository root:

```sh
python3 /private/tmp/nanofase_phase6_zi4qfe3g/check_source.py
rg -n 'use[[:space:]]+GlobalsModule|\bC%' src/BedSediment src/BedSedimentLayer
rg -n -i 'C%(sedimentLayerDepth|includeBedSediment)([^A-Za-z0-9_]|$)' src
git diff --check
```

The searches found no remaining matches. The comment, source-code, input-hash,
version-hash, removed-default, removed-error-entry, and whitespace checks passed.

## Known Failure Preserved by Agreement

With `include_bed_sediment = .false.`, the river scenario still fails in
`depositToBedReach`: it skips setting `depositRslt`, then attempts to read its data.
The original message remains:

```text
Error trying to return 0D data as REAL(DP). Are you sure the data is of type and kind REAL(DP)?
```

River resuspension and nanomaterial transfer calls also remain outside the switch.
Consequently, fixing just this read would not settle the complete disabled behaviour.
The user chose to preserve and document the existing failure during this migration.
A separate fix must define and test all affected river operations. Estuary runs with
the switch on and off both complete and passed their exact comparisons.

## Remaining Migration Work

1. Phase 7: migrate WaterBody settings, defaults, and assigned errors. Preserve the
   missing code 405 until the separate error-list correction.
2. Phase 8: migrate Reactor.
3. Phase 9: migrate Biota, including the existing Soil-to-Biota connection.
4. Migrate remaining shared-`C` readers in data, output, grid, logging, utilities,
   checkpoint code, and other consumers. Sediment still uses shared input and utility
   code indirectly.
5. Correct blank error entries, overwritten code 405, code 901 ownership, and the
   other unassigned error owners in a separately tested behaviour change.
6. Define and fix river behaviour when bed sediment is disabled, with dedicated
   tests for deposition, resuspension, nanomaterial transfers, and water depth.
7. Add an exact checkpoint continuation test after resolving warm-up and reinstatement
   timing. This phase checked only that saving and loading complete.
8. Stop CMake from rewriting the tracked version file during configuration.
9. Remove the shared `C` compatibility object, its copying helpers, and the empty
   legacy error list only after their remaining consumers and owners have migrated.
