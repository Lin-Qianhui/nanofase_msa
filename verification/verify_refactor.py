#!/usr/bin/env python3
"""Run NanoFASE and compare outputs against a local refactor baseline."""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Iterable


CSV_OUTPUTS = (
    "output_water.csv",
    "output_sediment.csv",
    "output_soil.csv",
)
SUMMARY_OUTPUT = "summary.md"
NETCDF_OUTPUT = "output.nc"
MISSING = object()
NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[EeDd][-+]?\d+)?(?![A-Za-z0-9_])"
)


class VerificationError(RuntimeError):
    """Expected verification failure with a user-facing message."""


@dataclass(frozen=True)
class Tolerance:
    """Absolute and relative numeric comparison tolerances."""

    atol: float
    rtol: float


def nonnegative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"must be a number: {value}") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a nonnegative finite number: {value}")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a NanoFASE executable with a copied config and compare generated "
            "outputs against a local baseline directory."
        )
    )
    parser.add_argument("--exe", required=True, help="Path to NanoFASE executable.")
    parser.add_argument("--baseline", required=True, help="Directory containing baseline outputs.")
    parser.add_argument("--config", required=True, help="Config namelist to copy and run.")
    parser.add_argument(
        "--run-dir",
        help=(
            "Directory for this verification run. Defaults to a timestamped directory "
            "under verification/runs/."
        ),
    )
    parser.add_argument(
        "--atol",
        type=nonnegative_finite_float,
        default=1.0e-14,
        help="Absolute tolerance for numeric comparisons. Default: 1e-14.",
    )
    parser.add_argument(
        "--rtol",
        type=nonnegative_finite_float,
        default=1.0e-12,
        help="Relative tolerance for numeric comparisons. Default: 1e-12.",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help=(
            "Disable numeric tolerance checks. CSV outputs must be byte-identical, "
            "and filtered summary/NetCDF text must match exactly."
        ),
    )
    return parser.parse_args()


def resolve_existing_file(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise VerificationError(f"{label} does not exist or is not a file: {resolved}")
    return resolved


def resolve_existing_dir(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise VerificationError(f"{label} does not exist or is not a directory: {resolved}")
    return resolved


def validate_executable(path: Path) -> None:
    if not os.access(path, os.X_OK):
        raise VerificationError(f"Executable is not runnable: {path}")


def expected_outputs() -> tuple[str, ...]:
    return (*CSV_OUTPUTS, SUMMARY_OUTPUT, NETCDF_OUTPUT)


def validate_output_set(directory: Path, label: str) -> None:
    missing = [name for name in expected_outputs() if not (directory / name).is_file()]
    if missing:
        formatted = ", ".join(missing)
        raise VerificationError(f"{label} is missing required output file(s): {formatted}")


def default_run_dir() -> Path:
    root = Path(__file__).resolve().parent / "runs"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"run_{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"run_{stamp}_{suffix}"
        suffix += 1
    return candidate


def prepare_run_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise VerificationError(f"Run directory already exists and is not empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def rewrite_output_path(config_text: str, output_dir: Path) -> str:
    output_path = output_dir.as_posix().rstrip("/") + "/"
    pattern = re.compile(r"(^\s*output_path\s*=\s*)(['\"])(.*?)(\2)(.*)$", re.MULTILINE)

    def replacement(match: re.Match[str]) -> str:
        return f'{match.group(1)}"{output_path}"{match.group(5)}'

    updated, count = pattern.subn(replacement, config_text, count=1)
    if count != 1:
        raise VerificationError("Could not find exactly one output_path entry in config.")
    return updated


def write_run_config(config: Path, run_dir: Path) -> tuple[Path, Path]:
    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_config = run_dir / "config.nml"
    run_config.write_text(rewrite_output_path(config.read_text(), output_dir), encoding="utf-8")
    return run_config, output_dir


def run_model(exe: Path, run_config: Path, run_dir: Path) -> None:
    stdout_path = run_dir / "model.stdout.log"
    stderr_path = run_dir / "model.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            [str(exe), str(run_config)],
            stdout=stdout,
            stderr=stderr,
            cwd=Path.cwd(),
            check=False,
        )
    if completed.returncode != 0:
        raise VerificationError(
            f"Model run failed with exit code {completed.returncode}. "
            f"See {stdout_path} and {stderr_path}."
        )


def compare_binary_files(expected: Path, actual: Path, label: str) -> None:
    expected_size = expected.stat().st_size
    actual_size = actual.stat().st_size
    if expected_size != actual_size:
        raise VerificationError(
            f"{label} differs: size mismatch baseline={expected_size} candidate={actual_size}"
        )

    offset = 0
    chunk_size = 8 * 1024 * 1024
    with expected.open("rb") as left, actual.open("rb") as right:
        while True:
            left_chunk = left.read(chunk_size)
            right_chunk = right.read(chunk_size)
            if not left_chunk and not right_chunk:
                return
            if left_chunk != right_chunk:
                for index, (left_byte, right_byte) in enumerate(zip(left_chunk, right_chunk)):
                    if left_byte != right_byte:
                        exact_offset = offset + index
                        raise VerificationError(
                            f"{label} differs at byte offset {exact_offset}: "
                            f"baseline=0x{left_byte:02x} candidate=0x{right_byte:02x}"
                        )
                raise VerificationError(f"{label} differs near byte offset {offset}")
            offset += len(left_chunk)


def try_parse_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None


def floats_close(expected: float, actual: float, tolerance: Tolerance) -> bool:
    if math.isnan(expected) or math.isnan(actual):
        return math.isnan(expected) and math.isnan(actual)
    if math.isinf(expected) or math.isinf(actual):
        return expected == actual
    return math.isclose(actual, expected, rel_tol=tolerance.rtol, abs_tol=tolerance.atol)


def format_tolerance(tolerance: Tolerance) -> str:
    return f"atol={tolerance.atol:g}, rtol={tolerance.rtol:g}"


def parse_csv_line(line: str, label: str, line_number: int) -> list[str]:
    try:
        return next(csv.reader([line]))
    except csv.Error as error:
        raise VerificationError(f"{label} has invalid CSV at line {line_number}: {error}") from error


def compare_csv_with_tolerance(expected: Path, actual: Path, label: str, tolerance: Tolerance) -> None:
    headers: list[str] | None = None

    with expected.open("r", encoding="utf-8", errors="replace", newline="") as left_handle, actual.open(
        "r", encoding="utf-8", errors="replace", newline=""
    ) as right_handle:
        for line_number, (left_raw, right_raw) in enumerate(
            zip_longest(left_handle, right_handle, fillvalue=MISSING), start=1
        ):
            if left_raw is MISSING:
                assert isinstance(right_raw, str)
                raise VerificationError(
                    f"{label} differs: candidate has extra line {line_number}: {right_raw.rstrip()!r}"
                )
            if right_raw is MISSING:
                assert isinstance(left_raw, str)
                raise VerificationError(
                    f"{label} differs: candidate is missing line {line_number}: {left_raw.rstrip()!r}"
                )

            assert isinstance(left_raw, str)
            assert isinstance(right_raw, str)
            left = left_raw.rstrip("\r\n")
            right = right_raw.rstrip("\r\n")

            if left == right:
                if headers is None and left and not left.lstrip().startswith("#"):
                    headers = parse_csv_line(left, label, line_number)
                continue

            if left.lstrip().startswith("#") or right.lstrip().startswith("#"):
                raise VerificationError(
                    f"{label} differs at comment/header line {line_number}: "
                    f"baseline={left!r} candidate={right!r}"
                )

            left_fields = parse_csv_line(left, label, line_number)
            right_fields = parse_csv_line(right, label, line_number)
            if len(left_fields) != len(right_fields):
                raise VerificationError(
                    f"{label} differs at line {line_number}: field count mismatch "
                    f"baseline={len(left_fields)} candidate={len(right_fields)}"
                )
            if headers is None:
                headers = left_fields

            for index, (left_field, right_field) in enumerate(zip(left_fields, right_fields), start=1):
                if left_field == right_field:
                    continue

                left_value = try_parse_float(left_field)
                right_value = try_parse_float(right_field)
                if left_value is not None and right_value is not None:
                    if floats_close(left_value, right_value, tolerance):
                        continue
                    difference = abs(right_value - left_value)
                    column = headers[index - 1] if index - 1 < len(headers) else f"column {index}"
                    raise VerificationError(
                        f"{label} differs at line {line_number}, column {index} ({column}): "
                        f"baseline={left_field!r} candidate={right_field!r} "
                        f"abs_diff={difference:.6g} tolerance={format_tolerance(tolerance)}"
                    )

                column = headers[index - 1] if index - 1 < len(headers) else f"column {index}"
                raise VerificationError(
                    f"{label} differs at line {line_number}, column {index} ({column}): "
                    f"baseline={left_field!r} candidate={right_field!r}"
                )


def split_numeric_tokens(line: str) -> tuple[list[str], list[str]]:
    parts: list[str] = []
    tokens: list[str] = []
    offset = 0
    for match in NUMERIC_TOKEN.finditer(line):
        parts.append(line[offset : match.start()])
        tokens.append(match.group(0))
        offset = match.end()
    parts.append(line[offset:])
    return parts, tokens


def compare_text_line_with_tolerance(
    left: str, right: str, label: str, line_number: int, tolerance: Tolerance
) -> None:
    if left == right:
        return

    left_parts, left_tokens = split_numeric_tokens(left)
    right_parts, right_tokens = split_numeric_tokens(right)
    if left_parts != right_parts or len(left_tokens) != len(right_tokens):
        raise VerificationError(
            f"{label} differs at filtered line {line_number}: "
            f"baseline={left.rstrip()!r} candidate={right.rstrip()!r}"
        )

    for token_index, (left_token, right_token) in enumerate(zip(left_tokens, right_tokens), start=1):
        left_value = try_parse_float(left_token)
        right_value = try_parse_float(right_token)
        if left_value is None or right_value is None:
            raise VerificationError(
                f"{label} has an unparsable numeric token at filtered line {line_number}: "
                f"baseline={left_token!r} candidate={right_token!r}"
            )
        if not floats_close(left_value, right_value, tolerance):
            difference = abs(right_value - left_value)
            raise VerificationError(
                f"{label} differs at filtered line {line_number}, numeric token {token_index}: "
                f"baseline={left_token!r} candidate={right_token!r} "
                f"abs_diff={difference:.6g} tolerance={format_tolerance(tolerance)}"
            )


def iter_filtered_lines(path: Path, ignored_patterns: Iterable[str]) -> Iterable[str]:
    ignored = tuple(ignored_patterns)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(pattern in line for pattern in ignored):
                yield line


def compare_text_filtered(
    expected: Path,
    actual: Path,
    label: str,
    ignored_patterns: Iterable[str],
    tolerance: Tolerance | None,
) -> None:
    for index, (left, right) in enumerate(
        zip_longest(
            iter_filtered_lines(expected, ignored_patterns),
            iter_filtered_lines(actual, ignored_patterns),
            fillvalue=MISSING,
        ),
        start=1,
    ):
        if left is MISSING:
            assert isinstance(right, str)
            raise VerificationError(
                f"{label} differs at filtered line {index}: baseline='<missing>' "
                f"candidate={right.rstrip()!r}"
            )
        if right is MISSING:
            assert isinstance(left, str)
            raise VerificationError(
                f"{label} differs at filtered line {index}: baseline={left.rstrip()!r} "
                "candidate='<missing>'"
            )

        assert isinstance(left, str)
        assert isinstance(right, str)
        if tolerance is not None:
            compare_text_line_with_tolerance(left, right, label, index, tolerance)
            continue
        if left != right:
            raise VerificationError(
                f"{label} differs at filtered line {index}: "
                f"baseline={left.rstrip()!r} candidate={right.rstrip()!r}"
            )


def ncdump_process(path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["ncdump", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )


def next_unignored_line(handle, ignored_patterns: tuple[str, ...]) -> str | None:
    for line in handle:
        if not any(pattern in line for pattern in ignored_patterns):
            return line
    return None


def finish_ncdump(proc: subprocess.Popen[str], label: str) -> None:
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise VerificationError(f"ncdump failed for {label}: {stderr.strip()}")


def compare_netcdf_with_ncdump(expected: Path, actual: Path, tolerance: Tolerance | None) -> None:
    if shutil.which("ncdump") is None:
        raise VerificationError("ncdump is required for NetCDF comparison but was not found on PATH.")

    ignored = (":history =",)
    left = ncdump_process(expected)
    right = ncdump_process(actual)
    assert left.stdout is not None
    assert right.stdout is not None

    line_number = 0
    failed = True
    try:
        while True:
            left_line = next_unignored_line(left.stdout, ignored)
            right_line = next_unignored_line(right.stdout, ignored)
            line_number += 1
            if left_line is None and right_line is None:
                break
            if tolerance is not None and left_line is not None and right_line is not None:
                compare_text_line_with_tolerance(
                    left_line,
                    right_line,
                    f"{NETCDF_OUTPUT} ncdump output",
                    line_number,
                    tolerance,
                )
                continue
            if left_line != right_line:
                raise VerificationError(
                    f"{NETCDF_OUTPUT} differs in ncdump output at filtered line {line_number}: "
                    f"baseline={(left_line or '<missing>').rstrip()!r} "
                    f"candidate={(right_line or '<missing>').rstrip()!r}"
                )
        failed = False
    finally:
        if failed:
            for proc in (left, right):
                if proc.poll() is None:
                    proc.terminate()

    finish_ncdump(left, "baseline output.nc")
    finish_ncdump(right, "candidate output.nc")


def compare_outputs(baseline: Path, candidate: Path, tolerance: Tolerance, exact: bool) -> None:
    for name in CSV_OUTPUTS:
        if exact:
            compare_binary_files(baseline / name, candidate / name, name)
            print(f"PASS {name}: byte-identical", flush=True)
        else:
            compare_csv_with_tolerance(baseline / name, candidate / name, name, tolerance)
            print(f"PASS {name}: numeric fields match within {format_tolerance(tolerance)}", flush=True)

    compare_text_filtered(
        baseline / SUMMARY_OUTPUT,
        candidate / SUMMARY_OUTPUT,
        SUMMARY_OUTPUT,
        ignored_patterns=("Simulation datetime",),
        tolerance=None if exact else tolerance,
    )
    if exact:
        print(f"PASS {SUMMARY_OUTPUT}: matches after filtering Simulation datetime", flush=True)
    else:
        print(
            f"PASS {SUMMARY_OUTPUT}: numeric tokens match within {format_tolerance(tolerance)} "
            "after filtering Simulation datetime",
            flush=True,
        )

    compare_netcdf_with_ncdump(
        baseline / NETCDF_OUTPUT,
        candidate / NETCDF_OUTPUT,
        tolerance=None if exact else tolerance,
    )
    if exact:
        print(f"PASS {NETCDF_OUTPUT}: ncdump matches after filtering history metadata", flush=True)
    else:
        print(
            f"PASS {NETCDF_OUTPUT}: ncdump numeric tokens match within {format_tolerance(tolerance)} "
            "after filtering history metadata",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    try:
        tolerance = Tolerance(atol=args.atol, rtol=args.rtol)
        exe = resolve_existing_file(args.exe, "Executable")
        validate_executable(exe)
        baseline = resolve_existing_dir(args.baseline, "Baseline directory")
        config = resolve_existing_file(args.config, "Config")
        validate_output_set(baseline, "Baseline directory")

        run_dir = prepare_run_dir(Path(args.run_dir) if args.run_dir else default_run_dir())
        run_config, output_dir = write_run_config(config, run_dir)

        print(f"Run directory: {run_dir}", flush=True)
        print(f"Running: {exe} {run_config}", flush=True)
        run_model(exe, run_config, run_dir)
        validate_output_set(output_dir, "Candidate output directory")
        compare_outputs(baseline, output_dir, tolerance, args.exact)
        print("Verification passed.", flush=True)
        return 0
    except VerificationError as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
