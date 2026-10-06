#!/usr/bin/env python3
"""Capture and compare Biota concentrations and ordinary model outputs.

Build the identical BiotaScienceTest and BiotaIntegrationTest programs against
each source version. No production output additions or Python packages are needed.
Generated inputs and evidence stay in --work-dir; existing stages are never replaced.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import verify_refactor as comparison
from verify_waterbody import digest, invoke, run_case, setting


ROOT = Path(__file__).resolve().parents[1]
PROBES = ("test/BiotaScienceTest.f90", "test/BiotaIntegrationTest.f90")


def biota_groups(compartments: list[str], harvest: int) -> str:
    count = len(compartments)
    values = {
        "name": [f"'organism_{i}_{kind}'" for i, kind in enumerate(compartments, 1)],
        "compartment": [f"'{kind}'" for kind in compartments],
        "initial_C_org": [f"{i}.0e-6" for i in range(1, count + 1)],
        "k_uptake_np": ["0.2"] * count,
        "k_uptake_transformed": ["0.4"] * count,
        "k_uptake_dissolved": ["0.6"] * count,
        "k_elim_np": ["0.1"] * count,
        "k_elim_transformed": ["0.3"] * count,
        "k_elim_dissolved": ["0.5"] * count,
        "k_growth": ["0.02"] * count,
        "k_death": ["0.04"] * count,
        "stored_fraction": ["0.25"] * count,
        "uptake_from_form": ["'free_and_attached'"] * count,
        "harvest_in_month": [str(harvest)] * count,
    }
    return (f"\n&n_biota_grp\n n_biota = {count}\n/\n&biota\n"
            + "".join(f" {key} = {', '.join(items)}\n" for key, items in values.items()) + "/\n")


def prepare(work: Path) -> dict:
    inputs = work / "inputs"
    inputs.mkdir()
    for name in (
        "config.example/test-scenario.example.nml",
        "config.example/batch_config_test-scenario.example.nml",
        "data.example/constants_test-scenario.nml", "data.example/test-scenario.nc",
        "data.example/test-scenario-estuary.nc", "data.example/test-scenario-t11.nc",
    ):
        shutil.copy2(ROOT / name, inputs / Path(name).name)
    base = (inputs / "test-scenario.example.nml").read_text()
    constants = (inputs / "constants_test-scenario.nml").read_text()
    if "&biota" in constants.lower() or "&n_biota_grp" in constants.lower():
        raise ValueError("Shipped constants now contain Biota; review fixture generation")
    mixed = ["water", "soil", "water", "soil"]
    manifest = {}
    for name, compartments in (
        ("none", []), ("soil", ["soil", "soil"]), ("water", ["water", "water"]),
        ("mixed", mixed), ("estuary", mixed), ("batch", mixed),
    ):
        case = inputs / name
        case.mkdir()
        values = constants + (biota_groups(compartments, 2 if name == "batch" else 0) if compartments else "")
        constants_path = case / "constants.nml"
        constants_path.write_text(values)
        dataset = "test-scenario-estuary.nc" if name == "estuary" else "test-scenario.nc"
        config = setting(base, "input_file", f'"{inputs / dataset}"')
        config = setting(config, "constants_file", f'"{constants_path}"')
        config = setting(config, "warm_up_period", "2")
        config_path = case / "config.nml"
        config_path.write_text(config)
        manifest[name] = {"config": str(config_path), "compartments": compartments}
        if name == "batch":
            batch = (inputs / "batch_config_test-scenario.example.nml").read_text()
            for original in ("test-scenario.nc", "test-scenario-t11.nc"):
                batch = batch.replace(f"data.example/{original}", str(inputs / original))
            batch = batch.replace("data.example/constants_test-scenario.nml", str(constants_path))
            batch = setting(batch, "start_dates", '"2015-01-25", "2015-02-04", "2015-03-01"')
            batch_path = case / "batch.nml"
            batch_path.write_text(batch)
            manifest[name]["batch"] = str(batch_path)
    return manifest


def trace(log: Path, destination: Path, prefixes: tuple[str, ...]) -> list[str]:
    lines = [line.strip() for line in log.read_text().splitlines() if line.startswith(prefixes)]
    if not lines:
        raise ValueError(f"No state records in {log}")
    for line in lines:
        if line.startswith(("DIRECT ", "STATE ")):
            if not all(math.isfinite(float(value)) for value in line.split()[-2:]):
                raise ValueError(f"Non-finite Biota concentration: {line}")
    destination.write_text("\n".join(lines) + "\n")
    return lines


def integration_evidence(name: str, case: dict, lines: list[str]) -> dict:
    initial = {}
    changes = set()
    snapshots = {}
    observed = {}
    harvest = 0
    recovered = set()
    for line in lines:
        fields = line.split()
        phase, chunk, step = fields[1], int(fields[2]), int(fields[3])
        stamp = (phase, chunk, step)
        if fields[0] == "COUNTS":
            snapshots[stamp] = tuple(map(int, fields[4:7]))
            continue
        kind, index = fields[4], int(fields[10])
        compartment = "soil" if kind == "soil" else "water"
        if index < 1 or index > len(case["compartments"]) or case["compartments"][index - 1] != compartment:
            raise ValueError(f"Wrong organism selected in {name}: {line}")
        identity = tuple(fields[4:11])
        concentration = tuple(map(float, fields[-2:]))
        counts = observed.setdefault(stamp, [0, 0, 0])
        counts[{"soil": 0, "riv": 1, "est": 2}[kind]] += 1
        if phase == "created":
            initial[identity] = concentration
        elif concentration != initial[identity]:
            changes.add(kind)
        if name == "batch" and phase == "update" and chunk == 2:
            if concentration != (0.0, 0.0):
                raise ValueError("February batch did not retain harvest resets")
            harvest += 1
        if name == "batch" and phase == "update" and chunk == 3 and any(value > 0 for value in concentration):
            recovered.add(compartment)
    if not snapshots or any(tuple(observed.get(key, [0, 0, 0])) != count for key, count in snapshots.items()):
        raise ValueError(f"State records disagree with organism counts in {name}")
    expected_kinds = set()
    if "soil" in case["compartments"]:
        expected_kinds.add("soil")
    if "water" in case["compartments"]:
        expected_kinds.add("est" if name == "estuary" else "riv")
    if {key[0] for key in initial} != expected_kinds or changes != expected_kinds:
        raise ValueError(f"Organisms were not created and updated as expected in {name}: {changes}")
    if name == "batch" and (not harvest or recovered != {"soil", "water"}):
        raise ValueError("Batch dates did not exercise harvest and subsequent recovery in both compartments")
    if not any(key[0] == "warmup" for key in snapshots) or not any(key[0] == "update" for key in snapshots):
        raise ValueError("Warm-up and normal update paths were not both exercised")
    return {"organisms": len(initial), "snapshots": len(snapshots), "changed_kinds": sorted(changes),
            "harvest_records": harvest, "recovered_compartments": sorted(recovered)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--science-exe", required=True, type=Path)
    parser.add_argument("--integration-exe", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    executables = {"model": args.exe.resolve(), "science": args.science_exe.resolve(),
                   "integration": args.integration_exe.resolve()}
    stage = work / ("reference" if args.mode == "capture" else "candidate")
    commands = []
    created = False
    try:
        for exe in executables.values():
            comparison.validate_executable(exe)
        if shutil.which("ncdump") is None:
            raise ValueError("Required tool is unavailable: ncdump")
        stage.mkdir(parents=True)
        created = True
        hashes = {key: {"path": str(exe), "sha256": digest(exe)} for key, exe in executables.items()}
        probe_hashes = {name: digest(ROOT / name) for name in PROBES}
        if args.mode == "capture":
            manifest = prepare(work)
            (work / "manifest.json").write_text(json.dumps(manifest, indent=2))
            provenance = {
                "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "executables": hashes, "probe_source_hashes": probe_hashes,
                "input_hashes": {str(p.relative_to(work)): digest(p)
                                 for p in (work / "inputs").rglob("*") if p.is_file()},
            }
            (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
        else:
            manifest = json.loads((work / "manifest.json").read_text())
            provenance = json.loads((work / "provenance.json").read_text())
            if provenance["probe_source_hashes"] != probe_hashes:
                raise ValueError("Probe source changed since reference capture; rebuild both probes and recapture")
            for path, expected in provenance["input_hashes"].items():
                if digest(work / path) != expected:
                    raise ValueError(f"Reference input changed: {path}")
        if invoke([str(executables["science"])], stage / "direct.log", commands):
            raise ValueError(f"Direct Biota check failed: {stage / 'direct.log'}")
        direct = trace(stage / "direct.log", stage / "direct.txt", ("DIRECT ",))
        if args.mode == "compare":
            comparison.compare_binary_files(work / "reference/direct.txt", stage / "direct.txt", "Biota direct state")
        evidence = {"direct_records": len(direct)}
        for name, case in manifest.items():
            extra = [case["batch"]] if "batch" in case else []
            run = stage / name
            result = run_case(executables["model"], Path(case["config"]), run, commands, extra)
            if result["exit"]:
                raise ValueError(f"Biota model scenario failed: {run / 'run.log'}")
            comparison.validate_output_set(run / "output", name)
            probe_dir = run / "probe"
            probe_dir.mkdir()
            probe_config, _ = comparison.write_run_config(Path(case["config"]), probe_dir)
            if invoke([str(executables["integration"]), str(probe_config), *extra], probe_dir / "run.log", commands):
                raise ValueError(f"Biota integration check failed: {probe_dir / 'run.log'}")
            state_path = run / "state.txt"
            lines = trace(probe_dir / "run.log", state_path, ("STATE ", "COUNTS "))
            evidence[name] = integration_evidence(name, case, lines)
            if args.mode == "compare":
                reference = work / "reference" / name
                comparison.compare_binary_files(reference / "state.txt", state_path, f"Biota {name} state")
                comparison.compare_outputs(reference / "output", run / "output", comparison.Tolerance(0, 0), exact=True)
            print(f"PASS {name}: state and model output", flush=True)
        for key, exe in executables.items():
            if digest(exe) != hashes[key]["sha256"]:
                raise ValueError(f"Executable changed during verification: {exe}")
        (stage / "executables.json").write_text(json.dumps(hashes, indent=2))
        (stage / "branch_evidence.json").write_text(json.dumps(evidence, indent=2))
        print(f"PASS Biota direct checks and six integration scenarios; evidence: {stage}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, comparison.VerificationError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    finally:
        if created:
            (stage / "commands.json").write_text(json.dumps(commands, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
