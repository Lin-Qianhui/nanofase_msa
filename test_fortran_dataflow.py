"""Semantic regression tests; no Fortran compiler or model execution required."""
import tempfile
import unittest
from pathlib import Path

from fortran_dataflow import Access, Project, discover, to_dot


class DataflowTests(unittest.TestCase):
    def analyse(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.f90'
            path.write_text(source)
            project = Project([str(path)], strict=True)
            accesses, deps = project.analyse()
        self.project = project
        self.deps = deps
        return {(a.home.lower(), a.owner, a.var): a.mode for a in accesses}

    def test_bounds_allocation_and_indices_are_reads(self):
        rows = self.analyse('''
module dimensions
 integer :: npdim(3), i
contains
 subroutine init
 npdim = [1,2,3]
 end subroutine
end module
module consumer
 use dimensions
 real, allocatable :: a(:)
contains
 subroutine work
 real :: b(npdim(1))
 allocate(a(npdim(2)))
 a(i) = npdim(3)
 deallocate(a)
 end subroutine
end module
''')
        self.assertEqual(rows['consumer', 'dimensions', 'npdim'], 'R')
        self.assertEqual(rows['consumer', 'dimensions', 'i'], 'R')
        self.assertEqual(rows['consumer', 'consumer', 'a'], 'W')
        self.assertEqual(rows['dimensions', 'dimensions', 'npdim'], 'W')

    def test_intents_keywords_function_arguments_and_unknown_calls(self):
        rows = self.analyse('''
module api
contains
 subroutine transfer(source, dest, both)
 integer, intent(in) :: source
 integer, intent(out) :: dest
 integer, intent(inout) :: both
 dest = source
 both = both + source
 end subroutine
 integer function fill(x)
 integer, intent(out) :: x
 x = 1
 fill = 0
 end function
end module
module client
 use api
 integer :: a, b, c, d, e, f
contains
 subroutine run
 integer :: temp
 call transfer(dest=b, source=a, both=c)
 temp = fill(d)
 call unavailable(e)
 call unavailable(f+1)
 end subroutine
end module
''')
        self.assertEqual({v: rows['client', 'client', v] for v in 'abcdef'},
                         dict(a='R', b='W', c='RW', d='W', e='?', f='R'))

    def test_wildcard_renames_reexports_visibility_and_shadowing(self):
        rows = self.analyse('''
module state
 private
 integer, public :: value, other
 integer :: hidden
 integer, parameter, public :: constant=3
end module
module facade
 use state, renamed => value
 private
 public :: renamed, other, constant
end module
module consumer
 use facade
contains
 subroutine run
 integer :: other, local
 other=0
 local=renamed+constant
 end subroutine
 subroutine local_import
 use state, only: alternate => other
 integer :: local
 local = alternate
 end subroutine
end module
''')
        self.assertEqual(rows, {('consumer', 'state', 'value'): 'R',
                                ('consumer', 'state', 'other'): 'R'})
        self.assertFalse(self.project.resolve(self.project.modules['facade'], 'value', True))
        self.assertFalse(self.project.resolve(self.project.modules['facade'], 'hidden', True))

    def test_component_paths_local_objects_and_same_type_name(self):
        rows = self.analyse('''
module definitions
 type :: inner
 integer :: n
 end type
 type :: state_type
 type(inner) :: child
 integer :: values(4)
 end type
 type(state_type) :: global
 integer :: idx
end module
module consumer
 use definitions
contains
 subroutine work(arg)
 type(state_type), intent(inout) :: arg
 type(state_type) :: state_type
 integer :: local
 global%values(idx) = global%child%n
 state_type%child%n = arg%child%n
 end subroutine
end module
''')
        self.assertEqual(rows, {('consumer', 'definitions', 'global%values'): 'W',
                                ('consumer', 'definitions', 'idx'): 'R',
                                ('consumer', 'definitions', 'global%child%n'): 'R'})
        self.assertTrue(any(d.comp == 'child%n' and d.kind == 'local' and d.mode == 'W' for d in self.deps))
        self.assertTrue(any(d.comp == 'child%n' and d.kind == 'arg' and d.mode == 'R' for d in self.deps))
        self.assertFalse(any('component type' in d[-1] for d in self.project.diagnostics))

    def test_bound_procedures_inheritance_pass_and_nopass(self):
        rows = self.analyse('''
module objects
 type :: base
 integer :: n
 contains
 procedure :: get
 procedure, pass(this) :: change
 procedure, nopass :: plain
 end type
 type, extends(base) :: child
 end type
 type(child) :: obj
 integer :: input, output, result
contains
 integer function get(this)
 class(base), intent(in) :: this
 get=this%n
 end function
 subroutine change(value, this)
 integer, intent(in) :: value
 class(base), intent(inout) :: this
 this%n=value
 end subroutine
 subroutine plain(value)
 integer, intent(out) :: value
 value=1
 end subroutine
 subroutine run
 result=obj%get()
 call obj%change(value=input)
 end subroutine
 subroutine correct_run
 result=obj%base%get()
 call obj%change(input)
 call obj%plain(output)
 end subroutine
end module
''')
        self.assertEqual(rows['objects', 'objects', 'input'], 'R')
        self.assertEqual(rows['objects', 'objects', 'output'], 'W')
        self.assertEqual(rows['objects', 'objects', 'obj'], 'RW')
        self.assertEqual(rows['objects', 'objects', 'obj%base'], 'R')
        self.assertFalse(any('%get' in k[2] or '%change' in k[2] for k in rows))

    def test_missing_intent_inferred_through_calls(self):
        rows = self.analyse('''
module implementation
contains
 subroutine outer(x,y,z)
 integer :: x,y,z
 call inner(x,y)
 call unavailable(z)
 end subroutine
 subroutine inner(source, dest)
 integer :: source,dest
 dest=source
 end subroutine
end module
module caller
 use implementation
 integer :: input, output, mystery
contains
 subroutine run
 call outer(input, output, mystery)
 end subroutine
end module
''')
        self.assertEqual(rows, {('caller', 'caller', 'input'): 'R',
                                ('caller', 'caller', 'output'): 'W',
                                ('caller', 'caller', 'mystery'): '?'})

    def test_generic_conflicting_intents_are_uncertain(self):
        rows = self.analyse('''
module overload
 integer :: value
 interface action
 module procedure read_int, write_real
 end interface
contains
 subroutine read_int(x)
 integer, intent(in) :: x
 end subroutine
 subroutine write_real(x)
 real, intent(out) :: x
 end subroutine
 subroutine run
 call action(value)
 end subroutine
end module
''')
        self.assertEqual(rows['overload', 'overload', 'value'], '?')

    def test_generic_constructor_keeps_type_and_function_effects(self):
        rows = self.analyse('''
module constructors
 type :: thing
 integer :: n
 end type
 interface thing
 module procedure make_thing
 end interface
 integer :: value
 type(thing) :: obj
contains
 type(thing) function make_thing(x) result(result)
 integer, intent(out) :: x
 x=1
 result%n=1
 end function
 subroutine work
 obj=thing(value)
 print *, obj%n
 end subroutine
end module
''')
        self.assertEqual(rows['constructors', 'constructors', 'value'], 'W')
        self.assertEqual(rows['constructors', 'constructors', 'obj%n'], 'R')
        self.assertFalse(any('component type' in d[-1] for d in self.project.diagnostics))

    def test_polymorphic_overrides_do_not_assume_base_effects(self):
        rows = self.analyse('''
module polymorphism
 type :: base
 contains
 procedure :: action => read_value
 end type
 type, extends(base) :: extension
 contains
 procedure :: action => write_value
 end type
 integer :: state
contains
 subroutine read_value(this, x)
 class(base) :: this
 integer :: x
 print *, x
 end subroutine
 subroutine write_value(this, x)
 class(extension) :: this
 integer :: x
 x=1
 end subroutine
 subroutine run(obj)
 class(base) :: obj
 call obj%action(state)
 end subroutine
end module
''')
        self.assertEqual(rows['polymorphism', 'polymorphism', 'state'], '?')

    def test_associate_alias_and_select_type(self):
        rows = self.analyse('''
module definitions
 type :: thing
 integer :: n
 end type
 type(thing) :: obj
end module
module consumer
 use definitions
contains
 subroutine run
 associate (alias => obj)
 alias%n=1
 end associate
 end subroutine
 subroutine dynamic(arg)
 class(*), intent(inout) :: arg
 select type (alias => arg)
 type is (thing)
 alias%n=2
 end select
 end subroutine
end module
''')
        self.assertEqual(rows, {('consumer', 'definitions', 'obj%n'): 'W'})
        self.assertFalse(any('component type' in d[-1] for d in self.project.diagnostics))
        self.assertTrue(any(d.tname == 'thing' and d.kind == 'arg' and d.mode == 'W' for d in self.deps))

    def test_missing_wildcard_provider_does_not_hide_host_symbols(self):
        rows = self.analyse('''
module state
 type :: item
 integer :: n
 end type
 type(item) :: obj
contains
 subroutine work
 use omp_lib
 use absent_library
 integer :: local
 local=obj%n
 end subroutine
end module
''')
        self.assertEqual(rows, {('state', 'state', 'obj%n'): 'R'})
        self.assertFalse(any('component type' in d[-1] for d in self.project.diagnostics))

    def test_component_actuals_in_external_functions_and_substrings(self):
        rows = self.analyse('''
module state
 use absent_library
 type :: item
 integer :: n
 end type
 type(item) :: obj
 character(20) :: string
contains
 subroutine work
 integer :: local
 local=external_function(obj%n, key=1)
 call fill(string(1:3))
 end subroutine
 subroutine fill(value)
 character(*), intent(out) :: value
 value='abc'
 end subroutine
end module
''')
        self.assertEqual(rows, {('state', 'state', 'obj%n'): '?',
                                ('state', 'state', 'string'): 'W'})

    def test_io_namelist_and_intrinsics(self):
        rows = self.analyse('''
module io_state
 integer :: read_value, write_value, status, unit, clock
 real :: random
 character(80) :: buffer
 namelist /settings/ read_value
contains
 subroutine work
 read(unit,*,iostat=status) read_value
 write(unit,*) write_value
 read(unit,nml=settings)
 write(buffer,*) write_value
 call system_clock(count=clock)
 call random_number(random)
 end subroutine
end module
''')
        self.assertEqual({v: rows['io_state', 'io_state', v] for v in
                          ('read_value', 'write_value', 'status', 'unit', 'clock', 'random', 'buffer')},
                         dict(read_value='W', write_value='R', status='W', unit='R',
                              clock='W', random='W', buffer='W'))

    def test_interface_intent_and_local_use_override_host(self):
        rows = self.analyse('''
module state
 integer :: x
end module
module caller
 integer :: x, value
 interface
 subroutine explicit(a)
 integer, intent(in) :: a
 end subroutine
 end interface
contains
 subroutine run
 use state, only: x
 call explicit(x)
 value=x
 end subroutine
end module
''')
        self.assertEqual(rows, {('caller', 'state', 'x'): 'R',
                                ('caller', 'caller', 'value'): 'W'})

    def test_ambiguous_imports_do_not_choose_arbitrary_owner(self):
        rows = self.analyse('''
module a
 integer :: x
end module
module b
 integer :: x
end module
module consumer
 use a
 use b
contains
 subroutine run
 print *, x
 end subroutine
end module
''')
        self.assertEqual(rows, {})
        self.assertTrue(any('ambiguous symbol: x' in d[-1] for d in self.project.diagnostics))

    def test_empty_mode_cannot_become_write_in_dot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'graph.dot'
            to_dot([Access('consumer', 'owner', 'empty', '', True),
                    Access('consumer', 'owner', 'uncertain', '?', True),
                    Access('Consumer', 'owner', 'both', 'R', True),
                    Access('consumer', 'owner', 'both', 'W', True)], path)
            dot = path.read_text()
        self.assertNotIn('owner::empty', dot)
        self.assertIn('dir=none, style=dashed, label="?"', dot)
        self.assertEqual(dot.count('label="RW"'), 1)

    def test_duplicate_modules_fail_and_example_directories_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'test').mkdir()
            (root / 'a.F90').write_text('module a\nend module\n')
            (root / 'test' / 'a.f90').write_text('module a\nend module\n')
            self.assertEqual(discover([str(root)]), [str(root / 'a.F90')])
            with self.assertRaisesRegex(ValueError, 'Duplicate module'):
                Project(discover([str(root)], include_examples=True))

    def test_parse_failure_does_not_silently_generate_partial_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.f90'
            path.write_text('module broken\nthis is invalid\nend module\n')
            with self.assertRaisesRegex(ValueError, 'Cannot parse'):
                Project([str(path)])


if __name__ == '__main__':
    unittest.main()
