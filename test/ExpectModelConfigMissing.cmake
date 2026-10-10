# Each required group is removed in an isolated build-directory fixture.
file(READ "${FIXTURE}" config)
string(REGEX REPLACE "&${MISSING_GROUP}\n[^&]*[/]\n" "" missing "${config}")
if(missing STREQUAL config)
    message(FATAL_ERROR "Required-group fixture was not changed")
endif()
set(path "${CMAKE_CURRENT_BINARY_DIR}/model-config-missing-${MISSING_GROUP}.nml")
file(WRITE "${path}" "${missing}")
execute_process(COMMAND "${TEST_EXECUTABLE}" "${path}" "${FIXTURE}"
    RESULT_VARIABLE status OUTPUT_VARIABLE output ERROR_VARIABLE error)
if(NOT status EQUAL 2 OR NOT error MATCHES "End of file")
    message(FATAL_ERROR "Required ${MISSING_GROUP} failure changed (${status}):\n${output}\n${error}")
endif()
