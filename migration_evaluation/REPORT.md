# NanoFASE migration evaluation

Assessment date: 9 November 2026. Compared the current working trees at
`/Users/qianhuilin/Documents/nanofase_before_migration/nanofase` (before) and
`/Users/qianhuilin/Documents/nanofase-mono/nanofase` (after).

**The migration improves ownership of domain configuration and separates some
construction responsibilities. It does not yet demonstrate lower implementation
effort for every change, independent science development, or an easy path to new
contaminant families.** Several narrow changes need the same number of source edits
in both versions; one configuration extension needs an extra edit after migration.

The priority extension is **retain nanomaterials and add a selectable different
contaminant family**. This assessment assumes selection per simulation. Simulating
both families together is a separate scenario, not an assumed requirement.

| Goal | Evidence from these trees | Assessment |
| --- | --- | --- |
| Easier modification | Smaller domain configuration dependency surfaces; the same readers for six matched fields | Improved ownership and potential isolation; actual effort reduction not measured |
| Easier extension | Dedicated configuration owners and an assembly module; nanoparticle-specific scientific interfaces remain | Improvement depends on the extension; contaminant-family support still requires architectural work |
| Independent development | Different domains can change defaults in different files; shared input parsing and global runtime objects remain | Better for configuration work; partial for science and integration work |
| Code comprehension | Smaller Environment/GridCell modules, explicit imports, clearer owner names | Positive structural indicators; developer comprehension has not been measured |

**Define “affected” before counting.**

Your proposed metrics are useful, provided they distinguish these different sets:

| Measure | Definition | What it tells you |
| --- | --- | --- |
| Direct dependents | Source units containing `use ChangedModule` | Immediate module dependency exposure |
| Transitive dependents | Units that depend on it through one or more `use` edges | Conservative dependency exposure across the program |
| Field readers/writers | Units accessing the specific changed field | A more precise starting point for impact analysis |
| Existing units edited, E(s) | Distinct existing production units changed to complete scenario s | Spread of implementation changes |
| New units added, A(s) | New production units needed by s | How much new functionality can be added separately |
| Interface changes, I(s) | Existing public contracts whose callers or implementers must adapt | Coordination and compatibility burden |
| Domains touched, D(s) | Distinct responsibility areas changed, using the same domain mapping before/after | Cross-team coordination burden |
| Effort, T(s) | Active time to understand, implement, test, and review s | The outcome the structural metrics approximate |

Report tests, fixtures, configuration/data, build files, and documentation changes
separately from E(s), but include their work in T(s). Report changed procedures and
non-comment lines as secondary size measures: editing two lines and rewriting a
large module must not receive the same effort estimate just because E(s)=1.

Changing a value in `config.nml` can change model outputs while requiring **zero
Fortran edits**. Changing an implementation with a stable interface may also need
zero edits to dependent modules. Conversely, a configuration schema can couple
modules without any direct `use` edge between them. Neither a dependency graph nor
a shared-state graph alone measures all semantic propagation or required edits.

Actual recompilation is a separate measurement. Record compiler invocations under
a fixed compiler/build system for a controlled patch; do not equate graph reachability
with modules that a particular build actually recompiles.

Using concrete change scenarios is consistent with SEI's
[scenario-based architecture evaluation](https://www.sei.cmu.edu/library/scenario-based-analysis-of-software-architecture/).
SEI's [modifiability scenario guidance](https://www.sei.cmu.edu/documents/704/2003_005_001_14213.pdf)
also treats affected components and effort as separate response measures. The
specific scorecard and experiments here are recommendations for this repository.

**Measured module dependency exposure.**

Scope: production Fortran units under `src`, including `main`; exclude vendor and
test units. Counts exclude the changed unit. A direct edge includes `use` statements
inside procedures and interfaces. Transitive counts include direct dependents.
These are source graph measurements, not edit or recompilation counts.

| Before: owner | Direct / transitive | After: owner | Direct / transitive |
| --- | ---: | --- | ---: |
| GlobalsModule: soil runtime configuration | 34 / 34 | SoilConfigModule | 4 / 27 |
| GlobalsModule: water runtime configuration | 34 / 34 | WaterBodyConfigModule | 4 / 27 |
| GlobalsModule: bed sediment runtime configuration | 34 / 34 | BedSedimentConfigModule | 8 / 28 |
| GlobalsModule: source runtime configuration | 34 / 34 | SourceConfigModule | 2 / 16 |
| DefaultsModule: reactor fallback constants | 6 / 35 | ReactorConfigModule | 2 / 27 |
| GlobalsModule: biota error registration | 34 / 34 | BiotaConfigModule | 1 / 2 |
| GlobalsModule: model runtime configuration | 34 / 34 | ModelConfigModule | 20 / 32 |
| GlobalsModule: shared dimensions | 34 / 34 | ModelDimensionsModule | 28 / 35 |
| DataInputModule | 18 / 24 | DataInputModule | 21 / 26 |

Each row compares responsibility ownership, not equivalent whole modules. For
example, old `GlobalsModule` also supplied precision and diagnostics, and domain
fallback constants previously came from `DefaultsModule`. The old rows repeat
shared owners and must not be summed. `BiotaConfigModule` currently registers an
error; it does not parse biota scientific parameters. Those remain in DataInput.

SoilConfig's four direct dependents are Bootstrap, DataInput, SoilLayer, and
SoilProfile. Its large transitive count partly follows the path through DataInput,
which supplies many other domains. Thus even a much smaller direct count does not
establish that every soil-related change has become isolated.

**Measured field dependencies tell a different story.**

The following are direct external reader counts from the audited dataflow exports.
The owning module is excluded. All six selected relationships have zero uncertain
effects and zero external writers in both versions. This is not a claim about
all state or all call effects in the analyzer.

| Matched field | Before readers | After readers | Reader(s) |
| --- | ---: | ---: | --- |
| includeAttachment | 1 | 1 | SoilLayerModule |
| includeBioturbation | 1 | 1 | SoilProfileModule |
| includePointSources | 1 | 1 | PointSourceModule |
| includeEstuary | 1 | 1 | DataInputModule |
| sedimentLayerDepth | 4 | 4 | AbstractBedSediment, BedSedimentLayer, DataOutput, GridCell |
| npDim | 17 | 17 | Cross-domain array shapes and allocations; full list in metrics.json |

For example, moving `C%includeAttachment` to `soilConfig%includeAttachment` changes
its owner without reducing the number of consumers. Calling this a change from
34 affected modules to 1 would compare different measurements. The defensible
claim is smaller ownership/dependency exposure, with unchanged direct scientific
consumption for this field. Downstream numerical effects can still extend beyond
the direct reader.

**The global graph is mixed evidence.**

| Metric | Before | After |
| --- | ---: | ---: |
| Production units | 38 | 49 |
| Direct dependency edges | 148 | 249 |
| Average inclusive reachable-unit count (ACD) | 14.29 | 16.37 |
| Inclusive propagation cost | 37.60% | 33.40% |
| Cyclic components | 0 | 0 |

Splitting modules changes the denominator of propagation cost. Its reduction
coexists with more edges and a higher average reachable count; it cannot establish
that modification became easier. The graphs were already acyclic. See the existing
[dependency comparison](../dependency_graphs/comparison/report.md) for definitions
and additional metrics. The new analysis independently extracts source `use` edges
and verifies exact agreement with both stored project-source DOT graphs.

**Scoped changes suitable for a fair before/after experiment.**

The counts below are **source-inspection estimates for explicitly scoped patches**,
not completed implementations or measured developer effort. They include existing
production units only. New tests, examples, documentation, and build work must be
recorded separately. There can be multiple valid implementations; keep the change
contract fixed, record the chosen edit set, and compare working implementations.

| ID and precise change | Before E | After E | Expected existing edit set and interpretation |
| --- | ---: | ---: | --- |
| M0: Set an existing input flag to a different value | 0 | 0 | Input file only, in either version |
| M1: Change the fallback for omitted include_clay_enrichment | 1 | 1 | DefaultsModule → SoilConfigModule; same count, clearer ownership |
| M2: Rename public includeAttachment, keeping the input spelling unchanged | 2 | 2 | Globals + SoilLayer → SoilConfig + SoilLayer; same consumer |
| E1: Add a neutral optional soil process multiplier, consumed only in SoilProfile | 2 | 2 | Globals + SoilProfile → SoilConfig + SoilProfile, with an inline initializer in either reader; using the old separate Defaults convention adds one pre-migration edit |
| E2: Add an optional stored flag to the existing config.nml /sediment/ group, before adding science behaviour | 1 | 2 | Globals → BedSedimentConfig + ModelDimensions; both post-migration readers must accept the field |
| E3: Add a uniform point-emission multiplier, defaulting to 1, using existing emissions | 2 | 2 | Globals + PointSource → SourceConfig + PointSource; no new input dataset variable |
| E4: Replace the dissolution calculation using the same inputs, fields, and signatures | 1 | 1 | ReactorModule in both versions; acceptance includes nonzero rates and mass balance |
| E5: Substitute a new reactor implementation for river and estuary, using existing inputs/state and compile-time selection | 2, plus 1 new | 2, plus 1 new | RiverReach + EstuaryReach select the new module/type; the existing reactor contract already supports this narrow case |
| E6: Add a new water diagnostic derived solely from existing state, in CSV and both NetCDF layouts | 3 | 3 | DataOutput + NetCDFOutput + NetCDFAggregatedOutput; output documentation/metadata also needs review |

E1 shows why minimum edit counts are implementation-sensitive: putting defaults
inline can change the score without changing functionality. Do not present a
convention-dependent 3-to-2 reduction as an unavoidable architectural improvement.

E2 is a concrete regression in schema locality. Both
[ModelDimensions](../src/ModelDimensions/ModelDimensionsModule.f90#L61) and
[BedSedimentConfig](../src/BedSediment/BedSedimentConfigModule.f90#L35) read the same
`config.nml` group and declare its complete member list. A field present in the
input must be accepted by both readers. The `/sediment/` group in DataInput is in
the separate **constants file**; it is not a third reader of this config group.
If E2 also enables behaviour in one additional consumer, the estimate becomes
2 before versus 3 after. A new separate group or a shared parsing owner would be
a different design decision that must be scored explicitly.

E5 tests a limit of the assembly extraction: concrete Reactor allocation remains
in [RiverReach](../src/WaterBody/RiverReachModule.f90#L61) and
[EstuaryReach](../src/WaterBody/EstuaryReachModule.f90#L62). ModelAssembly constructs
cells, profiles and reaches, but does not yet centralize all component selection.
Runtime reactor selection would require additional configuration and wiring work.

**Likely extension scenarios.**

These are inferred from the existing model responsibilities and visible extension
points, not from a confirmed product roadmap. Give the contaminant-family scenario
highest priority because it is an explicit requirement. The remaining priorities
should reflect actual research plans; include both easy and difficult cases.

| Scenario | Why it is plausible | Existing areas to inspect / acceptance criteria |
| --- | --- | --- |
| Add another parameterization of an existing nanomaterial | Existing material density, sizes, rates and distributions are inputs | Configuration/constants/data only if the existing science applies; 0 engine edits is a useful control, not evidence of a new capability |
| Add or select reaction kinetics | Reactor already isolates dissolution, transformation and aggregation | Reactor, abstract contract if new state is needed, DataInput/default owner for new parameters, reach construction for implementation selection; test nonzero behaviour and conservation |
| Add a soil transport/attachment process | Existing soil flags and process methods form clear sites | SoilConfig, SoilLayer/SoilProfile; DataInput for spatial or material-dependent coefficients; preserve existing soil scenarios |
| Add an emission mode | PointSource currently handles water points; diffuse pathways are separate | Source, GridCell, receiving compartments, DataInput and the separate preprocessing schema; account for total emitted mass and timing |
| Add an organism category or uptake mechanism | Biota parameters are data-driven; water/soil organisms have concrete classes | A new parameter-only organism may need 0 engine edits; a new mechanism may change AbstractBiota, BiotaSoil/Water, DataInput and owning compartment construction |
| Add a reach-like compartment, such as a lake/reservoir | Current assembly explicitly selects riv/est | ModelAssembly, GridCell reach classification, DataInput, output type labels and possibly routing/interfaces; a new class alone is insufficient |
| Add a diagnostic/output variable | Existing CSV and two NetCDF layouts need coordinated support | DataOutput, both NetCDF writers, metadata/docs; verify both layouts and streaming/buffered modes |
| Extend restart to new state | New science may add state that must survive restart | Checkpoint plus relevant state owners; compare continuous and interrupted runs, including organism state |
| Retain NM and add a selectable different contaminant family | User's priority | State model, reactions, inputs, emission pathways, soil/water/sediment/biota contracts, output and restart; retain NM regression behaviour |
| Simulate multiple contaminant families together | Possible later research need | Additional species/family axes, per-species properties and process selection, potentially interactions; scope separately from selecting one family per run |

For the larger scenarios, this table is a **review surface**, not a claim that every
listed module must be edited. Assigning a total before selecting concrete state,
process, input/output, and compatibility requirements would manufacture precision.
Use E1–E6 to establish small-change baselines, then implement a bounded version of
the priority scenario in each snapshot to measure its actual E, A, I, D and T.

**What the priority contaminant extension would test.**

A useful bounded first experiment is: retain selectable NM runs and add a single
dissolved contaminant with specified emissions, transport, and a specified decay
law; produce mass/concentration outputs and account explicitly for degraded mass.
Treat sorption, metabolites, uptake, and simultaneous families as separate increments
unless the chosen contaminant requires them for scientific validity. This is an
engineering experiment specification, not a proposed scientifically adequate model
for an unspecified real substance.

Acceptance criteria should require old NM inputs to retain their agreed behaviour,
new inputs to select the family explicitly, a conserved/accounted mass budget,
correct units, deterministic output, and documented restart semantics. If correct
restart is required, address the known baseline restart limitations explicitly;
loading a checkpoint successfully is not evidence of equivalent continuation.

The migration did not introduce a contaminant-independent state or process contract:

- [ModelDimensions](../src/ModelDimensions/ModelDimensionsModule.f90#L23) still
  defines NM size/form/state dimensions, with `npDim` directly read by 17 other units.
- [AbstractReactor](../src/Reactor/AbstractReactorModule.f90#L5) exposes nanoparticle
  masses, particle concentrations, settling and heteroaggregation operations. Its
  `update` interface takes NP arrays and a scalar dissolved mass. A scalar dissolved
  channel by itself does not make the whole model a generic dissolved-contaminant model.
- [PointSource](../src/Source/PointSourceModule.f90#L61) places emissions into fixed
  form/state positions, and other compartments exchange related NM-shaped arrays.
- [DataInput](../src/Data/DataInputModule.f90#L792) still owns cross-domain scientific
  constants and material-specific input interpretation.
- [NetCDFOutput](../src/Data/NetCDFOutputModule.f90#L16) and
  [Checkpoint](../src/CheckpointModule.f90#L41) explicitly enumerate existing state.

The practical next boundary to design is contaminant state/properties and the
contract by which compartments invoke processes and exchange mass. Separate family
selection/construction from the calculations. A new `ContaminantConfigModule` alone
would not remove the assumptions above. Keep measured module counts separate from
the amount of scientific validation required.

**Independent development: measure task collisions.**

For two unrelated tasks a and b, record their existing edit sets Ma and Mb:
`overlap(a,b) = |Ma ∩ Mb|`. Also report `|Ma ∩ Mb| / |Ma ∪ Mb|` when the union is
nonempty. File overlap is a coordination proxy; edits in different procedures can
merge cleanly, and edits in different files can still conflict semantically.

A concrete pair is changing the omitted soil clay-enrichment default and changing
the omitted water bank-erosion default. Both live in DefaultsModule before migration:
overlap = 1. Afterwards they live in SoilConfigModule and WaterBodyConfigModule:
overlap = 0. Each task still edits one production module. This demonstrates why
equal individual E scores can coexist with improved independent development.

Repeat the experiment with two teams adding a scientific input coefficient in
different domains. Both still need DataInput's database/namelist handling; this
shared integration point has not been removed. Measure actual merge conflicts,
time spent integrating, contract renegotiations, and defects after integration.

Distinguish independent domain work from running independent simulations inside
one process. The post-migration config objects, dimensions and
[DATASET](../src/Data/DataInputModule.f90#L223) remain module-level shared state.
They are not passed as separate simulation contexts. Ownership is clearer, but
encapsulation/re-entrancy is not established simply by changing their module names.
When auditing writers, owner-method calls appear as whole-object effects in the
dataflow report; they must not be confused with uncontrolled external field writes.

There is useful test infrastructure: the Soil config test target lists only its
configuration/foundation and FEH sources, without DataInput/NetCDF science sources
([CMakeLists](../CMakeLists.txt#L128)). That supports isolated configuration testing.
It does not prove that a full Soil science component can be compiled and tested
without the rest of the model. Measure the minimal test harness dependency closure,
setup effort, and test duration for the science component separately. Global CMake
configuration still performs NetCDF discovery.

**Code comprehension: measure people performing concrete tasks.**

Two structural indicators improved:

| Indicator | Before | After |
| --- | ---: | ---: |
| Environment physical lines | 454 | 303 |
| GridCell physical lines | 1,044 | 966 |
| Dedicated ModelAssembly physical lines | absent | 286 |
| `use` statements with an `only` list | 151/313 (48.2%) | 346/447 (77.4%) |
| DataInput physical lines | 1,206 | 1,214 |

Line counts include comments/blank lines and are navigation indicators, not
complexity scores. Import counts include external modules and repeated imports
inside interfaces. These indicators support clearer organization but cannot
measure comprehension directly. More modules also mean more navigation, and some
source comments still explain intermediate migration states rather than only the
current architecture (for example the preamble in ModelDimensions).

Use timed tasks with a fixed correctness rubric: locate a default and all its
readers; explain startup order; trace a point emission into water; locate where to
select another reactor; identify every serialization point for new state. Record
answer accuracy, time to a correct answer, files inspected, and incorrect edits.
Counterbalance old/new order across developers or use equivalent paired tasks to
reduce learning effects. Report medians and spread; do not declare success from
one developer who already knows the migration. Record repository familiarity and
Fortran experience. Evaluate code structure and documentation assistance separately
if attributing the benefit specifically to architecture.

**Recommended evaluation protocol.**

1. Freeze both working-tree source manifests and equivalent compiler/dependency
   versions. Use stable responsibility groups for D(s); a new folder name should
   not manufacture an apparent new domain. Source hashes matter more than HEAD
   alone when a tree has uncommitted work.
2. Select scenarios before measuring. Start with M1, E1, E2, E5, E6 and the bounded
   new-family scenario; include the paired-default and paired-input experiments.
   Define acceptance criteria and what compatibility is required for each.
3. Implement each task independently against each baseline, using disposable
   copies/worktrees, and capture E/A/I/D, procedures/lines changed, build/test work,
   and active effort. Keep exploration and rejected changes in the effort log;
   final diff size alone hides that cost.
4. Require functional/scientific acceptance before comparing ease. Existing NM
   results need regression checks; new processes need appropriate scientific
   checks. Known preserved defects should be recorded rather than counted as
   scientific correctness. The repository's verification documentation explicitly
   distinguishes preserved reactor mass loss and restart limitations from correctness.
5. Publish scenario-by-scenario results, with estimated versus implemented values
   clearly separated. Report absolute values and differences. With enough repeated
   observations, report uncertainty as well. Do not compute a percentage improvement
   from a zero baseline.
6. If a single summary is needed, agree scenario weights from the research roadmap
   first and calculate weighted effort or weighted edits. Keep the separate quality
   measures visible; do not average unrelated metrics into an unexplained score.

Priorities suggested by this inspection are to establish a contaminant contract,
reduce shared scientific input parsing responsibilities, give the config-file
sediment schema one owner, and centralize component selection where alternatives
are needed. These target observed constraints; they are not changes made by this
assessment.

**Artifacts and verification.**

- [analyze.py](analyze.py) extracts the current source graphs and validates the
  existing dataflow exports before measuring matched fields.
- [metrics.json](metrics.json) contains source hashes, graph metrics and edges,
  per-module counts, field readers/writers, and file/line/statement evidence.
- Existing [dataflow documentation](../dataflow/README.md) records unresolved
  call/alias limitations. Selected-field results here do not eliminate those
  wider limitations.

Regenerate from the post-migration repository root:

```sh
python3 -B migration_evaluation/analyze.py \
  --pre-root /Users/qianhuilin/Documents/nanofase_before_migration/nanofase
```

The script verified all 47 pre-migration and 58 post-migration dataflow source
hashes, including their scanned vendor sources, and exact production-source
coverage. Both extracted production graphs match the corresponding stored DOT
graphs. The existing graph-analysis tests passed: 18 tests. The script intentionally
fails on stale dataflow/DOT inputs; regenerate those inputs using their documented
commands before evaluating a changed source tree.

No model implementation or extension was changed, no scenario patch was executed,
and no new model build or simulation regression was run for this assessment.
Its measured results establish structure and dependency ownership; its scenario
edit counts are inspection estimates, and its effort/comprehension experiments
remain to be conducted. Existing user analysis files were left unchanged.
