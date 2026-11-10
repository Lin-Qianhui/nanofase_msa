#!/usr/bin/env python3
"""Measure the supplied NanoFASE snapshots without changing either source tree.

Uses the existing statement scanner, graph calculations, and audited dataflow
exports. No compiler or third-party Python package is required. Field metrics
fail closed if a dataflow input is missing sources or has stale source hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dependency_graphs"))
from compare_metrics import (  # noqa: E402
    Graph, NodeSource, analyze_graph, fortran_statements, parse_dot,
    source_group, unit_names,
)

USE = re.compile(
    r"use\s*(?:,\s*(?:non_)?intrinsic\s*::\s*|::\s*)?([a-z_]\w*)\b", re.I
)
FIELDS = [
    ("includeAttachment", "soilconfigmodule", "soilconfig%includeattachment"),
    ("includeBioturbation", "soilconfigmodule", "soilconfig%includebioturbation"),
    ("includePointSources", "sourceconfigmodule", "sourceconfig%includepointsources"),
    ("includeEstuary", "waterbodyconfigmodule", "waterbodyconfig%includeestuary"),
    ("sedimentLayerDepth", "bedsedimentconfigmodule", "bedsedimentconfig%sedimentlayerdepth"),
    ("npDim", "modeldimensionsmodule", "npdim"),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(root, dataflow_path, dot_path, before):
    units, hashes, edges = {}, {}, set()
    statements = wildcard = 0
    for path in sorted((root / "src").rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".f90":
            continue
        source = path.read_text()
        names = unit_names(source)
        if len(names) != 1 or names[0] in units:
            raise ValueError(f"Expected one unique source unit: {path}: {names}")
        name = names[0]
        relative = path.relative_to(root).as_posix()
        hashes[relative] = digest(path)
        logical = list(fortran_statements(source))
        units[name] = {
            "file": relative, "physical_lines": len(source.splitlines()),
            "logical_statements": len(logical),
        }
        for statement in logical:
            match = USE.match(statement)
            if match:
                edges.add((name, match[1].lower()))
                statements += 1
                wildcard += not bool(re.search(r"\bonly\s*:", statement, re.I))

    # Include procedure/interface-scope USEs; remove external/vendor endpoints.
    edges = {(a, b) for a, b in edges if b in units}
    graph = Graph(frozenset(units), frozenset(edges))
    mapping = {u: NodeSource(v["file"], source_group(v["file"])) for u, v in units.items()}
    graph_metrics = analyze_graph(graph, mapping)
    dot = parse_dot(dot_path.read_text()).induced(set(units))
    dot_matches = graph == dot
    if not dot_matches:
        raise ValueError(f"Source graph differs from existing DOT snapshot: {dot_path}")

    data = json.loads(dataflow_path.read_text())
    recorded_src = set()
    for record in data["sources"]:
        path = Path(record["path"])
        if not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError(f"Stale or missing dataflow source: {path}; regenerate dataflow first")
        if path.is_relative_to(root / "src"):
            recorded_src.add(path.relative_to(root).as_posix())
    if recorded_src != set(hashes):
        raise ValueError("Dataflow input does not cover exactly the current production sources")

    fields = {}
    for field, owner, variable in FIELDS:
        if before:
            owner, variable = "globalsmodule", "c%" + field.lower()
        access = [a for a in data["accesses"]
                  if a["owner"].lower() == owner and a["var"].lower() == variable
                  and a["home"].lower() in units and a["home"].lower() != owner]
        evidence = [a for a in data["evidence"]
                    if a["owner"].lower() == owner and a["var"].lower() == variable
                    and a["home"].lower() in units and a["home"].lower() != owner]
        fields[field] = {
            "owner": owner, "variable": variable,
            "readers": sorted({a["home"] for a in access if "R" in a["mode"]}),
            "writers": sorted({a["home"] for a in access if "W" in a["mode"]}),
            "uncertain": sorted({a["home"] for a in access if "?" in a["mode"]}),
            "evidence": evidence,
        }

    return {
        "root": str(root), "source_sha256": hashes, "units": units,
        "graph": graph_metrics, "edges": sorted(edges),
        "use_statements": statements, "use_without_only": wildcard,
        "use_with_only_percent": 100 * (statements - wildcard) / statements,
        "checks": {
            "source_graph_matches_dot": dot_matches,
            "dataflow_hashes_verified": len(data["sources"]),
            "dataflow_src_coverage_exact": True,
        },
        "inputs": {
            "dot": {"path": str(dot_path), "sha256": digest(dot_path)},
            "dataflow": {"path": str(dataflow_path), "sha256": digest(dataflow_path)},
        },
        "fields": fields,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-root", type=Path, required=True)
    parser.add_argument("--post-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("metrics.json"))
    args = parser.parse_args()
    result = {
        "schema_version": 1,
        "method": {
            "scope": "Production src/*.f90 units including main; exclude vendors and tests from metrics",
            "edge": "A -> B means a USE of B anywhere in A's source, including interfaces",
            "dependent_counts": "Deduplicated reverse reachability; exclude changed unit itself",
            "interpretation": "Potential source dependency exposure; neither edits nor measured recompilation",
            "field_readers": "Direct static may-read relationships, excluding owner; not runtime propagation",
            "use_counts": "All USE statements, including external imports and repeated procedure-scope imports",
            "limits": "No preprocessing or compiler dependency tracing; dataflow retains documented alias/call limitations",
        },
    }
    for label, root, stem, dot in [
        ("pre", args.pre_root, "premigration", "nanofase_premigration_fixed/nanofase_premigration.dot"),
        ("post", args.post_root, "postmigration", "nanofase_postmigration/nanofase_postmigration.dot"),
    ]:
        result[label] = measure(
            root.resolve(), ROOT / "dataflow" / f"flow_{stem}.json",
            ROOT / "dependency_graphs" / dot, label == "pre",
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for label in ("pre", "post"):
        snap = result[label]
        print(f"{label}: {len(snap['units'])} source units, {len(snap['edges'])} edges; "
              f"DOT agrees; {snap['checks']['dataflow_hashes_verified']} dataflow source hashes verified")
        print("  Field readers: " + ", ".join(
            f"{name}={len(value['readers'])}" for name, value in snap["fields"].items()))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
