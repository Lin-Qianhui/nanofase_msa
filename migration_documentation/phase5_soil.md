# Phase 5 Soil Domain Migration

## Summary

Phase 5 moved Soil-owned settings and error registration out of the shared `C`
settings object and into a Soil module. This was a source-code reorganisation only:
the supported input files, public Soil types and procedures, calculation order, and
model results remain unchanged.

- Added `src/Soil/SoilConfigModule.f90` as the owner of the model-configuration
  `/soil/` group, the shared `soilConfig` object, Soil fallback constants, and error
  code 600.
- Removed the five migrated Soil settings from `GlobalsType` and repointed all four
  modules under `src/Soil/` to the modules that now own the values they use.
- Kept the separate constants-file `/soil/` group in `DataInputModule`.
- Added a focused Soil configuration test and updated the shared error-handler test.
- Added `verification/README.md` and `verification/verify_refactor.py` to the
  repository so exact output checks are repeatable.
- Verified seven scenarios against pre-change outputs, including every migrated
  switch and both kinds of existing defaults.

## What Changed

### Soil settings now have a Soil owner

`SoilConfigModule` exposes this public interface:

- `type(SoilConfigType)`;
- the shared `type(SoilConfigType) :: soilConfig` object;
- `defaultSoilAttachmentEfficiency`;
- `defaultSoilDarcyVelocity`.

The shared object is a single instance used by the whole running model. It owns
exactly these five settings:

- default-real `soilLayerDepth(:)`;
- `includeBioturbation`;
- `includeAttachment`;
- `includeSoilErosion`;
- `includeClayEnrichment`.

`soilConfig%init(configFilePath)` obtains the number of Soil layers from
`ModelDimensionsModule`, allocates the depth array, opens the configuration file with
a new Fortran file-unit number, and reads the required model-configuration `/soil/`
group. Local values are created afresh on every call. The existing optional defaults
are applied before the read:

- clay enrichment defaults to false;
- Soil erosion defaults to true.

Layer depth, bioturbation, and attachment remain required. Phase 5 did not invent
defaults or validation for them and did not add an audit procedure.

The two constants used when Soil values are absent from the constants input file were
moved from `DefaultsModule` to `SoilConfigModule`. Their names, default-real kind,
values, and comments remain unchanged:

- `defaultSoilAttachmentEfficiency = 0.0`;
- `defaultSoilDarcyVelocity = 9e-6_dp`.

Keeping default real here, and for `soilLayerDepth`, is intentional. Changing these
declarations to double precision could change rounding and therefore model results.

### The two `/soil/` groups remain separate

The project has two unrelated input groups with the same `/soil/` name. They are in
different files and are read for different purposes:

| Input group | Owner after Phase 5 | Purpose |
| --- | --- | --- |
| `/soil/` in the model configuration file | `SoilConfigModule` | Soil layer depths and the bioturbation, attachment, erosion, and clay-enrichment switches |
| `/soil/` in the constants file | `DataInputModule` | Soil material and transport data, including Darcy velocity and attachment efficiency |

Only the first group moved. `DataInputModule` still declares and reads the second
group in its previous order and still stores its values in `DATASET`. Its only change
is that it imports the two fallback constants from `SoilConfigModule` instead of
`DefaultsModule`.

### Startup and shared-settings cleanup

Bootstrap now performs the relevant part of startup in this order:

1. initialise model dimensions and general model settings;
2. initialise the shared error handler;
3. call `soilConfig%init`;
4. read the remaining legacy Sediment and Water settings;
5. audit the general model settings.

This preserves the previous Soil, Sediment, Water, then audit failure order. Error
code 600 is registered only after the shared handler exists.

The following fields were removed from `GlobalsType` and from the legacy Bootstrap
reader:

- `soilLayerDepth`;
- `includeBioturbation`;
- `includeAttachment`;
- `includeSoilErosion`;
- `includeClayEnrichment`.

`C%nSoilLayers` and its startup synchronisation remain for older output and other
non-Soil consumers. Similarly named output controls, such as
`includeSoilErosionYields`, were not changed.

### Error code 600 now belongs to Soil

The original code-600 message and warning status moved from the base error list to
`SoilConfigModule`:

```text
All water removed from SoilLayer.
```

It remains non-critical, which means it is a warning rather than an error that must
stop the model. Soil registers it with the named
`error=ErrorInstance(...)` argument after the shared handler is initialised.

The base legacy error array was reduced from 17 to 16 elements. Codes 901 to 904 now
occupy slots 13 to 16. The unrelated existing registry defects were deliberately
preserved: blank slots 4 and 5 remain, and code 405 is still overwritten in slot 11.
The base handler therefore has 25 effective entries and no code 600. Soil
initialisation adds code 600 exactly once, bringing the effective total to 26.

### Soil science modules use their direct owners

All `GlobalsModule` imports and all `C%...` reads were removed from:

- `AbstractSoilLayerModule.f90`;
- `AbstractSoilProfileModule.f90`;
- `SoilLayerModule.f90`;
- `SoilProfileModule.f90`.

Those modules now read precision and physical functions from `KernelModule`, array
sizes and particle-size values from `ModelDimensionsModule`, timing and tolerance
from `ModelConfigModule`, and Soil settings from `SoilConfigModule`. The shared error
handler, result type, error type, and NetCDF missing-value constants are also imported
explicitly where used. The same replacement was made inside the local abstract
procedure declarations.

No Soil public type, procedure binding, procedure argument, array shape, numerical
expression order, or batch-update path was intentionally changed. Existing unused
abstract declarations were retained because removing them is outside this phase.

Phase 5 does not make Soil fully independent. Soil still calls `BiotaSoilModule` and
still reads spatial input through `DATASET` and `DataInputModule`. `BiotaSoilModule`
will be handled in the later Biota phase; wider input-data cleanup is also still
pending.

## What Deliberately Stayed Unchanged

- All shipped model configuration and constants examples remain valid and unchanged.
- The required and optional status of every Soil input remains the same.
- The constants-file `/soil/` declaration, read order, and assignments remain in
  `DataInputModule`.
- `C%nSoilLayers` remains available to older consumers.
- Soil calculations, update order, batch behaviour, output structure, and checkpoint
  layout were not redesigned.
- `BiotaSoilModule` and the Soil-to-input-data connection remain for later phases.
- The blank legacy registry entries and missing code 405 remain as known defects; a
  future, separately tested phase must correct them.

## Original Comments

Every original comment and TODO in the four Soil science modules was preserved
verbatim. A comment-sequence check compared the comment text before and after the
change and passed for all four files.

The five comments attached to the old shared Soil fields moved with their settings to
`SoilConfigType`. The `! Soil` registry heading, the Soil-erosion default comment, and
the Darcy-velocity source comment also moved with their code without rewording. A
final diff review and the automated comment-sequence checks found no removed or
rewritten original comment text.

After Phase 5 verification, a new comment labelled `not an original comment` was
added above the Soil configuration file `open` statement at the user's request. It
explains the new file-unit handling and does not replace or rewrite an original
comment.

## Tests Added or Updated

`soil_config_module_test` runs in a separate process because the shared error handler
is intended to be initialised once per process. Its three-layer fixture verifies:

- all three layer depths;
- the required bioturbation and attachment switches;
- the existing clay-enrichment and Soil-erosion defaults;
- the values and default-real kind of both public fallback constants;
- one and only one registration of code 600;
- the unchanged code-600 message and non-critical status;
- 26 effective error entries after Soil initialisation.

The existing registry test now checks 25 effective entries immediately after base
handler initialisation, confirms that code 600 is absent, and continues to check the
two blank entries, missing code 405, criteria operations, and the remaining legacy
codes.

The tracked verification script can run either tolerance-based comparisons or exact
comparisons. Phase 5 used `--exact`: the three CSV files had to be byte-for-byte
identical; `summary.md` could differ only in its `Simulation datetime` line; and the
text form of `output.nc` produced by `ncdump` could differ only in its `history`
metadata.

## Verification

### Pre-change evidence

Fresh outputs from the Phase 4 executable were saved outside the repository under
`/private/tmp/nanofase_phase5_pre_soil.s6GEkt`. They cover:

- canonical settings;
- bioturbation disabled;
- attachment disabled;
- Soil erosion disabled;
- clay enrichment enabled;
- clay enrichment and Soil erosion omitted so their existing defaults are used.

All six valid runs exited successfully. Each of the four switch variants changed all
three CSV files and the filtered summary and NetCDF output relative to the canonical
case. This proved that each branch was actually exercised before its post-change
result was compared. The omitted-default case matched the canonical case exactly.

The constants-file fallback evidence is under
`/private/tmp/nanofase-phase4-constants.viIeUy`. Its fallback input omits Soil
attachment efficiency and Darcy velocity, and the pre-change run exited
successfully.

All generated configurations, outputs, and logs were kept outside tracked source
directories.

### Configure, build, and focused tests

The following commands were run from the repository root:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
cmake --build build-debug -j2
ctest --test-dir build-debug --output-on-failure
```

Configuration passed. CMake rewrote `src/VersionModule.f90`, so its exact pre-phase
content was immediately restored. The build then passed, and CTest passed both tests:
2/2, including the base-registry and Soil-configuration executables.

### Exact result comparisons

Each scenario was checked with this command shape:

```sh
python3 verification/verify_refactor.py \
  --exe build-debug/nanofase \
  --baseline <pre-change-case>/output \
  --config <pre-change-case>/config.nml \
  --run-dir /private/tmp/nanofase_phase5_post_<case>_20260830 \
  --exact
```

For the first six cases, `<pre-change-case>` was the matching directory below
`/private/tmp/nanofase_phase5_pre_soil.s6GEkt`. The constants fallback used the
matching `fallback` directory below
`/private/tmp/nanofase-phase4-constants.viIeUy`.

| Scenario | Result |
| --- | --- |
| `canonical` | passed |
| `bioturbation_off` | passed |
| `attachment_off` | passed |
| `soil_erosion_off` | passed |
| `clay_enrichment_on` | passed |
| `defaults_omitted` | passed |
| `constants_fallback` | passed |

In every case, `output_water.csv`, `output_sediment.csv`, and `output_soil.csv` were
byte-identical to their pre-change versions. The summary text matched after removing
only `Simulation datetime`, and the `ncdump` text matched after removing only NetCDF
`history` metadata.

### Negative, batch, and checkpoint checks

The final model invocations were:

```sh
build-debug/nanofase \
  /private/tmp/nanofase_phase5_pre_soil.s6GEkt/missing_soil/config.nml

build-debug/nanofase \
  /private/tmp/nanofase_phase5_batch_20260830/config.nml \
  config.example/batch_config_test-scenario.example.nml

build-debug/nanofase \
  /private/tmp/nanofase_phase5_checkpoint_20260830/save/config.nml
build-debug/nanofase \
  /private/tmp/nanofase_phase5_checkpoint_20260830/reinstate/config.nml
```

- A temporary model configuration with the required model-configuration `/soil/`
  group removed exited with status 2. The group therefore remains required.
- The batch smoke test passed under
  `/private/tmp/nanofase_phase5_batch_20260830`; it completed 3 chunks and 31
  timesteps.
- Checkpoint save and reinstate both passed under
  `/private/tmp/nanofase_phase5_checkpoint_20260830`. The saved checkpoint was
  404,908 bytes. This proves that the existing save and load paths still run, but it
  is not proof that a reinstated simulation continues with exactly identical results.

### Source and workspace checks

The main checks used these commands:

```sh
rg -n 'use[[:space:]]+GlobalsModule|C%' src/Soil
rg -n 'C%(soilLayerDepth|includeBioturbation|includeAttachment|includeSoilErosion|includeClayEnrichment)([^A-Za-z0-9_]|$)' \
  --glob '*.f90' .
rg -n -i 'namelist[[:space:]]*/soil/' src
shasum -a 256 src/VersionModule.f90
shasum -a 256 config.nml config.example/config.example.nml \
  config.example/test-scenario.example.nml \
  config.example/batch_config.example.nml \
  config.example/batch_config_test-scenario.example.nml \
  config.example/batch_thames_tio2_2000-2015.example.nml \
  data.example/constants_test-scenario.nml data.example/constants_tio2.nml
git diff --check
```

Source-text checks passed for all of the following:

- no `use GlobalsModule` and no `C%` access remains under `src/Soil/`;
- there are no remaining repository reads of the five migrated `C` fields;
- those five fields are absent from `GlobalsType` and the legacy Bootstrap reader;
- the two Soil fallback constants are absent from `DefaultsModule`;
- code 600 is absent from the base registry and appears only in Soil registration,
  its existing raising site, and tests;
- the model-configuration `/soil/` declaration appears once in `SoilConfigModule`,
  while the separate constants-file declaration remains in `DataInputModule`;
- all original Soil science comments remain in the same sequence;
- `git diff --check` reports no whitespace errors.

The shipped input hashes were checked before and after the phase and remained:

| File | SHA-256 |
| --- | --- |
| `config.nml` | `cd083a7fbd0fb92139a83a48c1dccd8ea13bfee5feec47f7ef4b4f1f1443ea70` |
| `config.example/config.example.nml` | `cd083a7fbd0fb92139a83a48c1dccd8ea13bfee5feec47f7ef4b4f1f1443ea70` |
| `config.example/test-scenario.example.nml` | `30d74e4c95a9e6ac65482cac99651776ade1766a448f1bfe04f806a6aa239604` |
| `config.example/batch_config.example.nml` | `85d42b45668a558b35e38f4737f1efca8709c467f9d555a353d8128a0323fb39` |
| `config.example/batch_config_test-scenario.example.nml` | `219b415d2bbc46610dd30f40287de4bc1ff5580fc4d9e381b9b14e7e98137176` |
| `config.example/batch_thames_tio2_2000-2015.example.nml` | `595b40a5475108fc13991f0bb5d8afb40daa9af8ba5081bb87b73be48635287e` |
| `data.example/constants_test-scenario.nml` | `701e758a443b8c43b28fd7af6b34ae054bf7212f7798f826064dc62a5642d2e5` |
| `data.example/constants_tio2.nml` | `e3c14a78f46bd0e5cba816ea40a72b6708d23ca97d4ed2a5141540bdbd83be85` |

After the final build and comparisons, `src/VersionModule.f90` again had its exact
pre-phase SHA-256:
`3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652`.
No further CMake reconfiguration was needed after restoring it. A separate
build-system task is still required to stop CMake from changing this tracked file.

The pre-existing `vendor/nanofase-data` workspace state was preserved. The two
previously untracked verification files were intentionally added as part of Phase 5;
generated baselines and run outputs were not added to the repository.

## Remaining Migration Work

1. Phase 6: migrate BedSediment. This must remain before WaterBody because WaterBody
   depends on BedSediment settings and types.
2. Phase 7: migrate WaterBody.
3. Phase 8: migrate Reactor.
4. Phase 9: migrate Biota, including the current `BiotaSoilModule` connection.
5. After Phase 9, migrate all remaining readers of the shared `C` object in output,
   data, grid, logging, utility, checkpoint, and other cross-cutting code.
6. Correct the blank registry slots, the overwritten code 405, code 901 ownership,
   and other known registry defects only in a separate, explicitly tested
   behaviour-changing phase.
7. Remove the empty shared `C` compatibility object only after all domain and
   cross-cutting readers have moved to their real owners.
8. Add an exact checkpoint continuation test. The Phase 5 checkpoint check proves
   only that saving and reinstating still execute successfully.
9. Correct the CMake behaviour that rewrites tracked `src/VersionModule.f90` during
   configuration.
