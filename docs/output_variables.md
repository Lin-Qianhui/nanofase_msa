# NanoFASE model output variables

This document describes every variable written to the model's output files: what it
means, its internal data structure, an example of that structure, and where in the
code the value is calculated.

It is generated from the output routines in
[`src/Data/DataOutputModule.f90`](../src/Data/DataOutputModule.f90), the state
variables in [`src/WaterBody/WaterBodyModule.f90`](../src/WaterBody/WaterBodyModule.f90),
the flux types in [`src/WaterBody/FlowModule.f90`](../src/WaterBody/FlowModule.f90),
and the dimension definitions in [`src/GlobalsModule.f90`](../src/GlobalsModule.f90).

---

## 1. How the output is structured

The model writes **tidy/long CSV tables**. Each call to `output%update(t, tInChunk)`
in the main loop appends **one row per non-masked grid cell** (and, optionally, one row
per waterbody or soil profile within that cell). The spatial grid and the time axis are
therefore encoded as *columns* (`t`, `x`, `y`, …), not as array dimensions.

**Key fact about every numeric column:** internally almost every quantity is a
multi-dimensional array, but it is collapsed to a **single scalar** with Fortran's
`sum()` before being written. For example `output_water.csv`'s `m_np(kg)` column is
written as `trim(str(sum(reach%m_np)))`. Optional config flags (the `...Breakdown`
options) "unroll" one hidden dimension into extra columns instead of summing it.

### Output files

| File | Produced by | Enabled when |
|------|-------------|--------------|
| `summary<hash>.md` | metadata + final mean PECs | always |
| `output_water<hash>.csv` | `updateWaterDataOutput` | `C%writeCSV` |
| `output_sediment<hash>.csv` | `updateSedimentDataOutput` | `C%writeCSV` |
| `output_soil<hash>.csv` | `updateSoilDataOutput` | `C%writeCSV` |
| `output_ssd<hash>.csv` | `updateSedimentSizeDistributionDataOutput` | steady-state SSD mode |
| `stats<hash>.csv` | header stub only (not yet implemented) | `C%writeCompartmentStats` |
| NetCDF file | `me%ncout` | `C%writeNetCDF` |

`<hash>` is the optional `C%outputHash` suffix. Files are opened in
[`initDataOutput`](../src/Data/DataOutputModule.f90#L51).

---

## 2. Dimension primer

A handful of array shapes recur throughout the outputs. They are all set from config in
[`GlobalsModule.f90`](../src/GlobalsModule.f90#L428).

### `C%npDim` — the shape of every nanomaterial (NM) array

```fortran
C%npDim = [C%nSizeClassesNM, C%nFormsNM, C%nSizeClassesSpm + C%nExtraStatesNM]
```

So every NM mass/concentration array is **3-D**:

| Axis | Size | Meaning |
|------|------|---------|
| 1 | `nSizeClassesNM` | NM **size class** (e.g. small / medium / large particles) |
| 2 | `nFormsNM` | NM **form** (e.g. pristine, capped/coated variants) |
| 3 | `nSizeClassesSpm + nExtraStatesNM` | NM **physical state**: heteroaggregated to each SPM size class (`nSizeClassesSpm` of them), **plus** extra states such as free / dissolved-organic-bound (`nExtraStatesNM` of them) |

> **Example.** With `nSizeClassesNM = 5`, `nFormsNM = 4`, `nSizeClassesSpm = 5`,
> `nExtraStatesNM = 3`, an NM array has shape `(5, 4, 8)` — 160 numbers. When written to
> CSV as e.g. `m_np(kg)` it becomes `sum()` of all 160 → one scalar.

Pristine NM (`m_np`) and transformed NM (`m_transformed`) are tracked as **separate**
3-D arrays; dissolved NM (`m_dissolved`) is a **scalar**.

### Other recurring dimensions

| Symbol | Meaning | Typical example |
|--------|---------|-----------------|
| `nSizeClassesSpm` | suspended particulate matter (sediment) size classes | 5 |
| `nSedimentLayers` | layers in the riverbed sediment | 4 |
| `nSoilLayers` | layers in a soil profile | 4 |

SPM arrays (`m_spm`, `C_spm`) are **1-D** of length `nSizeClassesSpm`.

---

## 3. Columns common to the CSV files

These identify *where* and *when* a row applies. They come from loop indices and the
input grid, not from simulated state.

| Column | Meaning | Type / structure | Example | Source |
|--------|---------|------------------|---------|--------|
| `t` | timestep index (global across batch) | scalar integer | `42` | loop variable `t + tPreviousChunk` |
| `datetime` | ISO date of this timestep | string | `2015-02-11` | `C%batchStartDate + timedelta(t-1)` ([L133](../src/Data/DataOutputModule.f90#L133)) |
| `x`, `y` | grid cell column/row index | scalar integers | `12, 7` | loop indices over `colGridCells` |
| `easts`, `norths` | cell-centre coordinates (m) | scalar reals | `429500.0, 512500.0` | `DATASET%x(x)`, `DATASET%y(y)` |
| `w` *(water/sediment, if `includeWaterbodyBreakdown`)* | waterbody index within the cell | scalar integer | `1` | loop over `cell%nReaches` |
| `p` *(soil)* | soil profile index within the cell | scalar integer | `1` | loop over `cell%nSoilProfiles` |
| `waterbody_type` | `riv` (river) or `est` (estuary); or dominant type if aggregated | 3-char string | `riv` | `select type (reach)` ([L177](../src/Data/DataOutputModule.f90#L177)) |
| `land_use` *(soil)* | dominant land use of the profile | string | `arable` | `profile%dominantLandUseName` |

---

## 4. `output_water.csv`

Source object per row: a **reach** (river or estuary),
`reach => me%env%item%colGridCells(x,y)%item%colRiverReaches(w)%item`
([L175](../src/Data/DataOutputModule.f90#L175)). The state variables themselves are
declared on the `WaterBody` base type
([WaterBodyModule.f90 L44–L55](../src/WaterBody/WaterBodyModule.f90#L44)) and are filled
in each timestep by the contained `reactor` (chemistry/partitioning) and the reach's own
`update` routine (transport). If `includeWaterbodyBreakdown` is **off**, the equivalent
`cell%get_*()` accessors are written instead, aggregating the cell's reaches.

| Column | Meaning | Internal structure | Example value of the structure | Calculated from |
|--------|---------|--------------------|--------------------------------|-----------------|
| `m_np(kg)` | pristine NM mass in the water | `real(dp)` array `npDim` (3-D) | `(5,4,8)` array, summed → `3.1e-9` | `reach%m_np`, set by `reactor`; CSV = `sum(reach%m_np)` |
| `C_np(kg/m3)` | pristine NM concentration | 3-D `npDim` | summed → `2.0e-12` | `reach%C_np` = `m_np / volume` |
| `m_transformed(kg)` | transformed (e.g. dissolved-then-precipitated) NM mass | 3-D `npDim` | summed scalar | `reach%m_transformed` |
| `C_transformed(kg/m3)` | transformed NM concentration | 3-D `npDim` | summed scalar | `reach%C_transformed` |
| `m_dissolved(kg)` | dissolved NM (ionic) mass | scalar `real(dp)` | `4.5e-10` | `reach%m_dissolved` |
| `C_dissolved(kg/m3)` | dissolved NM concentration | scalar `real(dp)` | `3.0e-13` | `reach%C_dissolved` |
| `m_np_deposited(kg)` | pristine NM settled to bed this step | 3-D `npDim` (a flux field) | summed scalar | `reach%j_nm%deposition` |
| `m_transformed_deposited(kg)` | transformed NM deposited | 3-D `npDim` | summed scalar | `reach%j_nm_transformed%deposition` |
| `m_np_resuspended(kg)` | pristine NM resuspended from bed | 3-D `npDim` | summed scalar | `reach%j_nm%resuspension` |
| `m_transformed_resuspended(kg)` | transformed NM resuspended | 3-D `npDim` | summed scalar | `reach%j_nm_transformed%resuspension` |
| `m_np_outflow(kg)` | pristine NM leaving downstream | 3-D `npDim` | summed scalar | `reach%j_nm%outflow` |
| `m_transformed_outflow(kg)` | transformed NM leaving downstream | 3-D `npDim` | summed scalar | `reach%j_nm_transformed%outflow` |
| `m_dissolved_outflow(kg)` | dissolved NM leaving downstream | scalar | `1.2e-10` | `reach%j_dissolved%outflow` |
| `m_spm(kg)` | suspended sediment mass | `real(dp)` array, 1-D `nSizeClassesSpm` | `(5)` array, summed → `1500.0` | `reach%m_spm` |
| `C_spm(kg/m3)` | suspended sediment concentration | 1-D `nSizeClassesSpm` | summed → `0.03` | `reach%C_spm` = `m_spm / volume` |
| `volume(m3)` | water volume in the reach | scalar | `25000.0` | `reach%volume` |
| `depth(m)` | water depth | scalar | `0.8` | `reach%depth` |
| `flow(m3/s)` | outflow discharge | scalar | `12.5` | `reach%Q%outflow / C%timeStep` |

### Optional water columns

**If `C%includeSpmSizeClassBreakdown`** — the 1-D SPM arrays are unrolled, one pair of
columns per size class `i`:

| Column | Meaning | Structure | Example | From |
|--------|---------|-----------|---------|------|
| `m_spm_sci(kg)` | sediment mass in size class *i* | one element of `m_spm(:)` | `m_spm(3) = 420.0` | `reach%m_spm(i)` |
| `C_spm_sci(kg/m3)` | sediment conc in size class *i* | one element of `C_spm(:)` | `0.008` | `reach%C_spm(i)` |

**If `C%includeSedimentFluxes`** — SPM flux terms (each a 1-D `SPMFlows` field,
summed):

| Column | Meaning | From |
|--------|---------|------|
| `m_spm_erosion(kg)` | sediment entering via soil erosion | `reach%j_spm%soilErosion` |
| `m_spm_dep(kg)` | sediment deposited to bed | `reach%j_spm%deposition` |
| `m_spm_res(kg)` | sediment resuspended from bed | `reach%j_spm%resuspension` |
| `m_spm_inflow(kg)` | sediment from upstream inflow | `reach%j_spm%inflow` |
| `m_spm_outflow(kg)` | sediment leaving downstream | `reach%j_spm%outflow` |
| `m_spm_bank_erosion(kg)` | sediment from bank erosion | `reach%j_spm%bankErosion` |

---

## 5. `output_sediment.csv`

Source object: the **bed sediment** contained in each reach, `reach%bedSediment`
([L290](../src/Data/DataOutputModule.f90#L290)). NM masses come back from the bed in
**kg/m²** and are multiplied by `reach%bedArea` to give kg.

| Column | Meaning | Internal structure | Example | Calculated from |
|--------|---------|--------------------|---------|-----------------|
| `m_np_total(kg)` | total NM mass in all bed layers | 3-D `npDim` (per m²), summed then ×area | `8.0e-8` | `sum(reach%bedSediment%get_m_np()) * reach%bedArea` |
| `C_np_total(kg/m3)` | NM conc by sediment **volume** | 3-D `npDim` | summed → `1.5e-9` | `reach%bedSediment%get_C_np()` |
| `C_np_total(kg/kg)` | NM conc by sediment **dry mass** | 3-D `npDim` | summed → `4.0e-12` | `reach%bedSediment%get_C_np_byMass()` |
| `m_np_buried(kg)` | NM permanently buried this step | 3-D `npDim`, ×area | `2.0e-11` | `reach%bedSediment%get_m_np_buried() * bedArea` |
| `bed_area(m2)` | area of the bed sediment | scalar | `8000.0` | `reach%bedArea` |
| `sediment_mass(kg)` | total fine sediment mass in the bed | scalar (computed) | `1.2e6` | `reach%bedSediment%Mf_bed_all() * bedArea` |
| `sediment_density(kg/m3)` | mean bulk density of bed sediment | scalar (computed) | `1500.0` | `Mf_bed_all() / sum(C%sedimentLayerDepth)` |

**If `C%includeSedimentLayerBreakdown`** — two columns per bed layer `l`:

| Column | Meaning | Structure | From |
|--------|---------|-----------|------|
| `C_np_li(kg/m3)` | NM conc in layer *l*, by volume | 3-D `npDim` per layer | `reach%bedSediment%get_C_np_l(l)` |
| `C_np_li(kg/kg)` | NM conc in layer *l*, by mass | 3-D `npDim` per layer | `reach%bedSediment%get_C_np_l_byMass(l)` |

> The layer dimension `nSedimentLayers` is what distinguishes sediment output from water
> output. Example: with 4 layers you get `C_np_l1 … C_np_l4` column pairs.

---

## 6. `output_soil.csv`

Source object: a **soil profile**,
`profile => me%env%item%colGridCells(x,y)%item%colSoilProfiles(p)%item`
([L346](../src/Data/DataOutputModule.f90#L346)). One row per profile per cell.
Concentration units are configurable via `C%soilPECUnits` (e.g. `kg/kg`).

| Column | Meaning | Internal structure | Example | Calculated from |
|--------|---------|--------------------|---------|-----------------|
| `m_np_total(kg)` | pristine NM mass in whole profile (free + attached) | 3-D `npDim` | summed → `6.0e-7` | `profile%get_m_np()` |
| `m_transformed_total(kg)` | transformed NM mass | 3-D `npDim` | summed scalar | `profile%get_m_transformed()` |
| `m_dissolved_total(kg)` | dissolved NM mass | scalar | `3.0e-8` | `profile%get_m_dissolved()` |
| `C_np_total(<units>)` | pristine NM conc, mean over layers | 3-D `npDim` | summed scalar | `profile%get_C_np()` |
| `C_transformed_total(<units>)` | transformed NM conc | 3-D `npDim` | summed scalar | `profile%get_C_transformed()` |
| `C_dissolved_total(<units>)` | dissolved NM conc | scalar | `1.0e-11` | `profile%get_C_dissolved()` |
| `m_np_buried(kg)` | pristine NM buried below profile this step | 3-D `npDim` | summed scalar | `profile%m_np_buried` |
| `m_transformed_buried(kg)` | transformed NM buried | 3-D `npDim` | summed scalar | `profile%m_transformed_buried` |
| `m_dissolved_buried(kg)` | dissolved NM buried | scalar | `5.0e-12` | `profile%m_dissolved_buried` |
| `bulk_density(kg/m3)` | soil bulk density | scalar | `1300.0` | `profile%bulkDensity` |

### Optional soil columns

**If `C%includeSoilStateBreakdown`** — splits NM concentration into **free** (mobile)
vs **attached** (bound to soil) using the `freeNM()` / `attachedNM()` helpers
([L354](../src/Data/DataOutputModule.f90#L354)):

| Column | Meaning | From |
|--------|---------|------|
| `C_np_free`, `C_transformed_free` | free NM conc (mean over layers) | `freeNM(profile%get_C_np())` etc. |
| `C_np_att`, `C_transformed_att` | attached NM conc (mean over layers) | `attachedNM(profile%get_C_np())` etc. |

**If `C%includeSoilLayerBreakdown`** — three (or more) columns per soil layer `l`,
read straight from each layer object `profile%colSoilLayers(l)%item`:

| Column | Meaning | Structure | From |
|--------|---------|-----------|------|
| `C_np_li(<units>)` | pristine NM conc in layer *l* | 3-D `npDim` | `colSoilLayers(l)%item%C_np` |
| `C_transformed_li(<units>)` | transformed NM conc in layer *l* | 3-D `npDim` | `colSoilLayers(l)%item%C_transformed` |
| `C_dissolved_li(<units>)` | dissolved NM conc in layer *l* | scalar | `colSoilLayers(l)%item%C_dissolved` |
| `C_np_free_li` / `C_np_att_li` … *(if state breakdown also on)* | free/attached per layer | — | `freeNM(...)` / `attachedNM(...)` of the layer |

**If `C%includeSoilErosionYields`** ([L376](../src/Data/DataOutputModule.f90#L376)):

| Column | Meaning | From |
|--------|---------|------|
| `m_soil_eroded(kg)` | soil mass eroded this step | `sum(profile%erodedSediment) * profile%area` |
| `m_np_eroded(kg)` | pristine NM eroded with soil | `sum(profile%m_np_eroded(:,:,2))` |
| `m_transformed_eroded(kg)` | transformed NM eroded | `sum(profile%m_transformed_eroded(:,:,2))` |

---

## 7. `output_ssd.csv` (steady-state sediment size distribution mode)

Written once per **model iteration** (not per timestep) when running to steady state in
`sediment_size_distribution` mode. Produced by
[`updateSedimentSizeDistributionDataOutput`](../src/Data/DataOutputModule.f90#L389).
The underlying quantity is `me%env%item%get_m_sediment_byLayer()`, a **2-D** array of
shape `(nSedimentLayers, nSizeClassesSpm)`.

| Column | Meaning | Structure | Example | Calculated from |
|--------|---------|-----------|---------|-----------------|
| `i` | model iteration index | scalar integer | `7` | loop iterator `i_model` |
| `ssd_sci_all_layers` | fraction of bed sediment in SPM size class *i*, averaged over layers | one value per SPM size class | `0.21` | `sum(m_sediment_byLayer, dim=1) / sum(m_sediment_byLayer)` |
| `ssd_sci_lj` | size-class fraction for layer *j* | `nSedimentLayers × nSizeClassesSpm` values | `0.18` | `m_sediment_byLayer(j,:) / sum(m_sediment_byLayer(j,:))` |
| `delta_max_lj` | largest change in layer *j*'s distribution since last iteration | one value per layer | `0.004` | `maxval(abs(previousSSDByLayer(j,:) - ...))` |
| `delta_max_all_layers` | largest change in the layer-averaged distribution | scalar | `0.002` | `maxval(abs(previousSSD - sedimentSizeDistribution))` |

`delta_max_all_layers` is the convergence metric the main loop compares against
`C%steadyStateDelta` to decide whether steady state has been reached.

---

## 8. `summary<hash>.md`

Not a table — a human-readable run report. Written at start
([`writeHeadersSimulationSummary`](../src/Data/DataOutputModule.f90#L500)) and at the end
([`finaliseDataOutput`](../src/Data/DataOutputModule.f90#L422)).

**Metadata** (from `C` and `DATASET`): run description, model version, batch flag,
number of chunks, start/end dates, timestep length, number of timesteps, grid
resolution, grid bounds, grid shape, number of non-empty and non-masked cells.

**Final predicted environmental concentrations (PECs)**:

| Line | Meaning | Calculated from |
|------|---------|-----------------|
| Soil, spatial mean on final timestep | mean soil NM conc (kg/kg) | `sum(env%get_C_np_soil())` |
| Water, spatiotemporal mean | mean water NM conc (kg/m³) over all cells & timesteps | mean of `env%C_np_water_t` (a **4-D** accumulator: timestep × `npDim`) |
| Sediment, spatiotemporal mean | mean sediment NM conc (kg/kg) | mean of `env%C_np_sediment_t` (4-D accumulator) |

The `C_np_water_t` / `C_np_sediment_t` accumulators are the arrays grown by one row each
timestep inside
[`updateEnvironment`](../src/Environment/EnvironmentModule.f90#L198).

---

## 9. Appendix — the flux types

The `j_*` "flux" columns above all read from typed structs defined in
[`FlowModule.f90`](../src/WaterBody/FlowModule.f90). Each struct groups the in/out
pathways for one material over a single timestep.

| Struct | Field rank | Fields |
|--------|-----------|--------|
| `WaterFlows` (`reach%Q`) | scalars | `inflow`, `runoff`, `transfers`, `demands`, `outflow` |
| `SPMFlows` (`reach%j_spm`) | 1-D, `nSizeClassesSpm` | `inflow`, `soilErosion`, `bankErosion`, `transfers`, `demands`, `deposition`, `resuspension`, `outflow` |
| `NMFlows` (`reach%j_nm`, `reach%j_nm_transformed`) | 3-D, `npDim` | `inflow`, `soilErosion`, `bankErosion`, `transfers`, `demands`, `deposition`, `resuspension`, `outflow`, `pointSources`, `diffuseSources` |
| `DissolvedFlows` (`reach%j_dissolved`) | scalars | `inflow`, `transfers`, `demands`, `outflow`, `pointSources`, `diffuseSources` |

So, e.g., `reach%j_nm%deposition` is itself a full `(nSizeClassesNM, nFormsNM,
nSizeClassesSpm + nExtraStatesNM)` array describing how much NM of every size/form/state
settled to the bed this timestep — which the water output collapses to the single
`m_np_deposited(kg)` value via `sum()`.

---

### Quick reference: the dimensional "shape" of each compartment

```
WATER     reach state:    NM = 3-D (npDim)          SPM = 1-D (nSizeClassesSpm)
SEDIMENT  reach%bedSediment:  + nSedimentLayers dimension on top of NM
SOIL      profile:            + nSoilLayers dimension, + free/attached split
TIME/SPACE                always columns (t, x, y), never array axes in CSV
CSV cell                  one internal array, sum()-reduced to a scalar
                          (unless a ...Breakdown flag unrolls one dimension)
```
