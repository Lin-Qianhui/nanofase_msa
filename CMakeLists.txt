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
