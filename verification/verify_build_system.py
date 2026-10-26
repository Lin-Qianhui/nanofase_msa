#!/usr/bin/env python3
"""Exercise the actual version generator with small, isolated Fortran builds.

No third-party Python packages are needed. All fixtures, Git repositories,
commands, logs and results stay in a fresh directory beneath --work-dir.
The full model comparisons and fpm/Make builds are documented separately.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FILES = ("src/VersionModule.f90", "cmake/NanoFASEVersion.cmake", "cmake/VersionModule.f90.in",
         "src/Kernel/KernelModule.f90", "src/ModelConfig/ModelConfigModule.f90",
         "src/ModelConfig/ModelDefaultsModule.f90", "src/mod_strptime.f90",
         "vendor/datetime-fortran/src/datetime_module.f90",
         "vendor/feh/src/ErrorInstance.f90", "vendor/feh/src/Result.f90",
         "test/fixtures/model-config-omitted.nml")
PROJECT = """cmake_minimum_required(VERSION 3.13)
project(version_check LANGUAGES Fortran)
include(cmake/NanoFASEVersion.cmake)
nanofase_setup_version(version_source)
set(config_sources src/Kernel/KernelModule.f90 src/ModelConfig/ModelConfigModule.f90
    src/ModelConfig/ModelDefaultsModule.f90 src/mod_strptime.f90
    vendor/datetime-fortran/src/datetime_module.f90
    vendor/feh/src/ErrorInstance.f90 vendor/feh/src/Result.f90)
foreach(name probe probe_again)
    add_executable(${name} ${version_source} ${config_sources} probe.f90)
    set_target_properties(${name} PROPERTIES
        Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/${name}-modules")
    add_dependencies(${name} nanofase_version)
endforeach()
"""
PROBE = """program version_probe
    use VersionModule, only: MODEL_VERSION
    use ModelConfigModule, only: modelConfig
    implicit none
    character(len=1024) :: configPath
    call get_command_argument(1, configPath)
    if (modelConfig%modelVersion /= '') error stop 'Version was set before initialisation'
    write(*, '(a)') MODEL_VERSION
    call modelConfig%clear()
    if (modelConfig%modelVersion /= MODEL_VERSION) error stop 'ModelConfig version was truncated'
    write(*, '(a)') modelConfig%modelVersion
    call modelConfig%init(trim(configPath))
    if (modelConfig%modelVersion /= MODEL_VERSION) error stop 'Version changed during initialisation'
    modelConfig%modelVersion = 'changed'
    call modelConfig%clear()
    if (modelConfig%modelVersion /= MODEL_VERSION) error stop 'Version was not reset'
    modelConfig%modelVersion = 'changed again'
    call modelConfig%init(trim(configPath))
    if (modelConfig%modelVersion /= MODEL_VERSION) error stop 'Version was not reset on repeated input'
end program version_probe
"""


def hashes(source: Path) -> dict[str, str]:
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in FILES}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--compiler", default="gfortran")
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="version_", dir=args.work_dir.resolve()))
    commands: list[dict] = []
    passed: list[str] = []
    original = hashes(ROOT)
    sources = {}

    def run(command: list[str], cwd: Path = work) -> str:
        result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120)
        record = {"command": command, "cwd": str(cwd), "exit": result.returncode,
                  "output": result.stdout}
        commands.append(record)
        if result.returncode:
            raise AssertionError(f"Command failed: {command}\n{result.stdout}")
        return result.stdout

    def fixture(name: str) -> Path:
        source = work / name
        for relative in FILES:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        (source / "CMakeLists.txt").write_text(PROJECT)
        (source / "probe.f90").write_text(PROBE)
        return source

    def configure(source: Path, build: Path, *options: str) -> str:
        sources[build] = source
        return run([args.cmake, "-S", str(source), "-B", str(build),
                    "-DCMAKE_Fortran_COMPILER=" + args.compiler, *options])

    def build_and_check(build: Path, label: str, target: str = "probe") -> None:
        run([args.cmake, "--build", str(build), "--target", target, "--parallel", "2"])
        assert (build / "generated/version.txt").read_text() == label + "\n"
        executable = build / target
        if not executable.exists():
            executable = build / (target + ".exe")
        actual = run([str(executable), str(sources[build] / "test/fixtures/model-config-omitted.nml")]).splitlines()
        expected = [label, label.ljust(16)]
        assert actual == expected, (actual, expected)
        generated = (build / "generated/VersionModule.f90").read_text()
        assert max(map(len, generated.splitlines())) <= 120, "Generated Fortran line is too long"

    def git(source: Path, *arguments: str) -> str:
        return run(["git", "-c", "user.name=NanoFASE build test", "-c",
                    "user.email=build-test@example.invalid", *arguments], cwd=source).strip()

    try:
        source = fixture("archive")
        source_before = hashes(source)
        first = work / "override-one"
        # Test source quoting and CMake script quoting, including a literal ${...}.
        special = 'v";${x}\\]=]123456789'
        configure(source, first, "-DNANOFASE_VERSION=" + special)
        build_and_check(first, special, "probe_again")
        generated = first / "generated/VersionModule.f90"
        before = {p: p.stat().st_mtime_ns for p in first.rglob("*.o")}
        before[generated] = generated.stat().st_mtime_ns
        before[first / "probe_again"] = (first / "probe_again").stat().st_mtime_ns
        build_and_check(first, special, "probe_again")
        assert before == {p: p.stat().st_mtime_ns for p in before}, "Unchanged build recompiled"
        passed += ["explicit archive label and escaping", "direct secondary target", "no-op build"]

        second = work / "override-two"
        configure(source, second, "-DNANOFASE_VERSION=second-build")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(build_and_check, first, special),
                       pool.submit(build_and_check, second, "second-build")]
            for future in futures:
                future.result()
        passed.append("independent concurrent build directories")
        # The system Make on macOS compares file times at whole-second precision.
        # Separate edits from the preceding compile so this checks dependencies,
        # rather than depending on sub-second timestamp support in the build tool.
        time.sleep(1.1)
        configure(source, first, "-DNANOFASE_VERSION=changed")
        build_and_check(first, "changed")
        time.sleep(1.1)
        configure(source, first, "-DNANOFASE_VERSION=")
        build_and_check(first, "0.0.5")
        passed += ["override changes reach executable", "clearing override selects archive fallback"]
        assert hashes(source) == source_before

        for length in (1, 15, 16, 17, 18, 256):
            time.sleep(1.1)
            label = 'v' + 'x' * (length - 1)
            configure(source, first, "-DNANOFASE_VERSION=" + label)
            build_and_check(first, label)
        time.sleep(1.1)
        long_special = ('x' * 31 + '\";${x}\\\\]=]') * 8
        configure(source, first, "-DNANOFASE_VERSION=" + long_special)
        build_and_check(first, long_special)
        passed += ["full labels at length boundaries and 256 characters", "long labels preserve escaping",
                   "real ModelConfig initialisation, reset and repeated reads"]

        tagged = fixture("tagged")
        git(tagged, "init", "--quiet")
        git(tagged, "add", ".")
        git(tagged, "commit", "--quiet", "-m", "fixture")
        no_tags = work / "no-tags-build"
        configure(tagged, no_tags)
        build_and_check(no_tags, "0.0.5")
        passed.append("repository without tags")
        git(tagged, "tag", "v1.2.3")
        automatic = work / "automatic"
        output = configure(tagged, automatic)
        assert "git describe --tags" in output
        build_and_check(automatic, "v1.2.3")
        time.sleep(1.1)
        git(tagged, "commit", "--quiet", "--allow-empty", "-m", "next commit")
        description = git(tagged, "describe", "--tags")
        build_and_check(automatic, description)
        time.sleep(1.1)
        git(tagged, "tag", "v1.2.4")
        build_and_check(automatic, "v1.2.4")
        passed += ["Git selection from outside source directory", "commit and tag refresh without configuration"]
        time.sleep(1.1)
        configure(tagged, automatic, "-DNANOFASE_VERSION=fixed")
        build_and_check(automatic, "fixed")
        time.sleep(1.1)
        configure(tagged, automatic, "-DNANOFASE_VERSION=")
        build_and_check(automatic, "v1.2.4")
        passed.append("explicit override takes precedence over Git and clears")

        # Rebuild only the second target after the first has compiled a different
        # label. A module leaked into the build root would override its new copy.
        time.sleep(1.1)
        configure(tagged, automatic, "-DNANOFASE_VERSION=secondary-only")
        build_and_check(automatic, "secondary-only", "probe_again")
        passed.append("secondary target does not read the main target's previous version")

        # Reproduce the pre-cleanup layout: compile a stale module into the root.
        legacy = work / "legacy-build"
        legacy.mkdir()
        stale = work / "stale-version.f90"
        stale.write_text('module VersionModule\ncharacter(17), parameter :: MODEL_VERSION = "stale"\nend module\n')
        run([args.compiler, "-c", str(stale), "-o", str(legacy / "stale.o")], cwd=legacy)
        configure(tagged, legacy, "-DNANOFASE_VERSION=upgraded")
        build_and_check(legacy, "upgraded", "probe_again")
        assert (legacy / "legacy-fortran-modules/versionmodule.mod").exists()
        assert not (legacy / "versionmodule.mod").exists()
        passed.append("legacy build-root modules are retained outside the compiler search path")

        no_git = work / "git-unavailable"
        configure(tagged, no_git, "-DCMAKE_DISABLE_FIND_PACKAGE_Git=TRUE")
        build_and_check(no_git, "0.0.5")
        passed.append("Git unavailable")
        nested = fixture("tagged/nested-archive")
        nested_build = work / "nested-archive-build"
        configure(nested, nested_build)
        build_and_check(nested_build, "0.0.5")
        passed.append("archive does not inherit parent Git history")

        linked = work / "linked-worktree"
        git(tagged, "worktree", "add", "--quiet", "--detach", str(linked), "HEAD")
        linked_build = work / "worktree-build"
        configure(linked, linked_build)
        build_and_check(linked_build, "v1.2.4")
        passed.append("Git worktree with .git file")
        assert hashes(ROOT) == original, "Tracked version-generation source changed"
        assert hashes(tagged) == original
        passed.append("source hashes unchanged")
    finally:
        (work / "commands.json").write_text(json.dumps(commands, indent=2))
        (work / "results.json").write_text(json.dumps({"passed": passed}, indent=2))
        print(f"Build-version evidence: {work}")
    for name in passed:
        print("PASS", name)


if __name__ == "__main__":
    main()
