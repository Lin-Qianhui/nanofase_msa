# Phase 8 Reactor Migration

## Summary

Phase 8 is complete. Reactor now owns its four default constants and error code
903. Both Reactor science modules read shared dimensions, physical values, and
timing from the modules that own them. The calculations, supported inputs, public
types and procedures, and original comments were preserved.

Verification on 16 September 2026 passed a clean build, all **25 focused tests**,
and **23 exact scientific comparisons** against a fresh Phase 7 executable.
Four expected failures retained their exit status and meaningful error text.
Batch operation and checkpoint save/load also passed.

The next domain is **Phase 9: Biota**. Reactor's existing attachment mass-loss
defect was reproduced and retained; correcting it is separate work.

## What Changed

### Reactor owns four defaults without adding an input group

Added `src/Reactor/ReactorConfigModule.f90`. A module groups related Fortran code
and values. This module exposes four constants and `registerReactorErrors()`:

| Constant | Existing type and value |
| --- | --- |
| `default_k_diss_pristine` | default `real`, `0.0` |
| `default_k_diss_transformed` | default `real`, `0.0` |
| `default_k_transform_pristine` | default `real`, `0.0` |
| `defaultShearRate` | default `real`, `10.0` |

Each constant supplies a value when its corresponding input is absent. All four
declarations moved from `DefaultsModule`, including the original heading and
shear-rate reference. Their names, values, and number precision are unchanged.
`parameter` in their declarations means they are constants rather than values
that can change during a run.

Reactor has no settings group in the model configuration file, so it has no new
configuration object, file-reading procedure, or `/reactor/` group. No defaults
or validation rules were invented.

DataInput now imports the four constants from Reactor. It still reads reaction
rates and shear from the separate constants-file `/water/` group. A group is a
named set of values in the Fortran input file. The reader's declarations, reading
order, assignments, conversions, and batch reload behaviour are unchanged.
Reaction-rate input buffers and stored rates remain double precision; shear
remains default `real`. Reactor's new module does not depend on DataInput or
Reactor science code.

### Error 903 is registered by Reactor

`registerReactorErrors()` registers the existing message:

```text
Invalid Reactor index provided.
```

It remains critical, meaning that triggering it can stop the model when error
output is enabled. Registration uses the named `error=ErrorInstance(...)`
argument. Bootstrap calls this procedure immediately after WaterBody
initialisation and before copying dimensions into the older shared `C` object.

Only code 903 was removed from the shared error list. Its array shrank from nine
positions to eight; blank positions 4 and 5 and codes 901 and 902 in positions 7
and 8 remain. No new science error-raising site was added: code 903 currently has
none.

| Initialisation completed | Registered errors |
| --- | --- |
| Shared handler | 17 |
| Soil | 18 |
| BedSediment | 19 |
| WaterBody | 25 |
| Reactor | 26 |

The final total is unchanged. Code 405 remains absent, and the existing blank
code-1 message and other error definitions remain unchanged.

### Reactor science reads shared values from their owners

Both `AbstractReactorModule` and `ReactorModule`, including their abstract
procedure declarations, now obtain:

- precision, the Boltzmann constant, pi, and water viscosity from Kernel;
- particle counts, array dimensions, diameters, and sediment densities from
  ModelDimensions;
- the timestep from `modelConfig`.

Other imports name the required `Result`, `AbstractReactor`, `DATASET`, and
`isZero` directly. The `.errors.` operation belongs to the `Result` type and is
available through that import; it is not a separately exported module operation.

No direct `GlobalsModule` imports or `C%` reads remain under Reactor. This does
not make the science independent of input data or utilities: `DATASET` remains
in use, and `isZero` still reads its default tolerance through the existing Util
implementation. That indirect use of `C` is left for the later shared-consumer
phase.

Particle attachment, dissolution, and transformation still run in that order.
Public types, procedure arguments and bindings, array shapes, number precision,
equations, and expression order are unchanged. Existing unused declarations and
TODOs remain. Unused `C%T` remains unchanged for final cleanup; actual water
temperatures come from input data.

## Original Comments and Source Checks

All **480 original comment occurrences** across the ten changed existing Fortran
files were retained, including repeated comments. Comments in both Reactor
science files remain in their original order. The two comments removed from
`DefaultsModule` moved verbatim with its four constants into the new module.
The other changed existing Fortran files retain their complete comment sequences.
All original CMake comment lines remain in order too.

A separate source check removed imports and comments, then applied only the
planned replacements of old owner references. Both Reactor science files matched
their originals after those replacements. DataInput's body matched its original
after removing imports. These checks verify that the migration did not rewrite
calculations, procedure interfaces, or constants-file parsing.

Checks also confirmed one declaring owner for each moved constant, one code-903
registration site, unchanged shipped input hashes, unchanged earlier phase reports,
and unchanged Globals, Kernel, and Util source. The existing
`vendor/nanofase-data` workspace state was preserved. `git diff --check` passed.

## Verification

### Reference and saved evidence

The fresh reference executable was built from unchanged Phase 7 revision:

```text
aaed497723225b05a52c94d101fa4225c998c418
```

The build used the existing Debug CMake setup and gfortran-14. Before production
source edits, configuration and build passed, the original 21 CTest cases passed,
and reference scientific outputs and error results were captured.

Evidence is outside tracked source directories at:

```text
/private/tmp/nanofase_phase8__zql3ecn
```

`original/` and `original_hashes.json` preserve the starting source and input hashes.
`revision.txt`, the saved CMake caches, `reference_nanofase`, and its SHA-256 file
identify the reference. `reactor_checks/` and `waterbody_checks/` contain saved
inputs, hashes, commands, logs, reference results, and candidate results. The small
pre-change mass and error probe sources and their logs are also saved there.
`check_source.py` and `source_checks.json` record the comment and source checks.

These local evidence files may eventually be removed. The tracked runners and
focused tests make the checks repeatable without relying on that directory.

### Build and focused tests

The build and test commands were:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the exact saved src/VersionModule.f90 contents before building.
cmake --build build-debug -j2
# The final candidate build refreshed all compiled files:
cmake --build build-debug --clean-first -j2
ctest --test-dir build-debug --output-on-failure
```

CMake rewrote the version file during configuration. Its saved contents were
restored before each build. The final hash remains:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

The first candidate build rejected an attempt to import `.errors.` separately;
the import was corrected to `Result`, which supplies that operation. A subsequent
incremental build encountered inconsistent older compiled module files. The final
clean build passed. Remaining warnings concerned existing conversions, unused
variables and arguments, continued strings, version-text truncation, and duplicate
library search paths. Logs are `reference_build.log`, `candidate_build.log`,
`candidate_incremental_build.log`, and `final_build.log`.

CTest passed **25/25** cases. The new Reactor configuration test checks all four
constant values and precisions, the complete 17/18/19/25/26 registration sequence,
exactly one unchanged critical code 903, and preservation of all earlier errors.
Separate processes verify that 903 stops execution with error output enabled and
continues without its message when disabled. Warnings are disabled in these tests
to confirm that this does not suppress a critical error.

Existing shared-handler, Soil, BedSediment, and WaterBody tests use the new
intermediate counts and confirm that they do not register 903. The fourth new
test preserves the known mass-loss result described below. Both new Fortran test
executables have their own directories for compiled module files.
The full results are in `final_ctest.log`.

### Exact scientific comparisons

The actual runner commands, from the repository root, were:

```sh
python3 -B verification/verify_reactor.py capture \
  --exe /private/tmp/nanofase_phase8__zql3ecn/reference_nanofase \
  --work-dir /private/tmp/nanofase_phase8__zql3ecn/reactor_checks
python3 -B verification/verify_reactor.py compare \
  --exe build-debug/nanofase \
  --work-dir /private/tmp/nanofase_phase8__zql3ecn/reactor_checks

python3 -B verification/verify_waterbody.py capture \
  --exe /private/tmp/nanofase_phase8__zql3ecn/reference_nanofase \
  --work-dir /private/tmp/nanofase_phase8__zql3ecn/waterbody_checks
python3 -B verification/verify_waterbody.py compare \
  --exe build-debug/nanofase \
  --work-dir /private/tmp/nanofase_phase8__zql3ecn/waterbody_checks
```

| Reactor scenario | Input variation | Before/after result |
| --- | --- | --- |
| `river` | Explicit zero rates and shear 10 | exact match |
| `defaults` | All three rates and shear omitted | exact match |
| `pristine_dissolution` | Pristine dissolution rate `1.0e-7` | exact match |
| `transformed_dissolution` | Transformed dissolution rate `2.0e-7` | exact match |
| `transformation` | Pristine transformation rate `3.0e-7` | exact match |
| `combined` | All three nonzero rates above | exact match |
| `shear_20` | Shear set to `20.0` | exact match |
| `estuary` | Existing estuary inputs | exact match |
| `estuary_combined` | Estuary with all three nonzero rates | exact match |

All fourteen existing successful WaterBody scenarios also matched exactly: river,
missing/empty/partial Water groups, disabled bank erosion, estuary, estuary treated
as river, the shorter estuary timestep, disabled estuary bed sediment, omitted and
explicit constants, and both spatial bank-erosion cases.

For all **23** before/after comparisons, every CSV file was byte-identical.
`summary.md` matched after removing only its `Simulation datetime` line, and
`ncdump` text matched after removing only the NetCDF `history` metadata. Raw NetCDF
bytes were not required to match because that metadata records the run time.

Reference checks confirmed useful coverage. All three active river reactions,
combined reactions, and changed shear altered water results. Pristine dissolution,
transformation, combined reactions, and changed shear also altered sediment
results. Active estuary reactions altered water results. Omitting the four defaults
reproduced all three explicit-default CSV files exactly. The same checks passed
for the candidate; each runner saves this evidence in `branch_evidence.json`.

### Expected failures, batch, and checkpoints

| Check | Before and after |
| --- | --- |
| Terrain heights added at the river outlet | exit 2; terrain-array index exceeds its upper bound |
| River with bed sediment disabled | exit 1; unset deposit result cannot be returned as `REAL(DP)` |
| Unknown Water setting | exit 2; cannot match `unknown_water_setting` |
| Invalid Water integer followed by another group | exit 2; cannot match `'invalid'` |
| Trigger Reactor error 903, output enabled | exit 1; unchanged Reactor error message |
| Trigger Reactor error 903, output disabled | exit 0; no Reactor error message |
| Batch run | exit 0; 3 chunks and 31 timesteps |
| Checkpoint save after warm-up | exit 0; 404,908-byte file |
| Checkpoint reinstatement with timestep preservation | exit 0 |

Expected failures retain their exit status and meaningful text; changing source
locations and runtime addresses are not compared. Checkpoint checks establish that
saving and loading complete. They do not prove identical scientific continuation
from a saved state.

## Known Reactor Defect Preserved

Reactor's particle attachment calculation repeatedly scales the same temporary
mass when distributing it between suspended-sediment size classes. With two equal
attachment rates and all free mass attaching in one timestep, the current results
are:

| Material | Initial mass | Mass after attachment |
| --- | --- | --- |
| Pristine particles | 100 | 75 |
| Transformed particles | 50 | 37.5 |

The operation should redistribute mass, so this loss is a defect. It was reproduced
on the fresh Phase 7 build and preserved by `reactor_known_mass_loss` after
migration. That test explicitly checks the current defective result; it is not
proof that the science is correct. A separate correction must test equal, unequal,
and zero attachment rates, as well as partial and complete attachment, before
changing the calculation and these expectations.

## Remaining Work

1. Phase 9: migrate Biota, including the existing Soil-to-Biota relationship.
2. Move remaining shared-`C` readers in data, output, logging, utilities, checkpoint
   code, and other consumers to the modules that own those values. This includes
   Util's default tolerance used indirectly by Reactor.
3. Move model-wide defaults into the model configuration area before reducing or
   removing `DefaultsModule`.
4. Correct the Reactor attachment mass loss in a separate, tested science change.
5. Correct the blank error entries, missing code 405, code 901 ownership, and the
   remaining unassigned error owners in a separate tested change.
6. Define and repair river behaviour with bed sediment disabled, including
   deposition, resuspension, particle transfers, and water-depth effects.
7. Repair terrain-height access when a reach's outflow is outside the terrain array.
8. Resolve warm-up and reinstatement timing, then prove exact checkpoint continuation.
9. Stop CMake from rewriting the tracked version file during configuration.
10. Remove unused `C%T`, the remaining `C` object, its copying helpers, and the empty
    legacy error list only after the required consumer and error-owner work is done.
11. If optional Water input validation is tightened, test it separately; its current
    end-of-file-sensitive behaviour remains unchanged.

The main plan now records these corrections, the exception for domains without
configuration settings, and Phase 8 completion. Earlier phase reports were left
unchanged. Every future phase must likewise document what changed, how it was
checked, and what remains, while preserving original code comments.
