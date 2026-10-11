# Phase 11 Diagnostic-Registry Correction

## Summary

Phase 11 is complete. The registry, meaning the list of available error codes and
messages, now includes WaterBody warning 405. WaterBody also owns critical error
901. The four general codes remain shared, and blank slots 4 and 5 deliberately
keep the existing blank message for code 1.

Verification on 10 October 2026 passed a clean build, **57 CTest cases**, and
**47 exact model-output comparisons** against a fresh Phase 10 reference. CTest
is the program that runs the project's automated tests. All 50 direct Biota
records and 7,500 organism-state records inside the model also matched exactly.
The original code comments were preserved.

Final compatibility cleanup is the next migration step. It must retain the
approved shared error list; an empty list is not required.

## What Changed

### WaterBody registers 405 and 901

WaterBody's private list now has eight distinct entries, in this order:

```text
401, 402, 403, 404, 405, 500, 501, 901
```

Code 405 was previously assigned to the same position as code 500 and overwritten
before registration. They now occupy separate positions. Code 405 retains its
original message and warning status:

```text
RiverReach lengths specified in input data sum to greater than straight-line river branch length. Are you sure this is intended?
```

Code 901 moved from ErrorHandling to WaterBody because its message describes a
RiverReach type. Its unchanged message is:

```text
Invalid RiverReach type index provided.
```

It remains critical: triggering it stops the program when error output is enabled.
Suppressing warnings does not suppress critical errors. Disabling error output
still suppresses both the message and the stop, matching existing behavior.

Neither code has a current production call that raises it. Restoring 405 therefore
does not add a river-length check, and moving 901 does not add a river-type check.
Their reporting is tested directly without inventing new scientific checks.

### Shared codes and blank slots remain intentionally

The shared array now has six positions. Positions 1, 2, 3, and 6 retain these codes:

| Code | Unchanged message | Status |
| --- | --- | --- |
| 110 | Invalid object type index in data file. | Critical |
| 200 | File not found. | Critical |
| 201 | Variable not found in input file. | Critical |
| 300 | Newton's method failed to converge. | Critical |

These describe general input, file, and numerical problems. They have no current
production raising sites. Keeping them shared preserves their availability without
adding another registration module or assigning them to a speculative caller.

Positions 4 and 5 remain unassigned by explicit agreement. The error library gives
each a default code of 1, a blank message, and critical status. During initialization
it combines these into one registered code-1 entry and replaces the usual generic
message with blank text. This is intentional compatibility behavior, not spare
space that a later cleanup may silently remove.

The counts include the library's two default entries and nine comparison errors:

| Initialization completed | Before | After |
| --- | ---: | ---: |
| Shared handler | 16 | 15 |
| Soil | 17 | 16 |
| BedSediment | 18 | 17 |
| WaterBody | 24 | 25 |
| Reactor | 25 | 26 |
| Biota | 26 | 27 |

Moving 901 changes when it is registered. Restoring 405 adds the one new entry to
the final total. Blank array positions are not counted as extra registered errors.

### Public behavior and original comments

Only the two error-registration production modules changed. Public procedure
names and arguments, configuration settings, startup order, scientific calculations,
input readers, output layouts, and checkpoint formats remain unchanged. WaterBody
registration stays private and is still called by its existing initializer. The
shared handler and the third-party error library are unchanged apart from the
contents supplied by the model's two registration modules.

All **76 original comment occurrences** in changed existing Fortran files and
CMake remain verbatim: 34 in production code, three in tests, and 39 in CMake.
The original `! General` heading moved with code 901. Other comments retain their
order. Historical comments describing six WaterBody entries and the overwritten
405 remain, with adjacent Phase 11 notes explaining the new behavior.

## Verification

### Fresh reference and saved evidence

The reference was built from unchanged Phase 10 production source at:

```text
cf0e904c8bb2044bcded305743b316288efb19c5
```

Evidence is saved at:

```text
/private/tmp/nanofase_phase11_cfz4pid3
```

It contains original tracked-file copies and hashes, the pre-existing working
changes, compiler settings, saved reference executables, generated inputs,
commands, logs, comparison results, and the comment/source check.

Both builds used GNU Fortran 14.2.0 with the existing Debug configuration and
identical flags. Existing runtime checks remained enabled. Each build used:

```sh
cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Debug
# Restore the exact saved src/VersionModule.f90 contents before building.
cmake --build build-debug --clean-first -j2
ctest --test-dir build-debug --output-on-failure
```

Both clean builds passed with existing compiler and linker warnings. The reference
passed all **33** original tests. Its model, shared-consumer integration, and two
Biota test executables were saved before test or production edits.

CMake still rewrites the version file. Its saved contents were restored after
each configuration, before building. Its final SHA-256 remains:

```text
3cb5e276d8d6b856ce903b1707bc3aff4256fbe2fa3792427ff6462897142652
```

### New expectations failed before the correction

The new tests were first compiled against unchanged production code:

```sh
cmake --build build-debug --target error_handling_registry_test water_body_config_module_test -j2
ctest --test-dir build-debug --output-on-failure \
  -R '^(error_handling_registry|water_body_config_empty)$'
```

Both failed for the intended reasons: the shared handler already contained 901,
and WaterBody did not contain 405. The test command exited 8, as expected for
failed tests. The evidence is in `red_configure.log`, `red_build.log`, and
`red_ctest.log`. Production registration was changed only after these failures
were confirmed and all four reference captures had passed.

### Final diagnostic tests

The candidate passed **57/57** tests: the existing 33 plus 24 new reporting cases.
The updated configuration tests verify exact code membership without duplicates,
the complete startup counts, messages, and warning/critical status. They also
verify that later domain registration preserves earlier definitions and that
named single-error registration still works.

| Added reporting checks | Result |
| --- | --- |
| 405 triggered by code, by a retrieved error, and by an array containing that error | Exact warning printed once; exit 0 and continued execution |
| 405 with warnings suppressed or error output disabled | No warning; exit 0 and continued execution |
| 901 with warnings enabled or suppressed | Exact error printed once; exit 1 without continued execution |
| 901 with error output disabled | No error message; exit 0 and continued execution |
| Each of 110/200/201/300 with ordinary output or warnings suppressed | Exact critical message; exit 1 |
| Each shared code with error output disabled | No diagnostic; exit 0 and continued execution |
| Code 1 with ordinary output, warnings suppressed, or a trigger without arguments | Blank-message error line; exit 1 |
| Code 1 with error output disabled | No diagnostic; exit 0 and continued execution |

The retrieved-error tests use the registered warning status. A newly constructed
`ErrorInstance` is critical by default, so constructing one with only code 405
would not test the intended warning behavior. The reporting wrappers check exit
status, full diagnostic lines, and whether execution continued. They remove known
console color sequences for text checks and ignore changing runtime backtraces.

Build and test results are in `candidate_configure.log`, `candidate_build.log`,
and `candidate_ctest.log`.

### Exact scientific comparisons

The four existing verification runners were unchanged. The saved execution helper
ran their independent suites using these actual commands:

```sh
python3 /private/tmp/nanofase_phase11_cfz4pid3/run_suites.py capture
python3 /private/tmp/nanofase_phase11_cfz4pid3/run_suites.py compare
```

Capture used the saved reference executables; compare used the corresponding
`build-debug/` executables. Each runner's complete command is saved in its
`*_capture_command.json` and `*_compare_command.json` files, with logs alongside.
The work directories are `waterbody_checks`, `reactor_checks`, `biota_checks`, and
`shared_consumers_checks`. All eight runner invocations exited 0.

| Runner | Actual result |
| --- | --- |
| WaterBody | 14 exact output comparisons; four expected failures unchanged; batch and checkpoint save/load checks passed |
| Reactor | Nine exact output comparisons, including active reaction rates and changed shear |
| Biota | Six exact output comparisons; 50 direct and 7,500 running-model state records matched; organism creation, updates, and harvest/batch checks passed |
| Shared consumers | 18 exact output comparisons; four startup diagnostic cases and six checkpoint cases passed, including logs, output choices, masks, and changing batch inputs |

All **47 ordinary output sets** matched. CSV files are byte-identical. Summaries
exclude only `Simulation datetime`, and NetCDF text excludes only `history`.
The integration-test sources and their hash checks remained unchanged. Checkpoint
comparisons retained the existing record layout and defined-value rules, excluding
only the already documented unused reach positions. These checks do not establish
correct simulation continuation from a checkpoint.

### Final source and workspace checks

The saved `check_source.py` passed; results are in `source_checks.json`. It checks
original comment occurrences and order, including the moved code-901 heading,
and compares all original tracked-file hashes. Only the planned source, test,
build-test configuration, and documentation files changed. `git diff --check`
also passed.

Earlier phase reports, all shipped inputs, scientific source files, Bootstrap,
Globals, the integration-test sources, and the saved version-file contents are
unchanged. The pre-existing migration-plan edits were preserved while updating
its agreed ownership and cleanup rules. The pre-existing `vendor/nanofase-data`
workspace state was left untouched.

Temporary evidence may eventually disappear. The tracked tests, unchanged scenario
runners, fixtures, reference revision, and [verification guide](../verification/README.md)
provide the steps needed to repeat the checks with a fresh evidence directory.

## What Remains

1. Complete final compatibility cleanup: remove Globals, its old fields and copying
   helpers, Bootstrap's startup copies, the old defaults compatibility exports,
   and the historical test's compatibility writes. Preserve original comments and
   the approved shared errors, blank slots, and diagnostic behavior.
2. Stop CMake from rewriting the tracked version file in a separate build change.
3. Correct river-disabled bed-sediment behavior and terrain access at outlets in
   their separate tested repairs.
4. Correct Reactor attachment mass loss separately, with mass-conservation tests.
5. Correct Biota harvest timing and invalid-form handling separately. Correct
   checkpoint continuation, including missing organism state, warm-up timing,
   and the main loop's unused restored timestep, with compatibility tests.
6. Keep optional work on unused checkpoint positions and the empty compartment
   statistics output separate from this migration.

Blank slots are accepted behavior, not unfinished Phase 11 work. Adding production
checks that raise 405, 901, or the four retained shared codes would be a separate
behavior change. No such checks are claimed here.

The main plan and verification guide now describe this completed phase. Earlier
phase reports remain historical records. Each following phase must likewise
document what changed, what actually passed, and what remains in this folder,
using plain language and preserving original code comments.
