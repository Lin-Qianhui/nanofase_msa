#!/usr/bin/env python3
"""Capture and compare repeatable Phase 7 WaterBody scenarios.

Uses only Python's standard library and the project's ncdump/ncgen tools.
All generated inputs, outputs, commands, and logs stay in --work-dir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import verify_refactor as comparison


ROOT = Path(__file__).resolve().parents[1]
CSV_NAMES = comparison.CSV_OUTPUTS


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setting(text: str, name: str, value: str, group: str | None = None) -> str:
    pattern = rf"(?m)^([ \t]*{re.escape(name)}[ \t]*=).*$"
    result, count = re.subn(pattern, lambda m: f"{m[1]} {value}", text)
    if count == 0 and group:
        result, count = re.subn(rf"(?m)^&{group}\s*$", lambda m: f"{m[0]}\n{name} = {value}", text)
    if count != 1:
        raise ValueError(f"Expected one setting or insertion point for {name}, found {count}")
    return result


def water_group(text: str, body: str | None) -> str:
    replacement = "" if body is None else f"&water\n{body}\n/\n"
    result, count = re.subn(r"(?ms)^&water[ \t]*\n.*?^/[ \t]*\n", replacement, text)
    if count != 1:
        raise ValueError("Expected one configuration /water/ group")
    return result


def invoke(command: list[str], log: Path, commands: list[list[str]]) -> int:
    commands.append(command)
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    return result.returncode


def generated_netcdf(source: Path, target: Path, fields: dict[str, tuple[str, str]], commands: list) -> None:
    dump = ["ncdump", str(source)]
    commands.append(dump)
    cdl = subprocess.check_output(dump, text=True)
    declarations = "".join(f"\t{kind} {name}(y, x);\n" for name, (kind, _) in fields.items())
    cdl = cdl.replace("variables:\n", "variables:\n" + declarations, 1)
    assignments = "".join(f"\n {name} = {', '.join([value] * 12)};\n" for name, (_, value) in fields.items())
    cdl = cdl.rsplit("}", 1)[0] + assignments + "}\n"
    cdl_path = target.with_suffix(".cdl")
    cdl_path.write_text(cdl)
    command = ["ncgen", "-k", "netCDF-4", "-o", str(target), str(cdl_path)]
    commands.append(command)
    subprocess.run(command, check=True, capture_output=True, text=True)


def prepare(work: Path, commands: list) -> dict:
    inputs = work / "inputs"
    inputs.mkdir()
    originals = [
        "config.example/test-scenario.example.nml",
        "config.example/batch_config_test-scenario.example.nml",
        "data.example/test-scenario.nc", "data.example/test-scenario-estuary.nc",
        "data.example/test-scenario-t11.nc", "data.example/constants_test-scenario.nml",
    ]
    for name in originals:
        shutil.copy2(ROOT / name, inputs / Path(name).name)
    river = inputs / "test-scenario.nc"
    estuary = inputs / "test-scenario-estuary.nc"
    flat = inputs / "flat-terrain.nc"
    spatial = inputs / "spatial-bank.nc"
    header = subprocess.check_output(["ncdump", "-h", str(river)], text=True)
    estuary_header = subprocess.check_output(["ncdump", "-h", str(estuary)], text=True)
    for field in ("dem", "bank_erosion_alpha", "bank_erosion_beta"):
        if re.search(rf"\b{field}\(", header + estuary_header):
            raise ValueError(f"Shipped fixtures unexpectedly contain {field}; review branch coverage")
    generated_netcdf(river, flat, {"dem": ("short", "100")}, commands)
    generated_netcdf(river, spatial, {
        "bank_erosion_alpha": ("float", "4.0e-9f"),
        "bank_erosion_beta": ("float", "1.2f"),
    }, commands)
    base = (inputs / "test-scenario.example.nml").read_text()
    base = setting(base, "input_file", f'"{river}"')
    constants = (inputs / "constants_test-scenario.nml").read_text()
    fallback = re.sub(r"(?m)^\s*(?:min_water_temperature|max_water_temperature|min_water_temperature_day_of_year)\s*=.*\n", "", constants)
    bank = constants.replace("&water\n", "&water\n bank_erosion_alpha = 2.0e-9\n bank_erosion_beta = 1.1\n")
    explicit = setting(setting(setting(bank, "min_water_temperature", "6.0"),
                               "max_water_temperature", "19.0"), "min_water_temperature_day_of_year", "60")
    cases = {
        "river": (base, constants),
        "missing_water": (water_group(base, None), constants),
        "empty_water": (water_group(base, ""), constants),
        "partial_water": (water_group(base, "include_bank_erosion = .false."), constants),
        "bank_off": (setting(base, "include_bank_erosion", ".false."), constants),
        "estuary": (setting(base, "input_file", f'"{estuary}"'), constants),
        "estuary_as_river": (setting(setting(base, "input_file", f'"{estuary}"'), "include_estuary", ".false."), constants),
        "estuary_1800": (setting(setting(base, "input_file", f'"{estuary}"'), "min_estuary_timestep", "1800"), constants),
        "estuary_bed_off": (setting(setting(base, "input_file", f'"{estuary}"'), "include_bed_sediment", ".false."), constants),
        "constants_fallback": (base, fallback),
        "bank_explicit": (base, bank),
        "constants_explicit": (base, explicit),
        "spatial_bank": (setting(base, "input_file", f'"{spatial}"'), constants),
        "spatial_bank_changed_constants": (setting(base, "input_file", f'"{spatial}"'), bank),
        "terrain_outlet_failure": (setting(base, "input_file", f'"{flat}"'), constants),
        "river_bed_off_failure": (setting(base, "include_bed_sediment", ".false."), constants),
        "unknown_water": (water_group(base, "unknown_water_setting = 1"), constants),
        "malformed_water": (water_group(base, "min_estuary_timestep = 'invalid'"), constants),
    }
    failures = {
        "terrain_outlet_failure": (2, "of array 'dataset%dem' above upper bound"),
        "river_bed_off_failure": (1, "Error trying to return 0D data as REAL(DP)."),
        "unknown_water": (2, "Cannot match namelist object name unknown_water_setting"),
        "malformed_water": (2, "Cannot match namelist object name 'invalid'"),
    }
    manifest = {}
    for name, (config, values) in cases.items():
        case = inputs / name
        case.mkdir()
        constant_path = case / "constants.nml"
        constant_path.write_text(values)
        config = setting(config, "constants_file", f'"{constant_path}"')
        (case / "config.nml").write_text(config)
        manifest[name] = {"config": str(case / "config.nml")}
        if name in failures:
            manifest[name]["failure"] = failures[name]
    # Keep batch references independent of later edits to the shipped files.
    batch = (inputs / "batch_config_test-scenario.example.nml").read_text()
    for path in ("data.example/test-scenario.nc", "data.example/test-scenario-t11.nc", "data.example/constants_test-scenario.nml"):
        batch = batch.replace(path, str(inputs / Path(path).name))
    (inputs / "batch.nml").write_text(batch)
    return manifest


def run_case(exe: Path, config: Path, run: Path, commands: list, extra: list[str] | None = None) -> dict:
    run.mkdir(parents=True)
    copied, output = comparison.write_run_config(config, run)
    status = invoke([str(exe), str(copied), *(extra or [])], run / "run.log", commands)
    return {"exit": status, "csv_hashes": {p.name: digest(p) for p in output.glob("*.csv")}}


def smoke(exe: Path, work: Path, stage: Path, commands: list) -> dict:
    base = Path(json.loads((work / "manifest.json").read_text())["river"]["config"])
    batch = run_case(exe, base, stage / "batch", commands, [str(work / "inputs/batch.nml")])
    if batch["exit"]:
        raise ValueError("Batch run failed")
    summary = (stage / "batch/output/summary.md").read_text()
    if not re.search(r"(?im)^.*batch.*\b3\b", summary) or not re.search(r"(?im)^.*timestep.*\b31\b", summary):
        raise ValueError("Batch summary did not confirm 3 batches and 31 timesteps")
    checkpoint = stage / "checkpoint.dat"
    save_text = setting(base.read_text(), "checkpoint_file", f'"{checkpoint}"')
    save_text = setting(save_text, "save_checkpoint_after_warm_up", ".true.", "checkpoint")
    save_config = stage / "save.nml"
    save_config.write_text(save_text)
    saved = run_case(exe, save_config, stage / "save", commands)
    if saved["exit"] or not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ValueError("Checkpoint save failed")
    load_text = setting(setting(setting(setting(save_text, "save_checkpoint_after_warm_up", ".false."),
                        "reinstate_checkpoint", ".true."), "preserve_timestep", ".true."), "warm_up_period", "0")
    load_config = stage / "reinstate.nml"
    load_config.write_text(load_text)
    loaded = run_case(exe, load_config, stage / "reinstate", commands)
    if loaded["exit"]:
        raise ValueError("Checkpoint reinstate failed")
    return {"batch": batch["exit"], "checkpoint_save": saved["exit"], "checkpoint_reinstate": loaded["exit"],
            "checkpoint_bytes": checkpoint.stat().st_size}


def branch_evidence(results: dict) -> dict:
    pairs = [
        ("river", "bank_off", True), ("river", "missing_water", False),
        ("river", "empty_water", False), ("bank_off", "partial_water", False),
        ("estuary", "estuary_as_river", True), ("estuary", "estuary_1800", True),
        ("estuary", "estuary_bed_off", True), ("river", "constants_fallback", True),
        ("river", "bank_explicit", True), ("constants_fallback", "constants_explicit", True),
        ("river", "spatial_bank", True), ("spatial_bank", "spatial_bank_changed_constants", False),
    ]
    evidence = {}
    for first, second, should_change in pairs:
        changed = [name for name in CSV_NAMES if results[first]["csv_hashes"][name] != results[second]["csv_hashes"][name]]
        if bool(changed) != should_change:
            raise ValueError(f"Unexpected branch coverage: {first} versus {second}: {changed}")
        evidence[f"{first} versus {second}"] = changed
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work, exe = args.work_dir.resolve(), args.exe.resolve()
    commands: list[list[str]] = []
    stage = work / ("reference" if args.mode == "capture" else "candidate")
    stage_created = False
    try:
        comparison.validate_executable(exe)
        for tool in ("ncdump", "ncgen"):
            if shutil.which(tool) is None:
                raise ValueError(f"Required tool is unavailable: {tool}")
        stage.mkdir(parents=True)
        stage_created = True
        if args.mode == "capture":
            manifest = prepare(work, commands)
            (work / "manifest.json").write_text(json.dumps(manifest, indent=2))
            provenance = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                          "executable": str(exe), "executable_sha256": digest(exe),
                          "input_hashes": {str(p.relative_to(work)): digest(p) for p in (work / "inputs").rglob("*") if p.is_file()}}
            (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
        else:
            manifest = json.loads((work / "manifest.json").read_text())
            for path, expected in json.loads((work / "provenance.json").read_text())["input_hashes"].items():
                if digest(work / path) != expected:
                    raise ValueError(f"Reference input changed: {path}")
        results = {}
        for name, case in manifest.items():
            run = stage / name
            if args.mode == "compare" and "failure" not in case:
                command = [sys.executable, str(ROOT / "verification/verify_refactor.py"), "--exe", str(exe),
                           "--baseline", str(work / "reference" / name / "output"), "--config", case["config"],
                           "--run-dir", str(run), "--exact"]
                if invoke(command, stage / f"{name}_verify.log", commands):
                    raise ValueError(f"Exact comparison failed: {name}")
                result = {"exit": 0, "csv_hashes": {name: digest(run / "output" / name) for name in CSV_NAMES}}
            else:
                result = run_case(exe, Path(case["config"]), run, commands)
                if "failure" in case:
                    status, message = case["failure"]
                    log = (run / "run.log").read_text()
                    if result["exit"] != status or message not in log:
                        raise ValueError(f"Expected failure did not match: {name}; inspect {run / 'run.log'}")
                    result["diagnostic"] = message
                elif result["exit"]:
                    raise ValueError(f"Reference run failed: {name}")
                else:
                    comparison.validate_output_set(run / "output", name)
            results[name] = result
            print(f"PASS {name} (exit {result['exit']})", flush=True)
        (stage / "branch_evidence.json").write_text(json.dumps(branch_evidence(results), indent=2))
        results["smoke"] = smoke(exe, work, stage, commands)
        (stage / "results.json").write_text(json.dumps(results, indent=2))
        (stage / "executable.json").write_text(json.dumps({"path": str(exe), "sha256": digest(exe)}, indent=2))
        print(f"PASS batch and checkpoint smoke checks; evidence: {stage}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, comparison.VerificationError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    finally:
        if stage_created:
            (stage / "commands.json").write_text(json.dumps(commands, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
