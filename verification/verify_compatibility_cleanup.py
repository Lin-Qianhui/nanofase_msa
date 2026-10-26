#!/usr/bin/env python3
"""Check that removed settings code is absent and original comments survive.

Use --reference-source with an isolated pre-phase source copy to also record a
destination for every original Fortran comment, including repeated occurrences.
Only the Python standard library is needed. This program does not edit source.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def source_parts(source: str) -> tuple[str, list[tuple[int, str]]]:
    """Separate Fortran code from strings/comments, respecting doubled quotes."""
    code = []
    comments = []
    quote = None
    for number, line in enumerate(source.splitlines(), 1):
        output = []
        i = 0
        while i < len(line):
            char = line[i]
            if quote:
                if char == quote:
                    if i + 1 < len(line) and line[i + 1] == quote:
                        output.extend('  ')
                        i += 2
                        continue
                    quote = None
                output.append(' ')
            elif char in ('"', "'"):
                quote = char
                output.append(' ')
            elif char == '!':
                comments.append((number, line[i:].rstrip()))
                break
            else:
                output.append(char)
            i += 1
        code.append(''.join(output))
    return '\n'.join(code), comments


def fortran_files(root: Path, archives: bool = False) -> list[Path]:
    folders = ['src', 'test'] + (['migration_documentation'] if archives else [])
    return sorted(p for folder in folders for p in (root / folder).rglob('*.f90'))


def check(root: Path, reference: Path | None = None) -> dict:
    forbidden = re.compile(
        r'\b(?:GlobalsModule|DefaultsModule|GlobalsType|syncRuntimeModelConfigToGlobals|'
        r'syncModelConfigToGlobals|syncModelDimensionsToGlobals)\b|\bC\s*%', re.I)
    for path in fortran_files(root):
        code, _ = source_parts(path.read_text())
        match = forbidden.search(code)
        if match:
            line = code[:match.start()].count('\n') + 1
            raise AssertionError(f'Old settings code: {path.relative_to(root)}:{line}: {match.group()}')
    for name in ('GlobalsModule.f90', 'DefaultsModule.f90'):
        assert not (root / 'src' / name).exists(), f'Removed module remains: {name}'
    result = {'active_compatibility_references': 0}
    if reference:
        destinations = defaultdict(deque)
        for path in fortran_files(root, archives=True):
            _, comments = source_parts(path.read_text())
            for line, comment in comments:
                destinations[comment].append(f'{path.relative_to(root)}:{line}')
        mapping = []
        for path in fortran_files(reference):
            _, comments = source_parts(path.read_text())
            for line, comment in comments:
                assert destinations[comment], f'Original comment lost: {path.relative_to(reference)}:{line}: {comment}'
                mapping.append({'original': f'{path.relative_to(reference)}:{line}',
                                'destination': destinations[comment].popleft(), 'comment': comment})
        result.update(original_comment_count=len(mapping), comment_destinations=mapping)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--reference-source', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = check(args.source.resolve(), args.reference_source)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: no active compatibility code')
    if args.reference_source:
        print(f"PASS: {result['original_comment_count']} original comment occurrences preserved")


if __name__ == '__main__':
    main()
