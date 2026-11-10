#!/usr/bin/env python3
"""Compare fortdepend snapshots using Python 3.10+ and the standard library."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCOPES = {"src": "Project source only (primary)", "full": "Full DOT graphs (secondary)"}
EXCLUDED_VENDOR_FOLDERS = {"example", "examples", "test", "tests"}
IDENTIFIER = r'(?:[A-Za-z_][A-Za-z_0-9]*|"[A-Za-z_][A-Za-z_0-9]*")'
DOT_HEADER = re.compile(r'(?:strict\s+)?digraph(?:\s+(?:"[^"\\]*"|[A-Za-z_][A-Za-z_0-9]*))?\s*\{')
DOT_STATEMENT = re.compile(rf'({IDENTIFIER})(?:\s*->\s*({IDENTIFIER}))?\s*;?')
UNIT_DECLARATION = re.compile(
    r'^(?:module\s+(?!procedure\b|subroutine\b|function\b)|program\s+)'
    r'([A-Za-z_][A-Za-z_0-9]*)\s*$', re.I)

# Key, report label, machine-readable unit. Changes always mean post minus pre.
METRICS = (
    ("node_count", "Nodes", "count"),
    ("edge_count", "Direct edges", "count"),
    ("group_count", "Groups", "count"),
    ("ccd", "Cumulative Component Dependency (CCD)", "count"),
    ("acd", "Average Component Dependency (ACD)", "components"),
    ("propagation_cost_percent", "Propagation cost", "percent"),
    ("directed_modularity", "Directed folder modularity", "score"),
    ("direct_edge_density", "Direct-edge density (excluding self-loops)", "fraction"),
    ("cross_group_edge_count", "Cross-group direct edges", "count"),
    ("cross_group_edge_fraction", "Cross-group direct-edge fraction", "fraction"),
    ("cyclic_component_count", "Cyclic strongly connected components", "count"),
    ("cyclic_node_count", "Nodes in cycles", "count"),
    ("largest_component_size", "Largest strongly connected component", "count"),
    ("isolated_node_count", "Isolated nodes", "count"),
)

DEFINITIONS = {
    "edge_direction": "A -> B means A depends on B; edges are unweighted and deduplicated.",
    "node_granularity": "DOT module/program units, including main and isolated nodes.",
    "src_scope": "Induced subgraph of nodes mapped beneath src; remove vendor nodes before reachability.",
    "full_scope": "Every node and edge in the supplied DOT graph, including isolated vendor nodes.",
    "partition": "First directory beneath src; each root-level src file is its own group; vendors by library.",
    "ccd": "Sum of unique reachable-node counts, including the starting node exactly once.",
    "acd": "CCD / N.",
    "propagation_cost_percent": "100 * CCD / N^2; includes the visibility-matrix diagonal.",
    "directed_modularity": "Sum_g [L_g / m - K_out_g * K_in_g / m^2], resolution 1, on direct edges.",
    "direct_edge_density": "Non-self direct edges / [N * (N - 1)]; undefined for N = 1.",
    "cross_group_edge_fraction": "Direct edges with different endpoint groups / all direct edges.",
    "transitive_counts": "Unique nodes reachable by one or more edges, including direct neighbors but excluding self.",
    "component_dependency": "Transitive dependency count + 1 (self).",
    "direct_counts": "Distinct direct neighbors in the supplied graph; explicit self-loops, if present, count.",
    "cyclic_components": "Strongly connected components of size > 1, or singleton nodes with explicit self-loops.",
    "undefined_values": "JSON null / empty CSV cells / 'undefined' in Markdown; modularity and cross-group fraction for m = 0.",
    "changes": "Post minus pre; propagation-cost changes are percentage points.",
    "source_manifest_sha256": "SHA-256 of sorted UTF-8 records: relative_path + NUL + file_sha256 + newline.",
}


@dataclass(frozen=True)
class Graph:
    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]

    def induced(self, nodes: set[str]) -> Graph:
        return Graph(frozenset(nodes), frozenset((u, v) for u, v in self.edges if u in nodes and v in nodes))


@dataclass(frozen=True)
class NodeSource:
    file: str
    group: str


def parse_dot(text: str, label: str = "DOT input") -> Graph:
    """Read fortdepend's one-statement-per-line format, rejecting other DOT syntax."""
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    started = closed = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        where = f"{label}:{number}"
        if not started:
            if not DOT_HEADER.fullmatch(line):
                raise ValueError(f"{where}: expected a digraph header with an opening brace on its own line")
            started = True
        elif closed:
            raise ValueError(f"{where}: unexpected content after the closing brace")
        elif line in ("}", "};"):
            closed = True
        else:
            match = DOT_STATEMENT.fullmatch(line)
            if not match:
                raise ValueError(f"{where}: unsupported DOT statement; expected one node or A -> B per line")
            source, target = (value.strip('"') if value else None for value in match.groups())
            nodes.add(source)
            if target is not None:
                nodes.add(target)
                edges.add((source, target))
    if not started or not closed:
        raise ValueError(f"{label}: incomplete digraph (missing header or closing brace)")
    if not nodes:
        raise ValueError(f"{label}: empty graphs are not supported")
    return Graph(frozenset(nodes), frozenset(edges))


def fortran_statements(source: str):
    """Remove strings/comments and join free-form continuations before scanning declarations."""
    quote = None
    pending = ""
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue
        code = []
        i = 0
        while i < len(line):
            char = line[i]
            if quote:
                if char == quote:
                    if i + 1 < len(line) and line[i + 1] == quote:
                        code.extend("  ")
                        i += 2
                        continue
                    quote = None
                code.append(" ")
            elif char in ("'", '"'):
                quote = char
                code.append(" ")
            elif char == "!":
                break
            else:
                code.append(char)
            i += 1
        clean = "".join(code).strip()
        if not clean:
            continue
        if pending and clean.startswith("&"):
            clean = clean[1:]
        continued = clean.endswith("&")
        pending += clean[:-1] if continued else clean
        if continued:
            continue
        yield from (part.strip() for part in pending.split(";") if part.strip())
        pending = ""
    if pending:
        raise ValueError("unterminated Fortran continuation")


def unit_names(source: str) -> list[str]:
    return [match.group(1).lower() for statement in fortran_statements(source)
            if (match := UNIT_DECLARATION.fullmatch(statement))]


def source_group(relative: str) -> str:
    parts = Path(relative).parts
    if parts[0] == "src":
        return relative if len(parts) == 2 else "/".join(parts[:2])
    if parts[0] == "vendor" and len(parts) >= 3:
        return "/".join(parts[:2])
    raise ValueError(f"source is outside src/vendor: {relative}")


def scan_sources(root: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    if not (root / "src").is_dir():
        raise ValueError(f"source root has no src directory: {root}")
    declarations = defaultdict(list)
    hashes = {}
    for folder in ("src", "vendor"):
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".f90":
                continue
            relative = path.relative_to(root)
            parts = relative.parts
            if folder == "vendor" and len(parts) >= 4 and parts[2] in EXCLUDED_VENDOR_FOLDERS:
                continue
            raw = path.read_bytes()
            name = relative.as_posix()
            hashes[name] = hashlib.sha256(raw).hexdigest()
            try:
                names = unit_names(raw.decode("utf-8", errors="replace"))
            except ValueError as error:
                raise ValueError(f"{path}: {error}") from error
            for unit in names:
                declarations[unit].append(name)
    return dict(declarations), dict(sorted(hashes.items()))


def map_nodes(graph: Graph, declarations: dict[str, list[str]]) -> dict[str, NodeSource]:
    mapping = {}
    errors = []
    seen_units = {}
    for node in sorted(graph.nodes):
        unit = node.lower()
        candidates = declarations.get(unit, [])
        if not candidates:
            errors.append(f"node {node!r}: no module/program declaration found in production sources")
        elif len(candidates) != 1:
            errors.append(f"node {node!r}: ambiguous declarations: {', '.join(candidates)}")
        elif unit in seen_units:
            errors.append(f"nodes {seen_units[unit]!r} and {node!r} name the same case-insensitive Fortran unit")
        else:
            seen_units[unit] = node
            mapping[node] = NodeSource(candidates[0], source_group(candidates[0]))
    if errors:
        raise ValueError("cannot map DOT nodes:\n  " + "\n  ".join(errors))
    return mapping


def analyze_graph(graph: Graph, mapping: dict[str, NodeSource]) -> dict:
    if not graph.nodes:
        raise ValueError("cannot analyze an empty graph (including an empty src scope)")
    if set(mapping) != graph.nodes:
        raise ValueError("source mapping must partition exactly the graph's nodes")
    outgoing = {node: set() for node in sorted(graph.nodes)}
    incoming = {node: set() for node in sorted(graph.nodes)}
    for u, v in graph.edges:
        outgoing[u].add(v)
        incoming[v].add(u)
    reachable = {}
    for node in outgoing:
        visited = {node}
        stack = [node]
        while stack:
            for neighbor in outgoing[stack.pop()] - visited:
                visited.add(neighbor)
                stack.append(neighbor)
        reachable[node] = visited

    # Mutual reachability is an equivalence relation. Reuse the already computed
    # closure to obtain SCCs without a second graph algorithm or recursion limit.
    components = []
    assigned = set()
    for node in outgoing:
        if node not in assigned:
            component = sorted(other for other in reachable[node] if node in reachable[other])
            components.append(component)
            assigned.update(component)
    cyclic = [part for part in components if len(part) > 1 or (part[0], part[0]) in graph.edges]
    n, m = len(graph.nodes), len(graph.edges)
    group_nodes = defaultdict(list)
    for node in outgoing:
        group_nodes[mapping[node].group].append(node)
    groups = {}
    modularity_numerator = 0
    internal_count = 0
    for group, members in sorted(group_nodes.items()):
        internal = sum(mapping[u].group == group and mapping[v].group == group for u, v in graph.edges)
        out_degree = sum(len(outgoing[node]) for node in members)
        in_degree = sum(len(incoming[node]) for node in members)
        numerator = internal * m - out_degree * in_degree
        modularity_numerator += numerator
        internal_count += internal
        groups[group] = {
            "nodes": members, "internal_edge_count": internal,
            "out_degree_sum": out_degree, "in_degree_sum": in_degree,
            "modularity_contribution": numerator / m**2 if m else None,
        }
    ccd = sum(len(value) for value in reachable.values())
    isolates = [node for node in outgoing if not outgoing[node] and not incoming[node]]
    metrics = {
        "node_count": n, "edge_count": m, "group_count": len(groups),
        "ccd": ccd, "acd": ccd / n, "propagation_cost_percent": 100 * ccd / n**2,
        "directed_modularity": modularity_numerator / m**2 if m else None,
        "direct_edge_density": sum(u != v for u, v in graph.edges) / (n * (n - 1)) if n > 1 else None,
        "cross_group_edge_count": m - internal_count,
        "cross_group_edge_fraction": (m - internal_count) / m if m else None,
        "cyclic_component_count": len(cyclic), "cyclic_node_count": sum(map(len, cyclic)),
        "largest_component_size": max(map(len, components)), "isolated_node_count": len(isolates),
    }
    node_metrics = {}
    for node in outgoing:
        node_metrics[node] = {
            **asdict(mapping[node]),
            "direct_dependency_count": len(outgoing[node]),
            "direct_dependent_count": len(incoming[node]),
            "transitive_dependency_count": len(reachable[node]) - 1,
            "transitive_dependent_count": sum(node in value for value in reachable.values()) - 1,
            "component_dependency": len(reachable[node]),
        }
    return {
        "metrics": metrics, "nodes": node_metrics, "groups": groups,
        "is_acyclic": not cyclic, "cyclic_components": cyclic, "isolated_nodes": isolates,
    }


def load_snapshot(root: Path, dot: Path) -> dict:
    root, dot = root.resolve(), dot.resolve()
    raw = dot.read_bytes()
    graph = parse_dot(raw.decode("utf-8"), str(dot))
    declarations, hashes = scan_sources(root)
    mapping = map_nodes(graph, declarations)
    source_nodes = {node for node, source in mapping.items() if source.file.startswith("src/")}
    manifest = "".join(f"{name}\0{digest}\n" for name, digest in hashes.items())
    return {
        "inputs": {
            "source_root": str(root),
            "dot": {"path": str(dot), "sha256": hashlib.sha256(raw).hexdigest()},
            "source_manifest_sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
            "source_files_sha256": hashes,
        },
        "node_mapping": {node: asdict(source) for node, source in mapping.items()},
        "edges": [list(edge) for edge in sorted(graph.edges)],
        "scopes": {
            "src": analyze_graph(graph.induced(source_nodes), {node: mapping[node] for node in source_nodes}),
            "full": analyze_graph(graph, mapping),
        },
    }


def comparison(pre: dict, post: dict) -> dict:
    comparisons = {}
    for scope in SCOPES:
        rows = {}
        for key, _, unit in METRICS:
            before, after = (snapshot["scopes"][scope]["metrics"][key] for snapshot in (pre, post))
            rows[key] = {
                "unit": unit, "pre": before, "post": after,
                "change": after - before if before is not None and after is not None else None,
                "change_unit": "percentage_points" if unit == "percent" else unit,
            }
        comparisons[scope] = rows
    return {"schema_version": 1, "definitions": DEFINITIONS,
            "snapshots": {"pre": pre, "post": post}, "comparisons": comparisons}


def render_csv(result: dict) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("scope", "metric", "unit", "pre", "post", "change", "change_unit"))
    for scope, rows in result["comparisons"].items():
        for key, row in rows.items():
            writer.writerow((scope, key, row["unit"], row["pre"], row["post"], row["change"], row["change_unit"]))
    return buffer.getvalue()


def format_metric(value, unit: str, change: bool = False) -> str:
    if value is None:
        return "undefined"
    sign = "+" if change else ""
    if unit == "count":
        return format(value, sign + ",d")
    if unit in ("percent", "fraction"):
        scaled = value * 100 if unit == "fraction" else value
        return format(scaled, sign + ".4f") + (" pp" if change else "%")
    return format(value, sign + (".6f" if unit == "score" else ".4f"))


def render_report(result: dict) -> str:
    snapshots = result["snapshots"]
    lines = [
        "# NanoFASE dependency structure: pre- and post-migration", "",
        "This compares the corrected pre-migration DOT snapshot with the post-migration snapshot. "
        "The primary comparison measures project source; the secondary comparison includes vendors.", "",
        "## Results", "",
    ]
    primary = result["comparisons"]["src"]
    lines.extend([
        f"The project graph has {primary['node_count']['pre']} nodes before migration and "
        f"{primary['node_count']['post']} after. ACD changes from {primary['acd']['pre']:.4f} to "
        f"{primary['acd']['post']:.4f}, while propagation cost changes from "
        f"{primary['propagation_cost_percent']['pre']:.4f}% to "
        f"{primary['propagation_cost_percent']['post']:.4f}% "
        f"({primary['propagation_cost_percent']['change']:+.4f} percentage points).", "",
        "Changes below are post minus pre, not relative percentage changes. Density and cross-group "
        "fractions are displayed as percentages here and stored as fractions in JSON/CSV.", "",
    ])
    for scope, title in SCOPES.items():
        lines.extend([f"### {title}", "", "| Metric | Pre | Post | Change |", "|---|---:|---:|---:|"])
        for key, label, unit in METRICS:
            row = result["comparisons"][scope][key]
            values = [format_metric(row[phase], unit, phase == "change") for phase in ("pre", "post", "change")]
            lines.append(f"| {label} | {' | '.join(values)} |")
        lines.append("")
        for phase, snapshot in snapshots.items():
            data = snapshot["scopes"][scope]
            cycles = "; ".join(", ".join(part) for part in data["cyclic_components"]) or "none (acyclic)"
            isolates = ", ".join(data["isolated_nodes"]) or "none"
            lines.append(f"- **{phase.title()}:** cyclic components: {cycles}; isolated nodes: {isolates}.")
        lines.append("")
    lines.extend([
        "## Definitions and interpretation", "",
        "A node is a Fortran module/program unit from the DOT file, including `main`. An edge "
        "`A -> B` means A depends on B. Repeated edges count once, and edges have equal weight.", "",
        "Let R(i) contain i itself and all distinct nodes reachable by following dependency arrows. "
        "Multiple paths to the same node do not increase its contribution:", "",
        "- **CCD = sum of |R(i)|.** Counts self once for every node, including isolated nodes.",
        "- **ACD = CCD / N.** Average Component Dependency is the average inclusive reachable-node count.",
        "- **Propagation cost = 100 × CCD / N².** This is the percentage of entries in the "
        "self-inclusive visibility matrix that are reachable; it is a potential-coupling measure.",
        "- **Directed modularity Q = sum over groups of [L(g)/m − K_out(g) × K_in(g)/m²].** "
        "L(g) counts direct internal edges; K_out and K_in sum all out-/in-degrees in the group. "
        "The resolution is 1. No reachability-derived self-edges are added for this calculation.", "",
        "CCD, ACD and propagation cost are different normalizations of the same reachability information, "
        "not independent evidence. Increasing the number of components can reduce the reachable fraction "
        "while increasing the average reachable count. Module splitting changes the measurement "
        "granularity, so lower propagation cost alone does not establish migration success.", "",
        "Modularity scores the graph together with its supplied folder partition. Higher Q means "
        "more internal connectivity relative to a directed degree-preserving null model. Compare "
        "the actual folder structures using the same grouping rule; group sizes and counts may change. "
        "The score is not a percentage or a universal architecture-quality grade.", "",
        "The migration's stated goals include moving configuration/state ownership into domains and "
        "separating construction from behavior. Shared foundations such as Kernel and ModelDimensions "
        "can legitimately receive many cross-group dependencies. These unweighted graphs cannot "
        "distinguish those dependencies from broad shared-state access, measure field-level ownership, "
        "or estimate actual change probabilities. Interpret the scores alongside the migration's "
        "ownership and layering evidence.", "",
        "### Scope and partition", "",
        "- **Source scope:** remove vendor nodes and their incident edges before computing reachability. "
        "Keep every DOT node mapped under `src`, including orchestration and utility modules.",
        "- **Full scope:** retain all supplied DOT nodes, including isolated vendors. External modules "
        "already omitted by graph generation (`omp_lib`, `netcdf`, `spoof`) are not restored.",
        "- **Groups:** use the first directory beneath `src` (including its descendants); each file "
        "directly under `src` is its own group. Vendor groups use `vendor/<library>`. "
        "Thus `src/Soil/...` belongs to `src/Soil`, and `src/UtilModule.f90` is a separate group.",
        "- **Mapping:** read case-insensitive module/program declarations from production `.f90` files. "
        "Exclude `vendor/<library>/{example,examples,test,tests}/` recursively. "
        "Require exactly one declaration for every graph node; bare `end module` is accepted.",
        "- **Other measures:** direct-edge density excludes explicit self-loops; cross-group fraction "
        "uses direct edges. Cycles are strongly connected components with multiple nodes or an "
        "explicit self-loop. Empty graphs fail; undefined ratios appear as `undefined`/null/empty CSV cells.", "",
        "Folder groups label the existing nodes; they are not collapsed into new graph nodes. "
        "DOT files supply the authoritative edges. Source trees supply identities and partition "
        "membership; the tool does not regenerate dependencies or prove snapshot/source equivalence.", "",
        "### Project units with the most direct dependents", "",
        "These counts use the primary source-only scope. Transitive dependents include direct "
        "dependents and exclude the unit itself. A high count identifies a widely used unit, "
        "but does not by itself distinguish an appropriate foundation from excessive coupling.", "",
        "| Snapshot | Unit | Group | Direct dependents | Transitive dependents |",
        "|---|---|---|---:|---:|",
    ])
    for phase, snapshot in snapshots.items():
        nodes = snapshot["scopes"]["src"]["nodes"]
        for node in sorted(nodes, key=lambda name: (-nodes[name]["direct_dependent_count"], name))[:5]:
            data = nodes[node]
            lines.append(f"| {phase} | `{node}` | `{data['group']}` | {data['direct_dependent_count']} "
                         f"| {data['transitive_dependent_count']} |")
    lines.extend(["", "## Inputs and reproducibility", "",
                  "`metrics.json` records full-precision results, all node mappings and counts, group "
                  "contributions, edges, and SHA-256 hashes of the DOT files and every scanned source file. "
                  "`summary.csv` contains the numerical comparison. Outputs contain no run timestamp "
                  "and are byte-for-byte reproducible for identical inputs at the same paths.", ""])
    for phase, snapshot in snapshots.items():
        inputs = snapshot["inputs"]
        lines.extend([
            f"### {phase.title()} inputs", "",
            f"- Source root: `{inputs['source_root']}`",
            f"- DOT: `{inputs['dot']['path']}`",
            f"- DOT SHA-256: `{inputs['dot']['sha256']}`",
            f"- Scanned source files: {len(inputs['source_files_sha256'])}",
            f"- Source-manifest SHA-256: `{inputs['source_manifest_sha256']}`", "",
        ])
    lines.extend([
        "The manifest hashes sorted UTF-8 records of relative path, a NUL separator, the file's "
        "hex SHA-256, and a newline. Paths identify the local inputs; neither source checkout is edited.", "",
        "## References", "",
        "- [ArchUnit: Lakos cumulative dependency metrics](https://www.archunit.org/userguide/html/000_Index.html#_cumulative_dependency_metrics_by_john_lakos) "
        "documents self-inclusive CCD and ACD.",
        "- [MacCormack, Baldwin and Rusnak (2012)](https://www.hbs.edu/ris/Publication%20Files/Research%20Policy%2041%20%282012%29%201309%E2%80%93%201324_c5c2350e-013c-4065-a2f9-d95eb32177d5.pdf) "
        "describes propagation cost through dependency reachability; this report explicitly uses the self-inclusive convention.",
        "- [Leicht and Newman: Community structure in directed networks](https://arxiv.org/abs/0709.4500) "
        "provides the directed modularity formulation.", "",
    ])
    return "\n".join(lines)


def write_outputs(result: dict, output_dir: Path) -> None:
    contents = {
        "report.md": render_report(result),
        "summary.csv": render_csv(result),
        "metrics.json": json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
    }
    # An explicit output directory must never cause a supplied input to be replaced.
    input_paths = set()
    for snapshot in result["snapshots"].values():
        inputs = snapshot["inputs"]
        input_paths.add(Path(inputs["dot"]["path"]).resolve())
        input_paths.update((Path(inputs["source_root"]) / name).resolve()
                           for name in inputs["source_files_sha256"])
    for name in contents:
        if (output_dir / name).resolve() in input_paths:
            raise ValueError(f"output would overwrite an input: {output_dir / name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in contents.items():
        (output_dir / name).write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-root", type=Path, required=True, help="pre-migration checkout containing src and vendor")
    parser.add_argument("--post-root", type=Path, default=ROOT, help="post-migration checkout (default: this repository)")
    parser.add_argument("--pre-dot", type=Path, default=HERE / "nanofase_premigration_fixed/nanofase_premigration.dot")
    parser.add_argument("--post-dot", type=Path, default=HERE / "nanofase_postmigration/nanofase_postmigration.dot")
    parser.add_argument("--output-dir", type=Path, default=HERE / "comparison")
    args = parser.parse_args()
    try:
        result = comparison(load_snapshot(args.pre_root, args.pre_dot), load_snapshot(args.post_root, args.post_dot))
        write_outputs(result, args.output_dir)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote report.md, summary.csv and metrics.json to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
