# Both configuration and the build call this same version-selection procedure.
# The source fallback stays valid Fortran for fpm and source distributions.
set(nanofase_version_helper_dir "${CMAKE_CURRENT_LIST_DIR}")

function(nanofase_write_version show_status)
    file(READ "${version_source_root}/src/VersionModule.f90" fallback_source)
    string(REGEX MATCH "MODEL_VERSION[ \t]*=[ \t]*\"([^\"]+)\"" fallback_match "${fallback_source}")
    if(NOT fallback_match)
        message(FATAL_ERROR "VersionModule.f90 must contain a non-empty MODEL_VERSION fallback.")
    endif()
    set(version_label "${CMAKE_MATCH_1}")
    set(version_origin "tracked fallback")
    if(NOT "${version_override}" STREQUAL "")
        set(version_label "${version_override}")
        set(version_origin "explicit override")
    elseif(version_git AND EXISTS "${version_source_root}/.git")
        # A worktree may have a .git file. An archive inside another checkout must
        # not inherit that containing checkout's tags or commit description.
        execute_process(COMMAND "${version_git}" -C "${version_source_root}" rev-parse --show-toplevel
            RESULT_VARIABLE root_result OUTPUT_VARIABLE git_root
            OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
        get_filename_component(source_real "${version_source_root}" REALPATH)
        get_filename_component(git_real "${git_root}" REALPATH)
        if(root_result EQUAL 0 AND "${source_real}" STREQUAL "${git_real}")
            execute_process(COMMAND "${version_git}" -C "${version_source_root}" describe --tags
                RESULT_VARIABLE describe_result OUTPUT_VARIABLE git_label
                OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
            if(describe_result EQUAL 0 AND NOT "${git_label}" STREQUAL "")
                set(version_label "${git_label}")
                set(version_origin "git describe --tags")
            endif()
        endif()
    endif()
    if(version_label MATCHES "[\r\n]")
        message(FATAL_ERROR "The NanoFASE version label must be a single line.")
    endif()

    # Keep the existing 17-character constant and 16-character model fields.
    # Truncate before escaping so quotes still count as one Fortran character.
    string(SUBSTRING "${version_label}" 0 17 version_fortran_literal)
    string(REPLACE "\"" "\"\"" version_fortran_literal "${version_fortran_literal}")
    file(MAKE_DIRECTORY "${version_output_dir}")
    configure_file("${version_template}" "${version_output_dir}/VersionModule.f90" @ONLY)
    set(version_record "${version_label}\n")
    set(previous_record "")
    if(EXISTS "${version_output_dir}/version.txt")
        file(READ "${version_output_dir}/version.txt" previous_record)
    endif()
    if(NOT "${previous_record}" STREQUAL "${version_record}")
        file(WRITE "${version_output_dir}/version.txt" "${version_record}")
    endif()
    if(show_status)
        message(STATUS "NanoFASE version: ${version_label} (${version_origin}; model output keeps 16 characters)")
    endif()
endfunction()

function(nanofase_setup_version output_variable)
    # Older builds put the model's compiled modules in the build root. GFortran
    # searches that working directory before a target's private module directory,
    # which can silently give a separately rebuilt test an old version constant.
    # Keep those generated files as evidence, but move them out of the search path.
    if(EXISTS "${CMAKE_CURRENT_BINARY_DIR}/versionmodule.mod" OR
            EXISTS "${CMAKE_CURRENT_BINARY_DIR}/VERSIONMODULE.mod")
        if("${CMAKE_CURRENT_BINARY_DIR}" STREQUAL "${CMAKE_CURRENT_SOURCE_DIR}")
            message(FATAL_ERROR "Use a separate build directory when upgrading a legacy in-source build.")
        endif()
        file(GLOB legacy_modules "${CMAKE_CURRENT_BINARY_DIR}/*.mod" "${CMAKE_CURRENT_BINARY_DIR}/*.smod")
        file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/legacy-fortran-modules")
        foreach(legacy_module IN LISTS legacy_modules)
            get_filename_component(module_name "${legacy_module}" NAME)
            file(RENAME "${legacy_module}" "${CMAKE_CURRENT_BINARY_DIR}/legacy-fortran-modules/${module_name}")
        endforeach()
        message(STATUS "Moved legacy compiled modules out of the build root to avoid stale version imports")
    endif()
    set(NANOFASE_VERSION "" CACHE STRING "Version label override; empty selects Git, then the tracked fallback")
    find_package(Git QUIET)
    set(version_source_root "${CMAKE_CURRENT_SOURCE_DIR}")
    set(version_output_dir "${CMAKE_CURRENT_BINARY_DIR}/generated")
    set(version_override "${NANOFASE_VERSION}")
    set(version_git "")
    if(GIT_FOUND)
        set(version_git "${GIT_EXECUTABLE}")
    endif()
    set(version_template "${nanofase_version_helper_dir}/VersionModule.f90.in")
    set(version_helper "${nanofase_version_helper_dir}/NanoFASEVersion.cmake")
    nanofase_write_version(TRUE)

    # Bracket arguments preserve quotes, backslashes, semicolons and literal ${...}
    # in labels and paths. Choose a delimiter absent from the value itself.
    set(refresh_script "")
    foreach(name version_source_root version_output_dir version_override version_git version_template version_helper)
        set(equals "=")
        string(FIND "${${name}}" "]${equals}]" closing_delimiter)
        while(NOT closing_delimiter EQUAL -1)
            string(APPEND equals "=")
            string(FIND "${${name}}" "]${equals}]" closing_delimiter)
        endwhile()
        string(APPEND refresh_script "set(${name} [${equals}[${${name}}]${equals}])\n")
    endforeach()
    string(APPEND refresh_script "include(\"\${version_helper}\")\nnanofase_write_version(FALSE)\n")
    set(refresh_path "${CMAKE_CURRENT_BINARY_DIR}/RefreshVersion.cmake")
    file(WRITE "${refresh_path}" "${refresh_script}")
    add_custom_target(nanofase_version
        COMMAND "${CMAKE_COMMAND}" -P "${refresh_path}"
        BYPRODUCTS "${version_output_dir}/VersionModule.f90" "${version_output_dir}/version.txt"
        COMMENT "Checking the NanoFASE version without changing source files"
        VERBATIM)
    set(${output_variable} "${version_output_dir}/VersionModule.f90" PARENT_SCOPE)
endfunction()
