# Clean the wrapper's targets without removing neighbouring fpm/cache directories.
foreach(profile debug release fast)
    set(profile_dir "${OUTPUT_DIR}/make-${profile}")
    if(EXISTS "${profile_dir}/CMakeCache.txt")
        execute_process(COMMAND "${CMAKE_COMMAND}" --build "${profile_dir}" --target clean
            RESULT_VARIABLE clean_result)
        if(NOT clean_result EQUAL 0)
            message(FATAL_ERROR "Could not clean ${profile_dir}.")
        endif()
    endif()
endforeach()
if(EXISTS "${OUTPUT_DIR}/.nanofase-make-output")
    file(READ "${OUTPUT_DIR}/.nanofase-make-output" published_name)
    if("${published_name}" STREQUAL "${EXEC_FILE}")
        file(REMOVE "${OUTPUT_DIR}/${EXEC_FILE}" "${OUTPUT_DIR}/comp_meta"
            "${OUTPUT_DIR}/.nanofase-make-output")
    endif()
endif()
