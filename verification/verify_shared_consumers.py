#!/usr/bin/env python3
"""Capture/compare Phase 10 output choices, input updates, logs and checkpoints.

Build the identical SharedConsumerIntegrationTest against both source versions.
Only the standard library, ncdump and ncgen are required. All generated evidence
stays in --work-dir; a completed or failed stage is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import verify_refactor as comparison
from verify_waterbody import digest, setting


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "test/SharedConsumerIntegrationTest.f90"


def invoke(command: list[str], log: Path, commands: list) -> int:
    commands.append(command)
    with log.open("w") as stream:
        return subprocess.run(command, cwd=log.parent, stdout=stream,
                              stderr=subprocess.STDOUT, timeout=180).returncode


def prepare(work: Path, commands: list) -> dict:
    inputs = work / "inputs"
    inputs.mkdir()
    for name in ("config.example/test-scenario.example.nml",
                 "config.example/batch_config_test-scenario.example.nml",
                 "data.example/constants_test-scenario.nml", "data.example/test-scenario.nc",
                 "data.example/test-scenario-t11.nc"):
        shutil.copy2(ROOT / name, inputs / Path(name).name)
    base = (inputs / "test-scenario.example.nml").read_text()
    base = setting(base, "input_file", f'"{inputs / "test-scenario.nc"}"')
    base = setting(base, "constants_file", f'"{inputs / "constants_test-scenario.nml"}"')
    base = setting(base, "bash_colors", ".true.", "run")
    cases = {}

    def add(name: str, changes: dict | None = None, **metadata) -> None:
        config = base
        for key, (value, group) in (changes or {}).items():
            config = setting(config, key, value, group)
        path = inputs / f"{name}.nml"
        path.write_text(config)
        cases[name] = {"config": str(path), "csv": True, "nc": True, "suffix": "", **metadata}

    for breakdown in (False, True):
        for mode in ("end", "itr"):
            add(f'{"detailed" if breakdown else "aggregated"}_{mode}', {
                "include_waterbody_breakdown": (f".{str(breakdown).lower()}.", "output"),
                "netcdf_write_mode": (f"'{mode}'", "output")}, breakdown=breakdown)
    detail_flags = ("include_waterbody_breakdown", "include_sediment_layer_breakdown",
                    "include_soil_layer_breakdown", "include_soil_state_breakdown",
                    "include_soil_erosion_yields", "include_sediment_fluxes",
                    "include_spm_size_class_breakdown", "write_compartment_stats")
    add("full_detail", {key: (".true.", "output") for key in detail_flags}, stats=True)
    add("minimal_detail", {key: (".false.", "output") for key in (*detail_flags, "write_metadata_as_comment")})
    add("csv_only", {"write_netcdf": (".false.", "output")}, nc=False)
    add("netcdf_only", {"write_csv": (".false.", "output")}, csv=False)
    add("summary_only", {"write_csv": (".false.", "output"), "write_netcdf": (".false.", "output")}, csv=False, nc=False)
    add("suffix", {"output_hash": ("'_phase10'", "run")}, suffix="_phase10")
    add("units", {"soil_pec_units": ("'kg/m3'", "output"), "sediment_pec_units": ("'kg/m3'", "output")})
    add("steady", {"run_to_steady_state": (".true.", "steady_state"),
                   "delta": ("1e9", "steady_state")}, steady=True)
    for colors in (False, True):
        add(f"logging_{str(colors).lower()}", {"write_to_log": (".true.", "run"),
            "bash_colors": (f".{str(colors).lower()}.", "run")}, logging=True, colors=colors)

    # One isolated headwater is a self-contained simulation area.
    mask = inputs / "mask.cdl"
    mask.write_text("netcdf mask {\ndimensions: x = 4; y = 3;\nvariables: byte simulation_mask(y,x);\n"
                    "data: simulation_mask = 0,1,0,0, 0,0,0,0, 0,0,0,0;\n}\n")
    command = ["ncgen", "-o", str(inputs / "mask.nc"), str(mask)]
    commands.append(command)
    subprocess.run(command, check=True, capture_output=True, text=True)
    add("mask", {"simulation_mask": (f'"{inputs / "mask.nc"}"', "run")}, inspect=True)

    # Distinct paths, constants, dates and 10/11/10 lengths expose stale copies.
    constants = (inputs / "constants_test-scenario.nml").read_text()
    for chunk, rate in enumerate((10, 20, 30), 1):
        (inputs / f"constants_{chunk}.nml").write_text(setting(constants, "shear_rate", str(rate)))
    batch = (inputs / "batch_config_test-scenario.example.nml").read_text()
    batch = setting(batch, "input_files", ", ".join(f'"{inputs / name}"' for name in
                    ("test-scenario.nc", "test-scenario-t11.nc", "test-scenario.nc")))
    batch = setting(batch, "constants_files", ", ".join(f'"{inputs / f"constants_{k}.nml"}"' for k in (1,2,3)))
    batch = setting(batch, "start_dates", '"2015-01-25", "2015-02-04", "2015-03-01"')
    (inputs / "batch.nml").write_text(batch)
    for mode in ("end", "itr"):
        add(f"batch_{mode}", {"netcdf_write_mode": (f"'{mode}'", "output")},
            batch=str(inputs / "batch.nml"), inspect=True)

    add("checkpoint_save", {"save_checkpoint": (".true.", "checkpoint"),
        "checkpoint_file": (f'"{work / "generated_checkpoint.dat"}"', "checkpoint")})
    # Audit paths finish at startup: no undefined invalid-output-mode execution.
    for name, warning, enabled in (("warning", True, True), ("quiet_warning", False, True),
                                   ("disabled_error", False, False)):
        add(name, {"save_checkpoint": (".true.", "checkpoint"),
            "save_checkpoint_after_warm_up": (".true.", "checkpoint"),
            "trigger_warnings": (f".{str(warning).lower()}.", "run"),
            "error_output": (f".{str(enabled).lower()}.", "run")}, probe_only=True, warning=warning)
    add("critical", {"netcdf_write_mode": ("'bad'", "output")}, probe_only=True,
        failure=[1, "Invalid config file value for &output > netcdf_write_mode."])
    return cases


def expected_files(case: dict) -> set[str]:
    suffix = case["suffix"]
    files = {f"summary{suffix}.md"}
    if case["csv"]:
        files.update(f"output_{kind}{suffix}.csv" for kind in ("water", "soil", "sediment"))
    if case["nc"]:
        files.add(f"output{suffix}.nc")
    if case.get("stats"):
        files.add(f"stats{suffix}.csv")
    if case.get("steady"):
        files.add(f"output_ssd{suffix}.csv")
    return files


def compare_files(reference: Path, candidate: Path, names: set[str]) -> None:
    for name in sorted(names):
        before, after = reference / name, candidate / name
        if name.endswith(".nc"):
            comparison.compare_netcdf_with_ncdump(before, after, None)
        elif name.endswith(".md"):
            comparison.compare_text_filtered(before, after, name, ("Simulation datetime",), None)
        else:
            comparison.compare_binary_files(before, after, name)


def checkpoint_records(path: Path) -> list[bytes]:
    """Read the existing native gfortran record markers, without interpreting state."""
    data, position, records = path.read_bytes(), 0, []
    while position < len(data):
        if position + 8 > len(data):
            raise ValueError("Truncated checkpoint record")
        length = struct.unpack_from("=i", data, position)[0]
        end = position + 4 + length
        if length < 0 or end + 4 > len(data) or struct.unpack_from("=i", data, end)[0] != length:
            raise ValueError("Invalid checkpoint record layout")
        records.append(data[position + 4:end])
        position = end + 4
    if len(records) != 6:
        raise ValueError("Checkpoint record count changed")
    return records


def compare_checkpoint(reference: Path, candidate: Path, dataset: Path) -> dict:
    """Compare all defined values; unused reach slots have never been initialised."""
    before, after = checkpoint_records(reference), checkpoint_records(candidate)
    if list(map(len, before)) != list(map(len, after)):
        raise ValueError("Checkpoint record lengths changed")
    if before[:4] != after[:4]:
        raise ValueError("Checkpoint grid, timestep or soil state changed")
    text = subprocess.check_output(["ncdump", "-v", "n_waterbodies", str(dataset)], text=True)
    values = re.search(r"\bn_waterbodies\s*=([^;]+);", text)
    if not values:
        raise ValueError("Missing reach counts for checkpoint comparison")
    counts = [int(value.strip()) for value in values[1].split(",")]
    if len(counts) != 12 or min(counts) < 0:
        raise ValueError("Checkpoint fixture geography changed; review comparison")
    slots = len(counts) * max(counts)

    def compare_spatial(left: bytes, right: bytes) -> int:
        if len(left) % (8 * slots):
            raise ValueError("Unexpected spatial checkpoint array shape")
        compared = 0
        for offset in range(0, len(left), 8):
            index = (offset // 8) % slots
            if index // len(counts) < counts[index % len(counts)]:
                if left[offset:offset+8] != right[offset:offset+8]:
                    raise ValueError("Checkpoint state changed for an existing reach")
                compared += 1
        return compared

    # Water volume and bed area use (x,y,reach). Other water arrays have different
    # dimension order and are explicitly zeroed before saving, so compare in full.
    water_prefix = 2 * slots * 8
    compared = compare_spatial(before[4][:water_prefix], after[4][:water_prefix])
    if before[4][water_prefix:] != after[4][water_prefix:]:
        raise ValueError("Checkpoint water state changed")
    # Every sediment array starts with (x,y,reach); only existing reaches are set.
    compared += compare_spatial(before[5], after[5])
    return {"record_lengths": list(map(len, before)), "spatial_values_compared": compared,
            "unused_reach_slots": slots - sum(counts)}


def normalized_log(path: Path) -> str:
    text = path.read_text()
    text = re.sub(r"\d{4}-\d\d-\d\d_\d\d\.\d\d\.\d\d", "<timestamp>", text)
    return re.sub(r"((?:CPU|Wall) time taken to run simulation \(s\): )[^\n\x1b]*", r"\1<duration>", text)


def output_evidence(name: str, case: dict, run: Path) -> dict:
    output = run / "output"
    actual = {p.name for p in output.iterdir()}
    if actual != expected_files(case):
        raise ValueError(f"{name}: unexpected file set: {actual ^ expected_files(case)}")
    columns = {}
    for path in output.glob("*.csv"):
        # Statistics writing is currently a commented-out stub. Preserve and
        # explicitly compare the empty file rather than claiming statistics exist.
        if path.name == f"stats{case['suffix']}.csv":
            if path.stat().st_size != 0:
                raise ValueError("Historical empty statistics output changed")
            columns[path.stem] = ""
            continue
        lines = path.read_text().splitlines()
        rows = [line for line in lines if line and not line.startswith("#")]
        if len(rows) < 2:
            raise ValueError(f"{name}: no data rows in {path.name}")
        columns[path.stem] = rows[0]
    detail_columns = {
        "output_soil": ("C_np_l1(kg/kg)", "C_np_free(kg/kg)",
                        "C_np_free_l1(kg/kg)", "m_soil_eroded(kg)"),
        "output_sediment": ("C_np_l1(kg/m3)", "C_np_l1(kg/kg)"),
        "output_water": ("m_spm_sc1(kg)", "C_spm_sc1(kg/m3)",
                         "m_spm_erosion(kg)", "m_spm_dep(kg)", "m_spm_res(kg)"),
    }
    if name == "full_detail":
        for key, tokens in detail_columns.items():
            if not set(tokens).issubset(columns[key].split(",")):
                raise ValueError(f"Detailed columns missing: {key}")
            if not (output / f"{key}.csv").read_text().startswith("#"):
                raise ValueError(f"Metadata was not enabled: {key}")
    if name == "minimal_detail":
        if any(p.read_text().startswith("#") for p in output.glob("*.csv")):
            raise ValueError("Metadata was not disabled")
        for key, tokens in detail_columns.items():
            if set(tokens).intersection(columns[key].split(",")):
                raise ValueError(f"Disabled detail columns are still present: {key}")
    if case["csv"]:
        unit = "kg/m3" if name == "units" else "kg/kg"
        if f"C_np_total({unit})" not in columns[f"output_soil{case['suffix']}"].split(","):
            raise ValueError("Requested soil concentration units were not exercised")
        # The existing sediment writer always emits both units, independently
        # of sediment_pec_units; preserve that behavior explicitly.
        if not {"C_np_total(kg/m3)", "C_np_total(kg/kg)"}.issubset(
                columns[f"output_sediment{case['suffix']}"].split(",")):
            raise ValueError("Sediment concentration columns changed")
    if case.get("steady"):
        rows = [line for line in (output / "output_ssd.csv").read_text().splitlines()
                if line and not line.startswith("#")]
        if len(rows) != 2:
            raise ValueError("Steady-state fixture did not stop after one iteration")
    if "breakdown" in case:
        header = subprocess.check_output(["ncdump", "-h", str(output / "output.nc")], text=True)
        match = re.search(r"double water__m_nm\(([^)]*)\)", header)
        if not match or (("w" in match[1].split(", ")) != case["breakdown"]):
            raise ValueError("Wrong water-output dimensions")
    logs = list((run / "logs").iterdir())
    if len(logs) != int(case.get("logging", False)):
        raise ValueError("File logging selection was not respected")
    if "colors" in case:
        text = (run / "run.log").read_text()
        expected = "\x1b[32mModel run completeled successfully"
        if (expected in text) != case["colors"]:
            raise ValueError("Logger color selection was not exercised")
        # COLOR_RESET remains present even when colored messages are disabled.
        if "Model run completeled successfully\x1b[0m" not in text:
            raise ValueError("Historical reset sequence changed")
    return {"files": sorted(actual), "columns": columns}


def state_evidence(name: str, case: dict, log: Path) -> str:
    records = [line for line in log.read_text().splitlines()
               if line.startswith(("CHUNK_STATE ", "INPUT_PATH ", "CONSTANTS_PATH ", "MASK_STATE "))]
    chunks = [line.split() for line in records if line.startswith("CHUNK_STATE ")]
    if len(chunks) != (3 if case.get("batch") else 1):
        raise ValueError(f"Wrong chunk records in {name}")
    if case.get("batch"):
        for record, count, shear, date in zip(chunks, (10,11,10), (10,20,30),
                                             ("2015-01-25", "2015-02-04", "2015-03-01")):
            if list(map(int, record[2:4])) != [count,count] or float(record[5]) != shear or not record[6].startswith(date):
                raise ValueError(f"Chunk did not reload current inputs: {record}")
    if name == "mask" and "MASK_STATE T 1" not in records:
        raise ValueError("Simulation mask was not loaded")
    return "\n".join(records) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--probe-exe", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    stage = work / ("reference" if args.mode == "capture" else "candidate")
    commands, evidence = [], {}
    created = False
    try:
        executables = {"model": args.exe.resolve(), "probe": args.probe_exe.resolve()}
        for exe in executables.values():
            comparison.validate_executable(exe)
        for tool in ("ncdump", "ncgen"):
            if not shutil.which(tool):
                raise ValueError(f"Required tool unavailable: {tool}")
        stage.mkdir(parents=True)
        created = True
        provenance = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      "probe_source_hash": digest(PROBE),
                      "executables": {key: {"path": str(exe), "sha256": digest(exe)} for key, exe in executables.items()}}
        if args.mode == "capture":
            cases = prepare(work, commands)
            (work / "manifest.json").write_text(json.dumps(cases, indent=2))
            provenance["input_hashes"] = {str(p.relative_to(work)): digest(p) for p in (work / "inputs").iterdir() if p.is_file()}
            (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
        else:
            cases = json.loads((work / "manifest.json").read_text())
            previous = json.loads((work / "provenance.json").read_text())
            if previous["probe_source_hash"] != provenance["probe_source_hash"]:
                raise ValueError("Probe source changed; rebuild both probes and recapture")
            for name, expected in previous["input_hashes"].items():
                if digest(work / name) != expected:
                    raise ValueError(f"Input changed: {name}")
        # Reuse the same execution paths across stages, then archive each run.
        # Consequently logs need no path filtering, only timestamp/duration filtering.
        for name, case in cases.items():
            run = work / "run-area" / name
            run.mkdir(parents=True)
            (run / "output").mkdir()
            (run / "logs").mkdir()
            text = Path(case["config"]).read_text()
            text = setting(text, "output_path", f'"{run / "output"}/"')
            text = setting(text, "log_file_path", f'"{run / "logs"}/"')
            config = run / "config.nml"
            config.write_text(text)
            command = [str(executables["probe" if case.get("probe_only") else "model"]),
                       str(config), case.get("batch", "")]
            status = invoke(command, run / "run.log", commands)
            if case.get("failure"):
                code, message = case["failure"]
                if status != code or message not in (run / "run.log").read_text():
                    raise ValueError(f"Expected failure changed: {name}")
                evidence[name] = {"exit": status, "message": message}
            elif status:
                raise ValueError(f"{name} failed with {status}; see {run / 'run.log'}")
            elif case.get("probe_only"):
                warning = "You have specified to save a checkpoint after warm up" in (run / "run.log").read_text()
                if warning != case["warning"]:
                    raise ValueError(f"Warning controls changed in {name}")
                evidence[name] = {"warning": warning}
            else:
                evidence[name] = output_evidence(name, case, run)
                if case.get("inspect"):
                    if invoke([str(executables["probe"]), str(config), case.get("batch", "")], run / "probe.log", commands):
                        raise ValueError(f"State probe failed in {name}")
                    (run / "state.txt").write_text(state_evidence(name, case, run / "probe.log"))
                if args.mode == "compare":
                    reference = work / "reference" / name
                    compare_files(reference / "output", run / "output", expected_files(case))
                    if case.get("inspect"):
                        comparison.compare_binary_files(reference / "state.txt", run / "state.txt", f"{name} input state")
                    if normalized_log(reference / "run.log") != normalized_log(run / "run.log"):
                        raise ValueError(f"Console log changed: {name}")
                    if case.get("logging"):
                        if normalized_log(next((reference / "logs").iterdir())) != normalized_log(next((run / "logs").iterdir())):
                            raise ValueError(f"File log changed: {name}")
            if name == "checkpoint_save":
                saved = work / "generated_checkpoint.dat"
                shutil.copy2(saved, run / "checkpoint.dat")
                if args.mode == "capture":
                    shutil.copy2(saved, work / "reference_checkpoint.dat")
                    # Same native gfortran records, with just two grid values
                    # zeroed so normal epsilon can resolve the test perturbation.
                    grid = bytearray(saved.read_bytes())
                    if struct.unpack_from("=i", grid)[0] != 24 or struct.unpack_from("=i", grid, 28)[0] != 24:
                        raise ValueError("Unexpected checkpoint grid record layout")
                    struct.pack_into("=f", grid, 4, 0.0)
                    struct.pack_into("=f", grid, 20, 0.0)
                    (work / "grid_checkpoint.dat").write_bytes(grid)
                evidence[name]["checkpoint"] = compare_checkpoint(
                    work / "reference_checkpoint.dat", saved, work / "inputs/test-scenario.nc")
            shutil.move(str(run), stage / name)
            print(f"PASS {name}", flush=True)

        # Both builds load exactly the same nonzero-timestep reference checkpoint.
        checkpoint_hashes = {name: digest(work / name) for name in ("reference_checkpoint.dat", "grid_checkpoint.dat")}
        for mode in ("keep", "reset", "bounds_inside", "bounds_outside", "resolution_inside", "resolution_outside"):
            run = stage / f"checkpoint_{mode}"
            run.mkdir()
            text = Path(cases["checkpoint_save"]["config"]).read_text()
            checkpoint_name = "reference_checkpoint.dat" if mode in ("keep", "reset") else "grid_checkpoint.dat"
            text = setting(text, "checkpoint_file", f'"{work / checkpoint_name}"')
            (run / "config.nml").write_text(text)
            status = invoke([str(executables["probe"]), str(run / "config.nml"), "", f"checkpoint_{mode}"],
                            run / "run.log", commands)
            log = (run / "run.log").read_text()
            if mode.endswith("outside"):
                message = f"Grid {'bounds' if mode.startswith('bounds') else 'resolution'} of checkpoint and current simulation do not match."
                if status != 1 or message not in log:
                    raise ValueError(f"Grid compatibility failure changed: {mode}")
                result = {"exit": status, "message": message}
            else:
                expected = 1 if mode == "reset" else 10
                if status or f"CHECKPOINT_T0 {expected}" not in log:
                    raise ValueError(f"Checkpoint state changed: {mode}")
                result = {"exit": status, "t0": expected}
            evidence[f"checkpoint_{mode}"] = result
            print(f"PASS checkpoint_{mode}", flush=True)
        for name, expected in checkpoint_hashes.items():
            if digest(work / name) != expected:
                raise ValueError("Reference checkpoint was modified")
        if args.mode == "compare":
            old = json.loads((work / "reference/branch_evidence.json").read_text())
            if old != evidence:
                raise ValueError("Branch evidence differs from the reference")
        for key, exe in executables.items():
            if digest(exe) != provenance["executables"][key]["sha256"]:
                raise ValueError("Executable changed during checks")
        (stage / "executables.json").write_text(json.dumps(provenance, indent=2))
        print(f"PASS shared consumers; evidence: {stage}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, comparison.VerificationError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    finally:
        if created:
            (stage / "commands.json").write_text(json.dumps(commands, indent=2))
            (stage / "branch_evidence.json").write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
