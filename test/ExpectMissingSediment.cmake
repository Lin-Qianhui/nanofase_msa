# Require a failure after dimensions and Soil have been read successfully.
execute_process(
    COMMAND "${TEST_EXECUTABLE}" "${DIMENSIONS_FIXTURE}" missing "${SEDIMENT_FIXTURE}"
    RESULT_VARIABLE test_result
    OUTPUT_VARIABLE test_stdout
    ERROR_VARIABLE test_stderr
)
if(test_result STREQUAL "0"
   OR NOT test_stdout MATCHES "Reading required BedSediment group"
   OR test_stdout MATCHES "UNEXPECTED_SUCCESS")
    message(FATAL_ERROR "Missing sediment group did not fail at its reader: ${test_result}\n${test_stdout}\n${test_stderr}")
endif()
