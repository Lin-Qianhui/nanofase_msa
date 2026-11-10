#!/usr/bin/env python3
"""Generate both source-level baselines with identical options (no comparison)."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fortran_dataflow import Project, discover, report, to_dot, write_evidence


def generate(root, label, out, render):
    files = discover([str(root / 'src'), str(root / 'vendor')])
    if not files:
        raise ValueError(f'No sources in {root}')
    project = Project(files, ignore=('omp_lib', 'netcdf', 'spoof'), strict=True)
    accesses, deps = project.analyse()
    stem = out / f'flow_{label}'
    with stem.with_suffix('.txt').open('w') as stream:
        report(accesses, deps, project, stream)
    to_dot(accesses, stem.with_suffix('.dot'), show_external=False)
    write_evidence(stem.with_suffix('.json'), accesses, deps, project)
    # A compact view of the specific variable that exposed the exporter bug.
    focus = [a for a in accesses if (a.owner, a.var) in (
        ('modeldimensionsmodule', 'npdim'), ('globalsmodule', 'c%npdim'))]
    focus_stem = out / f'npdim_{label}'
    to_dot(focus, focus_stem.with_suffix('.dot'), show_external=False)
    if render:
        for graph in (stem, focus_stem):
            subprocess.run(['dot', '-Tsvg', str(graph.with_suffix('.dot')),
                            '-o', str(graph.with_suffix('.svg'))], check=True)
    summary = {
        'root': str(root), 'parsed_files': len(files),
        'shared_state_relationships': len(accesses),
        'type_dependencies': len(deps), 'diagnostics': len(project.diagnostics),
        'uncertain_shared_state': [a._asdict() for a in accesses if '?' in a.mode],
        'npdim_writers': sorted(a.home for a in focus if 'W' in a.mode),
        'npdim_readers': sorted(a.home for a in focus if 'R' in a.mode),
    }
    print(f'{label}: {len(files)} parsed files; {len(accesses)} state relationships; '
          f'{len(summary["uncertain_shared_state"])} with uncertain effects', flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre-root', type=Path, required=True)
    parser.add_argument('--post-root', type=Path, default=REPO)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args()
    if not args.no_render and not shutil.which('dot'):
        parser.error('Graphviz dot is required for SVGs; use --no-render to omit them')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for label, root in (('premigration', args.pre_root), ('postmigration', args.post_root)):
        summaries[label] = generate(root.resolve(), label, args.output_dir, not args.no_render)
    (args.output_dir / 'coverage.json').write_text(json.dumps(summaries, indent=2) + '\n')


if __name__ == '__main__':
    main()
