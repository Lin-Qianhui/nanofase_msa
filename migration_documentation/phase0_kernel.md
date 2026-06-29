# Phase 0 Kernel Migration

## Summary

Implemented the Phase 0 kernel as a behavior-preserving compatibility layer.

- Added `src/Kernel/KernelModule.f90` with application `dp`, IO-unit constants, ANSI color constants, cross-domain physical constants, and water-physics helper functions.
- Updated `src/DefaultsModule.f90` to import `dp` and IO-unit constants from `KernelModule`; `dp` remains private and existing `iou*` names remain publicly available through `DefaultsModule`.
- Updated `src/GlobalsModule.f90` to import kernel `dp`, colors, physical constants, and water functions while preserving the existing `C`, `ERROR_HANDLER`, `COLOR_*`, and `C%rho_w`/`C%nu_w`/`C%mu_w` facade.

## Deferred By Design

- `LOGR` stays in `LoggerModule`; moving it now would create a dependency cycle because `LoggerModule` still uses `GlobalsModule`.
- `ERROR_HANDLER` stays in `GlobalsModule`; FEH re-exports and domain error ownership are later migration phases.
- Domain config/default ownership, namelist reads, bootstrap changes, and call-site migrations were not changed in Phase 0.
- Vendor modules keep their own private precision kinds.

## Verification

Reference and post-change runs used `config.example/test-scenario.example.nml` with isolated temp output directories under `/private/tmp/nanofase_phase0.VWZFf6`.

- `cmake -S . -B build`: passed.
- `cmake --build build`: passed. Linker emitted existing duplicate rpath warnings only.
- `fpm @build`: not available in this checkout (`response name [@build] not found`).
- `fpm build`: fetched dependencies after network approval, then failed in `netcdf-interfaces` on a gfortran argument type mismatch.
- `fpm build --flag -fallow-argument-mismatch`: passed.
- Test scenario run before and after Phase 0: passed.
- CSV outputs compared byte-for-byte:
  - `output_water.csv`: identical.
  - `output_sediment.csv`: identical.
  - `output_soil.csv`: identical.
- `summary.md` matched after filtering the volatile `Simulation datetime` line.
- `output.nc` raw bytes differed because generated metadata changed; `ncdump` output matched after filtering volatile `history` metadata.
- Grep check confirmed `selected_real_kind(15, 307)` is now absent from `src/GlobalsModule.f90` and `src/DefaultsModule.f90`, and present in `src/Kernel/KernelModule.f90`.

## Notes

CMake rewrites `src/VersionModule.f90` during reconfiguration. That generated change was restored and the final CMake executable was rebuilt before the final regression comparison.
