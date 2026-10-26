# NanoFASE Model Engine — Modularisation Migration Plan

Current status: Phases 0–14 and Phase B are complete. The ownership migration and
version-length correction are finished; scientific repairs remain separate work.
Earlier architecture examples describe the migration stages, not code to restore.
See the phase records in §7 for implemented behavior and actual verification.

## 1. Goal

Make the NanoFASE **model engine** (simulation code, not input pre-processing or
output post-processing) modular and decoupled along science-domain lines, so each
domain is self-contained and different teams can work in parallel without colliding.

**Self-contained per domain** means each domain directory owns:

1. **Config** — where a domain has settings in `config.nml`, its own config module
   reads that existing group directly (for example, `namelist /soil/ …`). A domain
   without such settings does not need a configuration object or a new input group.
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
- The original flat error registry had several issues preserved through Phase 10:
  - `errors(4)` and `errors(5)` are never assigned and therefore behave as blank
    code-1 `ErrorInstance`s.
  - `errors(11)` was assigned twice, silently dropping code 405.
  - codes 110, 200, 201, 300, and 901 had no agreed target owners.
  Phase 11 restores 405 and assigns 901 to WaterBody. Codes 110/200/201/300 stay
  shared. By explicit agreement, slots 4 and 5 and their blank critical code-1
  message stay unchanged; they are an accepted compatibility choice, not unused
  space that cleanup may silently remove.
- `CheckpointModule.f90` uses shared dimension fields (`npDim` ×66,
  `nSedimentLayers` ×14, `nSizeClassesSpm` ×18, `nSoilLayers` ×10, `nFracCompsSpm` ×4)
  to shape its arrays. It also reads model-wide state such as `epsilon` and the
  preserved timestep; it does not own per-domain configuration flags.
- The FEH generic already supports incremental registration. The unambiguous form for
  one domain error is
  `call ERROR_HANDLER%add(error=ErrorInstance(code=..., ...))`
  ([vendor/feh/src/ErrorHandler.f90:31-34](../vendor/feh/src/ErrorHandler.f90#L31-L34)).
- Phase 6 investigation confirmed an existing river failure when
  `include_bed_sediment = .false.`: `depositToBedReach` skips deposition but still
  reads the unset deposit result. River resuspension and nanomaterial transfers also
  remain outside that switch. Phase 6 preserves this behaviour and tests the known
  failure. A separate fix must define and test the complete river-disabled behaviour.
- Phase 7 confirmed a separate terrain-height failure: adding a flat `dem` array to
  the shipped river example causes an out-of-bounds terrain read at the model outlet
  in `setReachLengthAndSlopeReach`. The shipped river and estuary examples have no
  `dem`, so their ordinary runs do not exercise `minStreamSlope`. Phase 7 preserves
  the outlet failure and tests the slope procedure directly on an interior reach.
  Repairing terrain access at outlets remains a separate behaviour change.
- Phase 8 investigation reproduced a Reactor mass-loss defect when particles attach
  to suspended sediment. The loop repeatedly scales the same temporary mass while
  distributing it between sediment size classes. With two equal rates, pristine mass
  falls from 100 to 75 and transformed mass from 50 to 37.5, although this operation
  should only redistribute mass. Preserve these current results during migration;
  correct the calculation in a separate, tested science change.
- The shipped constants examples explicitly set all three water reaction rates to
  zero. Ordinary example runs therefore cannot prove that active dissolution and
  transformation have been preserved. Reactor verification must include nonzero
  rates and omitted defaults.
- The shipped constants examples contain no Biota groups, and ordinary model output
  does not report organism concentrations. Phase 9 therefore checks concentrations
  directly and through the running model; ordinary output comparisons alone cannot
  establish that Biota calculations have been preserved.
- Biota's current harvest calendar advances one day per timestep even when the
  timestep is shorter than a day, and resets concentrations on every update in the
  selected month. An invalid uptake form records an error but continues using unset
  concentration sums. Phase 9 preserves these behaviours; unstable invalid-input
  numbers are not suitable reference expectations. Any correction needs separate tests.
- Checkpoints do not save or restore Biota concentrations. Exact continuation needs
  both the missing organism state and the already documented warm-up/reinstatement
  timing to be addressed. The main loop also starts at 1 and never reads restored
  `t0`; the older smoke test saves timestep zero. Phase 10 verifies nonzero stored
  timestep restoration, not correct continuation of the simulation.
- Phase 10 moved model-wide defaults into `ModelDefaultsModule`. `DefaultsModule`
  now exposes the same object for compatibility, with no duplicate values.
  Unused `C%T` stays for final cleanup; actual water temperatures come from input
  data, not this field.
- Phase 10 confirmed that compartment statistics currently creates an empty CSV:
  its writer is a commented-out stub. Preserve that result during migration.
- Some unused reach positions in checkpoint arrays are never initialised. Compare
  record layout and all values for existing reaches; raw checkpoint bytes are not
  a stable reference. Initialising these unused positions is separate cleanup.

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
- The shared list retains codes 110, 200, 201, and 300. They describe general input,
  file, and numerical errors and have no current production raising sites. Keeping
  them shared preserves their availability without inventing new domain checks.
- Positions 4 and 5 deliberately retain blank critical code-1 instances. The error
  library combines them into one registered code-1 entry and replaces its normal
  generic message with blank text. Final cleanup must preserve this agreed behavior.

### Model-dimensions (`src/ModelDimensions/` — proposed)
- `npDim` (unused `ionicDim` was removed in Phase 13)
- Counts: `nSizeClassesSpm`, `nSizeClassesNM`, `nFracCompsSpm`, `nFormsNM`,
  `nExtraStatesNM`, `nSoilLayers`, `nSedimentLayers`
- Distributions: `d_spm`, `d_spm_low`, `d_spm_upp`, `d_nm`,
  `sedimentParticleDensities`. Unused `defaultDistributionSediment` and
  `defaultDistributionNP` were removed in Phase 13 rather than moved.
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
| **WaterBody** (`src/WaterBody/`) | `minStreamSlope`, `minEstuaryTimestep`, `includeEstuary`, `includeBankErosion` | `defaultSlope`, `defaultBankErosionAlpha/Beta`, `defaultMin/MaxWaterTemperature`, `defaultMinWaterTemperatureDayOfYear` | 401–405, 500–501, 901 | `/water/` |
| **BedSediment** (`src/BedSediment/`) | `includeBedSediment`, `sedimentLayerDepth` | `defaultDepositionAlpha/Beta`, `defaultSedimentTransport_a/b/c`, `defaultSedimentEnrichment_k/a` | 904 | `/sediment/` (non-dimension part) |
| **Reactor** (`src/Reactor/`) | — | `default_k_diss_pristine/transformed`, `default_k_transform_pristine`, `defaultShearRate` | 903 | none |
| **Biota** (`src/Biota/`) | — | — | 902 | none in `config.nml`; constants-file groups stay in DataInput |

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
> Reactor owns four default-real constants and `registerReactorErrors()`, without a
> configuration object or file reader. DataInput continues to read reaction rates
> and shear from the separate constants-file `/water/` group. The rates remain
> double precision in the reader and stored data, while shear remains default real.
> The unused `C%T` field is deferred to final cleanup and is not a Reactor setting.
>
> Biota owns `registerBiotaErrors()` without a configuration object, fallback
> constants, or file reader. The existing `/n_biota_grp/` and `/biota/` groups belong
> to the separate constants file and remain read and stored by DataInput. Their
> absence in `config.nml` does not mean that organism inputs are absent from the model.
>
> Phase 11 settles the remaining error ownership separately from the domain moves.
> WaterBody owns restored warning 405 and critical error 901; the four general codes
> 110/200/201/300 remain in ErrorHandling. None of these six codes has a current
> production raising site. Registering 405 does not add a river-length check.

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
   has no remaining readers, **delete it**. Every error must have an agreed owner,
   but the shared error list does not need to be empty. Keep the approved shared
   codes and blank code-1 behavior; cleanup must not change diagnostics.

This means `LoggerModule` and most checkpoint state keep reading `C%…` until their
owning layers are migrated. The error registry moved to `ErrorHandlingModule` in
Phase 4. The Phase 1 exception is deliberate:
`CheckpointModule` may read dimension fields directly from `ModelDimensionsModule`,
while keeping `C` for non-dimension state such as `epsilon`, `t0`, and error handling.
Phase 2 adds `ModelConfigModule` as the source of truth for model-level config, while
`C` remains a facade. Runtime-mutated model config (`inputFile`, `constantsFile`,
`nTimeSteps`, `startDate`, `t0`) must be changed through `ModelConfigModule` helpers
and mirrored back into `C` until all readers migrate.

Phase 10 completed that reader migration. DataInput and Checkpoint still update
`modelConfig` through the same helpers, but no longer copy changes into `C`.
Bootstrap's startup copies and the unused runtime-copy helper remain for final
cleanup. Only Bootstrap imports Globals in production. The unchanged historical
Biota science test remains the explicit test exception so its Phase 8/9 comparisons
stay repeatable; new tests initialise only the real owners.

Phase 4 introduced `ErrorHandlingModule` before any error-owning domain phase and made
it the sole owner of `ERROR_HANDLER`. `GlobalsModule` temporarily re-exports that
singleton for untouched consumers. The bootstrap order is: initialise model
dimensions as needed for allocation, initialise `ModelConfig`, initialise the shared
handler from the model-level diagnostics controls, then initialise domain configs and
register their owned errors. Phase 7 places Soil initialisation immediately after the
handler, then BedSediment, model-config copying into `C`, WaterBody initialisation,
dimension copying into `C`, and the model audit. Phase 8 adds Reactor error
registration immediately after WaterBody initialisation. This preserves the later
domain-read order. Phase 9 registers Biota immediately after Reactor, before copying
dimensions. It is not the complete
startup failure order: model-dimensions already reads the full `/sediment/` group
before Soil, so missing or malformed sediment input can fail at that earlier read.
There must never be both a Globals-owned and diagnostics-owned handler.

The following handoff counts are historical records for Phases 5–9.
During the Soil error handoff, the legacy array shrank from 17 entries to 16. Codes
901–904 shifted to slots 13–16; the two blank slots at 4–5 and the overwritten slot 11
were deliberately preserved. At that stage the shared handler alone gave 25 effective
entries and Soil registration brought the count to 26. Phase 6 removes code 904 from
the legacy array, reducing it to 15 slots and 24 effective base entries. Soil adds
code 600 to reach 25; BedSediment adds the unchanged critical code 904 to reach 26.
At the end of Phase 6, codes 901–903 remained in slots 13–15.

Phase 7 moves the six effective WaterBody codes 401–404 and 500–501. At that stage the
legacy array has 9 slots, retaining blank slots 4–5 and codes 901–903 in slots 7–9. Effective
counts are 18 after shared-handler initialisation, 19 after Soil, 20 after
BedSediment, and 26 after WaterBody. The original 405-then-500 overwrite moves into
slot 5 of WaterBody's private six-entry list; only its final six entries are
registered. Removing only the old code-500 assignment would incorrectly restore
405. At that stage, deciding the blank-entry behavior and restoring missing 405
were deferred to a separate change.

Phase 8 removes only code 903 from the legacy list and registers it through Reactor.
At that stage the list has eight slots; blank slots 4–5 and codes 901–902 in slots 7–8 remain.
Effective counts are 17 after the shared handler, 18 after Soil, 19 after BedSediment,
25 after WaterBody, and 26 after Reactor. Code 903 has no current science raising
site; registration tests do not invent one.

Phase 9 removes only code 902 and registers it through Biota. The remaining list
has seven slots, retaining blank slots 4–5 and code 901 in slot 7. Effective counts
are 16 after the shared handler, 17 after Soil, 18 after BedSediment, 24 after
WaterBody, 25 after Reactor, and 26 after Biota. Code 902 has no current science
raising site; the existing inline invalid-uptake-form error remains unchanged.

Phase 11 leaves six positions in the shared array: codes 110/200/201 in positions
1–3, blank positions 4–5, and code 300 in position 6. WaterBody registers eight
entries: 401–405, 500–501, and 901. The effective counts are now 15 after the shared
handler, 16 after Soil, 17 after BedSediment, 25 after WaterBody, 26 after Reactor,
and 27 after Biota. Only restoring 405 increases the final count; moving 901 changes
when it becomes available. The blank code-1 message remains intentional.

The configuration-file `/water/` group and all four of its members are optional.
WaterBody owns their defaults and retains the original two-read/status-check logic.
Do not substitute the required Soil/BedSediment reading pattern. Even existing
malformed-input behaviour is retained: the invalid integer fixture at end of file
leaves defaults in place, while the same group followed by `/sources/` fails.
The unrelated constants-file `/water/` group continues to be read by DataInput;
WaterBody supplies its six moved fallback constants without changing input parsing.

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
    call syncModelConfigToGlobals()          ! temporary copies for older consumers
    call waterBodyConfig%init(configFilePath) ! optional config /water/ and six effective errors
    ! Phase 11: this same call now registers eight errors, including 405 and 901.
    call registerReactorErrors()             ! code 903; no Reactor config-file group
    call registerBiotaErrors()               ! code 902; constants-file inputs stay in DataInput
    call syncModelDimensionsToGlobals()      ! remaining dimension copies
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

Implementation status: Phases 0, 1, 2, B, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, and 14 are complete. Their authoritative
records are [phase0_kernel.md](phase0_kernel.md),
[phase1_model_dimensions.md](phase1_model_dimensions.md),
[phase2_model_config.md](phase2_model_config.md), and
[phaseB_builder_extraction.md](phaseB_builder_extraction.md), plus
[phase3_source.md](phase3_source.md) and
[phase4_bootstrap_diagnostics.md](phase4_bootstrap_diagnostics.md), and
[phase5_soil.md](phase5_soil.md), plus
[phase6_bed_sediment.md](phase6_bed_sediment.md), and
[phase7_waterbody.md](phase7_waterbody.md), and
[phase8_reactor.md](phase8_reactor.md), and
[phase9_biota.md](phase9_biota.md), and
[phase10_shared_consumers.md](phase10_shared_consumers.md), and
[phase11_diagnostic_registry.md](phase11_diagnostic_registry.md), and
[phase12_build_system_cleanup.md](phase12_build_system_cleanup.md), and
[phase13_compatibility_cleanup.md](phase13_compatibility_cleanup.md), and
[phase14_version_length.md](phase14_version_length.md). Final compatibility cleanup
and version-length correction are complete. Shared errors and blank code-1 behavior
remain intentional; scientific corrections remain separate.

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

### Phase 7 — WaterBody (complete)
- Added `WaterBodyConfigModule` owning the four optional `/water/` settings, six
  unchanged fallback constants, and six effective errors. The constants-file reader
  stays in DataInput; the original 405-then-500 overwrite stays uncorrected.
- Removed the four fields from `C`, repointed all five WaterBody science modules and
  DataInput consumers, and replaced Bootstrap's final domain read with WaterBody
  initialisation and separate model/dimension copying helpers.
- Preserved every original comment, numeric type, science interface, calculation
  order, optional-group behaviour, and both known river failures.
- Added the repeatable `verification/verify_waterbody.py` capture/compare runner,
  generated spatial/terrain fixtures, configuration/error tests, and an interior
  reach slope test. No third-party Python packages are required.
- **Verified:** 21 CTest cases, 14 exact scientific comparisons, four expected
  failures, batch operation, and checkpoint save/reinstate. See
  [phase7_waterbody.md](phase7_waterbody.md) for commands, actual results, comment
  checks, the EOF-sensitive malformed-input detail, and remaining work.

### Phase 8 — Reactor (complete)
- Added `ReactorConfigModule` with the four existing default-real constants and
  `registerReactorErrors()`. It has no configuration object or file reader.
  DataInput still reads the constants-file `/water/` group in its original order.
- Moved unchanged critical code 903 out of the shared list and registered it after
  WaterBody. Counts are now 17/18/19/25/26 across shared handler, Soil, BedSediment,
  WaterBody, and Reactor. No science raising site was added.
- Removed direct Globals imports and `C%` reads from both Reactor science modules
  and their abstract procedure declarations. Types, procedures, precision, shapes,
  equations, operation order, and all original comments remain unchanged.
- Kept unused `C%T` for final cleanup. The existing `isZero` helper still reads its
  default tolerance through Util and remains for the shared-consumer phase.
- **Verified:** clean build, 25 CTest cases, nine Reactor and fourteen WaterBody
  exact comparisons, four expected failures, batch operation, and checkpoint
  save/load. The known mass-loss result is explicitly preserved by a focused test.
  See [phase8_reactor.md](phase8_reactor.md) for commands, results, and remaining work.

### Phase 9 — Biota (complete)
- Added `BiotaConfigModule` exposing only `registerBiotaErrors()`. Critical code 902
  moved unchanged from the shared list and is registered immediately after Reactor.
  No configuration object, defaults, input group, or science raising site was added.
- Removed direct Globals imports and `C%` reads from all three Biota modules. The
  science reads precision from Kernel and current timing from ModelConfig, with
  explicit imports for errors, results, dates, input data, and utility functions.
- Preserved the constants-file readers and the SoilLayer, RiverReach, and
  EstuaryReach creation/update calls. Public types, procedures, number precision,
  calculation order, and every original comment remain unchanged.
- Added direct concentration checks and a model-state test program, both run
  unchanged against Phase 8 and Phase 9. The repeatable Biota capture/compare runner
  covers absent, soil-only, water-only, mixed, estuary, and changing batch-date inputs.
- **Verified:** clean build, 29 CTest cases, 50 exact direct concentration records,
  six exact model-state comparisons, and 29 exact ordinary output comparisons
  across Biota, Reactor, and WaterBody scenarios. Four expected failures, batch
  operation, and checkpoint save/load also passed. See [phase9_biota.md](phase9_biota.md).
- Missing checkpointed Biota state, current harvest timing, and invalid-form
  calculations remain separate follow-up work; saving/loading does not prove
  correct continuation of organism concentrations.

Each domain phase follows the **per-domain checklist** (§8), including migration of
all repository consumers of the domain's fields. Errors move only when that domain
has assigned codes; a domain without assigned errors skips error registration.

### Phase 10 — Cross-cutting facade consumers (complete)
- Moved all active shared-setting readers in GridCell, Crop, Data, output, Logger,
  Util, and Checkpoint to ModelConfig, ModelDimensions, Kernel, and ErrorHandling.
  ModelAssembly now imports the handler directly. Indirect NetCDF type and integer
  kind imports were made explicit where needed.
- Moved the model-default declarations and comments verbatim to ModelDefaultsModule.
  DefaultsModule exposes that same object and Kernel file units for compatibility.
- Removed runtime copying from DataInput and Checkpoint, preserving batch selection
  and `setT0` order. Globals, its fields/helpers, and Bootstrap's startup copies remain
  for final cleanup. The error registry already belongs to ErrorHandling and does
  not depend on Globals.
- Preserved all original comments, public science interfaces, calculations, input
  readers, output formats, and checkpoint records. The historical Biota test is the
  named Globals exception; new direct tests leave `C` untouched.
- **Verified:** clean build, 33 CTest cases, 18 new exact output comparisons plus
  the existing 29 WaterBody/Reactor/Biota comparisons, exact Biota concentration
  records, logging, mask/batch state, diagnostics, and checkpoint layout/defined
  values. See [phase10_shared_consumers.md](phase10_shared_consumers.md).

### Phase 11 — Separate diagnostic-registry correction (complete)
- Restored warning 405 without overwriting 500; WaterBody now registers 401–405,
  500–501, and critical code 901. Preserved every existing message and severity.
- Explicitly retained shared codes 110/200/201/300 and the blank positions 4–5.
  Their blank critical code-1 message remains by agreement. Keep this shared list
  through final cleanup; an empty registry is not a completion requirement.
- Preserved public interfaces, startup order, the error library, and all original
  comments. Added explanatory notes beside historical comments without replacing them.
- Tested exact membership and counts through startup, warning 405 through three
  reporting forms, critical 901, shared errors, blank code 1, warning suppression,
  and disabled error output. No new science raising sites are added.
- **Verified:** clean build, 57 CTest cases, 47 exact model-output comparisons with
  a fresh Phase 10 reference, unchanged Biota state, logs, batch/checkpoint checks,
  expected failures, and all 76 original comments in changed code/build files.
  See [phase11_diagnostic_registry.md](phase11_diagnostic_registry.md).

### Phase 12 — Separate build-system cleanup (complete)
- CMake and the example Makefile no longer rewrite tracked source. CMake generates
  a build-local VersionModule; fpm and the package recipe still compile the valid
  tracked fallback, now `0.0.5`, matching the manifest and recipe.
- `NANOFASE_VERSION` explicitly selects a CMake label. An empty override uses
  `git describe --tags` from this checkout, then the fallback if Git/history/tags
  are unavailable. Detection never adopts a containing repository's version.
  Every build refreshes the generated copy, writing it only if its content changes.
- The example Makefile delegates source ordering and compilation to CMake. Debug,
  release, fast, clean, compiler/NetCDF overrides, and compilation information remain
  available. Each mode has its own directory; clean leaves unrelated caches alone.
- Main-program compiled modules now have their own directory, like the tests.
  Legacy modules in the build root are retained in `legacy-fortran-modules` so they
  cannot silently supply an old version to a separately rebuilt test.
- Kept the 17-character version constant and 16-character model fields. Fixed-label
  scientific comparisons therefore preserve existing text exactly. Automatic and
  fallback builds intentionally change version metadata, including console output.
- Verified 58 CTest cases (57 existing plus a version-build test containing 16 check
  groups), 47 exact output comparisons, Biota state, expected failures, batch and
  checkpoint checks, all Make modes, source-archive builds, and `fpm @install`.
  Retained all 61 original comments in the changed existing code/build files.
  See [phase12_build_system_cleanup.md](phase12_build_system_cleanup.md).

### Phase 14 — Version-length correction (complete)
- Removed CMake's truncation and made the generated/fallback constant use its full
  literal length. ModelConfig stores at least 16 characters or the full label,
  whichever is longer; short-label output padding is preserved.
- Generated quoted labels use short continued lines, preserving special characters
  without changing numerical compiler settings or writing tracked source.
- Verified real ModelConfig initialisation/reset, boundary and long labels, all
  earlier version-selection/build checks, 58 CTest cases, 47 exact short-label
  output sets, and four full-model long-label comparisons. Console, summary and
  the complete NetCDF source/URL were checked explicitly before comparing the
  remaining scientific content. General comparison filters were not weakened.
- All build routes and original-comment checks passed. See
  [phase14_version_length.md](phase14_version_length.md) for commands and results.
- Release metadata remains separate: the fallback, manifest and recipe still say
  `0.0.5`; CITATION.cff retains `0.0.4` and its older date. No release date is invented.

### Separate river-disabled behaviour correction
- Define what disabling bed sediment should do to deposition, resuspension,
  nanomaterial transfers, and reach water-depth changes. Fixing only the unset
  deposit-result read would not address all current river operations.
- Add focused river-enabled and river-disabled tests before changing the behaviour.
  Keep this work separate from the domain migrations; Phase 6 deliberately retains
  the existing river-disabled failure as a negative test.

### Separate terrain-height outlet correction
- Define how a reach determines elevation difference when its outflow lies outside
  the terrain array. Test headwater and non-headwater outlets before changing code.
- Fix the out-of-bounds access separately from domain migrations. Phase 7 keeps the
  failing full-model fixture and covers minimum-slope calculations on interior reaches.

### Separate Reactor mass-loss correction
- Correct the attachment calculation so that distributing mass between sediment
  size classes preserves the total pristine and transformed mass. Test equal and
  unequal rates, zero-rate classes, and partial and complete attachment.
- Replace the Phase 8 known-defect expectations only in this separate change.
  Scientific outputs are expected to change and need science review; an exact
  comparison with the defective calculation is not the acceptance rule for this fix.

### Separate Biota behaviour and checkpoint corrections
- Define harvest dates for non-daily timesteps and whether harvesting should reset
  concentrations once or on every update in the selected month. Test these choices
  separately before changing the existing calculations.
- Stop invalid uptake forms from reaching calculations with unset concentration
  sums in a separately tested error-handling change. Do not preserve undefined
  numeric results as a reference for that repair.
- Save and restore both organism concentrations for soil and water Biota, with
  explicit checkpoint-format compatibility tests. Resolve the existing warm-up and
  reinstatement timing and the main loop's unused restored `t0` as well before
  claiming exact checkpoint continuation.

### Phase 13 — Final compatibility cleanup (complete)
- Removed GlobalsModule, DefaultsModule, the old `C` object, Bootstrap's two startup
  copying procedures, and the unused runtime-copy procedure. All active consumers
  now use the owners established in earlier phases.
- Updated the Biota direct test to use only ModelConfig; proved the same 50 records
  with both test forms against Phase 12, then compiled identical updated tests on
  both sides before fresh capture. Source-hash protections remain enabled.
- Replaced the defaults-alias test with a check of the actual defaults owner.
- Preserved startup order, construction methods, logging/error propagation, shared
  errors, blank code 1, all scientific operations, and all original comments.
  Useful comments moved to their owners; deleted-code comments have a labelled,
  comment-only archive in this folder.
- Verified 58 CTest cases, 47 exact output sets, Biota state, expected failures,
  batch/checkpoint checks, all build routes, and 4,910 original comments. See the
  [Phase 13 report](phase13_compatibility_cleanup.md) for actual commands and results.
- Earlier transition descriptions and skeletons above explain historical stages.
  Do not reintroduce their old copying calls or unused fields into current code.

Every phase adds a plain-language file in `migration_documentation/` recording what
was implemented, actual verification commands and results, preserved public behaviour
and original comments, and the exact work left. Define unavoidable code terms when
they first appear. Earlier records are historical snapshots: do not rewrite their
"work left" sections after later phases finish.

---

## 8. Per-domain migration checklist (repeatable recipe)

For domain `X`:

1. **Create `XConfigModule`** in `src/X/`. Add `XConfigType` and the shared `xConfig`
   object only when there are owned runtime settings to store. A domain such as
   Reactor can expose constants and an error-registration procedure without an
   empty configuration object.
2. **Move existing defaults** into the domain without inventing new ones. Keep their
   declared kinds and values. Science constants become module `parameter`s. For local
   namelist variables, use executable assignments on every call: declaration
   initialisation gives a Fortran local variable saved state and can leak values from
   an earlier call. Delete the moved values from `DefaultsModule`.
3. **Own an existing namelist, where present:** declare `namelist /x/ …` inside `XConfig%init`, open
   `config.nml` with `newunit`, allocate arrays before reading, read, populate, and
   `close`. Preserve whether the group and each member are required or optional,
   including their current read-status handling. WaterBody must retain its optional
   reader rather than copying the required Soil or BedSediment reader. Distinguish a
   config-file group from any same-named group in another input
   file; move only the group the domain currently owns. Skip file reading when
   there is no owned model-config group; Reactor's constants-file reader stays in DataInput.
4. **Move existing audits only:** if `C%audit` already contains domain-specific
   checks, move them into `XConfig%audit`. Do not create new validation merely to fit
   the module template.
5. **Register errors conditionally:** only if X has assigned codes, call
   `ERROR_HANDLER%add(error=ErrorInstance(code=…, …))` in `XConfig%init`, or a standalone
   domain registration procedure when no configuration object is needed, after the
   shared handler is initialised, and remove exactly those entries from the legacy
   registry. A domain with no assigned codes skips this step. Preserve existing
   trigger/clear/propagation semantics; redesigning diagnostic flow is separate from
   this pure refactor.
6. **Repoint every consumer:** across the repository, not just under `src/X/`, replace
   reads of X-owned facade fields with `XConfigModule`; use `KernelModule`,
   `ModelDimensionsModule`, or `ModelConfigModule` for values owned by those layers.
   Domain-to-domain imports must be explicit, one-way, and acyclic.
7. **Update bootstrap:** call the domain's config initializer or standalone error
   registration procedure in the right order; do not pass an unused file path.
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
  Phase 6 this applies to rivers with bed sediment disabled. Phase 7 also preserves
  the terrain-height outlet failure. Its minimum-slope test uses an interior reach;
  the ordinary examples lack terrain data and cannot prove that setting is exercised.
  Estuary enabled/disabled runs succeed and remain subject to exact comparisons.
- **Repeatable scenario setup:** keep small tests and fixture-generation scripts in
  the repository. Store generated data, reference executables, inputs, hashes, commands,
  and logs outside tracked source directories. Phase 7's
  `verification/verify_waterbody.py capture/compare` commands rebuild all its scenario
  inputs; old temporary Phase 6 evidence is not required.
- **Default-value coverage:** establish whether a value comes from its fallback,
  constants file, or spatial input. Test the applicable paths without accidentally
  hiding a moved default behind a spatial override. Preserve existing number kinds
  and conversions as well as the parameter values.
- **Active Reactor coverage:** use `verification/verify_reactor.py capture/compare`
  for omitted defaults, each nonzero reaction rate, combined river and estuary
  reactions, and changed shear. Confirm that the intended water results change in
  the reference runs. Keep the two-class mass-loss test explicitly labelled as
  preserving a known defect; identical before/after output does not prove correct science.
- **Focused config/error gate:** test existing required values and defaults in a
  separate process where shared singleton state requires it. Check both the base
  registry and the count after domain registration.
- **Phase 11 diagnostic gate:** require exact code membership without duplicates and
  counts 15/16/17/25/26/27 through shared/Soil/BedSediment/WaterBody/Reactor/Biota
  setup. Codes 405 and 901 appear only after WaterBody initialisation. Test exact
  messages, warning versus critical status, suppression controls, and continued or
  stopped execution. Keep the blank code-1 message. Restoring registered 405 proves
  reporting only, not automatic detection of excessive river lengths.
- **Active Biota coverage:** use `verification/verify_biota.py capture/compare` with
  identical direct and integration test programs built against each source version.
  Compare organism counts, selected input indices, and both concentrations, and
  require evidence that organisms are updated. Cover soil, river, estuary, all
  accepted uptake forms, storage, growth/death, timestep duration, and harvest/batch
  dates. Normal outputs do not contain organism concentrations and are insufficient
  by themselves. The runner also compares six ordinary output sets exactly.
- **Checkpoint smoke gate:** run the existing checkpoint save/reinstate smoke path
  after relevant phases. Exact continuation equivalence remains unresolved because
  warm-up/reinstate run-control semantics have not yet been separated and Biota
  concentrations are not saved/restored; do not report the smoke test as proof of
  checkpoint continuation correctness.
- **Shared-consumer gate:** use `verification/verify_shared_consumers.py capture/compare`
  against a fresh pre-phase reference, with the identical integration test program.
  Compare the complete expected output set, including disabled outputs, suffixes,
  empty statistics, and steady-state CSV. Check both NetCDF modes/layouts, optional
  columns/units, logs/colors, simulation masks, and changing batch state. Compare
  all defined checkpoint values and record sizes, excluding only uninitialised
  positions for nonexistent reaches. Verify nonzero `t0` and tolerance checks, while
  retaining the distinction between restored state and correct continuation.
- **Direct-owner gate:** initialise ModelConfig and ModelDimensions in standalone
  tests before using utilities. Check tolerance boundaries, explicit overrides,
  array shapes, repeated config reads, required groups, logger settings, and that
  ModelConfig reads current values from the real defaults owner. Do not initialise
  `C` in these tests. Keep Biota source-hash checks enabled. Phase 13 changes only
  the direct test setup;
  compile identical revised test sources against both reference and candidate before capture.
- **Batch smoke gate:** run the existing batch path whenever assembly, source snapping,
  config paths, or runtime-mutated model config are touched.
- **Tracked-file and version gate:** Phase 12 and later build a generated version
  module without rewriting tracked source. Give the reference and candidate the
  same explicit `-DNANOFASE_VERSION=<label>` and identical numerical compiler flags.
  When comparing Phase 14 with an older phase, use a label no longer than 16
  characters, such as `migration-check`. Check long-label metadata separately
  with `verify_version_outputs.py` before excluding those exact changed fields.
  Keep summary and NetCDF version fields in exact comparisons. Save and compare
  tracked-file hashes after configuration, building, reconfiguration, and cleaning.
  When the reference predates Phase 12, it cannot accept this override: build it in
  an isolated source copy, restore its exact saved version file after configuration,
  and verify that file again after building. Restore and rebuild again if automatic
  reconfiguration changed it. The candidate's override must equal that saved label.
  Use the new override procedure for both sides once both include Phase 12.
- **Source gates:** search case-insensitively and distinguish executable statements
  from comments and strings. After Phase 10 only retained Bootstrap/Globals code
  may use `C`; only Bootstrap imports Globals in production. BiotaScienceTest is
  the explicit historical test exception. Phase 13 removed all of these active
  dependencies, including the test exception, while retaining original comments.
  Run `verification/verify_compatibility_cleanup.py` to enforce their absence.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 490 `C%npDim` readers can't change at once | Facade shim — `C` stays populated until the last domain migrates |
| Namelist read-order coupling (`allocatable_array_sizes` first) | Model-dimensions reads sizes in Phase 1, before any domain init; bootstrap enforces order |
| IO-unit collisions when domains read independently | Use `open(newunit=…)`; retire the central `iou*` registry |
| Cleanup silently changes agreed diagnostics | Preserve the Phase 11 ownership and tests: 405/901 belong to WaterBody, 110/200/201/300 remain shared, and blank positions 4–5 keep the blank critical code-1 message |
| Silent behaviour change during refactor | `verify_refactor.py --exact` regression gate after every phase |
| Checkpoint depends on dimensions and run state | Dimensions moved in Phase 1 and remaining shared reads in Phase 10. Defined saved values and loading are checked; the main loop's unused restored timestep, warm-up timing, and missing Biota state still prevent claims of correct continuation |
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
- Correcting the terrain-height outlet failure or tightening optional Water input
  validation during a domain migration. Both require separately tested behaviour changes.
- Correcting Reactor's known attachment mass loss during the ownership migration.
  That calculation requires the separate science correction described in §7.
- Proving exact checkpoint continuation while the existing warm-up/reinstate
  run-control semantics remain coupled and Biota concentrations are absent from the
  saved state; current checkpoint coverage is a smoke test.
- Correcting Biota harvest timing, repeated resets, invalid-form calculations, or
  missing checkpoint state during the ownership migration. These need separate
  behaviour and compatibility tests.
- Introducing Source dependency injection or a new `AbstractSource` interface. The
  current explicit one-way Source dependency is acceptable and acyclic.
- Generalising the contaminant-specific accessor interfaces on the spatial containers
  (`get_C_np_water`, `get_j_nm_*` on `AbstractGridCell` / `AbstractEnvironment`) so the
  grid/environment become agnostic to the modelled stressor. This is a larger, more
  speculative refactor worth doing only once a concrete second science scenario exists
  to design against; it is noted here so it is not confused with the config or builder
  work, but is deferred.
