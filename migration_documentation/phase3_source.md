# Phase 3 Source Configuration Migration

## Summary

Implemented Phase 3 as a behavior-preserving extraction of Source configuration and
the first complete removal of a domain-owned field from the `C` compatibility facade.

- Added `src/Source/SourceConfigModule.f90` with public `SourceConfigType`, the
  `sourceConfig` singleton, and type-bound `init(configFilePath)`.
- Moved ownership of required `/sources/` member `include_point_sources` into
  `SourceConfigModule`; no fallback default, audit, or registered error was added.
- Updated `main.f90` to initialise `sourceConfig` immediately after `GLOBALS_INIT()`
  and before logger, dataset, and environment initialisation.
- Removed `includePointSources`, the `/sources/` namelist declaration/read, and the
  facade assignment from `GlobalsModule`.
- Repointed both Source science modules from broad `GlobalsModule` access to their
  explicit Kernel, ModelDimensions, ModelConfig, SourceConfig, NetCDF, and DATASET
  dependencies.
- Updated `migration_documentation/migrationplan.md` to repair the domain-dependency,
  diagnostics/bootstrap, error-registry, sequencing, verification, and documentation
  gaps found while planning Phase 3.

## Public API and Behavior Preserved

- `PointSource` and `DiffuseSource`, their public components, and their existing
  `create` and `update` bindings are unchanged.
- Array shapes are unchanged: `npDim` and `nSizeClassesNM` now come directly from
  `ModelDimensionsModule`.
- Disabled point sources are still parsed, constructed, and snapped to reaches, but
  contribute zero flux during `PointSource%update`.
- The existing `t .ge. warmUpPeriod` condition is unchanged; `warmUpPeriod` now comes
  directly from `ModelConfigModule`.
- `includePointSources` still controls only point sources. Diffuse-source behavior is
  unchanged.
- Batch updates still re-snap point sources through the existing GridCell and
  WaterBody APIs.
- The previously transitive `nf90_fill_double` dependency is now an explicit NetCDF
  import in `PointSourceModule`.
- `/sources/` and `include_point_sources` remain required supported input. Phase 3
  deliberately introduces no new default policy.

## Original Comments

All original comments and TODOs in `PointSourceModule.f90` and
`DiffuseSourceModule.f90` were preserved verbatim. The removed Globals field comment
`!! Should point sources be included?` was moved verbatim to
`SourceConfigType%includePointSources`.

## Verification

Fresh pre-change enabled and disabled baselines were generated with the unchanged
pre-Phase-3 `build-debug/nanofase` executable under
`/private/tmp/nanofase_phase3_pre_source.nRB41e`. Both baseline runs exited 0 and the
enabled/disabled outputs differed in water and sediment results, confirming that the
flag was exercised; soil output was byte-identical between the two variants.

- `cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug`: passed.
- `cmake --build build-debug -j2`: passed with existing warnings and duplicate-rpath
  linker warnings.
- Enabled exact regression:
  `python3 verification/verify_refactor.py --exe build-debug/nanofase --baseline /private/tmp/nanofase_phase3_pre_source.nRB41e/enabled/output --config /private/tmp/nanofase_phase3_pre_source.nRB41e/enabled/config.nml --run-dir /private/tmp/nanofase_phase3_enabled_verify --exact`: passed. All CSV files were byte-identical; filtered summary and NetCDF dumps matched exactly.
- Disabled exact regression:
  `python3 verification/verify_refactor.py --exe build-debug/nanofase --baseline /private/tmp/nanofase_phase3_pre_source.nRB41e/disabled/output --config /private/tmp/nanofase_phase3_pre_source.nRB41e/disabled/config.nml --run-dir /private/tmp/nanofase_phase3_disabled_verify --exact`: passed with the same exact gates.
- Batch smoke test using
  `config.example/batch_config_test-scenario.example.nml`: passed; the summary reports
  3 batches and 31 timesteps. Run artifacts are under
  `/private/tmp/nanofase_phase3_batch.9Y8iUa`.
- Checkpoint save/reinstate smoke test with `preserve_timestep = .true.`: passed. A
  404,908-byte checkpoint was saved and reinstated successfully under
  `/private/tmp/nanofase_phase3_checkpoint.JsRX3q`. This remains a smoke test, not an
  exact continuation comparison, because the known warm-up/reinstate semantics are
  unresolved.
- Required-group negative smoke test: a temporary config with `/sources/` removed
  exited nonzero at the unguarded `SourceConfigModule` namelist read, confirming that
  Phase 3 did not introduce an optional-group fallback.
- Static checks passed: no `use GlobalsModule`, `ResultModule`, or `C%` remains under
  `src/Source/`; `/sources/` is declared exactly once; Globals contains no Source flag;
  the shipped config examples retain their pre-phase SHA-256 hashes; and
  `git diff --check` reports no whitespace errors.

## CMake and Workspace Preservation

CMake reconfiguration rewrote `src/VersionModule.f90`. Its exact pre-existing content
was restored and the executable rebuilt; the file's pre- and post-verification SHA-256
is `3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652`.
The pre-existing `vendor/nanofase-data` state and untracked `verification/` directory
were not modified or claimed as Phase 3 changes.

## Remaining Migration Work

1. Add the bootstrap/error-infrastructure gate before any error-owning domain phase:
   create the shared `ErrorHandlingModule`, establish the required initialisation
   order, and progressively replace `GLOBALS_INIT` with an explicit bootstrap.
2. Migrate the remaining owner domains one at a time: Soil, BedSediment before
   WaterBody, then Reactor and Biota. Every phase must update all repo-wide consumers
   of the moved fields.
3. Migrate cross-cutting facade consumers in GridCell, Data, Output, Logger, Util,
   Checkpoint, and any other remaining ModelConfig/ModelDimensions readers.
4. Correct the malformed legacy error registry only in a separately tested behavior
   change: unassigned `errors(4:5)`, overwritten code 405 at `errors(11)`, incorrect
   code-901 ownership, and unowned codes 110/200/201/300.
5. Resolve exact checkpoint continuation semantics, Source/DataInput coupling, any
   future need for Source abstractions, model-version truncation, and the explicitly
   deferred Kernel/ModelDimensions/ModelConfig cleanup recorded by earlier phases.
6. Remove the empty Globals facade and legacy registry only after every domain and
   cross-cutting consumer has migrated.
