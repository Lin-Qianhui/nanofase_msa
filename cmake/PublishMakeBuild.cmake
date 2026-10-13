# Publish only the wrapper's model executable and compilation information.
set(executable "${PROFILE_DIR}/nanofase${CMAKE_EXECUTABLE_SUFFIX}")
if(EXISTS "${PROFILE_DIR}/${BUILD_CONFIG}/nanofase${CMAKE_EXECUTABLE_SUFFIX}")
    set(executable "${PROFILE_DIR}/${BUILD_CONFIG}/nanofase${CMAKE_EXECUTABLE_SUFFIX}")
endif()
file(MAKE_DIRECTORY "${OUTPUT_DIR}")
execute_process(COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${executable}" "${OUTPUT_DIR}/${EXEC_FILE}" RESULT_VARIABLE copy_result)
if(NOT copy_result EQUAL 0)
    message(FATAL_ERROR "Could not publish the Make build executable.")
endif()
file(READ "${PROFILE_DIR}/generated/version.txt" version)
string(STRIP "${version}" version)
set(commit "unavailable")
set(branch "unavailable")
find_package(Git QUIET)
if(GIT_FOUND AND EXISTS "${SOURCE_ROOT}/.git")
    execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_ROOT}" rev-parse HEAD
        OUTPUT_VARIABLE commit OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_ROOT}" rev-parse --abbrev-ref HEAD
        OUTPUT_VARIABLE branch OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
endif()
string(TIMESTAMP compiled_at "%Y-%m-%d %H:%M:%S UTC" UTC)
file(WRITE "${OUTPUT_DIR}/comp_meta" "${compiled_at}\nCommit: ${commit}\nBranch: ${branch}\nVersion: ${version}\nConfiguration: ${BUILD_CONFIG}\n")
# This record lets clean distinguish our published files from unrelated builds.
file(WRITE "${OUTPUT_DIR}/.nanofase-make-output" "${EXEC_FILE}")
