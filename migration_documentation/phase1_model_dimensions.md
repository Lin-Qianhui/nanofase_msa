# Phase 1 Model-dimensions Migration

## Summary

Implemented the Phase 1 model-dimensions extraction as a facade-preserving migration.

- Added `src/ModelDimensions/ModelDimensionsModule.f90` as the source of truth for shared model dimensions.
- Updated `src/GlobalsModule.f90` so `GLOBALS_INIT` delegates dimension reads to `initModelDimensions`, then copies those values back into `C`.
- Updated `src/CheckpointModule.f90` so checkpoint array dimensions read directly from `ModelDimensionsModule`, while `C` remains for non-dimension state such as `epsilon`, `t0`, and `ERROR_HANDLER`.
- Updated `migration_documentation/migrationplan.md` to resolve the checkpoint contradiction and document the `/sediment/` partial-namelist constraint.

## Fields Moved

`ModelDimensionsModule` now owns:

- Counts: `nSoilLayers`, `nSedimentLayers`, `nSizeClassesSpm`, `nSizeClassesNM`, `nFracCompsSpm`, `nFormsNM`, `nExtraStatesNM`.
- Dimensions: `npDim`.
- Size/distribution arrays: `d_spm`, `d_spm_low`, `d_spm_upp`, `d_nm`, `sedimentParticleDensities`.

The old `C%...` fields are still populated from `ModelDimensionsModule` so unmigrated domains keep compiling and keep existing behavior.

## Notes

- `ModelDimensionsModule` reads `/allocatable_array_sizes/`, `/nanomaterial/`, and the dimension-owned variables from `/sediment/`.
- Fortran namelist reads are group-wide. Because `/sediment/` also contains `include_bed_sediment` and `sediment_layer_depth`, the dimensions module declares those as local dummies when reading the group.
- `ionicDim`, `defaultDistributionSediment`, and `defaultDistributionNP` remain deferred because they are declared on `GlobalsType` but are not populated or used by the current code.
- `LOGR` and `ERROR_HANDLER` remain in their Phase 0 locations; Phase 1 does not depend on kernel-owned logging or error state.
- The checkpoint reader had a pre-existing shape mismatch for `water_j_dissolved` and `water_j_dissolved_final`. The reader declarations now match the existing save-file layout `(6, waterbody, x, y)`, so the checkpoint format is unchanged.

## Verification

Baseline was generated before implementation with `build-debug/nanofase` and `config.example/test-scenario.example.nml`, writing to `/private/tmp/nanofase_phase1_baseline.3XCara/output/`.

- `cmake -S . -B build-debug`: passed.
- `cmake --build build-debug`: passed with existing warnings.
- `python3 verification/verify_refactor.py --exe build-debug/nanofase --baseline /private/tmp/nanofase_phase1_baseline.3XCara/output --config config.example/test-scenario.example.nml`: passed.
- Checkpoint save-after-warm-up run matched the continuous baseline with the same verification script.
- Checkpoint reinstatement now completes after the reader shape fix, but exact output comparison still differs. The remaining mismatch is due to existing run-control semantics: setting `warm_up_period = 0` avoids a second warm-up after reinstatement but also changes source activation timing, while preserving `warm_up_period = 10` reruns warm-up after loading the checkpoint. This was not changed in Phase 1.
- Grep check confirmed no `C%npDim`, `C%nSoilLayers`, `C%nSedimentLayers`, `C%nSizeClassesSpm`/`SPM`, or `C%nFracCompsSpm` references remain in `src/CheckpointModule.f90`.

## CMake Caveat

CMake rewrites `src/VersionModule.f90` during reconfiguration. The generated version-string change was restored after verification so Phase 1 does not include version metadata churn.
