# NanoFASE Model Engine — Modularisation Migration Plan

## 1. Goal

Make the NanoFASE **model engine** (simulation code, not input pre-processing or
output post-processing) modular and decoupled along science-domain lines, so each
domain is self-contained and different teams can work in parallel without colliding.

**Self-contained per domain** means each domain directory owns:

1. **Config** — its own config module that reads *its own* namelist group directly
   from `config.nml` (declares `namelist /soil/ …` and does the `read` itself).
2. **Defaults** — default config values and science constants live with the domain.
3. **Errors & logging** — error definitions and log messages belong to the domain
   that raises them.
4. **Science code** behind the existing `Abstract*Module` interface — the contract
   other teams code against.

**What stays global:**

- A **slim model module** — only genuinely model-wide config: run control (timestep,
  nTimesteps, start date, warm-up), output options, checkpointing, steady-state,
  batch-run state, data paths.
- A small shared **kernel** — precision `dp`, cross-domain physical constants
  (`g`/`k_B`/`rho_w`), and IO infrastructure. Depends on nothing; everything may
  depend on it. This breaks circular `use` dependencies.

**Constraints:**

- `config.nml` stays a **single file** with per-domain namelist groups.
- A thin **bootstrap** decides domain init order and passes the config path down —
  orchestration, not coupling.
- Migration is **incremental, one domain at a time** — no big-bang rewrite.

---

## 2. Current state (measured from the codebase)

The blockers are real and quantified:

- **`GlobalsModule.f90` is a god-object.** `type(GlobalsType) :: C` holds ~100 fields
  spanning every domain, jumbled with physical constants and run control.
  `GLOBALS_INIT` ([src/GlobalsModule.f90:148](src/GlobalsModule.f90#L148)) centrally
  declares *all* namelist groups, reads them all, stores into `C`, and defines *all*
  error codes in one flat `errors(17)` array.
- **34 files** do `use GlobalsModule` and reach into `C%…`.
- The most-referenced fields are **cross-cutting dimensions**, not per-domain config:
  - `C%npDim` — **490** refs
  - `C%nSizeClassesSpm` — **133** (+24 as `nSizeClassesSPM`)
  - `C%nSedimentLayers` — **90**
  - `C%nSizeClassesNM` — 31, `C%d_spm` — 12, `C%d_nm` — 7
  - These are read by *every* domain ⇒ they are a **foundation layer**, not a peer domain.
- **`DefaultsModule.f90`** mixes model-level defaults (run/output/checkpoint) with
  domain ones (`includeEstuary`, `includeSoilErosion`) and bare science `parameter`s
  (`defaultSedimentTransport_a`, `defaultBankErosionAlpha`, soil attachment
  efficiency, …) that are all domain-specific.
- **`dp` is duplicated** in `GlobalsModule.f90:13` and `DefaultsModule.f90:7`.
- The flat error array has a **latent bug**: `errors(11)` is assigned twice
  ([src/GlobalsModule.f90:448](src/GlobalsModule.f90#L448) and
  [:452](src/GlobalsModule.f90#L452)), silently dropping code 405.
- `CheckpointModule.f90` reads **only dimension fields** (`npDim` ×66,
  `nSedimentLayers` ×14, `nSizeClassesSpm` ×18, `nSoilLayers` ×10, `nFracCompsSpm` ×4)
  — i.e. the foundation layer, **no per-domain config flags**.
- The error API already supports incremental registration:
  `ERROR_HANDLER%addErrorInstance` / `addMultipleErrorInstancesFromErrors`
  ([vendor/feh/src/ErrorHandler.f90:32-34](vendor/feh/src/ErrorHandler.f90#L32-L34)).

---

## 3. Target architecture (layered, not flat)

Dependencies point downward only. Domains never `use` each other.

```
┌─────────────────────────────────────────────────────────────┐
│  Bootstrap (main.f90 / BootstrapModule)                      │
│  orchestrates init order, passes config path down            │
└─────────────────────────────────────────────────────────────┘
        │ uses
        ▼
┌──────────────────┐   ┌─────────────────────────────────────┐
│  Domains         │   │  Slim Model module (ModelConfig)    │
│  Soil, Source,   │   │  run control, output, checkpoint,   │
│  WaterBody,      │   │  steady-state, batch, data paths    │
│  BedSediment,    │   └─────────────────────────────────────┘
│  Reactor, Biota  │        │ uses
│  (config +       │        ▼
│   defaults +     │   ┌─────────────────────────────────────┐
│   errors +       │   │  Model-setup (ModelSetup / Dims)    │
│   science behind │──▶│  npDim, ionicDim, size classes,     │
│   Abstract*)     │   │  layer counts, NM/SPM dimensions    │
└──────────────────┘   └─────────────────────────────────────┘
        │ uses                  │ uses
        ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Kernel (depends on NOTHING)                                 │
│  dp · physical constants (g, k_B, pi, n_river) ·            │
│  water physics (rho_w, nu_w, mu_w) ·                        │
│  IO infra (iou units / newunit, ANSI colors,               │
│  ERROR_HANDLER, LOGR) · Result/ErrorInstance re-exports     │
└─────────────────────────────────────────────────────────────┘
```

**Why model-setup is its own layer and not a domain:** `npDim` etc. are read 490×
across all domains. If modelled as a peer domain, everyone would `use` it and we'd
recreate the hub. It is privileged foundation, sitting between kernel and domains.

---

## 4. Field → home mapping

### Kernel (`src/Kernel/` — proposed)
- `dp` (single definition; delete the duplicate)
- Physical constants: `g`, `k_B`, `pi`, `n_river`
- Water physics functions: `rho_w`, `nu_w`, `mu_w` (currently methods on `C`;
  become free functions in the kernel — call sites change `C%rho_w(T)` → `rho_w(T)`)
- IO infra: IO unit policy (prefer `open(newunit=…)`), ANSI color constants,
  `ERROR_HANDLER` object, `LOGR` object
- Re-exports: `Result`, `ErrorInstance`, `ErrorCriteria`

### Model-setup (`src/ModelSetup/` — proposed)
- `npDim`, `ionicDim`
- Counts: `nSizeClassesSpm`, `nSizeClassesNM`, `nFracCompsSpm`, `nFormsNM`,
  `nExtraStatesNM`, `nSoilLayers`, `nSedimentLayers`
- Distributions: `d_spm`, `d_spm_low`, `d_spm_upp`, `d_nm`,
  `sedimentParticleDensities`, `defaultDistributionSediment`, `defaultDistributionNP`
- Namelists owned: `/allocatable_array_sizes/`, `/nanomaterial/`, and the size-class
  portion of `/sediment/`
- The `d_spm_low`/`d_spm_upp` derivation logic (currently
  [src/GlobalsModule.f90:404-421](src/GlobalsModule.f90#L404-L421))

### Slim model module (`src/ModelConfig` — proposed; replaces the global parts of `C`)
- Run: `timeStep`, `nTimeSteps`, `startDate`, `epsilon`, `warmUpPeriod`,
  `triggerWarnings`, `runDescription`, `logFilePath`, `writeToLog`, `configFilePath`,
  `hasSimulationMask`/`simulationMaskPath`, `ignoreNM`, `bashColors`, `modelVersion`
- Output: all `write*`/`include*` output flags, `soilPECUnits`, `sedimentPECUnits`,
  `netCDFWriteMode`
- Checkpoint: `checkpointFile`, `saveCheckpoint`, `saveCheckpointAfterWarmUp`,
  `reinstateCheckpoint`, `preserveTimestep`, `t0`
- Steady state: `runToSteadyState`, `steadyStateMode`, `steadyStateDelta`
- Batch: `nChunks`, `isBatchRun`, `batchInputFiles`, `batchConstantFiles`,
  `batchStartDates`, `batchNTimesteps`, `batchConfigFiles`, `nTimestepsInBatch`,
  `batchStartDate`, `batchEndDate`
- Data paths: `inputFile`, `constantsFile`, `outputPath`, `outputHash`
- Namelists owned: `/data/`, `/output/`, `/run/`, `/checkpoint/`, `/steady_state/`,
  `/batch_config/`, `/chunks/`

### Domains
| Domain | Config flags | Science defaults (from DefaultsModule) | Error codes | Namelist |
|---|---|---|---|---|
| **Soil** (`src/Soil/`) | `soilLayerDepth`, `includeBioturbation`, `includeAttachment`, `includeSoilErosion`, `includeClayEnrichment` | `defaultSoilAttachmentEfficiency`, `defaultSoilDarcyVelocity` | 600 | `/soil/` |
| **Source** (`src/Source/`) | `includePointSources` | — | — | `/sources/` |
| **WaterBody** (`src/WaterBody/`) | `minStreamSlope`, `minEstuaryTimestep`, `includeEstuary`, `includeBankErosion` | `defaultSlope`, `defaultBankErosionAlpha/Beta`, `defaultMin/MaxWaterTemperature`, `defaultMinWaterTemperatureDayOfYear` | 401–405, 500–501 | `/water/` |
| **BedSediment** (`src/BedSediment/`) | `includeBedSediment`, `sedimentLayerDepth` | `defaultDepositionAlpha/Beta`, `defaultSedimentTransport_a/b/c`, `defaultSedimentEnrichment_k/a` | 904, 901 | `/sediment/` (non-dimension part) |
| **Reactor** (`src/Reactor/`) | — | `default_k_diss_pristine/transformed`, `default_k_transform_pristine`, `defaultShearRate`, `T` | 903 | (none yet) |
| **Biota** (`src/Biota/`) | — | — | 902 | (none yet) |

> Note: dimension *counts* (`nSoilLayers`, `nSedimentLayers`) live in model-setup
> because they shape arrays across domains and in checkpoint; the *depths*
> (`soilLayerDepth`, `sedimentLayerDepth`) belong to the owning domain, which reads
> the count from model-setup to allocate.

---

## 5. Transition strategy: the facade shim (keep the build green)

The blocker for "incremental" is that `C` is a module singleton referenced 490+ times.
We cannot edit all call sites at once. Strategy:

1. Build new layers/modules as **pure additions** that become the source of truth.
2. Keep `type(GlobalsType) :: C` alive as a **facade**: during `GLOBALS_INIT`,
   populate the old `C%…` fields *from* the new modules (or make them pointers).
3. Migrate call sites **one domain at a time** from `C%foo` to the new module's
   accessor. Untouched domains keep reading `C%foo` and keep compiling.
4. When the last domain is migrated, `C` has no remaining readers → **delete it**,
   and do the final error/log distribution pass.

This means `CheckpointModule`, `LoggerModule`, and the error array keep reading `C%…`
**unchanged** for the entire migration; they are only touched in the final cleanup.

### Namelist read-order coupling (must preserve)
Today `/allocatable_array_sizes/` is read first because its counts size the
allocatable arrays read by `/soil/`, `/sediment/`, `/nanomaterial/`
([src/GlobalsModule.f90:280-302](src/GlobalsModule.f90#L280-L302)). After migration:
model-setup owns the counts and reads `/allocatable_array_sizes/` **first** during
its init; the bootstrap calls model-setup init before any domain init; each domain
queries model-setup for the count it needs, allocates, then reads its own group.
Each module opens `config.nml` with `open(newunit=…)` so there is no shared IO-unit
registry and no ordering coupling between domain reads.

---

## 6. Module skeletons (illustrative)

### Kernel
```fortran
module KernelModule
    implicit none
    integer, parameter :: dp = selected_real_kind(15, 307)
    real(dp), parameter :: g = 9.80665_dp
    real(dp), parameter :: k_B = 1.38064852e-23_dp
    real(dp), parameter :: pi = 4*atan(1.0_dp)
    real(dp), parameter :: n_river = 0.035_dp
    ! ANSI colors, IO unit policy, ERROR_HANDLER, LOGR live here too
contains
    pure function rho_w(T, S) result(r) ... end function   ! was C%rho_w
    pure function nu_w(T, S) result(r) ... end function
    pure function mu_w(T) result(r) ... end function
end module
```

### Per-domain config (template — Soil shown)
```fortran
module SoilConfigModule
    use KernelModule, only: dp
    use ModelSetupModule, only: nSoilLayers       ! count owned by setup
    implicit none

    type :: SoilConfigType
        real, allocatable :: soilLayerDepth(:)
        logical :: includeBioturbation, includeAttachment
        logical :: includeSoilErosion, includeClayEnrichment
        ! domain science defaults live here as components or module parameters
        real :: soilAttachmentEfficiency = 0.0
        real :: soilDarcyVelocity = 9e-6
    contains
        procedure :: init => initSoilConfig
        procedure :: audit => auditSoilConfig
    end type
    type(SoilConfigType) :: soilConfig
contains
    subroutine initSoilConfig(me, configFilePath)
        class(SoilConfigType), intent(inout) :: me
        character(*), intent(in) :: configFilePath
        integer :: iou
        ! domain-local defaults
        logical :: include_bioturbation = .true., include_attachment = .false.
        logical :: include_soil_erosion = .true., include_clay_enrichment = .false.
        real, allocatable :: soil_layer_depth(:)
        namelist /soil/ soil_layer_depth, include_bioturbation, &
            include_attachment, include_clay_enrichment, include_soil_erosion
        allocate(soil_layer_depth(nSoilLayers))
        open(newunit=iou, file=configFilePath, status="old")
        read(iou, nml=soil); close(iou)
        me%soilLayerDepth = soil_layer_depth
        me%includeBioturbation = include_bioturbation
        ! …
        call me%audit()
    end subroutine
    ! initSoilConfig also registers domain errors:
    !   call ERROR_HANDLER%add(ErrorInstance(code=600, message="All water removed from SoilLayer.", isCritical=.false.))
end module
```

### Bootstrap (orchestration only)
```fortran
subroutine bootstrap(configFilePath)
    call ERROR_HANDLER%init(...)           ! kernel: handler exists, defaults only
    call modelSetup%init(configFilePath)   ! reads /allocatable_array_sizes/, /nanomaterial/ first
    call modelConfig%init(configFilePath)  ! run/output/checkpoint/steady/batch
    call soilConfig%init(configFilePath)   ! each domain reads its own group + registers its errors
    call sourceConfig%init(configFilePath)
    call waterConfig%init(configFilePath)
    ! … bed sediment, reactor, biota
end subroutine
```

---

## 7. Phased execution (each phase = one reviewable PR)

### Phase 0 — Kernel (pure addition, no behaviour change)
- Create `KernelModule` with `dp`, physical constants, water-physics functions,
  IO/color/handler/logger infra.
- Replace the duplicate `dp` in `DefaultsModule.f90:7` and `GlobalsModule.f90:13`
  with `use KernelModule, only: dp`.
- Leave `C%rho_w` etc. as thin forwarders to kernel functions (don't touch call
  sites yet).
- **Verify:** full build + a reference run produces byte-identical output.

### Phase 1 — Model-setup (dimensions)
- Create `ModelSetupModule` owning `npDim`, size classes, counts, distributions, and
  the `/allocatable_array_sizes/` + `/nanomaterial/` reads + `d_spm_*` derivation.
- `GLOBALS_INIT` delegates dimension setup to it, then **copies** values back into `C`
  (facade) so the 490 `C%npDim` readers are untouched.
- Repoint `CheckpointModule` dimension reads to `use ModelSetupModule` (it reads only
  dimensions — clean, isolated change).
- **Verify:** build + reference run identical; checkpoint save/reinstate round-trips.

### Phase 2 — Slim model module + facade wiring
- Create `ModelConfigModule` owning run/output/checkpoint/steady-state/batch/data-path
  config and their namelist reads.
- `GLOBALS_INIT` delegates these reads to it, copies back into `C` (facade).
- Move model-level config audits ([src/GlobalsModule.f90:474-507](src/GlobalsModule.f90#L474-L507))
  into `ModelConfig%audit`.
- **Verify:** build + reference run identical.

### Phase 3 → N — One domain at a time (start smallest)
Order by blast radius (smallest first to prove the recipe):
1. **Source** — only `includePointSources`, 2 files, no science defaults. Smallest;
   proves config+errors ownership end-to-end.
2. **Soil**
3. **WaterBody** (river + estuary)
4. **BedSediment** (suspended + bed sediment dynamics)
5. **Reactor** (water-column reactor)
6. **Biota**

Each domain phase follows the **per-domain checklist** (§8).

### Final phase — Cleanup
- Move the flat `errors(17)` definitions into their owning domains' init (fixing the
  `errors(11)` duplicate bug → restore code 405).
- Move remaining log messages to domain code (most are already inline).
- Delete `type(GlobalsType) :: C` and `GLOBALS_INIT` once no readers remain.
- Delete migrated parameters from `DefaultsModule` (keep only IO units there, or fold
  into kernel).
- **Verify:** build + reference run identical; grep confirms zero `C%` / `use GlobalsModule`.

---

## 8. Per-domain migration checklist (repeatable recipe)

For domain `X`:

1. **Create `XConfigModule`** in `src/X/`: a `XConfigType` with the domain's config
   fields + a `type(XConfigType) :: xConfig` singleton.
2. **Move defaults** into the domain: config defaults as component initialisers,
   science constants as module `parameter`s. Delete them from `DefaultsModule`.
3. **Own the namelist:** declare `namelist /x/ …` inside `XConfig%init`, open
   `config.nml` with `newunit`, read, populate, `close`.
4. **Move audits:** domain-specific checks from `C%audit` into `XConfig%audit`.
5. **Register errors:** in `XConfig%init`, call
   `ERROR_HANDLER%add(ErrorInstance(code=…, …))` for the domain's codes; remove them
   from the global `errors(…)` array.
6. **Repoint science code:** in `src/X/*Module.f90`, change `use GlobalsModule` →
   `use KernelModule` + `use ModelSetupModule` + `use XConfigModule`; rewrite `C%foo`
   → `xConfig%foo` (or `ModelSetup`/kernel for dims/constants).
7. **Update bootstrap:** add `call xConfig%init(configFilePath)` in the right order.
8. **Drop facade fields:** remove domain fields from `GlobalsType`/`GLOBALS_INIT` once
   no other code reads them (grep `C%fieldName`).
9. **Verify:** build + reference run produces identical output (§9).

---

## 9. Verification strategy

- **Build gate:** the project build must pass after every phase. The facade keeps the
  build green between phases.
- **Regression gate:** keep one canonical config + input dataset. After each phase,
  run the model and diff output (CSV/NetCDF) against a pre-migration baseline. Output
  must be **identical** — this is a pure refactor, no science changes.
- **Checkpoint round-trip:** after Phase 1, confirm save-then-reinstate reproduces a
  continued run.
- **Grep gates** (final phase): `grep -rn "use GlobalsModule" src` → 0;
  `grep -rn "C%" src` → 0.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 490 `C%npDim` readers can't change at once | Facade shim — `C` stays populated until the last domain migrates |
| Namelist read-order coupling (`allocatable_array_sizes` first) | Model-setup reads sizes in Phase 1, before any domain init; bootstrap enforces order |
| IO-unit collisions when domains read independently | Use `open(newunit=…)`; retire the central `iou*` registry |
| `errors(11)` double-assignment bug carried forward | Fixed during final error-distribution pass; code 405 restored |
| Silent behaviour change during refactor | Byte-identical output regression gate after every phase |
| Checkpoint depends on dimensions | It reads *only* dimensions (verified); repointed once in Phase 1, untouched after |
| Layer-depth vs count split (soil/sediment) | Counts → model-setup; depths → domain, which queries the count to allocate |

---

## 11. Out of scope

- Input pre-processing (`src/Data/`, `DataInputModule`) and output post-processing
  (`DataOutputModule`) — these are not the model engine. They will continue to read
  the slim model module's output/data-path config.
- Any science/algorithm change. This migration is behaviour-preserving.
