#!/usr/bin/env python3
"""Cross-module data-flow extraction for modern Fortran, built on PSyclone.

Pass 1 (shared mutable state): reports how data moves through module-level
*variables* read/written across module boundaries. Named constants (kind params
like `dp`, `nf90_*`), derived TYPES, and PROCEDURES are filtered out - they are
not data flow. Emits a text report plus a colour-coded Graphviz .dot.

Pass 2 (derived-type component dependencies): for every obj%a access it resolves
obj's declared TYPE and the module that DEFINES that type, so "B depends on A via
C%a" is reported even when the object is local or a dummy argument. It also
classifies how the root object is bound (the `kind` field) to separate a
dependency on an imported TYPE (root local/dummy) from one on an imported
VARIABLE (root itself imported). Text report; disable with --no-types.

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
                                     RoutineSymbol, DataSymbol, DataTypeSymbol,
                                     ArrayType, StructureType)
from fparser.two.parser import ParserFactory
from fparser.common.readfortran import FortranStringReader
from fparser.two.utils import walk as fwalk
from fparser.two import Fortran2003 as f2

Access = namedtuple("Access", "home owner var mode internal")

# Pass-2 record:
#   home     accessing module (B)
#   tmod     module that DEFINES the derived type (A)
#   tname    derived type name (C)
#   comp     component path under the root object ("a", or nested "region%nx")
#   mode     "R" / "W" / "RW"
#   sure     False when the type's module could not be pinned down
#   kind     binding of the ROOT object - see _binding()
#   internal True when tmod is one of our internal modules
TypeDep = namedtuple("TypeDep", "home tmod tname comp mode sure kind internal")

# Bindings that mean "dependency on an imported TYPE" (root not itself imported).
_TYPE_ONLY = {"local", "arg", "module-var", "other"}

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

# --- pass 2 helpers --------------------------------------------------------

def _unwrap_derived(datatype):
    """Peel array wrappers and return (type_symbol, type_name) for a derived
    type, or (None, None) if the root is intrinsic / unresolvable."""
    for _ in range(8):                       # peel e.g. type(C) :: x(:,:)
        if isinstance(datatype, ArrayType):
            datatype = (getattr(datatype, "datatype", None)
                        or getattr(datatype, "_datatype", None))
        else:
            break
    if isinstance(datatype, DataTypeSymbol):
        return datatype, datatype.name
    if isinstance(datatype, StructureType):
        return datatype, "<inline>"          # defined in place, no module
    return None, None

def _resolve_datatype(sym, home, defs):
    """Return (type_sym, tname, type_home) for the root object's derived type.

    For a locally declared root the type is on the symbol itself. For a root
    IMPORTED from another module PSyclone leaves its datatype unresolved, so we
    follow the import into the defining module's declaration and read the type
    from there. type_home is the module whose declaration we used - it is where
    a DefaultModuleInterface type lives, so _defining_module needs it (not the
    accessing module) to attribute the type correctly."""
    type_sym, tname = _unwrap_derived(sym.datatype)
    if type_sym is not None:
        return type_sym, tname, home
    intf = getattr(sym, "interface", None)
    if isinstance(intf, ImportInterface):
        mod = intf.container_symbol.name.lower()
        real = defs.get(mod, {}).get(sym.name.lower())
        if real is not None and real is not sym:
            ts, tn = _unwrap_derived(real.datatype)
            if ts is not None:
                return ts, tn, mod
    return None, None, home

def _defining_module(type_sym, home):
    """Which module defines this derived type, and are we sure? ImportInterface
    is the reliable signal; DefaultModuleInterface means it is defined in the
    accessing module; anything else means the providing module was not parsed."""
    intf = getattr(type_sym, "interface", None)
    if isinstance(intf, ImportInterface):
        return intf.container_symbol.name.lower(), True
    if type(intf).__name__ == "DefaultModuleInterface":
        return home.lower(), True
    return home.lower(), False

def _binding(sym):
    """How the ROOT object is bound - separates a dep on an imported TYPE
    (root local/dummy) from a dep on an imported VARIABLE (root imported)."""
    n = type(getattr(sym, "interface", None)).__name__
    if n == "ImportInterface":
        return "var-import"        # the object itself is imported
    if n == "ArgumentInterface":
        return "arg"               # passed in - clean interface coupling
    if n == "DefaultModuleInterface":
        return "module-var"        # this module's own module-level state
    if n in ("AutomaticInterface", "StaticInterface", "LocalInterface"):
        return "local"             # local object of an imported type
    return "other"

# ---------------------------------------------------------------------------

def collect(files):
    """Pass 1: parse everything; record internal modules, routine names, the kind
    of every symbol each module DEFINES (not imports), and the actual DataSymbol
    for each module-level variable so Pass 2 can resolve imported roots' types."""
    reader = FortranReader()
    internal, routines, kinds, defs, trees, failed = (
        set(), set(), defaultdict(dict), defaultdict(dict), [], [])
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
                if isinstance(s, DataSymbol):
                    defs[c.name.lower()][s.name.lower()] = s
        for r in psyir.walk(Routine):
            routines.add(r.name.lower())
        trees.append((path, src, psyir))
    return internal, routines, kinds, defs, trees, failed

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

def _ref_part_name(part):
    """Name of one component in an fparser2 Data_Ref part, dropping any
    subscript so obj%comp(i) contributes 'comp', not 'comp' plus index names."""
    if isinstance(part, f2.Part_Ref):
        return str(part.children[0])
    return str(part)

def _fparser_tree(src):
    """Parse src with fparser2 and return (tree, home_module, used_modules)."""
    tree = ParserFactory().create(std="f2008")(FortranStringReader(src))
    mods = fwalk(tree, f2.Module_Stmt)
    home = str(fwalk(mods[0], f2.Name)[0]).lower() if mods else "<program>"
    used = {str(fwalk(u, f2.Name)[0]).lower() for u in fwalk(tree, f2.Use_Stmt)}
    return tree, home, used

def _component_deps_from_refs(drefs, home, used, write_ids, defs, var_owner,
                              internal, force_external):
    """Turn fparser2 Data_Ref nodes (obj%comp) into var-import TypeDeps, resolving
    the root's TYPE via defs. Only roots that are known imported module variables
    can be resolved (no type info for local/dummy roots without PSyIR); write iff
    the ref id is in write_ids, else read."""
    out, seen = [], set()
    for dref in drefs:
        parts = dref.children
        if len(parts) < 2:                       # need at least root%component
            continue
        root = _ref_part_name(parts[0]).lower()
        owners = var_owner.get(root, set()) & used
        if not owners:
            continue                             # root not a known imported var
        owner = sorted(owners)[0]
        real = defs.get(owner, {}).get(root)
        if real is None:
            continue
        type_sym, tname = _unwrap_derived(real.datatype)
        if type_sym is None:
            continue
        tmod, sure = _defining_module(type_sym, owner)
        if tmod in INTRINSIC:
            continue
        comp = "%".join(_ref_part_name(p) for p in parts[1:])
        mode = "W" if id(dref) in write_ids else "R"
        tmod_internal = tmod in internal and tmod not in force_external
        key = (home, tmod, tname.lower(), comp.lower(), mode)
        if key in seen:
            continue
        seen.add(key)
        out.append(TypeDep(home, tmod, tname, comp, mode, sure, "var-import",
                           tmod_internal))
    return out

def fallback_type_deps(src, defs, var_owner, internal, force_external):
    """Coarse Pass 2 for files PSyclone couldn't build PSyIR for. Scans every
    obj%comp ref (executable AND declaration) and emits var-import TypeDeps for
    imported-variable roots. R/W is approximated: write iff the ref is an
    assignment LHS. A salvage, not a full analysis."""
    tree, home, used = _fparser_tree(src)
    write_ids = {id(asg.children[0]) for asg in fwalk(tree, f2.Assignment_Stmt)
                 if isinstance(asg.children[0], f2.Data_Ref)}
    return _component_deps_from_refs(fwalk(tree, f2.Data_Ref), home, used,
                                     write_ids, defs, var_owner, internal,
                                     force_external)

def spec_expr_type_deps(src, defs, var_owner, internal, force_external):
    """PSyIR's reference_accesses() ignores declaration specification expressions
    (array bounds, kinds), so obj%comp used only to size a local array - e.g.
    real(dp) :: x(C%nSizeClassesSpm) - is invisible to Pass 2 even when the file
    parses. Recover those reads by scanning declaration statements with fparser2;
    a spec expression is always a read."""
    tree, home, used = _fparser_tree(src)
    drefs = [d for decl in fwalk(tree, f2.Type_Declaration_Stmt)
             for d in fwalk(decl, f2.Data_Ref)]
    return _component_deps_from_refs(drefs, home, used, set(), defs, var_owner,
                                     internal, force_external)

def type_component_deps(trees, internal, force_external, defs):
    """Pass 2: derived-type COMPONENT dependencies. For every obj%a access,
    resolve obj's declared TYPE and the module that defines it, and classify how
    the root object is bound so an imported-TYPE dependency can be told apart
    from an imported-VARIABLE one. Reuses the trees parsed by collect(); defs lets
    us recover the type of a root IMPORTED from another module."""
    out, seen = [], set()
    for _path, _src, psyir in trees:
        for rtn in psyir.walk(Routine):
            home = module_of(rtn)
            vam = rtn.reference_accesses()
            for sig in vam.all_signatures:
                if not sig.is_structure:         # need at least root%component
                    continue
                root = sig.var_name
                try:
                    sym = rtn.symbol_table.lookup(root)
                except KeyError:
                    continue
                if not isinstance(sym, DataSymbol):
                    continue
                type_sym, tname, type_home = _resolve_datatype(sym, home, defs)
                if type_sym is None:
                    continue                     # intrinsic-typed root, not a dep
                tmod, sure = _defining_module(type_sym, type_home)
                if tmod in INTRINSIC:
                    continue
                kind = _binding(sym)
                comp = str(sig[1:])              # component path below the root
                mode = ("R" if vam.is_read(sig) else "") + ("W" if vam.is_written(sig) else "")
                tmod_internal = tmod in internal and tmod not in force_external
                key = (home.lower(), tmod, tname.lower(), comp.lower(), mode, kind)
                if key in seen:
                    continue
                seen.add(key)
                out.append(TypeDep(home, tmod, tname, comp, mode, sure, kind,
                                   tmod_internal))
    return out

def analyse(args):
    exts = tuple(args.ext) if args.ext else DEFAULT_EXTS
    files = discover(args.src, exts)
    if not files:
        sys.exit("No source files found under --src")
    print(f"# analysing {len(files)} file(s)", file=sys.stderr)

    internal, routine_names, kinds, defs, trees, failed = collect(files)

    # modules forced to count as external (ignored by the user, or intrinsic)
    force_external = {m.lower() for m in (args.ignore or [])} | INTRINSIC

    # map of known module-level variable -> set of modules defining it (for fallback)
    var_owner = defaultdict(set)
    for mod, syms in kinds.items():
        for nm, k in syms.items():
            if k == "var":
                var_owner[nm].add(mod)

    seen, accesses = set(), []
    for _path, _src, psyir in trees:
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
    failed_modules, fallback_type = [], []
    for path, src in failed:
        try:
            home, cand = fallback_accesses(src, var_owner)
        except Exception as e:
            print(f"# FALLBACK FAILED {path}: {type(e).__name__}: {e}", file=sys.stderr)
            failed_modules.append((path, "<unparsed>"))
            continue
        failed_modules.append((path, home))
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
        # coarse pass-2 for the same file (imported-variable component access)
        try:
            fallback_type += fallback_type_deps(src, defs, var_owner, internal,
                                                force_external)
        except Exception as e:
            print(f"# FALLBACK TYPE FAILED {path}: {type(e).__name__}: {e}",
                  file=sys.stderr)

    # pass 2: derived-type component dependencies (parsed trees + salvaged files)
    type_deps = type_component_deps(trees, internal, force_external, defs)
    type_deps += fallback_type
    # supplement: declaration spec-expressions (array bounds etc.) that PSyIR's
    # reference_accesses() skips - parsed files only; failed ones are covered above
    for _path, src, _psyir in trees:
        try:
            type_deps += spec_expr_type_deps(src, defs, var_owner, internal,
                                             force_external)
        except Exception as e:
            print(f"# SPEC SCAN FAILED {_path}: {type(e).__name__}: {e}",
                  file=sys.stderr)
    # dedup across all sources (same component reached via more than one pass)
    uniq, deduped = set(), []
    for d in type_deps:
        key = (d.home.lower(), d.tmod, d.tname.lower(), d.comp.lower(), d.mode, d.kind)
        if key in uniq:
            continue
        uniq.add(key)
        deduped.append(d)
    return accesses, deduped, failed_modules

def report_degraded(failed_modules, out=sys.stdout):
    if not failed_modules:
        return
    print("# !! DEGRADED COVERAGE - PSyclone could not build PSyIR for these "
          "file(s).", file=out)
    print("#    They were salvaged with the coarse fparser2 fallback: shared-state "
          "and", file=out)
    print("#    derived-type component deps are recovered ONLY for imported "
          "module-variable", file=out)
    print("#    roots. Local/dummy roots, call-argument accesses and combined RW "
          "detail", file=out)
    print("#    may be MISSING for the module(s) below - treat their rows as a "
          "floor.", file=out)
    for path, mod in sorted(failed_modules):
        print(f"#    - {mod or '<program>'}  ({path})", file=out)
    print(file=out)

def _home_display(items):
    """Map each home.lower() to a single display name, preferring a mixed-case
    variant (from PSyIR) over an all-lowercase one (from the fparser2 fallback)
    so the two never split into separate report groups."""
    names = {}
    for it in items:
        lh = it.home.lower()
        if lh not in names or (names[lh] == lh and it.home != lh):
            names[lh] = it.home
    return names

def report(accesses, out=sys.stdout):
    print("# Shared mutable state (R=read, W=write, RW=both)\n", file=out)
    names = _home_display(accesses)
    cur = None
    for a in sorted(accesses, key=lambda a: (a.home.lower(), not a.internal, a.owner, a.var)):
        lh = a.home.lower()
        if lh != cur:
            cur = lh; print(names[lh] or "<program>", file=out)
        tag = "internal" if a.internal else "EXTERNAL"
        print(f"    [{tag:8s}] {a.owner}::{a.var:24s} {a.mode}", file=out)

def report_type_deps(deps, out=sys.stdout):
    print("# Derived-type component dependencies "
          "(home -> type_module::Type%component  R/W  [binding])", file=out)
    print("#   [binding] local/arg/module-var : dependency on an imported TYPE only", file=out)
    print("#   [binding] var-import           : root object imported -> also a "
          "shared VARIABLE (see list above)\n", file=out)
    names = _home_display(deps)
    by_home = defaultdict(list)
    for d in deps:
        by_home[d.home.lower()].append(d)
    for lh in sorted(by_home):
        rows = by_home[lh]
        n_type = sum(1 for d in rows if d.kind in _TYPE_ONLY)
        n_var = sum(1 for d in rows if d.kind == "var-import")
        print(f"{names[lh] or '<program>'}    ({n_type} type-dep, {n_var} var-import)", file=out)
        # type-only deps first (the rows unique to this pass), then var-imports
        for d in sorted(rows, key=lambda x: (x.kind == "var-import",
                                             not x.internal, x.tmod, x.tname, x.comp)):
            tag = "internal" if d.internal else "EXTERNAL"
            flag = "" if d.sure else "  (? type module unresolved)"
            label = f"{d.tname}%{d.comp}"
            print(f"    [{tag:8s}] {d.tmod}::{label:28s} {d.mode:2s} [{d.kind}]{flag}", file=out)

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
    ap.add_argument("--no-types", action="store_true",
                    help="skip pass 2 (derived-type component dependencies)")
    ap.add_argument("--strict", action="store_true",
                    help="also drop external names we cannot classify (nf90_* etc.)")
    ap.add_argument("-o", "--out", default="flow.dot")
    ap.add_argument("-r", "--report", default="flow.txt",
                    help="text report path; pass '-' to print to terminal")
    args = ap.parse_args()
    acc, type_deps, failed_modules = analyse(args)
    rf = sys.stdout if args.report == "-" else open(args.report, "w")
    try:
        report_degraded(failed_modules, out=rf)
        report(acc, out=rf)
        if not args.no_types:
            print(file=rf)
            report_type_deps(type_deps, out=rf)
    finally:
        if rf is not sys.stdout:
            rf.close()
            print(f"# wrote {args.report}", file=sys.stderr)
    to_dot(acc, args.out, show_external=not args.no_external)