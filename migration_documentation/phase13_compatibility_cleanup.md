# Phase 13 Compatibility Cleanup

## Summary

Phase 13 is complete. The running model now uses only the modules that own its
settings. GlobalsModule, DefaultsModule, the old `C` object, and all three copying
procedures have been removed. No equations, numerical settings, input rules, or
checkpoint records changed.

Verification on 13 October 2026 passed **58 CTest cases** (the automated test suite),
**47 exact model-output comparisons**, and the CMake, Make, archive, and fpm build
routes. Biota's 50 direct records and 7,500 concentrations inside the running model
matched. The four established failure scenarios retained their expected results.
Version-length correction is the next phase; scientific corrections remain separate.

## What Changed

Bootstrap no longer copies settings or dimensions into `C`. Its remaining order is
unchanged: dimensions, model configuration, shared error handler, Soil, BedSediment,
WaterBody, Reactor, Biota, model audit, Source, logger and welcome text, input data,
and environment construction. Existing construction log/trigger/clear calls remain.

The old `GlobalsType` contained 75 data fields. Five unused fields were removed
without replacements; this is the complete list for Phase 13:

| Removed field | Why no replacement was needed |
| --- | --- |
| `ionicDim` | Declared but never assigned or read by the model. |
| `defaultDistributionSediment` | Declared but never allocated, populated, or read. |
| `defaultDistributionNP` | Declared but never allocated, populated, or read. |
| `T` | Initialised to 15 degrees C, but never read by the model. Actual water temperatures remain in the input-data and compartment code. |
| `dataset` | An unused NetCDF dataset field on `C`. The separate, active `DataInputModule::DATASET` object remains. |

The other 70 fields were removed only from the old object: their existing owners
remain, with 53 fields in `ModelConfig`, 13 dimensions or size-class arrays in
`ModelDimensionsModule`, and four physical constants in `KernelModule` (`g`,
`k_B`, `pi`, and `n_river`). Removing these copies does not remove the settings
or quantities they represented. No replacement settings were introduced for the
five unused fields above. These counts exclude procedures and imported names.

Environment and GridCell creation methods and batch source snapping remain because
they still perform work. Kernel retains the same physical functions and file units.

The direct Biota test now sets only ModelConfig. Its original and revised forms
were compiled against unchanged Phase 12 production code and produced identical
50-record output. The revised source was then compiled identically on both sides
before reference capture. The comparison runner's source-hash checks were retained.
The Biota and shared-consumer integration programs and all four runners are unchanged.

The defaults test now changes the real defaults object, reads a configuration with
that value omitted, checks that ModelConfig receives the changed value, and restores
the defaults before its other checks. It no longer tests a removed import alias.

### Imports for external Fortran callers

| Removed access | Current owner |
| --- | --- |
| Model-wide `C` fields | `ModelConfigModule`, through `modelConfig` |
| Shared sizes and size-class arrays | `ModelDimensionsModule` |
| Physical constants/functions, precision, file units, colours | `KernelModule` |
| Error handler | `ErrorHandlingModule` |
| Default settings/type | `ModelDefaultsModule` |

Old Globals/Defaults imports intentionally no longer compile. Existing science
procedure names and arguments, Bootstrap's public procedure, inputs, outputs, and
saved checkpoint format remain unchanged. Rebuild dependent Fortran code.

### Original comments

All **4,910 original Fortran comment occurrences** in application and test source
were accounted for, including repeated comments and commented-out code. Original
field descriptions moved to ModelConfig and ModelDimensions. Physical descriptions,
equations and references moved to Kernel. Their spelling and formulas were not edited.

Comments belonging to removed code are retained verbatim in
[phase13_removed_compatibility_comments.f90](phase13_removed_compatibility_comments.f90),
a comment-only historical file outside the compiled source directories. Each archived
comment identifies its old source location. New notes explain outdated historical
wording without replacing it. The machine-readable destination list is in the evidence.
Current developer and output documentation now points to the real owners.

## Verification

The reference is Phase 12 revision:

```text
125d8c55e6747b6efa9c5a2aa08d07b9e4b444a0
```

Evidence is under:

```text
/private/tmp/nanofase_phase13_14_iceq6cpq
```

It contains isolated reference source with vendored dependencies, original hashes,
dependency revisions, compiler flags, commands, logs, test-source comparison output,
and generated scenario inputs. `original-comments-source` retains the original
Biota source; `phase12-source` contains the agreed revised test used for comparisons.
The pre-existing `vendor/nanofase-data` workspace state was preserved.

Both builds used GNU Fortran 14, the same NetCDF installation and numerical flags,
and `-DNANOFASE_VERSION=migration-check`. The build command form was:

```sh
cmake -S SOURCE -B BUILD -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_Fortran_COMPILER=gfortran-14 -DNANOFASE_VERSION=migration-check \
  -DNETCDF_INCLUDES=/opt/homebrew/Cellar/netcdf-fortran/4.6.2/include \
  '-DNETCDF_LIBRARIES_F90=-L/opt/homebrew/Cellar/netcdf-fortran/4.6.2/lib -lnetcdff -lnetcdf'
cmake --build BUILD -j2
ctest --test-dir BUILD --output-on-failure
```

`SOURCE`/`BUILD` were the isolated `phase12-source`/`phase12-build` for the reference,
and the working checkout/`phase13-build` for the candidate. Both passed 58/58 tests.
The saved `run_checks.py` invoked the four unchanged runners with these commands:

```sh
python3 /private/tmp/nanofase_phase13_14_iceq6cpq/run_checks.py suites phase13 capture phase12
python3 /private/tmp/nanofase_phase13_14_iceq6cpq/run_checks.py suites phase13 compare phase13
python3 /private/tmp/nanofase_phase13_14_iceq6cpq/run_checks.py routes phase13
```

Every underlying command and working directory is saved in a `*_command.json`
file, with its log beside it. The four suites passed 14 WaterBody, nine Reactor,
six Biota and 18 shared-consumer exact output comparisons. CSVs are byte-identical;
summaries exclude only simulation datetime; NetCDF text excludes only history.
Version fields were included. No comparison tolerance or general filter changed.

Diagnostics retained counts 15/16/17/25/26/27, shared codes 110/200/201/300,
WaterBody codes 405/901, and the agreed blank critical code-1 message. Logging,
batch state, output choices, simulation masks and checkpoint tolerance checks passed.
Checkpoint comparisons retain the existing record layout and all defined values;
only documented unused reach positions are excluded. This does not prove correct
simulation continuation from a checkpoint.

The build-route evidence is in `phase13-routes/routes_o2bu8url`. Automatic CMake,
Make Debug/Release/Fast, dry runs, clean/rebuild, an archive CMake build, and archive
`fpm @install` all passed. Tracked-source hashes stayed unchanged throughout those
commands. Existing compiler/linker warnings remain; no new build failure occurred.

The final source checks were:

```sh
python3 -B verification/verify_compatibility_cleanup.py \
  --reference-source /private/tmp/nanofase_phase13_14_iceq6cpq/original-comments-source \
  --report /private/tmp/nanofase_phase13_14_iceq6cpq/phase13_comments.json
git diff --check
```

They passed. No active old imports, `C%` references or copying procedures remain,
and the fresh build contains neither removed compiled module. The executable code
in Kernel, ModelConfig, ModelDefaults and ModelDimensions matches Phase 12 after
removing comments. Other scientific source, shipped inputs, earlier phase reports,
integration tests and comparison protections are unchanged.

## What Remains

1. Phase 14: remove version truncation in CMake and the two Fortran declarations,
   check complete labels and keep scientific results unchanged.
2. Correct Reactor attachment mass loss, river behaviour with bed sediment disabled,
   and terrain access at outlets in separately tested scientific changes.
3. Correct Biota harvest and invalid-input handling separately. Resolve missing
   organism checkpoint state, warm-up timing and the unused restored timestep
   before claiming correct checkpoint continuation.
4. Keep unused checkpoint positions, empty compartment statistics and release/citation
   metadata as separate work. Full Conda-package creation and Intel/Windows builds
   were not exercised by these macOS/GNU Fortran checks.

Earlier reports remain historical records. The ownership migration is complete;
that does not mean the documented scientific defects have been corrected.
