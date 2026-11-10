# NanoFASE dependency structure: pre- and post-migration

This compares the corrected pre-migration DOT snapshot with the post-migration snapshot. The primary comparison measures project source; the secondary comparison includes vendors.

## Results

The project graph has 38 nodes before migration and 49 after. ACD changes from 14.2895 to 16.3673, while propagation cost changes from 37.6039% to 33.4027% (-4.2011 percentage points).

Changes below are post minus pre, not relative percentage changes. Density and cross-group fractions are displayed as percentages here and stored as fractions in JSON/CSV.

### Project source only (primary)

| Metric | Pre | Post | Change |
|---|---:|---:|---:|
| Nodes | 38 | 49 | +11 |
| Direct edges | 148 | 249 | +101 |
| Groups | 18 | 22 | +4 |
| Cumulative Component Dependency (CCD) | 543 | 802 | +259 |
| Average Component Dependency (ACD) | 14.2895 | 16.3673 | +2.0779 |
| Propagation cost | 37.6039% | 33.4027% | -4.2011 pp |
| Directed folder modularity | 0.100027 | 0.080999 | -0.019029 |
| Direct-edge density (excluding self-loops) | 10.5263% | 10.5867% | +0.0604 pp |
| Cross-group direct edges | 123 | 217 | +94 |
| Cross-group direct-edge fraction | 83.1081% | 87.1486% | +4.0405 pp |
| Cyclic strongly connected components | 0 | 0 | +0 |
| Nodes in cycles | 0 | 0 | +0 |
| Largest strongly connected component | 1 | 1 | +0 |
| Isolated nodes | 0 | 0 | +0 |

- **Pre:** cyclic components: none (acyclic); isolated nodes: none.
- **Post:** cyclic components: none (acyclic); isolated nodes: none.

### Full DOT graphs (secondary)

| Metric | Pre | Post | Change |
|---|---:|---:|---:|
| Nodes | 46 | 57 | +11 |
| Direct edges | 211 | 328 | +117 |
| Groups | 22 | 26 | +4 |
| Cumulative Component Dependency (CCD) | 802 | 1,055 | +253 |
| Average Component Dependency (ACD) | 17.4348 | 18.5088 | +1.0740 |
| Propagation cost | 37.9017% | 32.4715% | -5.4302 pp |
| Directed folder modularity | 0.090002 | 0.075206 | -0.014796 |
| Direct-edge density (excluding self-loops) | 10.1932% | 10.2757% | +0.0825 pp |
| Cross-group direct edges | 181 | 291 | +110 |
| Cross-group direct-edge fraction | 85.7820% | 88.7195% | +2.9375 pp |
| Cyclic strongly connected components | 0 | 0 | +0 |
| Nodes in cycles | 0 | 0 | +0 |
| Largest strongly connected component | 1 | 1 | +0 |
| Isolated nodes | 1 | 1 | +0 |

- **Pre:** cyclic components: none (acyclic); isolated nodes: sparskit.
- **Post:** cyclic components: none (acyclic); isolated nodes: sparskit.

## Definitions and interpretation

A node is a Fortran module/program unit from the DOT file, including `main`. An edge `A -> B` means A depends on B. Repeated edges count once, and edges have equal weight.

Let R(i) contain i itself and all distinct nodes reachable by following dependency arrows. Multiple paths to the same node do not increase its contribution:

- **CCD = sum of |R(i)|.** Counts self once for every node, including isolated nodes.
- **ACD = CCD / N.** Average Component Dependency is the average inclusive reachable-node count.
- **Propagation cost = 100 × CCD / N².** This is the percentage of entries in the self-inclusive visibility matrix that are reachable; it is a potential-coupling measure.
- **Directed modularity Q = sum over groups of [L(g)/m − K_out(g) × K_in(g)/m²].** L(g) counts direct internal edges; K_out and K_in sum all out-/in-degrees in the group. The resolution is 1. No reachability-derived self-edges are added for this calculation.

CCD, ACD and propagation cost are different normalizations of the same reachability information, not independent evidence. Increasing the number of components can reduce the reachable fraction while increasing the average reachable count. Module splitting changes the measurement granularity, so lower propagation cost alone does not establish migration success.

Modularity scores the graph together with its supplied folder partition. Higher Q means more internal connectivity relative to a directed degree-preserving null model. Compare the actual folder structures using the same grouping rule; group sizes and counts may change. The score is not a percentage or a universal architecture-quality grade.

The migration's stated goals include moving configuration/state ownership into domains and separating construction from behavior. Shared foundations such as Kernel and ModelDimensions can legitimately receive many cross-group dependencies. These unweighted graphs cannot distinguish those dependencies from broad shared-state access, measure field-level ownership, or estimate actual change probabilities. Interpret the scores alongside the migration's ownership and layering evidence.

### Scope and partition

- **Source scope:** remove vendor nodes and their incident edges before computing reachability. Keep every DOT node mapped under `src`, including orchestration and utility modules.
- **Full scope:** retain all supplied DOT nodes, including isolated vendors. External modules already omitted by graph generation (`omp_lib`, `netcdf`, `spoof`) are not restored.
- **Groups:** use the first directory beneath `src` (including its descendants); each file directly under `src` is its own group. Vendor groups use `vendor/<library>`. Thus `src/Soil/...` belongs to `src/Soil`, and `src/UtilModule.f90` is a separate group.
- **Mapping:** read case-insensitive module/program declarations from production `.f90` files. Exclude `vendor/<library>/{example,examples,test,tests}/` recursively. Require exactly one declaration for every graph node; bare `end module` is accepted.
- **Other measures:** direct-edge density excludes explicit self-loops; cross-group fraction uses direct edges. Cycles are strongly connected components with multiple nodes or an explicit self-loop. Empty graphs fail; undefined ratios appear as `undefined`/null/empty CSV cells.

Folder groups label the existing nodes; they are not collapsed into new graph nodes. DOT files supply the authoritative edges. Source trees supply identities and partition membership; the tool does not regenerate dependencies or prove snapshot/source equivalence.

### Project units with the most direct dependents

These counts use the primary source-only scope. Transitive dependents include direct dependents and exclude the unit itself. A high count identifies a widely used unit, but does not by itself distinguish an appropriate foundation from excessive coupling.

| Snapshot | Unit | Group | Direct dependents | Transitive dependents |
|---|---|---|---:|---:|
| pre | `globalsmodule` | `src/GlobalsModule.f90` | 34 | 34 |
| pre | `datainputmodule` | `src/Data` | 18 | 24 |
| pre | `utilmodule` | `src/UtilModule.f90` | 17 | 29 |
| pre | `loggermodule` | `src/Logger` | 7 | 25 |
| pre | `defaultsmodule` | `src/DefaultsModule.f90` | 6 | 35 |
| post | `kernelmodule` | `src/Kernel` | 41 | 41 |
| post | `modeldimensionsmodule` | `src/ModelDimensions` | 28 | 35 |
| post | `datainputmodule` | `src/Data` | 21 | 26 |
| post | `modelconfigmodule` | `src/ModelConfig` | 20 | 32 |
| post | `utilmodule` | `src/UtilModule.f90` | 19 | 30 |

## Inputs and reproducibility

`metrics.json` records full-precision results, all node mappings and counts, group contributions, edges, and SHA-256 hashes of the DOT files and every scanned source file. `summary.csv` contains the numerical comparison. Outputs contain no run timestamp and are byte-for-byte reproducible for identical inputs at the same paths.

### Pre inputs

- Source root: `/Users/qianhuilin/Documents/nanofase_before_migration/nanofase`
- DOT: `/Users/qianhuilin/Documents/nanofase-mono/nanofase/dependency_graphs/nanofase_premigration_fixed/nanofase_premigration.dot`
- DOT SHA-256: `dd7c4828950b6f58a0acd5482cffacf481cdad4903c9ff481079a1e1f71e947e`
- Scanned source files: 47
- Source-manifest SHA-256: `803a947d0f0c5e592e22fa41956fbed5a69b3393b58585d95d05d3bbfbc6d738`

### Post inputs

- Source root: `/Users/qianhuilin/Documents/nanofase-mono/nanofase`
- DOT: `/Users/qianhuilin/Documents/nanofase-mono/nanofase/dependency_graphs/nanofase_postmigration/nanofase_postmigration.dot`
- DOT SHA-256: `3051188af514894e13ad5492aa11a1bd00c2fe38b82006a26de3d0116ee0aec4`
- Scanned source files: 58
- Source-manifest SHA-256: `1487b6a73c428ffe35c3edb991ce13c6d191b77e29e5a8d16be0350897bb3fa5`

The manifest hashes sorted UTF-8 records of relative path, a NUL separator, the file's hex SHA-256, and a newline. Paths identify the local inputs; neither source checkout is edited.

## References

- [ArchUnit: Lakos cumulative dependency metrics](https://www.archunit.org/userguide/html/000_Index.html#_cumulative_dependency_metrics_by_john_lakos) documents self-inclusive CCD and ACD.
- [MacCormack, Baldwin and Rusnak (2012)](https://www.hbs.edu/ris/Publication%20Files/Research%20Policy%2041%20%282012%29%201309%E2%80%93%201324_c5c2350e-013c-4065-a2f9-d95eb32177d5.pdf) describes propagation cost through dependency reachability; this report explicitly uses the self-inclusive convention.
- [Leicht and Newman: Community structure in directed networks](https://arxiv.org/abs/0709.4500) provides the directed modularity formulation.
