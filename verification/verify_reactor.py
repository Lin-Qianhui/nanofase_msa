#!/usr/bin/env python3
"""Capture and compare the nine Phase 8 Reactor scenarios.

Reuses the existing exact comparison and WaterBody runner helpers. Generated
inputs, outputs, hashes, commands, and logs stay in --work-dir.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import verify_refactor as comparison
from verify_waterbody import digest, invoke, run_case, setting


ROOT = Path(__file__).resolve().parents[1]


def prepare(work: Path) -> dict:
    inputs = work / "inputs"
    inputs.mkdir()
    for name in (
        "config.example/test-scenario.example.nml",
        "data.example/constants_test-scenario.nml",
        "data.example/test-scenario.nc",
        "data.example/test-scenario-estuary.nc",
    ):
        shutil.copy2(ROOT / name, inputs / Path(name).name)
    base = (inputs / "test-scenario.example.nml").read_text()
    constants = (inputs / "constants_test-scenario.nml").read_text()
    rates = {
        "k_diss_pristine": "1.0e-7",
        "k_diss_transformed": "2.0e-7",
        "k_transform_pristine": "3.0e-7",
    }
    fallback, omitted = re.subn(
        r"(?m)^[ \t]*(?:k_diss_pristine|k_diss_transformed|k_transform_pristine|shear_rate)[ \t]*=.*\n",
        "", constants,
    )
    if omitted != 4:
        raise ValueError(f"Expected four explicit Reactor defaults, found {omitted}")
    combined = constants
    for name, value in rates.items():
        combined = setting(combined, name, value)
    cases = {
        "river": ("test-scenario.nc", constants),
        "defaults": ("test-scenario.nc", fallback),
        "pristine_dissolution": ("test-scenario.nc", setting(constants, "k_diss_pristine", rates["k_diss_pristine"])),
        "transformed_dissolution": ("test-scenario.nc", setting(constants, "k_diss_transformed", rates["k_diss_transformed"])),
        "transformation": ("test-scenario.nc", setting(constants, "k_transform_pristine", rates["k_transform_pristine"])),
        "combined": ("test-scenario.nc", combined),
        "shear_20": ("test-scenario.nc", setting(constants, "shear_rate", "20.0")),
        "estuary": ("test-scenario-estuary.nc", constants),
        "estuary_combined": ("test-scenario-estuary.nc", combined),
    }
    manifest = {}
    for name, (dataset, values) in cases.items():
        case = inputs / name
        case.mkdir()
        constants_path = case / "constants.nml"
        constants_path.write_text(values)
        config = setting(base, "input_file", f'"{inputs / dataset}"')
        config = setting(config, "constants_file", f'"{constants_path}"')
        config_path = case / "config.nml"
        config_path.write_text(config)
        manifest[name] = {"config": str(config_path)}
    return manifest


def branch_evidence(results: dict) -> dict:
    pairs = [("river", "defaults", False)]
    pairs.extend(("river", name, True) for name in (
        "pristine_dissolution", "transformed_dissolution", "transformation", "combined", "shear_20",
    ))
    pairs.append(("estuary", "estuary_combined", True))
    evidence = {}
    for first, second, should_change in pairs:
        changed = [name for name in comparison.CSV_OUTPUTS
                   if results[first]["csv_hashes"][name] != results[second]["csv_hashes"][name]]
        if should_change and "output_water.csv" not in changed:
            raise ValueError(f"Reaction or shear did not affect water output: {first} versus {second}")
        if not should_change and changed:
            raise ValueError(f"Omitted defaults changed scientific output: {changed}")
        evidence[f"{first} versus {second}"] = changed
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work, exe = args.work_dir.resolve(), args.exe.resolve()
    stage = work / ("reference" if args.mode == "capture" else "candidate")
    commands: list[list[str]] = []
    stage_created = False
    try:
        comparison.validate_executable(exe)
        if shutil.which("ncdump") is None:
            raise ValueError("Required tool is unavailable: ncdump")
        stage.mkdir(parents=True)
        stage_created = True
        executable_hash = digest(exe)
        if args.mode == "capture":
            manifest = prepare(work)
            (work / "manifest.json").write_text(json.dumps(manifest, indent=2))
            provenance = {
                "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "executable": str(exe),
                "executable_sha256": executable_hash,
                "input_hashes": {str(p.relative_to(work)): digest(p)
                                 for p in (work / "inputs").rglob("*") if p.is_file()},
            }
            (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
        else:
            manifest = json.loads((work / "manifest.json").read_text())
            for path, expected in json.loads((work / "provenance.json").read_text())["input_hashes"].items():
                if digest(work / path) != expected:
                    raise ValueError(f"Reference input changed: {path}")
        results = {}
        for name, case in manifest.items():
            run = stage / name
            if args.mode == "capture":
                result = run_case(exe, Path(case["config"]), run, commands)
                if result["exit"]:
                    raise ValueError(f"Reference run failed: {name}; inspect {run / 'run.log'}")
                comparison.validate_output_set(run / "output", name)
            else:
                command = [sys.executable, "-B", str(ROOT / "verification/verify_refactor.py"),
                           "--exe", str(exe), "--baseline", str(work / "reference" / name / "output"),
                           "--config", case["config"], "--run-dir", str(run), "--exact"]
                if invoke(command, stage / f"{name}_verify.log", commands):
                    raise ValueError(f"Exact comparison failed: {name}")
                result = {"exit": 0, "csv_hashes": {filename: digest(run / "output" / filename)
                                                   for filename in comparison.CSV_OUTPUTS}}
            results[name] = result
            print(f"PASS {name}", flush=True)
        (stage / "branch_evidence.json").write_text(json.dumps(branch_evidence(results), indent=2))
        if digest(exe) != executable_hash:
            raise ValueError("Executable changed during verification")
        (stage / "executable.json").write_text(json.dumps({"path": str(exe), "sha256": executable_hash}, indent=2))
        (stage / "results.json").write_text(json.dumps(results, indent=2))
        print(f"PASS nine Reactor scenarios and branch checks; evidence: {stage}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, comparison.VerificationError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    finally:
        if stage_created:
            (stage / "commands.json").write_text(json.dumps(commands, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
