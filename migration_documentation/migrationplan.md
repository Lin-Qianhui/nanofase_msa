# NanoFASE Model Engine — Modularisation Migration Plan

## 1. Goal

Make the NanoFASE **model engine** (simulation code, not input pre-processing or
output post-processing) modular and decoupled along science-domain lines, so each
domain is self-contained and different teams can work in parallel without colliding.

**Self-contained per domain** means each domain directory owns:

1. **Config** — its own config module that reads *its own* namelist group directly
   from `config.nml` (declares `namelist /soil/ …` and does the `read` itself).
2. **Defaults** — default config values and science constants live with the domain.
3. **Errors & logging** — where a domain owns registered errors, their definitions
   and log messages belong to the domain that raises them. A domain with no assigned
   error codes does not need to invent an error registry merely to fit the template.
4. **Science code** behind an existing `Abstract*Module` interface, where that
   interface already exists — the contract other teams code against. Do not create an
   artificial `Abstract*` layer solely for this migration; Source currently has no
   abstract contract.

**What stays global:**

- A **slim model module** — only genuinely model-wide config: run control (timestep,
  nTimesteps, start date, warm-up), output options, checkpointing, steady-state,
  batch-run state, data paths.
- A small shared **kernel** — precision `dp`, cross-domain physical constants
  (`g`/`k_B`/`rho_w`), and dependency-free IO/color utilities. It depends on
  nothing; everything may depend on it. This breaks circular `use` dependencies.
- A shared **error-handling module** above the kernel — owns the single
  `ERROR_HANDLER` instance and FEH integration. It is deliberately not part of the
  pure kernel.

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

## 2. Pre-migration baseline and known current debt

The measurements below capture the baseline that motivated this migration. Completed
phase status and the authoritative per-phase records are listed in §7; baseline items
already addressed by those phases are retained here as design context. Registry and
other explicitly deferred defects remain current until their named follow-up phase.

- **`GlobalsModule.f90` is a god-object.** `type(GlobalsType) :: C` holds ~100 fields
  spanning every domain, jumbled with physical constants and run control.
  `GLOBALS_INIT` ([src/GlobalsModule.f90:148](../src/GlobalsModule.f90#L148)) centrally
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
- The flat error registry has several existing defects that this behaviour-preserving
  migration must record but not silently repair:
  - `errors(4)` and `errors(5)` are never assigned and therefore behave as blank
    code-1 `ErrorInstance`s.
  - `errors(11)` is assigned twice, silently dropping code 405.
  - code 901 is listed with BedSediment even though its message describes an invalid
    RiverReach type.
  - codes 110, 200, 201, and 300 do not yet have explicit target owners.
  These require a separate, explicitly tested behaviour-change phase.
- `CheckpointModule.f90` reads **only dimension fields** (`npDim` ×66,
  `nSedimentLayers` ×14, `nSizeClassesSpm` ×18, `nSoilLayers` ×10, `nFracCompsSpm` ×4)
  — i.e. the foundation layer, **no per-domain config flags**.
- The FEH generic already supports incremental registration. The unambiguous form for
  one domain error is
  `call ERROR_HANDLER%add(error=ErrorInstance(code=..., ...))`
  ([vendor/feh/src/ErrorHandler.f90:31-34](../vendor/feh/src/ErrorHandler.f90#L31-L34)).
- Phase 6 investigation confirmed an existing river failure when
  `include_bed_sediment = .false.`: `depositToBedReach` skips deposition but still
  reads the unset deposit result. River resuspension and nanomaterial transfers also
  remain outside that switch. Phase 6 preserves this behaviour and tests the known
  failure. A separate fix must define and test the complete river-disabled behaviour.

---

## 3. Target architecture (layered, not flat)

Dependencies point downward only and must remain acyclic. Domains are not required to
be mutually isolated peers: a higher-level domain may explicitly `use` a lower-level
domain when the model relationship requires it. In particular, Source is a lower-level
domain consumed by GridCell and WaterBody. The reverse dependency is forbidden, and
introducing `AbstractSource` interfaces or dependency injection is deferred until it
has a demonstrated design need.

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
│   owned errors + │   │  Model-dimensions (ModelDimensions) │
│   science behind │──▶│  npDim, ionicDim, size classes,     │
│   Abstract*)     │   │  layer counts, NM/SPM dimensions    │
└──────────────────┘   └─────────────────────────────────────┘
        │ uses                  │ uses
        ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Shared diagnostics (ErrorHandlingModule)                   │
│  owns ERROR_HANDLER and FEH integration; depends on kernel  │
└─────────────────────────────────────────────────────────────┘
        │ uses
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Kernel (depends on NOTHING)                                 │
│  dp · physical constants (g, k_B, pi, n_river) ·            │
│  water physics (rho_w, nu_w, mu_w) ·                        │
│  dependency-free IO-unit policy and ANSI color constants    │
└─────────────────────────────────────────────────────────────┘
```

The stacked diagram shows dependency level, not an assertion that every box imports
every intermediate module. `ModelConfig` remains independent of `ErrorHandlingModule`;
bootstrap reads its controls and passes them into handler initialisation. Only domain
configs that register owned errors import the shared diagnostics module.

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
([src/Environment/EnvironmentModule.f90:40-144](../src/Environment/EnvironmentModule.f90#L40-L144))
and `createGridCell` / `createReaches`
([src/GridCell/GridCellModule.f90:74-126](../src/GridCell/GridCellModule.f90#L74-L126))
four distinct jobs are mashed into the same type-bound procedures that also hold the
per-timestep science (`update`):

| # | Job | Example in code | Lifecycle | Belongs to |
|---|---|---|---|---|
| 1 | **Per-object self-init** | `allocate(GridCell :: …)`, allocate own arrays, set own defaults | once, at startup | the type itself (thin `init`) |
| 2 | **Topology / assembly / wiring** | link reach inflows/outflows across cells, mark headwaters & tidal limits, stream order, snap point sources ([EnvironmentModule.f90:69-127](../src/Environment/EnvironmentModule.f90#L69-L127)) | once, at startup | **the builder** |
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
[GridCellModule.f90:19](../src/GridCell/GridCellModule.f90#L19)). Two clean ways to
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
- Dependency-free IO-unit policy (prefer `open(newunit=…)`) and ANSI color constants.
  The kernel does not own `ERROR_HANDLER`, FEH re-exports, or logging state.

### Shared diagnostics (`src/ErrorHandling/` — proposed)
- `ErrorHandlingModule` owns the single `type(ErrorCriteria) :: ERROR_HANDLER` object
  and FEH integration; the criteria-capable type is required by existing calls such
  as `ERROR_HANDLER%equal`.
- Bootstrap initialises it from already-loaded `ModelConfig` controls before any
  domain config attempts error registration.
- During migration, `GlobalsModule` temporarily imports and publicly re-exports the
  same object so untouched consumers do not create a second handler instance.
- The legacy flat registry remains temporarily available and shrinks only when a
  domain with assigned codes takes ownership. Its known malformed/unowned entries are
  preserved until the separate registry-correction phase.

### Model-dimensions (`src/ModelDimensions/` — proposed)
- `npDim`, `ionicDim`
- Counts: `nSizeClassesSpm`, `nSizeClassesNM`, `nFracCompsSpm`, `nFormsNM`,
  `nExtraStatesNM`, `nSoilLayers`, `nSedimentLayers`
- Distributions: `d_spm`, `d_spm_low`, `d_spm_upp`, `d_nm`,
  `sedimentParticleDensities`, `defaultDistributionSediment`, `defaultDistributionNP`
- Namelists owned: `/allocatable_array_sizes/`, `/nanomaterial/`, and the size-class
  portion of `/sediment/`
- The `d_spm_low`/`d_spm_upp` derivation logic (currently
  [src/GlobalsModule.f90:404-421](../src/GlobalsModule.f90#L404-L421))

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
| **WaterBody** (`src/WaterBody/`) | `minStreamSlope`, `minEstuaryTimestep`, `includeEstuary`, `includeBankErosion` | `defaultSlope`, `defaultBankErosionAlpha/Beta`, `defaultMin/MaxWaterTemperature`, `defaultMinWaterTemperatureDayOfYear` | 401–404, 500–501; 405 intended but currently dropped | `/water/` |
| **BedSediment** (`src/BedSediment/`) | `includeBedSediment`, `sedimentLayerDepth` | `defaultDepositionAlpha/Beta`, `defaultSedimentTransport_a/b/c`, `defaultSedimentEnrichment_k/a` | 904 | `/sediment/` (non-dimension part) |
| **Reactor** (`src/Reactor/`) | — | `default_k_diss_pristine/transformed`, `default_k_transform_pristine`, `defaultShearRate`, `T` | 903 | (none yet) |
| **Biota** (`src/Biota/`) | — | — | 902 | (none yet) |

> Note: dimension *counts* (`nSoilLayers`, `nSedimentLayers`) live in model-dimensions
> because they shape arrays across domains and in checkpoint; the *depths*
> (`soilLayerDepth`, `sedimentLayerDepth`) belong to the owning domain, which reads
> the count from model-dimensions to allocate.
>
> There are two unrelated namelist groups both named `/soil/`. The group in
> `config.nml` contains layer depths and four runtime switches and is owned by
> `SoilConfigModule`. The group in the separate constants file contains Darcy
> velocity, attachment efficiency, and other input values; `DataInputModule` still
> reads that group. The two default-real fallback constants move to
> `SoilConfigModule` as public module constants so `DataInputModule` can use them,
> but the constants-file reading order and assignments do not move.
>
> Sediment defaults also cross input-group boundaries. `BedSedimentConfigModule`
> now owns the seven transport, enrichment, and deposition fallback constants.
> `DataInputModule` still reads their values from the separate constants-file
> `/soil/`, `/sediment/`, and `/water/` groups respectively. All seven constants
> remain `real(dp)`, while the existing local deposition buffers remain default
> `real`. Neither those conversions nor spatial input overrides change in Phase 6.
>
> Error ownership in this table is conditional and provisional. Restoring code 405 to
> WaterBody would change current diagnostic behaviour and is therefore deferred. Code
> 901 must not be moved into BedSediment merely because the legacy array places it
> nearby; its message refers to RiverReach. Codes 110, 200, 201, and 300 also need
> explicit ownership decisions in the separately tested registry-correction phase.

### Model assembly / builder (`src/ModelAssembly/` — proposed)

Owns **construction and wiring**, not config data. What moves here:

- The grid-instantiation loop and cell/reach/soil-profile construction currently in
  `createEnvironment` ([EnvironmentModule.f90:47-67](../src/Environment/EnvironmentModule.f90#L47-L67))
  and `createGridCell` ([GridCellModule.f90:74-126](../src/GridCell/GridCellModule.f90#L74-L126)).
- The **cross-cell topology wiring**: inflow/outflow pointer linking, headwater and
  tidal-limit detection ([EnvironmentModule.f90:69-113](../src/Environment/EnvironmentModule.f90#L69-L113)).
- `finaliseCreate` work that needs full cell linking, e.g. snapping point sources to
  cells ([EnvironmentModule.f90:115-122](../src/Environment/EnvironmentModule.f90#L115-L122)).
- Stream-order determination (`determineStreamOrder`,
  [EnvironmentModule.f90:124-126](../src/Environment/EnvironmentModule.f90#L124-L126),
  253-312) and `routedReaches` / `headwaters` allocation.

What **stays** with each type (thin `init`, not moved): allocation of an object's own
arrays and setting of its own defaults — e.g. the per-timestep mean arrays at
[EnvironmentModule.f90:130-137](../src/Environment/EnvironmentModule.f90#L130-L137) stay
local. Dependencies: `ModelAssembly` `use`s the concrete domain types and `DATASET`;
nothing `use`s `ModelAssembly` except the bootstrap.

---

## 5. Transition strategy: the facade shim (keep the build green)

The blocker for "incremental" is that `C` is a module singleton referenced 490+ times.
We cannot edit all call sites at once. Strategy:

1. Build new layers/modules as **pure additions** that become the source of truth.
2. Keep `type(GlobalsType) :: C` alive as a **facade**: during the private bootstrap
   facade synchronisation, populate the old `C%…` fields *from* the new modules (or
   make them pointers).
3. Migrate call sites **one domain at a time** from `C%foo` to the new module's
   accessor. Untouched domains keep reading `C%foo` and keep compiling.
4. After domain phases, migrate the remaining cross-cutting facade readers. When `C`
   has no remaining readers, **delete it**. By then every error with an agreed owner
   has already moved during that owner's phase; final cleanup only removes an empty
   legacy registry and must not be used to change diagnostic behaviour.

This means `LoggerModule` and most checkpoint state keep reading `C%…` until their
owning layers are migrated. The error registry moved to `ErrorHandlingModule` in
Phase 4. The Phase 1 exception is deliberate:
`CheckpointModule` may read dimension fields directly from `ModelDimensionsModule`,
while keeping `C` for non-dimension state such as `epsilon`, `t0`, and error handling.
Phase 2 adds `ModelConfigModule` as the source of truth for model-level config, while
`C` remains a facade. Runtime-mutated model config (`inputFile`, `constantsFile`,
`nTimeSteps`, `startDate`, `t0`) must be changed through `ModelConfigModule` helpers
and mirrored back into `C` until all readers migrate.

Phase 4 introduced `ErrorHandlingModule` before any error-owning domain phase and made
it the sole owner of `ERROR_HANDLER`. `GlobalsModule` temporarily re-exports that
singleton for untouched consumers. The bootstrap order is: initialise model
dimensions as needed for allocation, initialise `ModelConfig`, initialise the shared
handler from the model-level diagnostics controls, then initialise domain configs and
register their owned errors. Phase 6 places Soil initialisation immediately after the
handler, then BedSediment initialisation, the remaining legacy Water read, and the
model audit. This preserves the later domain-read order. It is not the complete
startup failure order: model-dimensions already reads the full `/sediment/` group
before Soil, so missing or malformed sediment input can fail at that earlier read.
There must never be both a Globals-owned and diagnostics-owned handler.

During the Soil error handoff, the legacy array shrank from 17 entries to 16. Codes
901–904 shifted to slots 13–16; the two blank slots at 4–5 and the overwritten slot 11
were deliberately preserved. At that stage the shared handler alone gave 25 effective
entries and Soil registration brought the count to 26. Phase 6 removes code 904 from
the legacy array, reducing it to 15 slots and 24 effective base entries. Soil adds
code 600 to reach 25; BedSediment adds the unchanged critical code 904 to reach 26.
Codes 901–903 remain in slots 13–15. Correcting the old blank and overwritten entries
remains a separate behaviour-change phase.

### Namelist read-order coupling (must preserve)
Today `/allocatable_array_sizes/` is read first because its counts size the
allocatable arrays read by `/soil/`, `/sediment/`, `/nanomaterial/`
([src/GlobalsModule.f90:280-302](../src/GlobalsModule.f90#L280-L302)). After migration:
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

Phase 6 keeps that early dimension read. `BedSedimentConfigModule` declares the same
four group members, with local size-class and density buffers, but stores only the
layer depths and bed-sediment switch. There are therefore two configuration-file
readers and the separate, unchanged constants-file sediment reader. A missing-group
test of the BedSediment reader must load dimensions from a valid fixture first;
otherwise an earlier failure would not test the new reader.

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
    ! Dependency-free ANSI colors and IO-unit policy live here too.
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
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: SoilConfigType, soilConfig
    public :: defaultSoilAttachmentEfficiency, defaultSoilDarcyVelocity

    real, parameter :: defaultSoilAttachmentEfficiency = 0.0
    real, parameter :: defaultSoilDarcyVelocity = 9e-6_dp

    type :: SoilConfigType
        real, allocatable :: soilLayerDepth(:)
        logical :: includeBioturbation, includeAttachment
        logical :: includeSoilErosion, includeClayEnrichment
    contains
        procedure :: init => initSoilConfig
    end type
    type(SoilConfigType) :: soilConfig
contains
    subroutine initSoilConfig(me, configFilePath)
        class(SoilConfigType), intent(inout) :: me
        character(*), intent(in) :: configFilePath
        integer :: iou
        real, allocatable :: soil_layer_depth(:)
        logical :: include_bioturbation, include_attachment
        logical :: include_soil_erosion, include_clay_enrichment
        namelist /soil/ soil_layer_depth, include_bioturbation, &
            include_attachment, include_clay_enrichment, include_soil_erosion

        ! These are the only existing optional defaults. Executable assignments are
        ! required so every call starts cleanly; initialized local variables retain
        ! their values between calls in Fortran.
        include_clay_enrichment = .false.
        include_soil_erosion = .true.

        allocate(soil_layer_depth(nSoilLayers))
        open(newunit=iou, file=configFilePath, status="old")
        read(iou, nml=soil); close(iou)
        me%soilLayerDepth = soil_layer_depth
        me%includeBioturbation = include_bioturbation
        me%includeAttachment = include_attachment
        me%includeClayEnrichment = include_clay_enrichment
        me%includeSoilErosion = include_soil_erosion

        call ERROR_HANDLER%add(error=ErrorInstance(code=600, &
            message="All water removed from SoilLayer.", isCritical=.false.))
    end subroutine
end module
```

Depth, bioturbation, and attachment are required because they were required before
the migration. The example deliberately invents no defaults, audit, or validation.
The depths and both fallback constants remain default `real`, matching the existing
calculations and exact output formatting.

### Bootstrap (orchestration only)
```fortran
subroutine bootstrap(env)
    type(Environment), target, intent(inout) :: env
    type(Result) :: rslt, auditResult
    ! Resolve configFilePath and optional batchRunFilePath from command-line arguments.
    call initModelDimensions(configFilePath) ! reads /allocatable_array_sizes/, /nanomaterial/ first
    call modelConfig%init(configFilePath)     ! pass batchRunFilePath when present
    call initErrorHandling(modelConfig%triggerWarnings, modelConfig%errorOutput)
    call soilConfig%init(configFilePath)      ! reads config /soil/ and registers code 600
    call bedSedimentConfig%init(configFilePath) ! reads config /sediment/ and registers code 904
    call initLegacyGlobalsFacade(configFilePath) ! remaining Water read and facade copies
    auditResult = modelConfig%audit()
    call ERROR_HANDLER%trigger(errors=.errors.auditResult)
    call sourceConfig%init(configFilePath)
    ! Future owner-domain initialisers are added after the handler in their required order.
    call LOGR%init(...)
    call printWelcome()
    call DATASET%init(modelConfig%inputFile, modelConfig%constantsFile)
    ! Only AFTER all config is loaded: build and wire the object graph
    rslt = buildEnvironment(env)            ! function: instantiate + wire, reads DATASET
    call LOGR%toFile(errors=.errors.rslt)
    call ERROR_HANDLER%trigger(errors=.errors.rslt)
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
    function buildEnvironment(env) result(r)
        type(Environment), target, intent(inout) :: env
        type(Result) :: r
        ! 1. instantiate the grid + cells (+ their reaches / soil profiles)
        ! 2. wire topology: inflow/outflow pointers, headwaters, tidal limits
        ! 3. finalise: snap point sources, determine stream order, allocate routedReaches
        ! (the body is the construction code lifted out of createEnvironment /
        !  createGridCell — see §4 "Model assembly / builder")
    end function
end module
```

---

## 7. Phased execution (each phase = one reviewable PR)

Implementation status: Phases 0, 1, 2, B, 3, 4, 5, and 6 are complete. Their authoritative
records are [phase0_kernel.md](phase0_kernel.md),
[phase1_model_dimensions.md](phase1_model_dimensions.md),
[phase2_model_config.md](phase2_model_config.md), and
[phaseB_builder_extraction.md](phaseB_builder_extraction.md), plus
[phase3_source.md](phase3_source.md) and
[phase4_bootstrap_diagnostics.md](phase4_bootstrap_diagnostics.md), and
[phase5_soil.md](phase5_soil.md), plus
[phase6_bed_sediment.md](phase6_bed_sediment.md). Remaining execution starts with
Phase 7 WaterBody.

### Phase 0 — Kernel (pure addition, no behaviour change)
- Create `KernelModule` with `dp`, physical constants, water-physics functions,
  and dependency-free IO/color utilities.
- Replace the duplicate `dp` in `DefaultsModule.f90:7` and `GlobalsModule.f90:13`
  with `use KernelModule, only: dp`.
- Leave `C%rho_w` etc. as thin forwarders to kernel functions (don't touch call
  sites yet).
- Keep `ERROR_HANDLER` and logger state in their existing locations; they are not
  pure-kernel responsibilities.
- **Verify:** full build + `verify_refactor.py --exact`.

### Phase 1 — Model-dimensions
- Create `ModelDimensionsModule` owning `npDim`, size classes, counts, distributions,
  and the `/allocatable_array_sizes/` + `/nanomaterial/` reads + `d_spm_*` derivation.
- `GLOBALS_INIT` delegates dimension setup to it, then **copies** values back into `C`
  (facade) so the 490 `C%npDim` readers are untouched.
- Repoint only `CheckpointModule`'s dimension-shaped reads to `use ModelDimensionsModule`;
  it keeps `C` for non-dimension state such as `epsilon`, `t0`, and error handling.
- **Verify:** build + `verify_refactor.py --exact`; checkpoint save/reinstate smoke test
  runs, with exact round-trip comparison deferred until the existing warm-up/reinstate
  run-control semantics are separated.

### Phase 2 — Slim model module + facade wiring
- Create `ModelConfigModule` owning run/output/checkpoint/steady-state/batch/data-path
  config and their namelist reads.
- `GLOBALS_INIT` delegates these reads to it, copies back into `C` (facade).
- Move model-level config audits ([src/GlobalsModule.f90:474-507](../src/GlobalsModule.f90#L474-L507))
  into `ModelConfig%audit`, returning a `Result` so `ModelConfigModule` does not
  depend on `GlobalsModule`/`ERROR_HANDLER`.
- Keep domain namelist reads (`/soil/`, `/sediment/`, `/water/`, `/sources/`) in
  `GLOBALS_INIT` until the corresponding domain phases migrate them.
- Route batch chunk selection and checkpoint-preserved `t0` through `ModelConfigModule`
  and mirror those runtime values back into `C`.
- **Verify:** build + `verify_refactor.py --exact`.

### Phase B — Builder extraction (parallel workstream, after Phases 1-2)
This is the §3b construction-vs-behaviour axis, independent of the per-domain config
phases below. It can run in parallel once `ModelDimensions` + `ModelConfig` exist.
- Create `ModelAssemblyModule` with `buildEnvironment(env)`.
- **Move** (don't rewrite) the construction + topology code out of `createEnvironment`
  and `createGridCell`/`createReaches` into the builder: grid/cell/reach/soil
  instantiation, inflow/outflow wiring, headwater & tidal-limit detection,
  `determineStreamOrder`, `routedReaches`/`headwaters` allocation (see §4
  "Model assembly / builder" for exact line ranges).
- `ModelAssemblyModule` owns the startup call order for point-source snapping by calling
  `GridCell%finaliseCreate()` after topology wiring, but `snapPointSourcesToReach`
  stays on `GridCell` because batch updates re-snap point sources after input data
  changes.
- **Keep** thin per-object self-`init` on each type (own-array allocation, own
  defaults). Do not over-split trivial allocation. `Environment%create` and
  `GridCell%create` stay as compatibility methods for the existing abstract contracts.
- **Preserve legacy construction error handling in Phase B.** Builder helpers that
  move code out of `create` methods may still log, trigger, and clear their local
  `Result` objects before returning, matching the old behavior where construction
  errors were reported locally and not propagated back to `main`. Do not treat
  `buildEnvironment`'s returned `Result` as a complete aggregate of every child
  construction error until the later error/log ownership migration removes those
  local trigger/clear side effects.
- `main.f90` calls `buildEnvironment(env)` after config init instead of `env%create()`;
  `createEnvironment` shrinks to environment-owned summary-array initialisation.
- Remove `determineStreamOrder` from the `AbstractEnvironment`/`Environment`
  type-bound interface once it becomes a private builder helper.
- Optional: use submodules to split a type's setup vs science methods into separate
  files where it aids readability.
- **Verify:** build + `verify_refactor.py --exact` — construction is
  behaviour-preserving; only the *location* of the code changes, not the order of
  operations.

### Phase 3 — Source (smallest domain slice; complete)
- Create `SourceConfigModule`, move ownership of `/sources/` and
  `includePointSources`, and initialise it from the transitional bootstrap in
  `main.f90` after `GLOBALS_INIT`.
- Relocate the existing `!! Should point sources be included?` comment with the field
  verbatim; preserve all other Source comments and TODOs.
- Remove the Source facade field and migrate every repo-wide consumer of that field,
  not only files physically under `src/Source/`.
- Repoint Source's dimension, precision, run-control, NetCDF-fill, and dataset imports
  to their explicit owning modules without changing parsing, construction, snapping,
  warm-up, or flux behaviour.
- Source has no assigned error codes. This phase proves namelist ownership, facade
  field removal, and explicit one-way dependency wiring; it does **not** prove error
  ownership end-to-end and does not add an artificial `AbstractSource` interface.
- **Verify:** enabled- and disabled-point-source comparisons with
  `verify_refactor.py --exact`, plus the existing batch and checkpoint
  save/reinstate smoke tests.

### Phase 4 — Bootstrap and diagnostics infrastructure gate (complete)
- Introduce `BootstrapModule` with one public startup routine and make `main.f90` call
  it instead of invoking `GLOBALS_INIT` and individual domain config initialisers.
  Bootstrap owns command-line config-path resolution and the complete initialisation
  order; remaining facade synchronisation and legacy namelist reads are private
  `BootstrapModule` transitional helpers until their owner phases remove them.
- Introduce `ErrorHandlingModule` as the sole owner of the criteria-capable
  `type(ErrorCriteria) :: ERROR_HANDLER`; keep the dependency-free kernel free of
  FEH state.
- Temporarily import and publicly re-export that singleton from `GlobalsModule` for
  untouched consumers.
- Establish the bootstrap order: model dimensions where allocation requires them →
  `ModelConfig` → shared handler initialisation → domain config/error registration →
  object assembly.
- Preserve the remaining legacy error registry exactly during this infrastructure
  move. Domain registration uses the valid FEH generic form
  `call ERROR_HANDLER%add(error=ErrorInstance(...))`.
- **Verify:** build, `verify_refactor.py --exact`, and diagnostic startup/error smoke
  tests. This gate passed before Soil starts; see
  [phase4_bootstrap_diagnostics.md](phase4_bootstrap_diagnostics.md).

### Phase 5 — Soil (complete)
- Create `SoilConfigModule` and move the config-file `/soil/` group, its five fields,
  and the two Soil fallback constants to it. Layer depth, bioturbation, and attachment
  remain required. Only clay enrichment (false) and soil erosion (true) have defaults.
- Keep layer depth and both constants as default `real`; add no new audit or
  validation. `DataInputModule` continues to read the separate constants-file
  `/soil/` group using the public fallback constants from `SoilConfigModule`.
- Initialise Soil after the shared handler, then register code 600 with its unchanged
  message and warning status. Shrink and shift the legacy array without repairing its
  two blank entries or missing code 405.
- Remove the five Soil fields from `C` and repoint all four Soil science files to the
  owning modules. Public types, procedure bindings and arguments, array shapes,
  calculation order, batch behaviour, and every original comment remain unchanged.
- This removes Soil's direct use of the global `C` object, but it does not make Soil
  fully independent: the science still calls Biota and input-data code.
- Track [verification/README.md](../verification/README.md) and
  [verification/verify_refactor.py](../verification/verify_refactor.py). Exact tests
  cover every Soil switch, both optional defaults, the constants fallback path,
  missing `/soil/`, batch operation, and checkpoint save/reinstate. See
  [phase5_soil.md](phase5_soil.md) for commands and actual results.

### Phase 6 — BedSediment (complete)
- Added `BedSedimentConfigModule` with default-real layer depths, the bed-sediment
  switch, seven unchanged sediment fallback constants, and registration of code 904.
  No new defaults or validation were added for the two settings.
- Kept all four configuration `/sediment/` members in the domain reader, using local
  buffers for values owned by model-dimensions. The earlier dimension read and all
  constants-file reads remain unchanged.
- Removed the two fields from `C`, migrated all five sediment science modules and
  every external consumer, and retained all original comments verbatim. GridCell now
  also imports the shared error handler directly from its owner.
- Kept inline construction errors and the known river-disabled failure unchanged.
  Code 904 has no current sediment raising site; the focused tests check its
  registration without adding one.
- **Verified:** five CTest cases, seven exact output comparisons, missing-group and
  construction-error checks, the known river-disabled failure, batch operation, and
  checkpoint save/reinstate. See [phase6_bed_sediment.md](phase6_bed_sediment.md) for
  actual commands, results, original-comment checks, and remaining work.

### Phase 7 — WaterBody (next)
- Migrate river and estuary settings after BedSediment because WaterBody consumes the
  bed-sediment switch. Keep the missing code 405 deferred to the registry-correction
  phase.

### Phase 8 — Reactor
- Migrate the water-column Reactor defaults and its assigned error without changing
  reaction calculations.

### Phase 9 — Biota
- Migrate Biota last, including the existing Soil-to-Biota relationship, without
  redesigning the science interfaces during the ownership move.

Each domain phase follows the **per-domain checklist** (§8), including migration of
all repository consumers of the domain's fields. Errors move only when that domain
has assigned codes; a domain without assigned errors skips error registration.

### Cross-cutting facade-consumer phase
- Run this after Phase 9. Migrate the remaining global `C` readers before attempting
  final removal of the compatibility object.
- Migrate the remaining `ModelConfig` and `ModelDimensions` facade readers in
  GridCell, Data, Output, Logger, Util, Checkpoint, and any other repo-wide consumer.
- Input/output algorithms remain unchanged, but their imports of configuration and
  dimensions are in scope and must point to the owning modules.
- Verify that only the intentionally retained legacy registry/bootstrap shim still
  requires `GlobalsModule`.

### Separate diagnostic-registry correction phase (behaviour change)
- Add focused tests that capture the intended diagnostics, then correct the two
  unassigned `errors(4:5)` entries, the overwritten code 405 at `errors(11)`, and the
  incorrect association of code 901 with BedSediment.
- Determine explicit owners for codes 110, 200, 201, and 300 from their raising sites,
  then move them to those owners. Do not bundle these behaviour changes into a pure
  config/domain refactor.
- Re-run exact valid-config regression tests and dedicated error-path assertions;
  valid scientific output remains unchanged while the corrected diagnostics are
  intentionally different.

### Separate build-system cleanup
- Stop CMake configuration from rewriting the tracked `src/VersionModule.f90` in a
  normal source checkout. Until then, each migration phase must use the tracked-file
  gate in §9.
- Test this separately from science-domain migrations so a version-generation change
  cannot hide a model-output change.

### Separate river-disabled behaviour correction
- Define what disabling bed sediment should do to deposition, resuspension,
  nanomaterial transfers, and reach water-depth changes. Fixing only the unset
  deposit-result read would not address all current river operations.
- Add focused river-enabled and river-disabled tests before changing the behaviour.
  Keep this work separate from the domain migrations; Phase 6 deliberately retains
  the existing river-disabled failure as a negative test.

### Final phase — Cleanup
- Remove the legacy flat registry only after all of its valid entries have moved in
  their owning phases and the separate registry-correction phase has resolved the
  malformed/unowned entries. Final cleanup must see an empty registry and must not
  change error behaviour.
- Move remaining log messages to domain code (most are already inline).
- Delete `type(GlobalsType) :: C` and the remaining transitional bootstrap facade
  helpers once no readers remain. `GLOBALS_INIT` was removed in Phase 4.
- Delete migrated parameters from `DefaultsModule` (keep only IO units there, or fold
  into kernel).
- **Verify:** build + `verify_refactor.py --exact`; grep confirms zero `C%` /
  `use GlobalsModule`.

Every phase adds a plain-language file in `migration_documentation/` recording what
was implemented, actual verification commands and results, preserved public behaviour
and original comments, and the exact work left. Define unavoidable code terms when
they first appear. Earlier records are historical snapshots: do not rewrite their
"work left" sections after later phases finish.

---

## 8. Per-domain migration checklist (repeatable recipe)

For domain `X`:

1. **Create `XConfigModule`** in `src/X/`: a `XConfigType` with the domain's config
   fields + a `type(XConfigType) :: xConfig` singleton.
2. **Move existing defaults** into the domain without inventing new ones. Keep their
   declared kinds and values. Science constants become module `parameter`s. For local
   namelist variables, use executable assignments on every call: declaration
   initialisation gives a Fortran local variable saved state and can leak values from
   an earlier call. Delete the moved values from `DefaultsModule`.
3. **Own the namelist:** declare `namelist /x/ …` inside `XConfig%init`, open
   `config.nml` with `newunit`, allocate arrays before reading, read, populate, and
   `close`. Distinguish a config-file group from any same-named group in another input
   file; move only the group the domain currently owns.
4. **Move existing audits only:** if `C%audit` already contains domain-specific
   checks, move them into `XConfig%audit`. Do not create new validation merely to fit
   the module template.
5. **Register errors conditionally:** only if X has assigned codes, call
   `ERROR_HANDLER%add(error=ErrorInstance(code=…, …))` in `XConfig%init` after the
   shared handler is initialised, and remove exactly those entries from the legacy
   registry. A domain with no assigned codes skips this step. Preserve existing
   trigger/clear/propagation semantics; redesigning diagnostic flow is separate from
   this pure refactor.
6. **Repoint every consumer:** across the repository, not just under `src/X/`, replace
   reads of X-owned facade fields with `XConfigModule`; use `KernelModule`,
   `ModelDimensionsModule`, or `ModelConfigModule` for values owned by those layers.
   Domain-to-domain imports must be explicit, one-way, and acyclic.
7. **Update bootstrap:** add `call xConfig%init(configFilePath)` in the right order.
8. **Drop facade fields:** remove domain fields from `GlobalsType` and the private
   bootstrap facade helper once no other code reads them (grep `C%fieldName`).
9. **Preserve comments:** retain every original code comment and TODO verbatim where
   its code remains; when ownership moves, relocate the associated comment without
   paraphrasing or dropping it.
10. **Verify:** build + `verify_refactor.py --exact` produces identical output (§9).
    Prove each focused variant actually exercises the branch it is meant to test, and
    run focused error/config tests plus the relevant checkpoint and batch paths.
11. **Document:** add `migration_documentation/phaseX_<domain>.md` in plain language,
    define unavoidable code terms, list actual commands and results, state preserved
    APIs/behaviour/comments, and give an explicit list of what remains.

---

## 9. Verification strategy

- **Build gate:** the project build must pass after every phase. The facade keeps the
  build green between phases.
- **Regression gate:** keep one canonical config + input dataset. After each phase,
  run `verify_refactor.py --exact` against a fresh pre-phase baseline. Output must be
  **exactly identical** — this is a pure refactor, no science changes. In exact mode,
  each CSV file is byte-for-byte identical, `summary.md` matches after removing only
  its `Simulation datetime` line, and `ncdump` text matches after removing only the
  NetCDF `history` field. Raw NetCDF bytes need not match because that metadata is
  time-dependent. Add focused scenario variants when a touched flag has
  enabled/disabled behaviour, and confirm before editing that each variant changes
  relevant output.
- **Known failing scenarios:** record and compare the existing exit status and
  meaningful error text instead of claiming a successful output comparison. In
  Phase 6 this applies to rivers with bed sediment disabled. Estuary enabled/disabled
  runs succeed and remain subject to exact output comparisons.
- **Default-value coverage:** establish whether a value comes from its fallback,
  constants file, or spatial input. Test the applicable paths without accidentally
  hiding a moved default behind a spatial override. Preserve existing number kinds
  and conversions as well as the parameter values.
- **Focused config/error gate:** test existing required values and defaults in a
  separate process where shared singleton state requires it. Check both the base
  registry and the count after domain registration.
- **Checkpoint smoke gate:** run the existing checkpoint save/reinstate smoke path
  after relevant phases. Exact continuation equivalence remains unresolved because
  warm-up/reinstate run-control semantics have not yet been separated; do not report
  the smoke test as proof of checkpoint continuation correctness.
- **Batch smoke gate:** run the existing batch path whenever assembly, source snapping,
  config paths, or runtime-mutated model config are touched.
- **Tracked-file gate:** some CMake configurations rewrite tracked
  `src/VersionModule.f90`. Save its content and hash before configuration. If CMake
  rewrites it, restore the exact content, rebuild without configuring again, and
  confirm the hash and regression results. Correcting this build-system mutation is a
  separate cleanup task.
- **Grep gates** (final phase): `grep -rn "use GlobalsModule" src` → 0;
  `grep -rn "C%" src` → 0.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 490 `C%npDim` readers can't change at once | Facade shim — `C` stays populated until the last domain migrates |
| Namelist read-order coupling (`allocatable_array_sizes` first) | Model-dimensions reads sizes in Phase 1, before any domain init; bootstrap enforces order |
| IO-unit collisions when domains read independently | Use `open(newunit=…)`; retire the central `iou*` registry |
| Malformed/unowned legacy registry entries carried into domains | Preserve them during pure refactors; fix `errors(4:5)`, duplicate `errors(11)`, code 901, and unowned 110/200/201/300 only in the separately tested diagnostic phase |
| Silent behaviour change during refactor | `verify_refactor.py --exact` regression gate after every phase |
| Checkpoint depends on dimensions | It reads *only* dimensions (verified); repointed once in Phase 1. Save/reinstate remains a smoke test until continuation semantics receive a dedicated test |
| Layer-depth vs count split (soil/sediment) | Counts → model-dimensions; depths → domain, which queries the count to allocate |
| Builder must `use` concrete domain types (reverse arrow) | Builder is a *top* layer (above domains); nothing below depends on it, so no cycle — see §3b |
| Source is consumed by GridCell/WaterBody | Allow the explicit one-way dependency onto lower-level Source; forbid the reverse edge and defer speculative `AbstractSource`/DI work |
| Construction reorder could change results | Phase B *moves* code without changing operation order; byte-identical regression gate catches any drift |

---

## 11. Out of scope

- Changes to input parsing and output-writing algorithms (`src/Data/`,
  `DataInputModule`, `DataOutputModule`) — these are not part of the model-engine
  refactor. Their imports and reads of migrated config/dimension fields **are** in
  scope and must be repointed repo-wide to the owning modules.
- Any science/algorithm change. This migration is behaviour-preserving — including the
  builder extraction (§3b / Phase B), which relocates construction code without
  altering the order of operations.
- Correcting the known legacy diagnostic-registry defects during a config/domain
  phase. Those corrections are a separately tested behaviour-change phase (§7).
- Correcting the existing river-disabled bed-sediment failure during a domain
  migration. Its complete behaviour needs a separate fix and dedicated tests (§7).
- Proving exact checkpoint continuation while the existing warm-up/reinstate
  run-control semantics remain coupled; current checkpoint coverage is a smoke test.
- Introducing Source dependency injection or a new `AbstractSource` interface. The
  current explicit one-way Source dependency is acceptable and acyclic.
- Generalising the contaminant-specific accessor interfaces on the spatial containers
  (`get_C_np_water`, `get_j_nm_*` on `AbstractGridCell` / `AbstractEnvironment`) so the
  grid/environment become agnostic to the modelled stressor. This is a larger, more
  speculative refactor worth doing only once a concrete second science scenario exists
  to design against; it is noted here so it is not confused with the config or builder
  work, but is deferred.
