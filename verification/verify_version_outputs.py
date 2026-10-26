#!/usr/bin/env python3
"""Compare Phase 13/14 models built with the same long version label.

Require the expected old and new metadata before excluding those exact fields
from the scientific comparison. General regression filters remain unchanged.
Both NetCDF layouts and writing modes are exercised. Evidence stays in --work-dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import verify_refactor as comparison
from verify_waterbody import setting

ROOT = Path(__file__).resolve().parents[1]


def checked_summary(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    versions = [line for line in lines if line.startswith(' - Model version: ')]
    assert versions == [' - Model version: ' + label.ljust(16)], versions
    return [line for line in lines if line not in versions and 'Simulation datetime' not in line]


def checked_netcdf(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    versions = [line for line in lines if line.lstrip().startswith(':source =')]
    expected = f'NanoFASE model v{label}: https://github.com/nerc-ceh/nanofase/tree/{label}'
    assert len(versions) == 1, versions
    assert versions[0].strip() == ':source = ' + json.dumps(expected) + ' ;', versions
    return [line for line in lines if line not in versions and ':history =' not in line]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-exe', required=True, type=Path)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--label', required=True)
    parser.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    if len(args.label) <= 17:
        parser.error('--label must exceed both old version limits (17 characters)')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='version_outputs_', dir=args.work_dir.resolve()))
    executables = {'reference': args.reference_exe.resolve(), 'candidate': args.exe.resolve()}
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in executables.items()}
    commands = []
    passed = []
    try:
        for mode in ('end', 'itr'):
            for breakdown in (True, False):
                case = f'{mode}_' + ('waterbodies' if breakdown else 'aggregated')
                output_sets = {}
                summaries = {}
                dumps = {}
                for stage, exe in executables.items():
                    run = work / case / stage
                    run.mkdir(parents=True)
                    config, output = comparison.write_run_config(
                        ROOT / 'config.example/test-scenario.example.nml', run)
                    text = setting(config.read_text(), 'write_netcdf', '.true.', 'output')
                    text = setting(text, 'netcdf_write_mode', repr(mode), 'output')
                    text = setting(text, 'include_waterbody_breakdown',
                                   '.true.' if breakdown else '.false.', 'output')
                    config.write_text(text)
                    command = [str(exe), str(config)]
                    commands.append(command)
                    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, timeout=180)
                    (run / 'model.log').write_text(result.stdout)
                    assert result.returncode == 0, f'{stage} {case}: exit {result.returncode}'
                    label = args.label[:16] if stage == 'reference' else args.label
                    console = [line for line in result.stdout.splitlines() if line.startswith('...version: ')]
                    assert console == ['...version: ' + label.ljust(16)], console
                    summaries[stage] = checked_summary((output / 'summary.md').read_text(), label)
                    command = ['ncdump', str(output / 'output.nc')]
                    commands.append(command)
                    dump = subprocess.check_output(command, text=True)
                    (run / 'output.cdl').write_text(dump)
                    dumps[stage] = checked_netcdf(dump, label)
                    output_sets[stage] = output
                before, after = output_sets['reference'], output_sets['candidate']
                names = {p.name for p in before.iterdir() if p.is_file()}
                assert names == {p.name for p in after.iterdir() if p.is_file()}, 'Output file set changed'
                for name in names - {'summary.md', 'output.nc'}:
                    comparison.compare_binary_files(before / name, after / name, name)
                assert summaries['reference'] == summaries['candidate'], 'Other summary text changed'
                assert dumps['reference'] == dumps['candidate'], 'Other NetCDF content changed'
                passed.append(case)
                print('PASS:', case, flush=True)
        assert hashes == {name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for name, path in executables.items()}, 'Executable changed during comparison'
    finally:
        (work / 'commands.json').write_text(json.dumps(commands, indent=2))
        (work / 'results.json').write_text(json.dumps({'label': args.label, 'passed': passed,
                                                    'executable_hashes': hashes}, indent=2))
        print('Version-output evidence:', work, flush=True)


if __name__ == '__main__':
    main()
