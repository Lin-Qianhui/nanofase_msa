#!/usr/bin/env python3
"""Cross-module data-flow extraction for modern Fortran, built on PSyclone.

Reports how data moves through genuine SHARED MUTABLE STATE: module-level
*variables* read/written across module boundaries. Named constants (kind
params like `dp`, `nf90_*`), derived TYPES, and PROCEDURES are filtered out -
they are not data flow. Emits a text report plus a colour-coded Graphviz .dot.

Everything passed to --src is INTERNAL (your system). Imports from a module you
did not pass are EXTERNAL. Intrinsic modules (iso_fortran_env, iso_c_binding,
omp_lib, ieee_*) are always treated as external noise and dropped.

Usage:
    python fortran_dataflow.py --src src vendor \
        --ignore omp_lib netcdf spoof -o flow.dot
    dot -Tsvg flow.dot -o flow.svg
"""
import argparse, glob, os, sys
from collections import namedtuple, defaultdict

from psyclone.psyir.frontend.fortran import FortranReader
from psyclone.psyir.nodes import Routine, Container
from psyclone.psyir.symbols import (ImportInterface, DefaultModuleInterface,
                                     RoutineSymbol, DataSymbol, DataTypeSymbol)
from fparser.two.parser import ParserFactory
from fparser.common.readfortran import FortranStringReader
from fparser.two.utils import walk as fwalk
from fparser.two import Fortran2003 as f2

Access = namedtuple("Access", "home owner var mode internal")
DEFAULT_EXTS = (".f90", ".F90", ".f95", ".F95", ".f03", ".F03", ".f08", ".F08")
INTRINSIC = {"iso_fortran_env", "iso_c_binding", "omp_lib",
             "ieee_arithmetic", "ieee_exceptions", "ieee_features"}

def discover(entries, exts):
    found = []
    for e in entries:
        if os.path.isdir(e):
            for root, _, names in os.walk(e):
                found += [os.path.join(root, n) for n in names if n.endswith(exts)]
        elif any(ch in e for ch in "*?[]"):
            found += [p for p in glob.glob(e, recursive=True) if p.endswith(exts)]
        elif os.path.isfile(e):
            found.append(e)
        else:
            print(f"# WARN: '{e}' matched nothing", file=sys.stderr)
    seen, out = set(), []
    for p in found:
        rp = os.path.normpath(p)
        if rp not in seen:
            seen.add(rp); out.append(rp)
    return out

def kind_of(sym):
    if isinstance(sym, RoutineSymbol):  return "routine"
    if isinstance(sym, DataTypeSymbol): return "type"
    if isinstance(sym, DataSymbol):
        return "const" if getattr(sym, "is_constant", False) else "var"
    return "unknown"

def module_of(routine):
    node = routine.parent
    while node is not None and not isinstance(node, Container):
        node = node.parent
    return node.name if isinstance(node, Container) else "<program>"

def collect(files):
    """Pass 1: parse everything; record internal modules, routine names, and for
    each module the kind of every symbol it DEFINES (not imports)."""
    reader = FortranReader()
    internal, routines, kinds, trees, failed = set(), set(), defaultdict(dict), [], []
    for path in files:
        src = open(path).read()
        try:
            psyir = reader.psyir_from_source(src)
        except Exception as e:
            print(f"# FALLBACK {path}: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append((path, src))
            continue
        for c in psyir.walk(Container):
            if type(c).__name__ == "FileContainer":
                continue
            internal.add(c.name.lower())
            for s in c.symbol_table.symbols:
                if isinstance(s.interface, ImportInterface):
                    continue  # only record what this module actually defines
                kinds[c.name.lower()][s.name.lower()] = kind_of(s)
        for r in psyir.walk(Routine):
            routines.add(r.name.lower())
        trees.append((path, psyir))
    return internal, routines, kinds, trees, failed

def fallback_accesses(src, var_owner):
    """Coarse extraction via fparser2 for files PSyclone couldn't build PSyIR for.
    Matches assignment reads/writes against known module variables (var_owner:
    {var_lower: set(owner_modules)}), restricted to modules the file actually uses.
    Returns (home_module, [(owner, var, mode), ...]). Misses call-argument and
    derived-type-component writes - it is a salvage, not a full analysis."""
    parser = ParserFactory().create(std="f2008")
    tree = parser(FortranStringReader(src))
    mods = fwalk(tree, f2.Module_Stmt)
    home = str(fwalk(mods[0], f2.Name)[0]).lower() if mods else "<program>"
    used = {str(fwalk(u, f2.Name)[0]).lower() for u in fwalk(tree, f2.Use_Stmt)}
    out = []
    for sub in fwalk(tree, (f2.Subroutine_Subprogram, f2.Function_Subprogram)):
        writes, reads = set(), set()
        for asg in fwalk(sub, f2.Assignment_Stmt):
            lhs = [str(n).lower() for n in fwalk(asg.children[0], f2.Name)]
            if lhs:
                writes.add(lhs[0])
            reads.update(str(n).lower() for n in fwalk(asg.children[2], f2.Name))
        for v in (writes | reads):
            owners = var_owner.get(v, set()) & used     # only vars from used modules
            if not owners:
                continue
            owner = sorted(owners)[0]
            mode = ("R" if v in reads else "") + ("W" if v in writes else "")
            out.append((owner, v, mode))
    return home, out

def analyse(args):
    exts = tuple(args.ext) if args.ext else DEFAULT_EXTS
    files = discover(args.src, exts)
    if not files:
        sys.exit("No source files found under --src")
    print(f"# analysing {len(files)} file(s)", file=sys.stderr)

    internal, routine_names, kinds, trees, failed = collect(files)

    # modules forced to count as external (ignored by the user, or intrinsic)
    force_external = {m.lower() for m in (args.ignore or [])} | INTRINSIC

    # map of known module-level variable -> set of modules defining it (for fallback)
    var_owner = defaultdict(set)
    for mod, syms in kinds.items():
        for nm, k in syms.items():
            if k == "var":
                var_owner[nm].add(mod)

    seen, accesses = set(), []
    for path, psyir in trees:
        for rtn in psyir.walk(Routine):
            home = module_of(rtn)
            vam = rtn.reference_accesses()
            for sig in vam.all_signatures:
                name = sig.var_name
                low = name.lower()
                if low in routine_names:
                    continue
                try:
                    sym = rtn.symbol_table.lookup(name)
                except KeyError:
                    continue
                # resolved cases we can reject outright
                if isinstance(sym, (RoutineSymbol, DataTypeSymbol)):
                    continue
                if isinstance(sym, DataSymbol) and getattr(sym, "is_constant", False):
                    continue
                # owning module
                intf = sym.interface
                if isinstance(intf, DefaultModuleInterface):
                    owner = home.lower()
                elif isinstance(intf, ImportInterface):
                    owner = intf.container_symbol.name.lower()
                else:
                    continue  # local var or dummy argument
                if owner in INTRINSIC:
                    continue
                # what does the OWNING module say this name is?
                k = kinds.get(owner, {}).get(low)
                if k in ("routine", "type", "const"):
                    continue                       # not data
                owner_internal = owner in internal and owner not in force_external
                if owner_internal and k is None:
                    # owner re-exports it from elsewhere (e.g. netcdf via mo_netcdf)
                    owner_internal = False         # treat as external
                if k is None and not owner_internal and args.strict:
                    continue                       # drop unclassifiable externals
                mode = ("R" if vam.is_read(sig) else "") + ("W" if vam.is_written(sig) else "")
                key = (home.lower(), owner, low, mode)
                if key in seen:
                    continue
                seen.add(key)
                accesses.append(Access(home, owner, low, mode, owner_internal))

    # salvage files PSyclone could not build PSyIR for
    for path, src in failed:
        try:
            home, cand = fallback_accesses(src, var_owner)
        except Exception as e:
            print(f"# FALLBACK FAILED {path}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        for owner, var, mode in cand:
            if owner in INTRINSIC:
                continue
            owner_internal = owner in internal and owner not in force_external
            if owner_internal and kinds.get(owner, {}).get(var) is None:
                owner_internal = False
            if not owner_internal and args.strict:
                continue
            key = (home, owner, var, mode)
            if key in seen:
                continue
            seen.add(key)
            accesses.append(Access(home, owner, var, mode, owner_internal))
    return accesses

def report(accesses):
    print("# Shared mutable state (R=read, W=write, RW=both)\n")
    cur = None
    for a in sorted(accesses, key=lambda a: (a.home.lower(), not a.internal, a.owner, a.var)):
        if a.home != cur:
            cur = a.home; print(a.home or "<program>")
        tag = "internal" if a.internal else "EXTERNAL"
        print(f"    [{tag:8s}] {a.owner}::{a.var:24s} {a.mode}")

def to_dot(accesses, path, show_external):
    # combine modes per (home-module, owner::var) edge
    combo = defaultdict(lambda: {"R": False, "W": False, "internal": True})
    for a in accesses:
        if not a.internal and not show_external:
            continue
        vid = f"{a.owner}::{a.var}"
        e = combo[(a.home, vid)]
        if "R" in a.mode: e["R"] = True
        if "W" in a.mode: e["W"] = True
        e["internal"] = a.internal
    COLOR = {"R": "#1f77b4", "W": "#d62728", "RW": "#7e3ff2"}
    mods, vars_ = set(), {}
    lines = []
    for (home, vid), e in combo.items():
        mods.add(home); vars_[vid] = e["internal"]
        mode = "RW" if (e["R"] and e["W"]) else ("R" if e["R"] else "W")
        c = COLOR[mode]
        if mode == "W":
            lines.append(f'  "{home}" -> "{vid}" [color="{c}", penwidth=1.6, label="W"];')
        elif mode == "R":
            lines.append(f'  "{vid}" -> "{home}" [color="{c}", penwidth=1.6, label="R"];')
        else:  # RW: one double-headed edge
            lines.append(f'  "{home}" -> "{vid}" [color="{c}", penwidth=1.8, dir=both, label="RW"];')
    with open(path, "w") as f:
        f.write("digraph dataflow {\n  rankdir=LR;\n  node [fontname=Helvetica];\n"
                "  edge [fontname=Helvetica, fontsize=9];\n")
        for m in sorted(mods):
            f.write(f'  "{m}" [shape=box, style=filled, fillcolor="#cfe8ff"];\n')
        for vid, internal in sorted(vars_.items()):
            f.write(f'  "{vid}" [shape=ellipse, style=filled, '
                    f'fillcolor="{"#fff2cc" if internal else "#eeeeee"}"];\n')
        f.write("\n".join(lines) + "\n")
        # legend
        f.write('''
  subgraph cluster_legend {
    label="Legend"; fontname=Helvetica; style=dashed; color="#999999";
    lw1 [shape=box, label="module", fillcolor="#cfe8ff", style=filled];
    lv1 [shape=ellipse, label="state var", fillcolor="#fff2cc", style=filled];
    lw1 -> lv1 [color="#d62728", label="writes (W)", penwidth=1.6];
    lr0 [shape=ellipse, label="state var ", fillcolor="#fff2cc", style=filled];
    lr1 [shape=box, label="module ", fillcolor="#cfe8ff", style=filled];
    lr0 -> lr1 [color="#1f77b4", label="reads (R)", penwidth=1.6];
    lb0 [shape=box, label="module  ", fillcolor="#cfe8ff", style=filled];
    lb1 [shape=ellipse, label="state var  ", fillcolor="#fff2cc", style=filled];
    lb0 -> lb1 [color="#7e3ff2", label="read+write (RW)", dir=both, penwidth=1.8];
  }
}
''')
    print(f"# wrote {path}  (render: dot -Tsvg {path} -o flow.svg)", file=sys.stderr)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-module Fortran data-flow extractor")
    ap.add_argument("--src", nargs="+", required=True,
                    help="dirs (walked recursively), globs, or files - all internal")
    ap.add_argument("--ignore", action="extend", nargs="+", default=[],
                    help="module name(s) to force-treat as external")
    ap.add_argument("--ext", nargs="+", help="source extensions (default: free-form Fortran)")
    ap.add_argument("--no-external", action="store_true", help="drop external state from graph")
    ap.add_argument("--strict", action="store_true",
                    help="also drop external names we cannot classify (nf90_* etc.)")
    ap.add_argument("-o", "--out", default="flow.dot")
    args = ap.parse_args()
    acc = analyse(args)
    report(acc)
    to_dot(acc, args.out, show_external=not args.no_external)