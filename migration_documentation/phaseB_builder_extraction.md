# Phase B Builder Extraction

## Summary

Implemented Phase B as a behavior-preserving extraction of startup construction into a top-level builder.

- Added `src/ModelAssembly/ModelAssemblyModule.f90` with public `buildEnvironment(env)`.
- Updated `src/main.f90` so bootstrap calls `buildEnvironment(env)` instead of `env%create()`.
- Moved environment grid allocation, concrete `GridCell` allocation, child soil/reach construction, reach topology wiring, headwater/routed-reach setup, and stream-order determination into `ModelAssemblyModule`.
- Kept `Environment%create` and `GridCell%create` as thin compatibility methods for their existing abstract contracts.
- Removed `determineStreamOrder` from the `AbstractEnvironment`/`Environment` type-bound interface; it is now a private builder helper.
- Cleaned Phase-B-touched imports so kernel-owned values come from `KernelModule`, dimension values come from `ModelDimensionsModule`, and model-level runtime config in `main.f90` comes from `ModelConfigModule` instead of the `C` facade.

## Notes

- Original construction comments and TODOs were moved with their code blocks.
- `GridCell%snapPointSourcesToReach` remains type-bound because batch updates still re-snap point sources when batch input changes.
- `GridCell%finaliseCreate` remains type-bound and is still called by the builder after reach topology is wired.
- `Environment%create` now only allocates and zeros the environment-owned per-timestep summary arrays, using `ModelDimensionsModule` for dimensions instead of new `C%...` reads.
- `GridCell%create` now only initializes the cell shell: own arrays, coordinates, empty flag, reference, and default soil-profile count.
- `GridCellModule` still imports `C` only for `sedimentLayerDepth`, which remains sediment-domain config until the later BedSediment/domain config phase.
- The builder preserves the historical create-time error/log behavior: cell construction results are logged, triggered, and cleared before returning, and environment construction does the same before returning to `main`.

## Deferred By Design

- No per-domain config/default/error ownership was migrated in Phase B.
- No broad `C%` call-site cleanup was done beyond Phase-B-touched modules and fields already owned by `KernelModule`, `ModelDimensionsModule`, or `ModelConfigModule`.
- `snapPointSourcesToReach` was not moved into `ModelAssemblyModule` because it is needed after startup by `parseNewBatchData`.
- Exact checkpoint output comparison remains deferred for the existing warm-up/reinstate semantics documented in Phase 1.

## Verification

Baseline was generated before implementation with `build-debug/nanofase` and `config.example/test-scenario.example.nml`, writing to `/private/tmp/nanofase_phaseB_baseline.BnbaKw/output/`.

- `cmake -S . -B build-debug`: passed.
- `cmake --build build-debug`: passed with existing warnings and duplicate rpath linker warnings.
- `python3 verification/verify_refactor.py --exe build-debug/nanofase --baseline /private/tmp/nanofase_phaseB_baseline.BnbaKw/output --config config.example/test-scenario.example.nml --run-dir /private/tmp/nanofase_phaseB_verify2`: passed.
- Batch smoke test passed with normal config plus `config.example/batch_config_test-scenario.example.nml`; summary reported 3 batches and 31 total timesteps.
- Checkpoint save/reinstate smoke test with `preserve_timestep = .true.`: passed.
- Static checks confirmed `main.f90` no longer calls `env%create()`, `createReaches` no longer exists in `GridCellModule`, topology wiring no longer lives in `EnvironmentModule`, and `snapPointSourcesToReach` remains available for batch updates.
- Follow-up import cleanup verification: `cmake --build build-debug` passed; `verify_refactor.py` passed with run directory `/private/tmp/nanofase_phaseB_import_cleanup_verify2`; batch and checkpoint smoke tests passed again.

## CMake Caveat

Re-running CMake rewrote `src/VersionModule.f90` from the pre-existing generated value to the current `git describe` value, which caused a summary-version mismatch during verification. That generated churn was restored to the pre-change value before the final verification run.
