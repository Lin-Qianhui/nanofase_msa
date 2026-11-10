#!/usr/bin/env python3
"""Source-level Fortran shared-state and derived-type access analysis.

Uses fparser2's syntax tree and a project-wide symbol/interface index. R/W are
syntactic accesses or explicit INTENT contracts; ? means an unresolved effect,
never a confirmed write. See dataflow/README.md for scope and limitations.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict, namedtuple
from dataclasses import dataclass, field
from pathlib import Path

from fparser.common.readfortran import FortranStringReader
from fparser.two.parser import ParserFactory
from fparser.two.utils import walk as fwalk
from fparser.two import Fortran2003 as f2

Access = namedtuple('Access', 'home owner var mode internal')
TypeDep = namedtuple('TypeDep', 'home tmod tname comp mode sure kind internal')
DEFAULT_EXTS = ('.f90', '.f95', '.f03', '.f08')
INTRINSIC = {'iso_fortran_env', 'iso_c_binding', 'omp_lib',
             'ieee_arithmetic', 'ieee_exceptions', 'ieee_features'}
EXAMPLE_DIRS = {'test', 'tests', 'example', 'examples'}


def children(node):
    if isinstance(node, (list, tuple)):
        return node
    return getattr(node, 'content', None) or getattr(node, 'items', ()) or ()


def tag(node):
    return type(node).__name__


def low(node):
    return str(node).lower()


def mode_union(modes):
    chars = set(''.join(modes))
    return ''.join(c for c in 'RW?' if c in chars)


def discover(entries, exts=DEFAULT_EXTS, include_examples=False):
    found = set()
    for entry in entries:
        if os.path.isdir(entry):
            for root, dirs, names in os.walk(entry):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and
                                 (include_examples or d.lower() not in EXAMPLE_DIRS))
                found.update(os.path.normpath(os.path.join(root, n)) for n in names
                             if n.lower().endswith(tuple(e.lower() for e in exts)))
        else:
            matches = glob.glob(entry, recursive=True)
            if not matches:
                raise ValueError(f"Source path matched nothing: {entry}")
            found.update(os.path.normpath(p) for p in matches if os.path.isfile(p))
    return sorted(found)


@dataclass(eq=False)
class Symbol:
    name: str
    scope: 'Scope'
    kind: str = 'var'
    type_name: str = ''
    intrinsic_type: str = ''
    rank: int = 0
    intent: str = ''
    optional: bool = False
    pointer: bool = False
    polymorphic: bool = False
    target: 'Scope' = None
    specifics: list = field(default_factory=list)
    # Type-bound procedure binding: interface or implementation, PASS/NOPASS.
    procedure: str = ''
    pass_arg: str = ''
    nopass: bool = False

    @property
    def owner(self):
        return self.scope.home.lower()


@dataclass(eq=False)
class Scope:
    name: str
    kind: str
    parent: 'Scope' = None
    path: str = ''
    node: object = None
    symbols: dict = field(default_factory=dict)
    uses: list = field(default_factory=list)
    public: bool = True
    visibility: dict = field(default_factory=dict)
    args: list = field(default_factory=list)
    base: str = ''
    namelists: dict = field(default_factory=dict)
    interface: bool = False
    imports: set = field(default_factory=set)
    import_all: bool = False
    aliases: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)

    @property
    def home(self):
        if self.kind in ('module', 'program', 'external'):
            return self.name
        return self.parent.home if self.parent else self.name


class Project:
    def __init__(self, files, ignore=(), strict=False):
        self.modules = {}
        self.scopes = []
        self.node_scopes = {}
        self.trees = []
        self.external = {}
        self.ignored = set(map(str.lower, ignore)) | INTRINSIC
        self.strict = strict
        self.evidence = set()
        self.type_rows = defaultdict(set)
        self.diagnostics = set()
        self._resolve_cache = {}
        self.effects = defaultdict(set)
        parser = ParserFactory().create(std='f2008')
        for path in files:
            source = Path(path).read_text()
            try:
                tree = parser(FortranStringReader(source))
            except Exception as exc:
                # Never silently compare graphs with different parser coverage.
                raise ValueError(f'Cannot parse {path}: {exc}') from exc
            self.trees.append((path, source, tree))
            self.index(tree, None, path)

    def add_scope(self, name, kind, parent, path, node, interface=False):
        scope = Scope(name, kind, parent, path, node, interface=interface)
        self.scopes.append(scope)
        self.node_scopes[id(node)] = scope
        if kind == 'module':
            if low(name) in self.modules:
                raise ValueError(f'Duplicate module {name}: {path}')
            self.modules[low(name)] = scope
        elif parent and kind in ('routine', 'type'):
            existing = parent.symbols.get(low(name))
            if existing and existing.kind == 'generic':
                existing.specifics.append(scope)
            else:
                parent.symbols[low(name)] = Symbol(low(name), parent, kind=kind,
                                                   target=scope)
        return scope

    def index(self, node, scope, path, interface=False):
        kind = tag(node)
        if kind in ('Module', 'Main_Program', 'Subroutine_Subprogram',
                    'Function_Subprogram', 'Subroutine_Body', 'Function_Body'):
            head = children(node)[0]
            name = str(head.items[1]) if head.items[1] else '<program>'
            skind = {'Module': 'module', 'Main_Program': 'program'}.get(kind, 'routine')
            scope = self.add_scope(name, skind, scope, path, node, interface)
            if skind == 'routine':
                scope.args = [low(a) for a in children(head.items[2])]
                for name in scope.args:
                    scope.symbols[name] = Symbol(name, scope)
                if tag(head) == 'Function_Stmt':
                    suffix = head.items[3]
                    result = low(suffix.items[0]) if suffix and suffix.items[0] else low(scope.name)
                    scope.symbols[result] = Symbol(result, scope)
                    for dtype in fwalk(head.items[0], f2.Declaration_Type_Spec):
                        scope.symbols[result].type_name = low(dtype.items[1])
        elif kind == 'Derived_Type_Def':
            head = children(node)[0]
            scope = self.add_scope(str(head.items[1]), 'type', scope, path, node)
            for attr in children(head.items[0]):
                if tag(attr) == 'Type_Attr_Spec' and attr.items[0] == 'EXTENDS':
                    scope.base = low(attr.items[1])
                elif low(attr) in ('public', 'private'):
                    scope.parent.visibility[low(scope.name)] = low(attr) == 'public'
        elif kind == 'Interface_Block':
            head = children(node)[0]
            name = head.items[0]
            generic = None
            if name and tag(name) == 'Name':
                generic = scope.symbols.setdefault(low(name), Symbol(low(name), scope, kind='generic'))
            for child in children(node)[1:]:
                if tag(child) == 'Procedure_Stmt':
                    if generic:
                        generic.specifics.extend(low(n) for n in children(child.items[0]))
                else:
                    self.index(child, scope, path, interface=True)
                    if generic and id(child) in self.node_scopes:
                        generic.specifics.append(self.node_scopes[id(child)])
            return
        elif scope:
            if kind == 'Use_Stmt':
                mod = low(node.items[2])
                only = 'ONLY' in str(node.items[3]).upper()
                mapping = {}
                for item in children(node.items[4]):
                    if tag(item) == 'Rename':
                        mapping[low(item.items[-2])] = low(item.items[-1])
                    elif tag(item) == 'Name':
                        mapping[low(item)] = low(item)
                scope.uses.append((mod, only, mapping))
                return
            if kind in ('Type_Declaration_Stmt', 'Data_Component_Def_Stmt'):
                dtype, attrs, decls = node.items
                type_name = low(dtype.items[1]) if tag(dtype) == 'Declaration_Type_Spec' else ''
                attr_text = str(attrs).lower() if attrs else ''
                intent = next((low(a.items[1]) for a in children(attrs)
                               if tag(a) == 'Intent_Attr_Spec'), '')
                dimension = next((a.items[1] for a in children(attrs)
                                  if tag(a) in ('Dimension_Attr_Spec', 'Dimension_Component_Attr_Spec')), None)
                for decl in children(decls):
                    name = low(decl.items[0])
                    sym = scope.symbols.setdefault(name, Symbol(name, scope))
                    sym.type_name = type_name
                    sym.polymorphic = tag(dtype) == 'Declaration_Type_Spec' and low(dtype.items[0]) == 'class'
                    sym.intrinsic_type = low(dtype.items[0]) if tag(dtype) == 'Intrinsic_Type_Spec' else ''
                    sym.kind = 'const' if 'parameter' in attr_text else 'var'
                    sym.intent = intent
                    sym.optional = 'optional' in attr_text
                    sym.pointer = 'pointer' in attr_text
                    shape = decl.items[1] or dimension
                    sym.rank = len(children(shape)) if shape else 0
                    for access in ('public', 'private'):
                        if access in attr_text:
                            scope.visibility[name] = access == 'public'
                return
            if kind == 'Access_Stmt':
                public = low(node.items[0]) == 'public'
                if node.items[1] is None:
                    scope.public = public
                else:
                    scope.visibility.update((low(n), public) for n in children(node.items[1]))
                return
            if kind == 'Import_Stmt':
                if node.items[1]:
                    scope.imports.update(low(n) for n in children(node.items[1]))
                else:
                    scope.import_all = True
                return
            if kind == 'Namelist_Stmt':
                for name, members in node.items:
                    scope.namelists[low(name)] = list(children(members))
                return
            if kind == 'Specific_Binding':
                interface_name, attrs, _, name, implementation = node.items
                attr_text = str(attrs).lower() if attrs else ''
                sym = Symbol(low(name), scope, kind='binding',
                             procedure=low(implementation or interface_name or name),
                             nopass='nopass' in attr_text)
                for attr in children(attrs):
                    if tag(attr) == 'Binding_PASS_Arg_Name':
                        sym.pass_arg = low(attr.items[1])
                scope.symbols[sym.name] = sym
                return
            if kind == 'Generic_Binding':
                _, name, specifics = node.items
                scope.symbols[low(name)] = Symbol(low(name), scope, kind='generic',
                                                specifics=[low(n) for n in children(specifics)])
                return
        for child in children(node):
            self.index(child, scope, path, interface)

    def external_symbol(self, mod, name):
        key = (mod, name)
        if key not in self.external:
            scope = Scope(mod, 'external')
            self.external[key] = Symbol(name, scope, kind='unknown')
        return self.external[key]

    def resolve(self, scope, name, exported=False, trail=frozenset(), types_only=False):
        name = low(name)
        # Keep the scope itself alive in the cache. Ephemeral ASSOCIATE/SELECT
        # scopes can otherwise reuse object ids and inherit a different binding.
        key = (scope, name, exported, types_only)
        if key in trail or scope is None:
            return ()
        if not trail and key in self._resolve_cache:
            return self._resolve_cache[key]
        if exported and not scope.visibility.get(name, scope.public):
            return ()
        trail = trail | {key}
        if name in scope.symbols and (not types_only or scope.symbols[name].kind == 'type'):
            return (scope.symbols[name],)
        found = []
        explicit_import = False
        for mod, only, mapping in scope.uses:
            if name in mapping:
                remote = mapping[name]
                explicit_import = True
            elif only or name in {v for k, v in mapping.items() if k != v}:
                continue
            else:
                remote = name
            if mod in self.modules:
                found.extend(self.resolve(self.modules[mod], remote, True, trail, types_only))
            elif mod not in INTRINSIC or name in mapping:
                # Wildcard imports from absent modules cannot prove ownership.
                found.append(self.external_symbol(mod, remote))
        concrete = [s for s in found if s.kind != 'unknown']
        if concrete:
            # Prefer a known declaration over hypothetical absent exports.
            # This assumes valid Fortran; unavailable providers are listed in JSON.
            found = concrete
        if not concrete and not explicit_import and not exported and scope.parent and (
                not scope.interface or scope.import_all or name in scope.imports):
            host = self.resolve(scope.parent, name, False, trail, types_only)
            known_host = [s for s in host if s.kind != 'unknown']
            found = known_host or list(dict.fromkeys(found + list(host)))
        result = tuple(dict.fromkeys(found))
        # Only cache complete top-level lookups (cycles may truncate recursion).
        if len(trail) == 1:
            self._resolve_cache[key] = result
        return result

    def one(self, scope, name):
        found = self.resolve(scope, name)
        return found[0] if len(found) == 1 else None

    def type_scope(self, symbol):
        if not symbol or not symbol.type_name or symbol.type_name == '*':
            return None
        found = self.resolve(symbol.scope, symbol.type_name, types_only=True)
        ts = found[0] if len(found) == 1 else None
        return ts.target if ts and ts.kind == 'type' else None

    def member(self, scope, name, seen=frozenset()):
        if not scope or id(scope) in seen:
            return None
        if name in scope.symbols:
            return scope.symbols[name]
        if scope.base:
            if name == scope.base:
                # EXTENDS implicitly declares a component with the parent's name.
                return Symbol(name, scope.parent, type_name=scope.base)
            base = self.one(scope.parent, scope.base)
            if base and base.target:
                return self.member(base.target, name, seen | {id(scope)})
        return None

    def location(self, node, scope):
        cur = node
        while cur is not None:
            item = getattr(cur, 'item', None)
            if item:
                return scope.path, item.span[0], str(cur).replace('\n', ' ')
            cur = getattr(cur, 'parent', None)
        return scope.path, 0, str(node).replace('\n', ' ')

    def diagnostic(self, node, scope, message):
        self.diagnostics.add((*self.location(node, scope), message))

    def ref_parts(self, node):
        if tag(node) in ('Name', 'Type_Name'):
            return [(low(node), None)]
        if tag(node) == 'Part_Ref':
            return [(low(node.items[0]), node.items[1])]
        if tag(node) == 'Data_Ref':
            return [part for item in node.items for part in self.ref_parts(item)]
        if tag(node) in ('Data_Pointer_Object', 'Procedure_Designator', 'Proc_Component_Ref'):
            return self.ref_parts(node.items[0]) + self.ref_parts(node.items[2])
        if tag(node) == 'Substring':
            return self.ref_parts(node.items[0])
        return []

    def root_ref(self, node, scope):
        """Return defining root, component names, final symbol, and index ASTs."""
        parts = self.ref_parts(node)
        if not parts:
            return None, [], None, []
        name = parts[0][0]
        indices = [idx for _, idx in parts if idx is not None]
        alias_scope = scope
        while alias_scope:
            if name in alias_scope.aliases:
                expr, origin = alias_scope.aliases[name]
                root, path, last, _ = self.root_ref(expr, origin)
                override = alias_scope.overrides.get(name)
                if override:
                    last = Symbol(name, alias_scope, type_name=override)
                break
            if name in alias_scope.symbols or alias_scope.uses:
                break
            alias_scope = alias_scope.parent
        if not alias_scope or name not in alias_scope.aliases:
            root = last = self.one(scope, name)
            path = []
        for comp, _ in parts[1:]:
            path.append(comp)
            last = self.member(self.type_scope(last), comp)
        return root, path, last, indices

    def reference(self, node, scope, mode, reason, site=None):
        root, path, last, indices = self.root_ref(node, scope)
        for idx in indices:
            self.expr(idx, scope)
        if tag(node) == 'Substring':
            self.expr(node.items[1], scope)
        if not root:
            names = self.ref_parts(node)
            if names:
                self.diagnostic(node, scope, f'Unresolved or ambiguous symbol: {names[0][0]}')
            return
        if root.kind not in ('var', 'unknown'):
            return
        if last and last.kind in ('routine', 'binding', 'generic', 'const', 'type'):
            return
        if path and last is None:
            self.diagnostic(node, scope, f'Unresolved component type: {root.name}%{"%".join(path)}')
        if root.name in root.scope.args and mode:
            self.effects[root].add(mode)
        if not mode:
            return
        if root.scope.kind in ('module', 'external') and root.owner not in INTRINSIC:
            if not (root.kind == 'unknown' and self.strict):
                # Unknown external exports might be constants: do not assert R/W.
                actual_mode = '?' if root.kind == 'unknown' else mode
                var = '%'.join([root.name] + path)
                self.evidence.add((scope.home, root.owner, var, actual_mode,
                                   *self.location(site or node, scope), reason))
        if path:
            ts = self.type_scope(root)
            if ts is None and self.ref_parts(node):
                # SELECT TYPE can supply the concrete type of an unlimited
                # polymorphic dummy without changing its original identity.
                first = node.items[0] if tag(node) == 'Data_Ref' else node
                ts = self.type_scope(self.root_ref(first, scope)[2])
            if ts:
                binding = ('var-import' if root.scope.kind == 'module' and root.owner != scope.home.lower()
                           else 'module-var' if root.scope.kind == 'module'
                           else 'arg' if root.name in root.scope.args else 'local')
                key = (scope.home, ts.home.lower(), ts.name.lower(), '%'.join(path),
                       True, binding, ts.home.lower() in self.modules and ts.home.lower() not in self.ignored)
                self.type_rows[key].add(mode)

    def signature(self, symbol, seen=frozenset()):
        if symbol is None or id(symbol) in seen:
            return []
        seen = seen | {id(symbol)}
        if symbol.kind == 'routine':
            return [(symbol.target, None)]
        if symbol.kind == 'binding':
            target = self.one(symbol.scope.parent, symbol.procedure)
            return [(r, symbol) for r, _ in self.signature(target, seen)]
        if symbol.kind in ('generic', 'type') and symbol.specifics:
            result = []
            for spec in symbol.specifics:
                if isinstance(spec, Scope):
                    result.append((spec, None))
                else:
                    target = (self.member(symbol.scope, spec) if symbol.scope.kind == 'type'
                              else self.one(symbol.scope, spec))
                    result.extend(self.signature(target, seen))
            return result
        return []

    def bound_candidates(self, obj, symbol):
        candidates = self.signature(symbol)
        declared = self.type_scope(obj)
        if not obj or not obj.polymorphic or not declared or not symbol:
            return candidates
        # A CLASS(Base) receiver can dispatch to any supplied extension. Keep
        # the declared interface too: missing intents on a deferred binding
        # remain uncertain rather than assuming a particular dynamic type.
        for scope in self.scopes:
            if scope.kind != 'type' or scope is declared:
                continue
            base, seen = scope, set()
            while base and base.base and id(base) not in seen:
                seen.add(id(base))
                parent = self.one(base.parent, base.base)
                base = parent.target if parent else None
                if base is declared:
                    candidates.extend(self.signature(self.member(scope, symbol.name)))
                    break
        return list(dict.fromkeys(candidates))

    def actuals(self, arglist):
        return [(low(a.items[0]), a.items[1]) if tag(a) in ('Actual_Arg_Spec', 'Component_Spec')
                else (None, a) for a in children(arglist)]

    def argument_modes(self, candidates, actuals, receiver):
        """Map keywords and PASS to dummies; require compatible intents on overloads.

        Ambiguous generics are deliberately not guessed by name/rank alone.
        """
        matches = []
        for routine, binding in candidates:
            names = list(routine.args)
            bound = {}
            if receiver is not None and binding and not binding.nopass:
                pname = binding.pass_arg or (names[0] if names else '')
                if pname not in names:
                    continue
                bound[pname] = -1
            positional = [n for n in names if n not in bound]
            valid = True
            for i, (keyword, _) in enumerate(actuals):
                name = keyword or (positional.pop(0) if positional else '')
                if name not in names or name in bound:
                    valid = False
                    break
                if keyword and name in positional:
                    positional.remove(name)
                bound[name] = i
            if not valid or any(n not in bound and not routine.symbols[n].optional for n in names):
                continue
            intents = {}
            for name, index in bound.items():
                intent = routine.symbols[name].intent
                dummy = routine.symbols[name]
                inferred = '?' if routine.interface or dummy.pointer else mode_union(self.effects[dummy])
                intents[index] = {'in': 'R', 'out': 'W', 'inout': 'RW'}.get(intent, inferred)
            matches.append(intents)
        if not matches:
            return {}
        return {i: next(iter(values)) if len(values := {m.get(i, '?') for m in matches}) == 1 else '?'
                for i in set().union(*(m.keys() for m in matches))}

    def call(self, designator, arglist, scope, intrinsic=False, receiver_override=None, symbol_override=None):
        actuals = self.actuals(arglist)
        name = low(designator)
        receiver = receiver_override
        obj = None
        if receiver_override is not None:
            symbol = symbol_override
            obj = self.root_ref(receiver, scope)[2]
        elif tag(designator) == 'Procedure_Designator':
            receiver = designator.items[0]
            _, _, obj, _ = self.root_ref(receiver, scope)
            symbol = self.member(self.type_scope(obj), low(designator.items[2]))
        else:
            symbol = self.one(scope, name)
        if symbol and symbol.kind == 'type' and not symbol.specifics:
            # Structure constructors copy component expressions.
            for _, arg in actuals:
                self.expr(arg, scope)
            return
        candidates = self.bound_candidates(obj, symbol) if receiver is not None else self.signature(symbol)
        modes = self.argument_modes(candidates, actuals, receiver)
        # Standard intrinsic functions only read arguments. Intrinsic subroutines
        # with output arguments require their own explicit contracts.
        contracts = {
            'random_number': (('harvest', 'W'),),
            'cpu_time': (('time', 'W'),),
            'system_clock': (('count', 'W'), ('count_rate', 'W'), ('count_max', 'W')),
            'date_and_time': (('date', 'W'), ('time', 'W'), ('zone', 'W'), ('values', 'W')),
            'random_seed': (('size', 'W'), ('put', 'R'), ('get', 'W')),
            'move_alloc': (('from', 'RW'), ('to', 'W')),
            'get_command_argument': (('number', 'R'), ('value', 'W'), ('length', 'W'), ('status', 'W')),
            'get_environment_variable': (('name', 'R'), ('value', 'W'), ('length', 'W'), ('status', 'W'), ('trim_name', 'R')),
        }
        if (not symbol or symbol.kind == 'unknown') and name in contracts:
            contract = contracts[name]
            modes = {i: dict(contract).get(keyword, '?') if keyword else
                     contract[i][1] if i < len(contract) else '?'
                     for i, (keyword, _) in enumerate(actuals)}
        elif intrinsic:
            modes = dict.fromkeys(range(len(actuals)), 'R')
        for i, (_, arg) in enumerate(actuals):
            mode = modes.get(i, '?')
            # Expressions are evaluated; only a designator can be modified by a
            # callee. In particular f(x + 1) does not write x.
            if self.is_variable(arg, scope):
                self.reference(arg, scope, mode, f'argument of {name}' +
                               (' (unresolved effect)' if '?' in mode else ' (callee intent/body)'))
            else:
                self.expr(arg, scope)
        if receiver is not None:
            # NOPASS bindings do not access the receiver's data.
            if not candidates or any(not b or not b.nopass for _, b in candidates):
                self.reference(receiver, scope, modes.get(-1, '?'), f'passed object of {name}')
            else:
                for idx in self.root_ref(receiver, scope)[3]:
                    self.expr(idx, scope)
        if (actuals or receiver is not None) and ((not modes and not candidates) or any('?' in m for m in modes.values())):
            self.diagnostic(designator, scope, f'Unresolved argument effects: {name}')

    def is_variable(self, node, scope):
        if tag(node) not in ('Name', 'Part_Ref', 'Data_Ref', 'Substring', 'Data_Pointer_Object', 'Proc_Component_Ref'):
            return False
        root, _, last, _ = self.root_ref(node, scope)
        if tag(node) == 'Part_Ref' and root and (root.kind not in ('var', 'unknown') or
                                               (not root.rank and root.intrinsic_type != 'character')):
            return False
        return last is None or last.kind in ('var', 'unknown')

    def expr(self, node, scope):
        kind = tag(node)
        if node is None or isinstance(node, (str, int)):
            return
        if kind == 'Name':
            self.reference(node, scope, 'R', 'expression')
        elif kind == 'Part_Ref':
            symbol = self.one(scope, low(node.items[0]))
            root = self.root_ref(node, scope)[0]
            if root is None or (symbol and symbol.kind in ('routine', 'generic', 'type')) or (
                    root and root.kind == 'unknown'):
                self.call(node.items[0], node.items[1], scope)
            else:
                self.reference(node, scope, 'R', 'array/substring expression')
        elif kind in ('Data_Ref', 'Substring', 'Data_Pointer_Object', 'Proc_Component_Ref'):
            last = self.root_ref(node, scope)[2]
            if kind == 'Data_Ref' and last and last.kind in ('binding', 'generic'):
                parts = node.items
                receiver = parts[0] if len(parts) == 2 else f2.Data_Ref('%'.join(map(str, parts[:-1])))
                receiver.parent = node
                args = parts[-1].items[1] if tag(parts[-1]) == 'Part_Ref' else None
                self.call(node, args, scope, receiver_override=receiver, symbol_override=last)
            else:
                self.reference(node, scope, 'R', 'component expression')
        elif kind in ('Function_Reference', 'Intrinsic_Function_Reference', 'Structure_Constructor'):
            self.call(node.items[0], node.items[1], scope, kind == 'Intrinsic_Function_Reference')
        elif kind in ('Actual_Arg_Spec', 'Component_Spec'):
            self.expr(node.items[1], scope)
        elif kind.endswith('_Literal_Constant'):
            return
        else:
            for child in children(node):
                self.expr(child, scope)

    def io(self, node, scope):
        kind = tag(node)
        output_keys = {'iostat', 'iomsg', 'newunit', 'size', 'id'}
        if kind == 'Inquire_Stmt':
            output_keys |= {'exist', 'opened', 'number', 'named', 'name', 'access',
                            'sequential', 'direct', 'form', 'formatted', 'unformatted',
                            'recl', 'nextrec', 'blank', 'position', 'action', 'read',
                            'write', 'readwrite', 'delim', 'pad', 'pending', 'pos',
                            'iolength', 'asynchronous', 'decimal', 'encoding', 'round', 'sign'}
        for child in children(node):
            if tag(child) in ('Input_Item_List', 'Output_Item_List'):
                for value in children(child):
                    if kind == 'Read_Stmt' and self.is_variable(value, scope):
                        self.reference(value, scope, 'W', 'READ input')
                    else:
                        self.expr(value, scope)
            elif tag(child).endswith('Spec_List'):
                for pos, spec in enumerate(children(child)):
                    key, value = spec.items
                    key = low(key) if key is not None else ('unit' if pos == 0 else 'fmt')
                    if key == 'nml':
                        cur = scope
                        while cur and low(value) not in cur.namelists:
                            cur = cur.parent
                        if cur:
                            for member in cur.namelists[low(value)]:
                                self.reference(member, scope, 'W' if kind == 'Read_Stmt' else 'R', 'namelist I/O', site=node)
                        else:
                            self.diagnostic(node, scope, f'Unresolved namelist: {value}')
                    elif key in output_keys or (key == 'unit' and kind == 'Write_Stmt' and
                                               (sym := self.root_ref(value, scope)[0]) and
                                               self.is_internal_file(sym)):
                        self.reference(value, scope, 'W', f'{kind} {key}')
                    else:
                        self.expr(value, scope)
            else:
                self.expr(child, scope)

    def is_internal_file(self, symbol):
        # Character type is stored separately from derived-type identity.
        return getattr(symbol, 'intrinsic_type', '') == 'character'

    def scan(self, node, scope=None):
        kind = tag(node)
        if id(node) in self.node_scopes:
            scope = self.node_scopes[id(node)]
        if scope is None:
            for child in children(node):
                self.scan(child, scope)
            return
        if kind in ('Type_Declaration_Stmt', 'Data_Component_Def_Stmt'):
            dtype, attrs, decls = node.items
            # Bounds/lengths are reads, including mutable dimensions in interfaces.
            if tag(dtype) == 'Intrinsic_Type_Spec':
                self.expr(dtype.items[1], scope)
            for attr in children(attrs):
                if tag(attr) in ('Dimension_Attr_Spec', 'Dimension_Component_Attr_Spec'):
                    self.expr(attr.items[1], scope)
            for decl in children(decls):
                self.expr(decl.items[1], scope)
                self.expr(decl.items[2], scope)
                init = decl.items[3]
                if init:
                    self.expr(init.items[1], scope)
                    if scope.kind != 'type':
                        self.reference(decl.items[0], scope, 'W', 'declaration initializer')
            return
        if kind in ('Assignment_Stmt', 'Pointer_Assignment_Stmt'):
            self.reference(node.items[0], scope, 'W', 'pointer association' if kind.startswith('Pointer') else 'assignment')
            self.expr(node.items[2], scope)
            if kind.startswith('Pointer'):
                self.diagnostic(node, scope, 'Pointer association: subsequent target aliases are not propagated')
            return
        if kind == 'Call_Stmt':
            self.call(node.items[0], node.items[1], scope)
            return
        if kind in ('Allocate_Stmt', 'Deallocate_Stmt'):
            for child in children(node):
                if tag(child) in ('Allocation_List', 'Allocate_Object_List'):
                    for alloc in children(child):
                        obj = alloc.items[0] if tag(alloc) == 'Allocation' else alloc
                        self.reference(obj, scope, 'W', kind)
                        if tag(alloc) == 'Allocation':
                            self.expr(alloc.items[1], scope)
                elif tag(child) in ('Alloc_Opt_List', 'Dealloc_Opt_List'):
                    for opt in children(child):
                        if low(opt.items[0]) in ('stat', 'errmsg'):
                            self.reference(opt.items[1], scope, 'W', 'allocation status')
                        else:
                            self.expr(opt.items[1], scope)
            return
        if kind in ('Read_Stmt', 'Write_Stmt', 'Print_Stmt', 'Open_Stmt', 'Close_Stmt',
                    'Inquire_Stmt', 'Wait_Stmt', 'Rewind_Stmt', 'Backspace_Stmt', 'Endfile_Stmt', 'Flush_Stmt'):
            self.io(node, scope)
            return
        if kind == 'Associate_Construct':
            alias = Scope('<associate>', 'block', scope, scope.path)
            for item in children(children(node)[0].items[1]):
                name, _, expr = item.items
                alias.aliases[low(name)] = (expr, scope)
                # Establishing a variable alias does not read its value.
                if self.is_variable(expr, scope):
                    for idx in self.root_ref(expr, scope)[3]:
                        self.expr(idx, scope)
                else:
                    self.expr(expr, scope)
            for child in children(node)[1:]:
                self.scan(child, alias)
            return
        if kind == 'Select_Type_Construct':
            head = children(node)[0]
            name, expr = head.items
            name = low(name or expr)
            alias = None
            for child in children(node)[1:]:
                if tag(child) == 'Type_Guard_Stmt':
                    alias = Scope('<select type>', 'block', scope, scope.path)
                    alias.aliases[name] = (expr, scope)
                    if child.items[1] and tag(child.items[1]) == 'Type_Name':
                        alias.overrides[name] = low(child.items[1])
                else:
                    self.scan(child, alias or scope)
            return
        if kind == 'Loop_Control':
            self.expr(node.items[0], scope)
            if node.items[1]:
                var, bounds = node.items[1]
                self.reference(var, scope, 'W', 'DO variable')
                self.expr(bounds, scope)
            if len(node.items) > 3 and node.items[3]:
                self.diagnostic(node, scope, 'DO CONCURRENT locality is not resolved')
                self.expr(node.items[3], scope)
            return
        if kind == 'If_Stmt':
            self.expr(node.items[0], scope)
            self.scan(node.items[1], scope)
            return
        if kind in ('If_Then_Stmt', 'Else_If_Stmt', 'Select_Case_Stmt', 'Case_Stmt',
                    'Where_Construct_Stmt', 'Masked_Elsewhere_Stmt', 'Stop_Stmt', 'Error_Stop_Stmt'):
            self.expr(node.items[0], scope)
            return
        if kind in ('Where_Stmt', 'Forall_Stmt'):
            self.expr(node.items[0], scope)
            self.scan(node.items[1], scope)
            return
        if kind == 'Nonlabel_Do_Stmt':
            self.scan(node.items[1], scope)
            return
        if kind in ('Module_Stmt', 'Program_Stmt', 'Function_Stmt', 'Subroutine_Stmt',
                    'Derived_Type_Stmt', 'Use_Stmt', 'Import_Stmt', 'Implicit_Stmt',
                    'Access_Stmt', 'Private_Components_Stmt', 'Contains_Stmt',
                    'Interface_Stmt', 'Procedure_Stmt', 'Specific_Binding', 'Generic_Binding',
                    'Namelist_Stmt', 'Return_Stmt', 'Continue_Stmt', 'Exit_Stmt', 'Cycle_Stmt',
                    'Goto_Stmt', 'Else_Stmt', 'Elsewhere_Stmt') or kind.startswith('End_'):
            return
        if kind.endswith('_Stmt'):
            self.diagnostic(node, scope, f'Unsupported statement (effects unknown): {kind}')
            # Preserve uncertain references without inventing writes.
            for name in fwalk(node, f2.Name):
                self.reference(name, scope, '?', f'unsupported {kind}')
            return
        for child in children(node):
            self.scan(child, scope)

    def analyse(self):
        # Missing INTENT is common in this codebase. Infer dummy effects from
        # implementations to a fixed point, including recursive call chains.
        # Unavailable bodies/interfaces retain ?, and may-effects are unioned.
        while True:
            before = {symbol: mode_union(modes) for symbol, modes in self.effects.items()}
            self.evidence.clear()
            self.type_rows.clear()
            self.diagnostics.clear()
            for _, _, tree in self.trees:
                self.scan(tree)
            after = {symbol: mode_union(modes) for symbol, modes in self.effects.items()}
            if before == after:
                break
        combined = defaultdict(set)
        for home, owner, var, mode, *_ in self.evidence:
            combined[(home, owner, var)].add(mode)
        accesses = [Access(home, owner, var, mode_union(modes),
                           owner in self.modules and owner not in self.ignored)
                    for (home, owner, var), modes in sorted(combined.items(), key=lambda x: tuple(map(str.lower, x[0])))]
        deps = [TypeDep(home, tmod, tname, comp, mode_union(modes), sure, binding, internal)
                for (home, tmod, tname, comp, sure, binding, internal), modes in sorted(self.type_rows.items())]
        return accesses, deps


def report(accesses, deps, project, out, no_types=False):
    print('# Shared mutable state: R=read, W=write/INTENT(OUT), RW=both, ?=unresolved effect', file=out)
    print('# Components retain their root instance; local/dummy type dependencies are separate.', file=out)
    print(f'# Parsed {len(project.trees)} files; {len(project.diagnostics)} diagnostics. See evidence JSON for locations.\n', file=out)
    home = None
    for row in accesses:
        if row.home != home:
            home = row.home
            print(home, file=out)
        print(f'    [{"internal" if row.internal else "EXTERNAL"}] {row.owner}::{row.var}  {row.mode}', file=out)
    if not no_types:
        print('\n# Derived-type component dependencies (not shared-state edges for local/dummy objects)', file=out)
        home = None
        for row in deps:
            if row.home != home:
                home = row.home
                print(home, file=out)
            print(f'    {row.tmod}::{row.tname}%{row.comp}  {row.mode} [{row.kind}]', file=out)


def to_dot(accesses, path, show_external=True):
    combo = defaultdict(set)
    internal = {}
    for a in accesses:
        if (a.internal or show_external) and a.mode:
            vid = f'{a.owner}::{a.var}'
            combo[(a.home.lower(), vid)].add(a.mode)
            internal[vid] = a.internal
    names = {a.home.lower(): a.home for a in accesses}
    quote = json.dumps
    lines = ['digraph dataflow {', '  rankdir=LR;', '  node [fontname=Helvetica];',
             '  edge [fontname=Helvetica, fontsize=9];']
    for home in sorted({h for h, _ in combo}):
        lines.append(f'  {quote(names[home])} [shape=box, style=filled, fillcolor="#cfe8ff"];')
    for vid in sorted(internal):
        color = '#fff2cc' if internal[vid] else '#eeeeee'
        lines.append(f'  {quote(vid)} [shape=ellipse, style=filled, fillcolor="{color}"];')
    for (home, vid), modes in sorted(combo.items()):
        mode = mode_union(modes)
        known = mode.replace('?', '')
        src, dst = (vid, names[home]) if known == 'R' else (names[home], vid)
        color = {'R': '#1f77b4', 'W': '#d62728', 'RW': '#7e3ff2', '': '#888888'}[known]
        direction = 'both' if known == 'RW' else 'forward' if known else 'none'
        style = 'dashed' if '?' in mode else 'solid'
        lines.append(f'  {quote(src)} -> {quote(dst)} [color="{color}", dir={direction}, style={style}, label="{mode}"];')
    lines += ['  labelloc="t";', '  label="R: read | W: write or output intent | RW: both | ?: unresolved effect (dashed; no assumed write)";', '}']
    Path(path).write_text('\n'.join(lines) + '\n')


def write_evidence(path, accesses, deps, project):
    document = {
        'schema_version': 1,
        'semantics': 'Syntactic and INTENT-based accesses; ? is unresolved. No whole-program pointer/heap analysis.',
        'sources': [{'path': path, 'sha256': hashlib.sha256(src.encode()).hexdigest()}
                    for path, src, _ in project.trees],
        'unavailable_modules': sorted({mod for scope in project.scopes for mod, _, _ in scope.uses
                                       if mod not in project.modules and mod not in INTRINSIC}),
        'accesses': [a._asdict() for a in accesses],
        'type_dependencies': [d._asdict() for d in deps],
        'evidence': [dict(zip(('home', 'owner', 'var', 'mode', 'file', 'line', 'statement', 'reason'), row))
                     for row in sorted(project.evidence)],
        'diagnostics': [dict(zip(('file', 'line', 'statement', 'message'), row))
                        for row in sorted(project.diagnostics)],
    }
    Path(path).write_text(json.dumps(document, indent=2) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--src', nargs='+', required=True)
    ap.add_argument('--ignore', action='extend', nargs='+', default=[])
    ap.add_argument('--ext', nargs='+')
    ap.add_argument('--include-examples', action='store_true', help='include test/example directories when walking source roots')
    ap.add_argument('--no-external', action='store_true')
    ap.add_argument('--no-types', action='store_true')
    ap.add_argument('--strict', action='store_true', help='omit unclassified external exports')
    ap.add_argument('-o', '--out', default='flow.dot')
    ap.add_argument('-r', '--report', default='flow.txt')
    ap.add_argument('--evidence', help='JSON containing source locations, hashes, and diagnostics')
    args = ap.parse_args()
    try:
        files = discover(args.src, tuple(args.ext or DEFAULT_EXTS), args.include_examples)
        if not files:
            raise ValueError('No source files found')
        project = Project(files, args.ignore, args.strict)
        accesses, deps = project.analyse()
    except ValueError as exc:
        ap.exit(1, f'{exc}\n')
    if args.report == '-':
        report(accesses, deps, project, sys.stdout, args.no_types)
    else:
        with open(args.report, 'w') as out:
            report(accesses, deps, project, out, args.no_types)
    to_dot(accesses, args.out, not args.no_external)
    if args.evidence:
        write_evidence(args.evidence, accesses, deps, project)
    print(f'# parsed {len(files)} files; {len(accesses)} state accesses; {len(project.diagnostics)} diagnostics', file=sys.stderr)
    print(f'# wrote {args.out} and {args.report}', file=sys.stderr)
    if project.diagnostics and not args.evidence:
        print('# Use --evidence FILE.json to inspect unresolved effects and coverage diagnostics.', file=sys.stderr)


if __name__ == '__main__':
    main()
