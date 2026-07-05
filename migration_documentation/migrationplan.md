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

**Two orthogonal axes of decoupling** (don't conflate them):

1. **Config/state ownership** (§§3-10) — pull per-domain configuration out of the
   `GlobalsModule` god-object into per-domain config modules. Answers *"who owns this
   setting?"*
2. **Construction vs. behaviour** (§3b, Phase B) — pull object construction and river-
   network wiring out of the science `create` methods into a `ModelAssembly` builder
   layer, leaving the science modules with per-timestep behaviour only. Answers *"who
   builds the object graph, vs. who runs the science on it?"*

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

> **Terminology — two different "setups".** This plan distinguishes two concerns that
> both get loosely called "model setup":
> - **`ModelDimensions`** — a low *foundation data* layer holding `npDim`, size
>   classes and layer counts that every domain reads. (Earlier drafts called this
>   "ModelSetup / Dims"; renamed to avoid the collision below.)
> - **`ModelAssembly` / `EnvironmentBuilder`** — a high *construction* layer that
>   instantiates the grid, cells, reaches and soil profiles and wires the river
>   network. This is "create grid cell / create reach" in the science sense.
>
> They sit at **opposite ends** of the dependency graph: domains depend *down onto*
> `ModelDimensions`; the builder depends *down onto* the domains. See §3b.

```
┌─────────────────────────────────────────────────────────────┐
│  Bootstrap (main.f90 / BootstrapModule)                      │
│  orchestrates: (1) config init  (2) assembly  (3) run loop   │
└─────────────────────────────────────────────────────────────┘
        │ uses
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Model assembly / EnvironmentBuilder                        │
│  instantiate grid + cells + reaches + soil profiles;        │
│  wire inflows/outflows, headwaters, stream order;           │
│  snap point sources to cells. Reads input DATASET.          │
└─────────────────────────────────────────────────────────────┘
        │ uses (constructs concrete domain types)
        ▼
┌──────────────────┐   ┌─────────────────────────────────────┐
│  Domains         │   │  Slim Model module (ModelConfig)    │
│  Soil, Source,   │   │  run control, output, checkpoint,   │
│  WaterBody,      │   │  steady-state, batch, data paths    │
│  BedSediment,    │   └─────────────────────────────────────┘
│  Reactor, Biota  │        │ uses
│  (config +       │        ▼
│   defaults +     │   ┌─────────────────────────────────────┐
│   errors +       │   │  Model-dimensions (ModelDimensions) │
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

**Why model-dimensions is its own layer and not a domain:** `npDim` etc. are read 490×
across all domains. If modelled as a peer domain, everyone would `use` it and we'd
recreate the hub. It is privileged foundation, sitting between kernel and domains.

**Why the builder is a top layer and not part of model-dimensions/-config:** the
builder must `use` the *concrete* domain types (`GridCell`, `RiverReach`, `SoilProfile`)
to construct them, so it depends *down onto the domains*. Putting construction into a
foundation layer would invert that arrow — the foundation would `use` every domain —
recreating the exact god-object hub this migration removes. Construction therefore
lives at the opposite end of the graph from configuration. See §3b.

---

## 3b. Construction vs. behaviour: the builder layer

This is a **second, orthogonal axis** of decoupling, separate from the config/state
work in §§3-9. Config decoupling answers *"who owns this setting?"*. This axis answers
*"who builds the object graph, vs. who runs the science on it?"*

### The problem today

`create` is overloaded. Inside `createEnvironment`
([src/Environment/EnvironmentModule.f90:40-144](src/Environment/EnvironmentModule.f90#L40-L144))
and `createGridCell` / `createReaches`
([src/GridCell/GridCellModule.f90:74-126](src/GridCell/GridCellModule.f90#L74-L126))
four distinct jobs are mashed into the same type-bound procedures that also hold the
per-timestep science (`update`):

| # | Job | Example in code | Lifecycle | Belongs to |
|---|---|---|---|---|
| 1 | **Per-object self-init** | `allocate(GridCell :: …)`, allocate own arrays, set own defaults | once, at startup | the type itself (thin `init`) |
| 2 | **Topology / assembly / wiring** | link reach inflows/outflows across cells, mark headwaters & tidal limits, stream order, snap point sources ([EnvironmentModule.f90:69-127](src/Environment/EnvironmentModule.f90#L69-L127)) | once, at startup | **the builder** |
| 3 | **Input-data parsing** | `parseInputData`, `createReaches` deciding which reaches exist from `DATASET` | once, at startup | input-data boundary (builder *calls* it) |
| 4 | **Science / process behaviour** | `update`, fate & transport equations | every timestep | the domain science modules |

Jobs 1-3 run **once** at startup; job 4 runs **every timestep**. They change for
different reasons and would be owned by different people — the classic signal to split
construction from behaviour.

### Target placement

- **Job 2 (topology/assembly) → `ModelAssembly` / `EnvironmentBuilder`** (new top
  layer, §3). "Which reaches exist and how they connect to form the river network"
  operates *across* many objects, so it belongs to none of them. This is the bulk of
  the win.
- **Job 1 (self-init) → stays as a thin type-bound `init`** near each type. The line
  to draw: *a reach initialises itself; it does not decide which other reaches it
  connects to.* The first stays; the second moves to the builder. **Do not** over-split
  trivial per-object allocation into separate files — that buys nothing.
- **Job 3 (parsing) → input-data boundary**, invoked by the builder. The builder is the
  seam where input data becomes a live, wired object graph; it legitimately depends on
  `DATASET`.
- **Job 4 (science) → stays in the domain science modules**, now containing only
  process behaviour.

### Fortran mechanism

`create` is a **type-bound procedure** (`procedure :: create => createGridCell`,
[GridCellModule.f90:19](src/GridCell/GridCellModule.f90#L19)). Two clean ways to
physically separate construction from science:

1. **Free-standing builder module** (recommended for Job 2) — `buildEnvironment(env)`,
   **not** type-bound. Best fit because cross-object wiring is not a property of any
   single type's interface, and it must `use` the concrete domain types anyway.
2. **Submodules** (Fortran 2008) — keep a procedure type-bound but move its body to a
   separate file (`GridCellModule_setup.f90` vs `GridCellModule_science.f90`,
   implementing the same parent module's interface). Use this if you want to split a
   type's own setup-vs-science methods into separate files without un-binding them.

**Recommendation:** free-standing builder for the cross-object assembly (Job 2);
submodules only where it helps split a single type's file.

### Sequencing relative to the config migration

Independent workstream. Sequence the builder extraction **after Phases 1-2** of the
config work so the builder leans on the clean `ModelDimensions` / `ModelConfig` rather
than the facade `C`. See the builder phase in §7.

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

### Model-dimensions (`src/ModelDimensions/` — proposed)
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
  `triggerWarnings`, `errorOutput`, `runDescription`, `logFilePath`, `writeToLog`,
  `configFilePath`, `hasSimulationMask`/`simulationMaskPath`, `ignoreNM`,
  `bashColors`, `modelVersion`
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

> Note: dimension *counts* (`nSoilLayers`, `nSedimentLayers`) live in model-dimensions
> because they shape arrays across domains and in checkpoint; the *depths*
> (`soilLayerDepth`, `sedimentLayerDepth`) belong to the owning domain, which reads
> the count from model-dimensions to allocate.

### Model assembly / builder (`src/ModelAssembly/` — proposed)

Owns **construction and wiring**, not config data. What moves here:

- The grid-instantiation loop and cell/reach/soil-profile construction currently in
  `createEnvironment` ([EnvironmentModule.f90:47-67](src/Environment/EnvironmentModule.f90#L47-L67))
  and `createGridCell` ([GridCellModule.f90:74-126](src/GridCell/GridCellModule.f90#L74-L126)).
- The **cross-cell topology wiring**: inflow/outflow pointer linking, headwater and
  tidal-limit detection ([EnvironmentModule.f90:69-113](src/Environment/EnvironmentModule.f90#L69-L113)).
- `finaliseCreate` work that needs full cell linking, e.g. snapping point sources to
  cells ([EnvironmentModule.f90:115-122](src/Environment/EnvironmentModule.f90#L115-L122)).
- Stream-order determination (`determineStreamOrder`,
  [EnvironmentModule.f90:124-126](src/Environment/EnvironmentModule.f90#L124-L126),
  253-312) and `routedReaches` / `headwaters` allocation.

What **stays** with each type (thin `init`, not moved): allocation of an object's own
arrays and setting of its own defaults — e.g. the per-timestep mean arrays at
[EnvironmentModule.f90:130-137](src/Environment/EnvironmentModule.f90#L130-L137) stay
local. Dependencies: `ModelAssembly` `use`s the concrete domain types and `DATASET`;
nothing `use`s `ModelAssembly` except the bootstrap.

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

This means `LoggerModule`, the error array, and most checkpoint state keep reading
`C%…` until their owning layers are migrated. The Phase 1 exception is deliberate:
`CheckpointModule` may read dimension fields directly from `ModelDimensionsModule`,
while keeping `C` for non-dimension state such as `epsilon`, `t0`, and error handling.
Phase 2 adds `ModelConfigModule` as the source of truth for model-level config, while
`C` remains a facade. Runtime-mutated model config (`inputFile`, `constantsFile`,
`nTimeSteps`, `startDate`, `t0`) must be changed through `ModelConfigModule` helpers
and mirrored back into `C` until all readers migrate.

### Namelist read-order coupling (must preserve)
Today `/allocatable_array_sizes/` is read first because its counts size the
allocatable arrays read by `/soil/`, `/sediment/`, `/nanomaterial/`
([src/GlobalsModule.f90:280-302](src/GlobalsModule.f90#L280-L302)). After migration:
model-dimensions owns the counts and reads `/allocatable_array_sizes/` **first** during
its init; the bootstrap calls model-dimensions init before any domain init; each domain
queries model-dimensions for the count it needs, allocates, then reads its own group.
Each module opens `config.nml` with `open(newunit=…)` so there is no shared IO-unit
registry and no ordering coupling between domain reads.

Fortran namelist reads are group-wide, not partial. Any module that reads a shared
group such as `/sediment/` must declare every variable that can appear in that group,
even if some variables are only local dummies. In Phase 1, `ModelDimensionsModule`
therefore declares dummy `include_bed_sediment` and `sediment_layer_depth` variables
when reading `/sediment/`, while storing only the SPM size classes and sediment
particle densities.

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
    use ModelDimensionsModule, only: nSoilLayers   ! count owned by dimensions layer
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
    call modelDimensions%init(configFilePath) ! reads /allocatable_array_sizes/, /nanomaterial/ first
    call modelConfig%init(configFilePath)  ! run/output/checkpoint/steady/batch
    call soilConfig%init(configFilePath)   ! each domain reads its own group + registers its errors
    call sourceConfig%init(configFilePath)
    call waterConfig%init(configFilePath)
    ! … bed sediment, reactor, biota
    ! Only AFTER all config is loaded: build and wire the object graph
    call buildEnvironment(env)             ! ModelAssembly: instantiate + wire, reads DATASET
end subroutine
```

### Builder (construction only — see §3b)
```fortran
module ModelAssemblyModule
    use DataInputModule, only: DATASET
    use GridCellModule,    only: GridCell        ! concrete domain types
    use RiverReachModule,  only: RiverReach
    use EstuaryReachModule, only: EstuaryReach
    use EnvironmentModule, only: Environment
    implicit none
contains
    subroutine buildEnvironment(env)
        type(Environment), target, intent(inout) :: env
        ! 1. instantiate the grid + cells (+ their reaches / soil profiles)
        ! 2. wire topology: inflow/outflow pointers, headwaters, tidal limits
        ! 3. finalise: snap point sources, determine stream order, allocate routedReaches
        ! (the body is the construction code lifted out of createEnvironment /
        !  createGridCell — see §4 "Model assembly / builder")
    end subroutine
end module
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

### Phase 1 — Model-dimensions
- Create `ModelDimensionsModule` owning `npDim`, size classes, counts, distributions,
  and the `/allocatable_array_sizes/` + `/nanomaterial/` reads + `d_spm_*` derivation.
- `GLOBALS_INIT` delegates dimension setup to it, then **copies** values back into `C`
  (facade) so the 490 `C%npDim` readers are untouched.
- Repoint only `CheckpointModule`'s dimension-shaped reads to `use ModelDimensionsModule`;
  it keeps `C` for non-dimension state such as `epsilon`, `t0`, and error handling.
- **Verify:** build + reference run identical; checkpoint save/reinstate smoke test
  runs, with exact round-trip comparison deferred until the existing warm-up/reinstate
  run-control semantics are separated.

### Phase 2 — Slim model module + facade wiring
- Create `ModelConfigModule` owning run/output/checkpoint/steady-state/batch/data-path
  config and their namelist reads.
- `GLOBALS_INIT` delegates these reads to it, copies back into `C` (facade).
- Move model-level config audits ([src/GlobalsModule.f90:474-507](src/GlobalsModule.f90#L474-L507))
  into `ModelConfig%audit`, returning a `Result` so `ModelConfigModule` does not
  depend on `GlobalsModule`/`ERROR_HANDLER`.
- Keep domain namelist reads (`/soil/`, `/sediment/`, `/water/`, `/sources/`) in
  `GLOBALS_INIT` until the corresponding domain phases migrate them.
- Route batch chunk selection and checkpoint-preserved `t0` through `ModelConfigModule`
  and mirror those runtime values back into `C`.
- **Verify:** build + reference run identical.

### Phase B — Builder extraction (parallel workstream, after Phases 1-2)
This is the §3b construction-vs-behaviour axis, independent of the per-domain config
phases below. It can run in parallel once `ModelDimensions` + `ModelConfig` exist.
- Create `ModelAssemblyModule` with `buildEnvironment(env)`.
- **Move** (don't rewrite) the construction + topology code out of `createEnvironment`
  and `createGridCell`/`createReaches` into the builder: grid/cell/reach/soil
  instantiation, inflow/outflow wiring, headwater & tidal-limit detection, point-source
  snapping, `determineStreamOrder`, `routedReaches`/`headwaters` allocation (see §4
  "Model assembly / builder" for exact line ranges).
- **Keep** thin per-object self-`init` on each type (own-array allocation, own
  defaults). Do not over-split trivial allocation.
- `main.f90` calls `buildEnvironment(env)` after config init instead of `env%create()`;
  `createEnvironment` shrinks to (or is replaced by) the thin self-init.
- Optional: use submodules to split a type's setup vs science methods into separate
  files where it aids readability.
- **Verify:** build + reference run identical — construction is behaviour-preserving;
  only the *location* of the code changes, not the order of operations.

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
   `use KernelModule` + `use ModelDimensionsModule` + `use XConfigModule`; rewrite
   `C%foo` → `xConfig%foo` (or `ModelDimensions`/kernel for dims/constants).
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
| Namelist read-order coupling (`allocatable_array_sizes` first) | Model-dimensions reads sizes in Phase 1, before any domain init; bootstrap enforces order |
| IO-unit collisions when domains read independently | Use `open(newunit=…)`; retire the central `iou*` registry |
| `errors(11)` double-assignment bug carried forward | Fixed during final error-distribution pass; code 405 restored |
| Silent behaviour change during refactor | Byte-identical output regression gate after every phase |
| Checkpoint depends on dimensions | It reads *only* dimensions (verified); repointed once in Phase 1, untouched after |
| Layer-depth vs count split (soil/sediment) | Counts → model-dimensions; depths → domain, which queries the count to allocate |
| Builder must `use` concrete domain types (reverse arrow) | Builder is a *top* layer (above domains); nothing below depends on it, so no cycle — see §3b |
| Construction reorder could change results | Phase B *moves* code without changing operation order; byte-identical regression gate catches any drift |

---

## 11. Out of scope

- Input pre-processing (`src/Data/`, `DataInputModule`) and output post-processing
  (`DataOutputModule`) — these are not the model engine. They will continue to read
  the slim model module's output/data-path config.
- Any science/algorithm change. This migration is behaviour-preserving — including the
  builder extraction (§3b / Phase B), which relocates construction code without
  altering the order of operations.
- Generalising the contaminant-specific accessor interfaces on the spatial containers
  (`get_C_np_water`, `get_j_nm_*` on `AbstractGridCell` / `AbstractEnvironment`) so the
  grid/environment become agnostic to the modelled stressor. This is a larger, more
  speculative refactor worth doing only once a concrete second science scenario exists
  to design against; it is noted here so it is not confused with the config or builder
  work, but is deferred.
