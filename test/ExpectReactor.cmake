execute_process(
    COMMAND "${TEST_EXECUTABLE}" "${DIMENSIONS_FIXTURE}" "${MODE}"
    RESULT_VARIABLE status
    OUTPUT_VARIABLE output
    ERROR_VARIABLE error
)
set(combined "${output}${error}")
if(NOT "${status}" STREQUAL "${EXPECTED_EXIT}")
    message(FATAL_ERROR "Expected exit ${EXPECTED_EXIT}, got ${status}:\n${combined}")
endif()
string(FIND "${combined}" "Registered Reactor error" registered_position)
if(registered_position EQUAL -1)
    message(FATAL_ERROR "Test did not reach Reactor registration:\n${combined}")
endif()
string(FIND "${combined}" "${EXPECTED_TEXT}" expected_position)
if(expected_position EQUAL -1)
    message(FATAL_ERROR "Missing expected diagnostic '${EXPECTED_TEXT}':\n${combined}")
endif()
string(FIND "${combined}" "${FORBIDDEN_TEXT}" forbidden_position)
if(NOT forbidden_position EQUAL -1)
    message(FATAL_ERROR "Unexpected diagnostic '${FORBIDDEN_TEXT}':\n${combined}")
endif()
