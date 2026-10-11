cmake_minimum_required(VERSION 3.13)

project(nanofase)
enable_language(Fortran)
enable_testing()

# GFortran compiler
if (CMAKE_Fortran_COMPILER_ID MATCHES GNU)
    # Runtime checks. gfortran 14's pointer check false-positives on the model's
    # polymorphic function-result Result objects (e.g. `.errors. me%audit()`), so
    # on those compilers disable just that sub-check while keeping all others.
    # Older gfortran handles the full set fine, so leave it untouched there.
    # (If an older gfortran also trips this, lower the version number below.)
    if (CMAKE_Fortran_COMPILER_VERSION VERSION_GREATER_EQUAL 14)
        set(fcheck_flag "-fcheck=all,no-pointer")
    else()
        set(fcheck_flag "-fcheck=all")
    endif()
    set(common_flags "${fcheck_flag} -ffpe-trap=zero,invalid,overflow,underflow")

    # On macOS the linker drops gfortran's hidden recursion-guard variables under
    # optimization, causing 'undefined symbol _is_recursive...' link errors.
    # -frecursive stops those guards being generated. Only needed on macOS, so it
    # is left off other platforms to preserve their original behaviour.
    if (APPLE)
        set(common_flags "-frecursive ${common_flags}")
    endif()

    # Debug build. -pg (gprof) needs gcrt1.o, which macOS does not provide, so it
    # is omitted there but kept on other platforms where profiling is useful.
    if (APPLE)
        set(debug_flags "-Wall -Og -g ${common_flags}")
    else()
        set(debug_flags "-Wall -Og -g -pg ${common_flags}")
    endif()

    # Release build. -march/-mtune=native is the x86 spelling; ARM gfortran
    # rejects it and needs -mcpu=native instead.
    if (CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
        set(release_flags "-Ofast -mcpu=native ${common_flags}")
    else()
        set(release_flags "-Ofast -march=native -mtune=native ${common_flags}")
    endif()
endif()

# Intel Fortran compiler
if (CMAKE_Fortran_COMPILER_ID MATCHES Intel)
    set(common_flags "-fpe0 -check bounds")
    set(debug_flags "-traceback -check stack -debug full -Od ${common_flags}")
    set(release_flags "-O3 ${common_flags}")
endif()

# Find NetCDF Fortran
set(CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake" CACHE INTERNAL "Location of CMake modules.")
set(NETCDF_F90 "YES")
if(NOT DEFINED NETCDF_INCLUDES)
    find_package(NetCDF REQUIRED)
endif()

# Set debug and release flags
set(CMAKE_Fortran_FLAGS_DEBUG "${CMAKE_Fortran_FLAGS_DEBUG} ${debug_flags}")
set(CMAKE_Fortran_FLAGS "${CMAKE_Fortran_FLAGS} ${release_flags}")

# Sources to compile - everything except those matching the regex
file(GLOB_RECURSE sources src/*.f90 vendor/*.f90)
list(FILTER sources EXCLUDE REGEX ".*vendor/feh/example/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/feh/tests/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/datetime-fortran/tests?/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/datetime-fortran/examples?/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/mo_netcdf/examples/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/mo_netcdf/tests/.*f90$")
list(FILTER sources EXCLUDE REGEX ".*vendor/spoof/example/.*f90$")

# Modify the version number
execute_process(COMMAND git describe --tags OUTPUT_VARIABLE model_version OUTPUT_STRIP_TRAILING_WHITESPACE)
file(READ "src/VersionModule.f90" version_file)
string(REGEX REPLACE "\".*\"" "\"${model_version}\"" version_file_new "${version_file}")
file(WRITE "src/VersionModule.f90" ${version_file_new})

# Compile to executable and link to NetCDF
add_executable(nanofase ${sources})
target_include_directories(nanofase PUBLIC "${NETCDF_INCLUDES}")
target_link_libraries(nanofase PRIVATE "${NETCDF_LIBRARIES_F90}")

# Focused regression test for the shared diagnostics singleton and the
# intentionally malformed legacy registry retained during migration.
# Phase 11 note: the shared codes and blank entries are now intentional; 901 belongs to WaterBody.
add_executable(error_handling_registry_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    test/ErrorHandlingModuleTest.f90
)
set_target_properties(error_handling_registry_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/error-handling-test-modules"
)
add_test(NAME error_handling_registry COMMAND error_handling_registry_test)

set(shared_message_1 "")
set(shared_message_110 "Invalid object type index in data file.")
set(shared_message_200 "File not found.")
set(shared_message_201 "Variable not found in input file.")
set(shared_message_300 "Newton's method failed to converge.")
foreach(code 1 110 200 201 300)
    foreach(mode critical quiet disabled)
        add_test(NAME shared_error_${code}_${mode}
            COMMAND "${CMAKE_COMMAND}"
                "-DTEST_EXECUTABLE=$<TARGET_FILE:error_handling_registry_test>"
                "-DCODE=${code}" "-DMODE=${mode}" "-DEXPECTED_MESSAGE=${shared_message_${code}}"
                -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectSharedDiagnostic.cmake")
    endforeach()
endforeach()
add_test(NAME shared_error_generic
    COMMAND "${CMAKE_COMMAND}"
        "-DTEST_EXECUTABLE=$<TARGET_FILE:error_handling_registry_test>"
        -DCODE=1 -DMODE=generic "-DEXPECTED_MESSAGE="
        -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectSharedDiagnostic.cmake")

# Focused regression test for Soil-owned configuration, defaults, and error
# registration. It is a separate process because the shared handler may only
# be initialised once in a process.
add_executable(soil_config_module_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/Kernel/KernelModule.f90
    src/ModelDimensions/ModelDimensionsModule.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    src/Soil/SoilConfigModule.f90
    test/SoilConfigModuleTest.f90
)
set_target_properties(soil_config_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/soil-config-test-modules"
)
add_test(
    NAME soil_config
    COMMAND soil_config_module_test "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/soil-config-defaults.nml"
)

# Read sediment configuration and register its error in a separate process.
# Distinct fixture dimensions exercise each namelist buffer's allocation.
add_executable(bed_sediment_config_module_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/Kernel/KernelModule.f90
    src/ModelDimensions/ModelDimensionsModule.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    src/Soil/SoilConfigModule.f90
    src/BedSediment/BedSedimentConfigModule.f90
    test/BedSedimentConfigModuleTest.f90
)
set_target_properties(bed_sediment_config_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bed-sediment-config-test-modules"
)
add_test(
    NAME bed_sediment_config_on
    COMMAND bed_sediment_config_module_test
        "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config.nml"
        on "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config.nml"
)
add_test(
    NAME bed_sediment_config_off
    COMMAND bed_sediment_config_module_test
        "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config.nml"
        off "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config-off.nml"
)
add_test(
    NAME bed_sediment_config_missing
    COMMAND "${CMAKE_COMMAND}"
        "-DTEST_EXECUTABLE=$<TARGET_FILE:bed_sediment_config_module_test>"
        "-DDIMENSIONS_FIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config.nml"
        "-DSEDIMENT_FIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/bed-sediment-config-missing.nml"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectMissingSediment.cmake"
)

# WaterBody owns an optional group and six effective errors. Each test starts
# a fresh process so that the shared error handler is initialised only once.
# Phase 11 note: restoring 405 and moving 901 brings WaterBody's count to eight.
add_executable(water_body_config_module_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/Kernel/KernelModule.f90
    src/ModelDimensions/ModelDimensionsModule.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    src/Soil/SoilConfigModule.f90
    src/BedSediment/BedSedimentConfigModule.f90
    src/WaterBody/WaterBodyConfigModule.f90
    test/WaterBodyConfigModuleTest.f90
)
set_target_properties(water_body_config_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/water-body-config-test-modules"
)
set(water_fixture_dir "${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures")
foreach(mode explicit empty missing partial omit_slope omit_timestep omit_estuary omit_bank malformed_eof)
    add_test(NAME water_body_config_${mode}
        COMMAND water_body_config_module_test
            "${water_fixture_dir}/bed-sediment-config.nml"
            "${mode}" "${water_fixture_dir}/water-body-${mode}.nml"
    )
endforeach()

# Read the same input/checkpoint state against the pre-phase and migrated sources.
# The capture/compare runner supplies its generated inputs and checks the records.
set(shared_consumer_probe_sources ${sources})
list(FILTER shared_consumer_probe_sources EXCLUDE REGEX "/src/main\\.f90$")
add_executable(shared_consumer_integration_test
    ${shared_consumer_probe_sources} test/SharedConsumerIntegrationTest.f90)
set_target_properties(shared_consumer_integration_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/shared-consumer-integration-test-modules")
target_include_directories(shared_consumer_integration_test PRIVATE "${NETCDF_INCLUDES}")
target_link_libraries(shared_consumer_integration_test PRIVATE "${NETCDF_LIBRARIES_F90}")

# Direct checks write only the real owners, deliberately leaving C untouched.
add_executable(shared_consumer_module_test ${shared_consumer_probe_sources} test/SharedConsumerModuleTest.f90)
set_target_properties(shared_consumer_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/shared-consumer-module-test-modules")
target_include_directories(shared_consumer_module_test PRIVATE "${NETCDF_INCLUDES}")
target_link_libraries(shared_consumer_module_test PRIVATE "${NETCDF_LIBRARIES_F90}")
add_test(NAME shared_consumer_owners
    COMMAND "${CMAKE_COMMAND}"
        "-DTEST_EXECUTABLE=$<TARGET_FILE:shared_consumer_module_test>"
        "-DEXPLICIT_FIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/model-config-explicit.nml"
        "-DOMITTED_FIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/model-config-omitted.nml"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectSharedConsumers.cmake")
foreach(group data output run)
    add_test(NAME model_config_missing_${group}
        COMMAND "${CMAKE_COMMAND}"
            "-DTEST_EXECUTABLE=$<TARGET_FILE:shared_consumer_module_test>"
            "-DFIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/model-config-omitted.nml"
            "-DMISSING_GROUP=${group}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectModelConfigMissing.cmake")
endforeach()

function(add_water_body_diagnostic_test mode fixture expected_exit expected_text)
    add_test(NAME water_body_${mode}
        COMMAND "${CMAKE_COMMAND}"
            "-DTEST_EXECUTABLE=$<TARGET_FILE:water_body_config_module_test>"
            "-DDIMENSIONS_FIXTURE=${water_fixture_dir}/bed-sediment-config.nml"
            "-DWATER_FIXTURE=${water_fixture_dir}/water-body-${fixture}.nml"
            "-DMODE=${mode}" "-DEXPECTED_EXIT=${expected_exit}" "-DEXPECTED_TEXT=${expected_text}"
            ${ARGN}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectWaterBody.cmake"
    )
endfunction()
add_water_body_diagnostic_test(unknown unknown 2 "Cannot match namelist object name unknown_water_setting")
add_water_body_diagnostic_test(malformed malformed 2 "Cannot match namelist object name 'invalid'")
add_water_body_diagnostic_test(warning empty 0 "All SPM advected from RiverReach.")
add_water_body_diagnostic_test(quiet_warning empty 0 "Completed WaterBody check" "-DFORBIDDEN_TEXT=Warning:")
add_water_body_diagnostic_test(disabled_error empty 0 "Completed WaterBody check" "-DFORBIDDEN_TEXT=Error:")
add_water_body_diagnostic_test(critical empty 1
    "Invalid RiverReach inflow reference. Inflow must be from a neighbouring RiverReach.")

set(water_warning_405 "RiverReach lengths specified in input data sum to greater than straight-line river branch length. Are you sure this is intended?")
foreach(mode warning405_code warning405_instance warning405_array)
    add_water_body_diagnostic_test(${mode} empty 0 "${water_warning_405}"
        "-DEXPECTED_DIAGNOSTIC=Warning: ${water_warning_405}")
endforeach()
foreach(mode quiet_405 disabled_405)
    add_water_body_diagnostic_test(${mode} empty 0 "Completed WaterBody check" "-DFORBIDDEN_TEXT=Warning:")
endforeach()
foreach(mode critical901 quiet_901)
    add_water_body_diagnostic_test(${mode} empty 1 "Invalid RiverReach type index provided."
        "-DEXPECTED_DIAGNOSTIC=Error: Invalid RiverReach type index provided.")
endforeach()
add_water_body_diagnostic_test(disabled_901 empty 0 "Completed WaterBody check" "-DFORBIDDEN_TEXT=Error:")

# Exercise the existing slope procedure on an interior reach without constructing
# an outlet, whose terrain-array failure belongs to a separate repair.
set(water_body_slope_sources ${sources})
list(FILTER water_body_slope_sources EXCLUDE REGEX "/src/main\\.f90$")
add_executable(water_body_slope_test ${water_body_slope_sources} test/WaterBodySlopeTest.f90)
set_target_properties(water_body_slope_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/water-body-slope-test-modules"
)
target_include_directories(water_body_slope_test PRIVATE "${NETCDF_INCLUDES}")
target_link_libraries(water_body_slope_test PRIVATE "${NETCDF_LIBRARIES_F90}")
add_test(NAME water_body_slope COMMAND water_body_slope_test "${water_fixture_dir}/water-body-explicit.nml")

# Reactor owns four constants and one error, with no configuration-file group.
add_executable(reactor_config_module_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/Kernel/KernelModule.f90
    src/ModelDimensions/ModelDimensionsModule.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    src/Soil/SoilConfigModule.f90
    src/BedSediment/BedSedimentConfigModule.f90
    src/WaterBody/WaterBodyConfigModule.f90
    src/Reactor/ReactorConfigModule.f90
    test/ReactorConfigModuleTest.f90
)
set_target_properties(reactor_config_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/reactor-config-test-modules"
)
add_test(NAME reactor_config
    COMMAND reactor_config_module_test "${water_fixture_dir}/bed-sediment-config.nml" defaults
)
foreach(mode critical disabled_error)
    if(mode STREQUAL "critical")
        set(reactor_expected_exit 1)
        set(reactor_expected_text "Invalid Reactor index provided.")
        set(reactor_forbidden_text "Completed Reactor check")
    else()
        set(reactor_expected_exit 0)
        set(reactor_expected_text "Completed Reactor check")
        set(reactor_forbidden_text "Invalid Reactor index provided.")
    endif()
    add_test(NAME reactor_${mode}
        COMMAND "${CMAKE_COMMAND}"
            "-DTEST_EXECUTABLE=$<TARGET_FILE:reactor_config_module_test>"
            "-DDIMENSIONS_FIXTURE=${water_fixture_dir}/bed-sediment-config.nml"
            "-DMODE=${mode}" "-DEXPECTED_EXIT=${reactor_expected_exit}"
            "-DEXPECTED_TEXT=${reactor_expected_text}" "-DFORBIDDEN_TEXT=${reactor_forbidden_text}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectReactor.cmake"
    )
endforeach()

# Record the current mass-loss defect without changing the science in this migration.
set(reactor_legacy_mass_sources ${sources})
list(FILTER reactor_legacy_mass_sources EXCLUDE REGEX "/src/main\\.f90$")
add_executable(reactor_legacy_mass_test ${reactor_legacy_mass_sources} test/ReactorLegacyMassTest.f90)
set_target_properties(reactor_legacy_mass_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/reactor-legacy-mass-test-modules"
)
target_include_directories(reactor_legacy_mass_test PRIVATE "${NETCDF_INCLUDES}")
target_link_libraries(reactor_legacy_mass_test PRIVATE "${NETCDF_LIBRARIES_F90}")
add_test(NAME reactor_known_mass_loss COMMAND reactor_legacy_mass_test)

# These probes use existing public procedures so the identical test sources can
# capture Phase 8 state before any Biota production code is changed.
set(biota_probe_sources ${sources})
list(FILTER biota_probe_sources EXCLUDE REGEX "/src/main\\.f90$")
foreach(probe Science Integration)
    string(TOLOWER "${probe}" probe_lower)
    add_executable(biota_${probe_lower}_test ${biota_probe_sources} test/Biota${probe}Test.f90)
    set_target_properties(biota_${probe_lower}_test PROPERTIES
        Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/biota-${probe_lower}-test-modules"
    )
    target_include_directories(biota_${probe_lower}_test PRIVATE "${NETCDF_INCLUDES}")
    target_link_libraries(biota_${probe_lower}_test PRIVATE "${NETCDF_LIBRARIES_F90}")
endforeach()
add_test(NAME biota_science COMMAND biota_science_test)

# Biota has no model-config group; only its existing error changes owner.
add_executable(biota_config_module_test
    vendor/feh/src/ErrorInstance.f90
    vendor/feh/src/ErrorHandler.f90
    vendor/feh/src/ErrorCriteria.f90
    src/Kernel/KernelModule.f90
    src/ModelDimensions/ModelDimensionsModule.f90
    src/ErrorHandling/ErrorHandlingModule.f90
    src/Soil/SoilConfigModule.f90
    src/BedSediment/BedSedimentConfigModule.f90
    src/WaterBody/WaterBodyConfigModule.f90
    src/Reactor/ReactorConfigModule.f90
    src/Biota/BiotaConfigModule.f90
    test/BiotaConfigModuleTest.f90
)
set_target_properties(biota_config_module_test PROPERTIES
    Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/biota-config-test-modules"
)
add_test(NAME biota_registry
    COMMAND biota_config_module_test "${water_fixture_dir}/bed-sediment-config.nml" registry
)
foreach(mode critical disabled_error)
    if(mode STREQUAL "critical")
        set(biota_expected_exit 1)
        set(biota_expected_text "Invalid Biota index provided.")
        set(biota_forbidden_text "Completed Biota check")
    else()
        set(biota_expected_exit 0)
        set(biota_expected_text "Completed Biota check")
        set(biota_forbidden_text "Invalid Biota index provided.")
    endif()
    add_test(NAME biota_${mode}
        COMMAND "${CMAKE_COMMAND}"
            "-DTEST_EXECUTABLE=$<TARGET_FILE:biota_config_module_test>"
            "-DDIMENSIONS_FIXTURE=${water_fixture_dir}/bed-sediment-config.nml"
            "-DMODE=${mode}" "-DEXPECTED_EXIT=${biota_expected_exit}"
            "-DEXPECTED_TEXT=${biota_expected_text}" "-DFORBIDDEN_TEXT=${biota_forbidden_text}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/test/ExpectBiota.cmake"
    )
endforeach()
