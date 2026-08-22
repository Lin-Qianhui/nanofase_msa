# Phase 4 Bootstrap and Diagnostics Infrastructure Gate

## Summary

Implemented Phase 4 as a behavior-preserving startup and diagnostics extraction.

- Added `src/ErrorHandling/ErrorHandlingModule.f90` as the sole owner of the shared
  `type(ErrorCriteria) :: ERROR_HANDLER` singleton and its legacy FEH registry.
- Added `src/Bootstrap/BootstrapModule.f90` with one public `bootstrap(env)` routine.
- Replaced `GLOBALS_INIT` and the staged startup calls in `main.f90` with one call to
  `bootstrap(env)`.
- Kept the `C` compatibility facade and its runtime synchronization helper in
  `GlobalsModule`; untouched consumers receive the same handler singleton through an
  explicit public re-export.
- Added a focused CTest executable that pins the current legacy registry and proves
  the named `ErrorInstance` registration form required by the owner-domain phases.

## Startup Order and Public Interfaces

`BootstrapModule` exposes only `bootstrap(env)`. It owns the following startup order:

1. Resolve the config path and optional batch-config path from command-line arguments.
2. Initialize `ModelDimensionsModule`.
3. Initialize `modelConfig`, including optional batch state.
4. Initialize the shared `ERROR_HANDLER` from `triggerWarnings` and `errorOutput`.
5. Synchronize the transitional `C` facade and read the remaining legacy `/soil/`,
   `/sediment/`, and optional `/water/` groups.
6. Audit `modelConfig` and trigger its returned errors.
7. Initialize `sourceConfig`.
8. Initialize `LOGR` and print the welcome message.
9. Initialize `DATASET`.
10. Build the environment and preserve the existing result log/trigger calls.

`ErrorHandlingModule` exposes only `ERROR_HANDLER` and
`initErrorHandling(triggerWarnings, errorOutput)`. It deliberately does not depend on
`ModelConfigModule`; bootstrap passes the two controls that the pre-phase code already
used. FEH `bashColors` and criteria `epsilon` remain at their historical behavior.

## Legacy Registry Preserved

The 17-slot registry assignments and original category comments were moved verbatim.
The known defects remain unchanged by design:

- slots 4 and 5 still default to blank critical code-1 instances;
- slot 11 is still assigned code 405 and then overwritten by code 500;
- code 901 retains its legacy placement and message;
- codes 110, 200, 201, and 300 remain without final domain owners.

The focused test observes 26 effective FEH entries: codes 0 and 1, nine built-in
criteria codes, and 15 effective legacy custom codes. It asserts that code 405 is
absent, code 1 has a blank message, codes 500 and 600 are warnings, the singleton
retains the `ErrorCriteria%equal` API, and
`ERROR_HANDLER%add(error=ErrorInstance(...))` works.

## Public Behavior and Original Comments

- Scientific algorithms, domain config/default ownership, output, checkpoint, batch,
  and construction behavior are unchanged.
- `main.f90` retains the simulation loop and imports `ERROR_HANDLER` directly for its
  existing run-loop trigger call.
- Existing modules that import `ERROR_HANDLER` through `GlobalsModule` still compile
  against the same singleton; broad import cleanup remains deferred.
- All original comments and TODOs in moved startup, facade, namelist, audit, and error
  registry blocks were retained verbatim with their code. The main program banner and
  run-loop comments were not changed.

## Verification

Fresh pre-change outputs and diagnostic logs were captured under
`/private/tmp/nanofase_phase4_pre.17t7Jd`. Post-change diagnostic logs are under
`/private/tmp/nanofase_phase4_post.mpNCDH`.

- `cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug`: passed.
- `cmake --build build-debug -j2`: passed with existing compiler warnings.
- `ctest --test-dir build-debug --output-on-failure`: passed; 1/1 registry test.
- Exact canonical regression using `verification/verify_refactor.py --exact`: passed.
  All CSV files were byte-identical; filtered summary and NetCDF dumps matched.
- Invalid `netcdf_write_mode`: pre/post exit status 1 with the same critical message
  and `Auditing config file` trace.
- Warning enabled: pre/post exit status 0 with the same checkpoint warning and trace.
- Warning suppressed: pre/post exit status 0 with no warning output.
- `error_output = .false.` with an invalid write mode: pre/post exit status 0; the
  audit created its result but FEH did not output or stop on it.
- Missing `/sources/`: pre/post exit status 2 with the same required-namelist EOF
  failure at `SourceConfigModule.f90:28`.
- Batch smoke test: passed under `/private/tmp/nanofase_phase4_batch.vCqcQ1`; summary
  reported 3 batches and 31 timesteps.
- Checkpoint save/reinstate smoke test with `preserve_timestep = .true.`: both runs
  passed under `/private/tmp/nanofase_phase4_checkpoint.ZGjgaq`; the checkpoint size
  was 404,908 bytes. This remains a smoke test, not exact continuation proof.
- Static checks confirmed one handler declaration, no `GLOBALS_INIT` definition or
  call, no handler initialization in `GlobalsModule`, one bootstrap call in
  `main.f90`, and no whitespace errors.

## Workspace Preservation

CMake reconfiguration rewrote `src/VersionModule.f90`; its exact pre-existing content
was restored before rebuilding. Its pre- and post-phase SHA-256 remains
`3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652`.
The pre-existing `vendor/nanofase-data` state and untracked `verification/` directory
were not modified or claimed as Phase 4 changes.

## Remaining Migration Work

1. Migrate Soil next, including `/soil/`, Soil defaults and code 600 registration,
   after removing exactly code 600 from the legacy registry initializer.
2. Migrate BedSediment before WaterBody, then Reactor and Biota, updating bootstrap
   order and every repo-wide consumer in each phase.
3. Migrate remaining cross-cutting `C` readers and remove the private transitional
   facade helpers as their fields become owner-managed.
4. Correct blank slots, code 405, code 901 ownership, and codes 110/200/201/300 only in
   the separately tested diagnostic-registry behavior-change phase.
5. Remove the empty Globals facade only after all domain and cross-cutting consumers
   have migrated; exact checkpoint continuation remains separately deferred.
