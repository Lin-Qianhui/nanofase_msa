#!/usr/bin/env python3
"""Build and run the model through CMake, the example Makefile, and fpm.

This slower companion to verify_build_system.py is run explicitly, not by CTest.
It checks reported versions and source preservation, not numerical equivalence
between different compiler optimization profiles. Use the existing four scenario
runners for the scientific comparison with a fixed version and matching flags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import verify_refactor as comparison

ROOT = Path(__file__).resolve().parents[1]


def source_hashes(root: Path) -> dict[str, str]:
    # Include tracked files plus the new, possibly not-yet-committed build files.
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    names += [str(p.relative_to(ROOT)) for folder in ("cmake", "verification")
              for p in (ROOT / folder).glob("*") if p.is_file()]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sorted(set(names)) if name and (root / name).is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="gfortran")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--fpm", default="fpm")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--jobs", default="2")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="routes_", dir=args.work_dir.resolve()))
    commands: list[dict] = []
    passed: list[str] = []
    baseline = source_hashes(ROOT)

    def run(name: str, command: list[str], cwd: Path = ROOT, env: dict | None = None) -> str:
        with (work / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=900)
        commands.append({"name": name, "command": command, "cwd": str(cwd), "exit": result.returncode})
        assert source_hashes(ROOT) == baseline, f"Source changed during {name}"
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; see {work / (name + '.log')}")
        return (work / (name + ".log")).read_text()

    def model(name: str, executable: Path, version: str) -> None:
        run_dir = work / name
        run_dir.mkdir()
        config, output = comparison.write_run_config(ROOT / "config.example/test-scenario.example.nml", run_dir)
        stdout = run(name, [str(executable), str(config)])
        visible = version[:16].ljust(16)
        assert "...version: " + visible in stdout
        assert " - Model version: " + visible in (output / "summary.md").read_text()
        header = run(name + "_netcdf", ["ncdump", "-h", str(output / "output.nc")])
        label = visible.rstrip()
        assert f'NanoFASE model v{label}: https://github.com/nerc-ceh/nanofase/tree/{label}' in header
        passed.append(name + ": console, summary and NetCDF version")

    includes = subprocess.check_output(["nf-config", "--includedir"], text=True).strip()
    libraries = subprocess.check_output(["nf-config", "--flibs"], text=True).strip()
    cmake_args = ["-DCMAKE_Fortran_COMPILER=" + args.compiler,
                  "-DNETCDF_INCLUDES=" + includes, "-DNETCDF_LIBRARIES_F90=" + libraries]
    try:
        automatic = work / "automatic-build"
        run("automatic_configure", [args.cmake, "-S", str(ROOT), "-B", str(automatic),
                                    "-DCMAKE_BUILD_TYPE=Debug", *cmake_args], cwd=work)
        run("automatic_build", [args.cmake, "--build", str(automatic), "--target", "nanofase", "-j" + args.jobs])
        label = subprocess.check_output(["git", "describe", "--tags"], cwd=ROOT, text=True).strip()
        model("automatic_model", automatic / "nanofase", label)

        make_dir = work / "make-build"
        sentinel = make_dir / "dependencies/keep.txt"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("unrelated fpm cache\n")
        make = ["make", "-f", str(ROOT / "Makefile.example"), "FC=" + args.compiler,
                "BUILD_DIR=" + str(make_dir), "JOBS=" + args.jobs, "MODEL_VERSION=make-check"]
        for target in ("all", "release", "fast", "clean"):
            run("make_dry_" + target, [*make, "-n", target])
        assert not (make_dir / "make-debug").exists(), "Dry run performed a build"
        for target in ("all", "release", "fast"):
            run("make_" + target, [*make, target])
            model("make_" + target + "_model", make_dir / "nanofase", "make-check")
            assert "Version: make-check" in (make_dir / "comp_meta").read_text()
        run("make_clean", [*make, "clean"])
        assert sentinel.read_text() == "unrelated fpm cache\n"
        assert not (make_dir / "nanofase").exists()
        assert not (make_dir / "comp_meta").exists()
        run("make_after_clean", [*make, "all"])
        model("make_rebuilt_model", make_dir / "nanofase", "make-check")
        passed.append("Make dry runs, three modes, clean, cache preservation and rebuild")

        # Use real source files, including vendored dependencies, without Git metadata.
        archive = work / "source-archive"
        archive.mkdir()
        for folder in ("src", "cmake", "test"):
            shutil.copytree(ROOT / folder, archive / folder)
        for folder in ("feh", "mo_netcdf", "datetime-fortran", "spoof"):
            shutil.copytree(ROOT / "vendor" / folder, archive / "vendor" / folder,
                            ignore=shutil.ignore_patterns(".git", "build", "__pycache__"))
        for name in ("CMakeLists.txt", "fpm.toml", "fpm.rsp"):
            shutil.copy2(ROOT / name, archive / name)
        archive_before = source_hashes(archive)
        archive_build = work / "archive-build"
        run("archive_configure", [args.cmake, "-S", str(archive), "-B", str(archive_build),
                                  "-DCMAKE_BUILD_TYPE=Debug", *cmake_args], cwd=work)
        run("archive_build", [args.cmake, "--build", str(archive_build), "--target", "nanofase", "-j" + args.jobs])
        model("archive_model", archive_build / "nanofase", "0.0.5")

        # Reuse already fetched dependencies when available; never rewrite manifests.
        # A fresh environment may let fpm fetch these same declared dependencies.
        if (ROOT / "build/cache.toml").exists() and (ROOT / "build/dependencies").exists():
            shutil.copytree(ROOT / "build/dependencies", archive / "build/dependencies")
            shutil.copy2(ROOT / "build/cache.toml", archive / "build/cache.toml")
        env = dict(os.environ, FPM_FC=args.compiler)
        prefix = work / "fpm-install"
        run("fpm_install", [args.fpm, "@install", "--prefix=" + str(prefix)], cwd=archive, env=env)
        model("fpm_model", prefix / "bin/nanofase", "0.0.5")
        assert source_hashes(archive) == archive_before, "Archive sources changed during builds"
        passed.append("source archive and package fpm install preserve source")
    finally:
        (work / "commands.json").write_text(json.dumps(commands, indent=2))
        (work / "results.json").write_text(json.dumps({"passed": passed}, indent=2))
        (work / "source_hashes.json").write_text(json.dumps(baseline, indent=2))
        print(f"Build-route evidence: {work}", flush=True)
    for name in passed:
        print("PASS", name)


if __name__ == "__main__":
    main()
