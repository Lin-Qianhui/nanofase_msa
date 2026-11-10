"""Hand-calculated metric, mapping and CLI checks; no Fortran build is needed."""

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import compare_metrics as cm


def dot(*statements):
    return 'digraph "fixture.dot" {\n' + '\n'.join(statements) + '\n}\n'


def analyze(*statements, groups=None):
    graph = cm.parse_dot(dot(*statements))
    mapping = {node: cm.NodeSource(f"src/{node}.f90", groups[node] if groups else "src/All")
               for node in graph.nodes}
    return cm.analyze_graph(graph, mapping)


class MetricTests(unittest.TestCase):
    def test_chain_and_edge_direction(self):
        result = analyze("a -> b", "b -> c")
        metrics = result["metrics"]
        self.assertEqual(metrics["ccd"], 6)
        self.assertEqual(metrics["acd"], 2)
        self.assertAlmostEqual(metrics["propagation_cost_percent"], 100 * 6 / 9)
        self.assertEqual(result["nodes"]["a"]["transitive_dependency_count"], 2)
        self.assertEqual(result["nodes"]["a"]["transitive_dependent_count"], 0)
        self.assertEqual(result["nodes"]["c"]["transitive_dependent_count"], 2)
        self.assertEqual(result["nodes"]["c"]["direct_dependent_count"], 1)
        self.assertEqual(metrics["directed_modularity"], 0)
        self.assertTrue(result["is_acyclic"])

    def test_diamond_counts_nodes_not_paths(self):
        result = analyze("a -> b", "a -> c", "b -> d", "c -> d")
        self.assertEqual(result["metrics"]["ccd"], 9)
        self.assertEqual(result["metrics"]["propagation_cost_percent"], 56.25)
        self.assertEqual(result["nodes"]["a"]["component_dependency"], 4)
        self.assertEqual(result["nodes"]["d"]["transitive_dependent_count"], 3)

    def test_cycle_and_isolate(self):
        result = analyze("a -> b", "b -> c", "c -> a", "d")
        self.assertEqual(result["metrics"]["ccd"], 10)
        self.assertEqual(result["metrics"]["propagation_cost_percent"], 62.5)
        self.assertEqual(result["cyclic_components"], [["a", "b", "c"]])
        self.assertEqual(result["metrics"]["cyclic_node_count"], 3)
        self.assertEqual(result["metrics"]["largest_component_size"], 3)
        self.assertEqual(result["isolated_nodes"], ["d"])
        self.assertEqual(result["nodes"]["a"]["transitive_dependency_count"], 2)
        self.assertFalse(result["is_acyclic"])
        self.assertEqual(analyze("a -> b", "b -> c", "c -> a")["metrics"]["propagation_cost_percent"], 100)

    def test_disconnected_grouped_edges(self):
        groups = {"a": "first", "b": "first", "c": "second", "d": "second"}
        result = analyze("a -> b", "c -> d", groups=groups)
        self.assertEqual(result["metrics"]["directed_modularity"], 0.5)
        self.assertEqual(result["groups"]["first"]["modularity_contribution"], 0.25)
        self.assertEqual(result["metrics"]["cross_group_edge_count"], 0)

    def test_directed_modularity_with_unbalanced_degrees(self):
        groups = {"a": "first", "b": "first", "c": "second", "d": "second"}
        result = analyze("a -> b", "a -> c", "b -> c", "c -> d", groups=groups)
        # Group degree products are 3*1 and 1*3. Undirected modularity would be 0.
        self.assertEqual(result["metrics"]["directed_modularity"], 0.125)
        self.assertEqual(result["metrics"]["cross_group_edge_fraction"], 0.5)

    def test_edgeless_graphs_and_explicit_self_loop(self):
        result = analyze("a", "b", "c")
        self.assertEqual(result["metrics"]["ccd"], 3)
        self.assertEqual(result["metrics"]["acd"], 1)
        self.assertEqual(result["metrics"]["direct_edge_density"], 0)
        self.assertIsNone(result["metrics"]["directed_modularity"])
        self.assertIsNone(result["metrics"]["cross_group_edge_fraction"])
        self.assertIsNone(analyze("a")["metrics"]["direct_edge_density"])
        loop = analyze("a -> a")
        self.assertEqual(loop["metrics"]["ccd"], 1)
        self.assertEqual(loop["cyclic_components"], [["a"]])
        self.assertEqual(loop["metrics"]["directed_modularity"], 0)

    def test_source_scope_removes_vendor_paths_before_closure(self):
        graph = cm.parse_dot(dot("a -> vendor", "vendor -> b"))
        mapping = {node: cm.NodeSource(f"src/{node}.f90", node) for node in ("a", "b")}
        result = cm.analyze_graph(graph.induced({"a", "b"}), mapping)
        self.assertEqual(result["metrics"]["ccd"], 2)
        self.assertEqual(result["metrics"]["edge_count"], 0)

    def test_empty_scope_or_incomplete_mapping_fails(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            cm.analyze_graph(cm.Graph(frozenset(), frozenset()), {})
        with self.assertRaisesRegex(ValueError, "partition exactly"):
            cm.analyze_graph(cm.parse_dot(dot("a", "b")), {"a": cm.NodeSource("src/a.f90", "a")})


class DotTests(unittest.TestCase):
    def test_duplicates_quoted_identifiers_and_implicit_nodes(self):
        graph = cm.parse_dot(dot('// comment', '# comment', '"a";', 'a -> "b";', 'a -> b', 'isolated'))
        self.assertEqual(graph.nodes, frozenset({"a", "b", "isolated"}))
        self.assertEqual(graph.edges, frozenset({("a", "b")}))

    def test_rejects_unsupported_syntax_instead_of_silently_dropping_it(self):
        for statement in ('a -> b [weight=2]', 'subgraph cluster_a {', 'a -> b -> c', 'a; b', 'a -- b'):
            with self.subTest(statement=statement), self.assertRaisesRegex(ValueError, r"fixture:2: unsupported"):
                cm.parse_dot(dot(statement), "fixture")

    def test_empty_incomplete_and_multiple_graphs(self):
        for text in (dot(), 'digraph x {\na\n', dot('a') + dot('b')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                cm.parse_dot(text)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_declarations_not_filenames_and_folder_partition(self):
        self.write("src/Soil/nested/unrelated_name.F90", "MODULE SoilUnit\nend module\n")
        self.write("src/UtilModule.f90", "module Helpers\nend module\nmodule Extra\nend module\n")
        self.write("src/main.f90", "PROGRAM Main\nend program\n")
        self.write("vendor/feh/src/different.f90", "module ErrorInstance\nend module\n")
        declarations, hashes = cm.scan_sources(self.root)
        graph = cm.parse_dot(dot("soilunit", "HELPERS", "extra", "main", "errorinstance"))
        mapping = cm.map_nodes(graph, declarations)
        self.assertEqual(mapping["soilunit"].group, "src/Soil")
        self.assertEqual(mapping["HELPERS"].group, "src/UtilModule.f90")
        self.assertEqual(mapping["extra"].group, "src/UtilModule.f90")
        self.assertEqual(mapping["main"].group, "src/main.f90")
        self.assertEqual(mapping["errorinstance"].group, "vendor/feh")
        self.assertEqual(len(hashes), 4)

    def test_vendor_examples_and_tests_cannot_overwrite_main(self):
        self.write("src/main.f90", "program main\nend program\n")
        self.write("src/tests/production.f90", "module production\nend module\n")
        for folder in cm.EXCLUDED_VENDOR_FOLDERS:
            self.write(f"vendor/lib/{folder}/nested/collision.f90", "program main\nend program\n")
        self.write("vendor/lib/src/library.f90", "module library\nend module\n")
        declarations, hashes = cm.scan_sources(self.root)
        self.assertEqual(declarations["main"], ["src/main.f90"])
        self.assertEqual(len(hashes), 3)
        self.assertIn("production", declarations)
        self.assertIn("library", declarations)

    def test_comment_string_procedure_and_continuation_handling(self):
        source = '''! module fake
module &
  ! a comment inside a continued declaration
  &RealUnit; implicit none
character(*) :: text = "module fake!; doubled "" quotes"
interface
  module procedure do_work
  module subroutine routine(x)
  end subroutine
  module pure function get_value()
  end function
end interface
end module
program driver; end program
'''
        self.assertEqual(cm.unit_names(source), ["realunit", "driver"])

    def test_unresolved_ambiguous_and_case_alias_nodes(self):
        graph = cm.parse_dot(dot("missing", "ambiguous"))
        with self.assertRaises(ValueError) as raised:
            cm.map_nodes(graph, {"ambiguous": ["src/a.f90", "src/b.f90"]})
        self.assertIn("no module/program declaration", str(raised.exception))
        self.assertIn("ambiguous declarations: src/a.f90, src/b.f90", str(raised.exception))
        with self.assertRaisesRegex(ValueError, "same case-insensitive"):
            cm.map_nodes(cm.parse_dot(dot("unit", "UNIT")), {"unit": ["src/unit.f90"]})


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roots = {phase: self.root / phase for phase in ("pre", "post")}
        self.dots = {}
        for phase, root in self.roots.items():
            for relative, name in (("src/Group/a.f90", "a"), ("src/b.f90", "b"),
                                   ("vendor/library/src/x.f90", "x")):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"module {name}\nend module\n", encoding="utf-8")
            self.dots[phase] = root / "input.dot"
            statements = ["a -> x", "x -> b"] + (["a -> b"] if phase == "post" else [])
            self.dots[phase].write_text(dot(*statements), encoding="utf-8")
        self.inputs = [path for root in self.roots.values() for path in root.rglob("*") if path.is_file()]

    def run_cli(self, output, seed="1"):
        return subprocess.run(
            [sys.executable, "-B", str(cm.HERE / "compare_metrics.py"),
             "--pre-root", str(self.roots["pre"]), "--post-root", str(self.roots["post"]),
             "--pre-dot", str(self.dots["pre"]), "--post-dot", str(self.dots["post"]),
             "--output-dir", str(output)], cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "PYTHONHASHSEED": seed})

    def test_cli_outputs_precision_fingerprints_determinism_and_input_integrity(self):
        original = {path: path.read_bytes() for path in self.inputs}
        outputs = [self.root / "first", self.root / "second"]
        for seed, output in enumerate(outputs, 1):
            completed = self.run_cli(output, str(seed))
            self.assertEqual(completed.returncode, 0, completed.stderr)
        for name in ("report.md", "summary.csv", "metrics.json"):
            self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes())
        self.assertEqual(original, {path: path.read_bytes() for path in self.inputs})
        result = json.loads((outputs[0] / "metrics.json").read_text())
        self.assertEqual(result["snapshots"]["pre"]["scopes"]["src"]["metrics"]["ccd"], 2)
        self.assertEqual(result["snapshots"]["pre"]["scopes"]["full"]["metrics"]["ccd"], 6)
        self.assertEqual(result["comparisons"]["src"]["propagation_cost_percent"]["change"], 25)
        for phase, snapshot in result["snapshots"].items():
            fingerprints = snapshot["inputs"]
            self.assertEqual(fingerprints["dot"]["sha256"], hashlib.sha256(original[self.dots[phase]]).hexdigest())
            for relative, digest in fingerprints["source_files_sha256"].items():
                self.assertEqual(digest, hashlib.sha256(original[self.roots[phase] / relative]).hexdigest())
        with (outputs[0] / "summary.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2 * len(cm.METRICS))
        modularity = next(row for row in rows if row["scope"] == "src" and row["metric"] == "directed_modularity")
        self.assertEqual(modularity["pre"], "")
        self.assertEqual(modularity["change"], "")
        pc = next(row for row in rows if row["scope"] == "full" and row["metric"] == "propagation_cost_percent")
        self.assertEqual(float(pc["pre"]), 100 * 6 / 9)
        self.assertEqual(pc["change_unit"], "percentage_points")

    def test_bad_mapping_fails_before_writing_outputs(self):
        self.dots["post"].write_text(dot("unknown"), encoding="utf-8")
        output = self.root / "output"
        completed = self.run_cli(output)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("no module/program declaration", completed.stderr)
        self.assertFalse(output.exists())

    def test_output_cannot_overwrite_dot_input(self):
        target = self.roots["pre"] / "report.md"
        target.write_bytes(self.dots["pre"].read_bytes())
        self.dots["pre"] = target
        original = target.read_bytes()
        completed = self.run_cli(self.roots["pre"])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("output would overwrite an input", completed.stderr)
        self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
