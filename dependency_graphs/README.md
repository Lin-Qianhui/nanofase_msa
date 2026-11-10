# Module dependency graphs

Generated with [fortdepend](https://github.com/ZedThree/fort_depend.py).

## Comparing pre- and post-migration structure

The [comparison report](comparison/report.md) presents project-source results first,
then results for the full DOT graphs including vendors. The accompanying
[CSV](comparison/summary.csv) contains pre/post values and changes; the
[JSON](comparison/metrics.json) also records node mappings, dependency/dependent
counts, group contributions, edges, and input fingerprints.

Regenerate all three with Python 3.10+ (standard library only):

```sh
python3 -B dependency_graphs/compare_metrics.py \
  --pre-root /Users/qianhuilin/Documents/nanofase_before_migration/nanofase
```

Optional arguments are `--post-root`, `--pre-dot`, `--post-dot`, and `--output-dir`.
The default post root is this repository. Both default DOT paths are anchored to
this script's directory, using `nanofase_premigration_fixed` and
`nanofase_postmigration`; overriding a source root does not change its DOT path.
The default output directory is `dependency_graphs/comparison`. Existing generated
outputs are replaced; source trees and DOT inputs are read-only. No compiler,
Graphviz installation, or third-party Python package is needed for comparison.

The tool measures DOT module/program nodes, including `main`. It maps these nodes
through case-insensitive Fortran declarations, accepting bare `end module`, and
fails on missing or ambiguous declarations. Production `.f90` files are scanned
beneath `src` and `vendor` (case-insensitive suffix); vendor library directories
named `example`, `examples`, `test`, and `tests` are excluded at the same level as
in the graph-generation command below. DOT edges remain authoritative: scanning
source establishes mapping and grouping, not dependency freshness.

- The primary scope removes vendor nodes and their edges before reachability.
- The full scope preserves all nodes, including the isolated vendor `sparskit`.
- Groups use the first folder beneath `src`, with each root-level source file in
  its own group. Vendor nodes are grouped by library. Groups label the original
  nodes; modularity does not run on a collapsed folder graph.
- CCD includes each starting node once. ACD is `CCD / N`, and propagation cost is
  `100 * CCD / N²` percent. Directed modularity uses direct edges and resolution 1.
- Transitive dependency/dependent counts include direct neighbors but exclude
  self; `component_dependency` adds self back. JSON/CSV preserve floating-point
  precision; the report rounds for readability. Changes are post minus pre, with
  propagation-cost changes expressed in percentage points.

The DOT reader deliberately supports fortdepend's simple format: a `digraph`
header, one node or single directed edge per line, and a closing brace. Identifiers
may be quoted, semicolons are optional, and blank lines or whole-line `//`/`#`
comments are accepted. Attributes, subgraphs, chained edges, inline comments, and
multiple statements on one line fail explicitly instead of being silently lost.
Duplicate edges count once. Empty graphs (including an empty source scope) fail;
modularity and cross-group fraction are undefined with no edges, and density is
undefined for a singleton. Undefined values are JSON `null` or empty CSV cells.

Run the focused checks without building the Fortran project:

```sh
python3 -B -m unittest discover -s dependency_graphs -p 'test_compare_metrics.py' -v
```

## Regenerating the post-migration graph

Run from the repo root:

```zsh
fortdepend -g -i omp_lib netcdf spoof \
  -f $(find src vendor -name '*.f90' | grep -vE 'vendor/[^/]+/(examples?|tests?)/')
```

fortdepend names the output after the current directory, so this writes
`nanofase.dot` and `nanofase.dot.svg` to the repo root (and opens the SVG).
Move them into place:

```zsh
mv nanofase.dot     dependency_graphs/nanofase_postmigration/nanofase_postmigration.dot
mv nanofase.dot.svg dependency_graphs/nanofase_postmigration/nanofase_postmigration.dot.svg
```

## Notes

- **Only pass files the build compiles.** The `grep -v` mirrors the exclusions in
  `CMakeLists.txt`. Without it, `vendor/spoof/example/example.f90` (also
  `program main`) overwrites `src/main.f90`, because fortdepend keys units by
  name, and `main` ends up with no edges.
- **`-i omp_lib netcdf spoof`** drops those modules from the graph.
- **Name every unit's end statement** (`end module ModuleName`). fortdepend fails
  on a bare `end module` with `Unmatched start/end of modules in <file>`.
- **Don't add `-o <file>`** to get an image. `-o` writes a Makefile dependency
  list; the graph comes from `-g`.

## Folders

- `nanofase_postmigration/`: current code.
- `nanofase_premigration/`: original pre-migration graph. Its `main` node has no
  edges because of the collision described above.
- `nanofase_premigration_fixed/`: pre-migration graph regenerated with the same
  file selection. It was built from
  `~/Documents/nanofase_before_migration/nanofase`, which uses bare
  `end module`, so the plain CLI command fails on that tree.
