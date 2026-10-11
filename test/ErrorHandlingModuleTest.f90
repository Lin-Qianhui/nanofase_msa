program ErrorHandlingModuleTest
    use iso_fortran_env, only: output_unit
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    implicit none

    integer, parameter :: expectedCodes(15) = [ &
        0, 1, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 200, 201, 300 &
    ]
    integer, parameter :: sharedCodes(4) = [110, 200, 201, 300]
    character(len=256), parameter :: sharedMessages(4) = [character(len=256) :: &
        "Invalid object type index in data file.", "File not found.", &
        "Variable not found in input file.", "Newton's method failed to converge." &
    ]
    character(len=32) :: codeArgument, mode
    type(ErrorInstance), allocatable :: errors(:)
    type(ErrorInstance) :: error
    integer :: i, code, readStatus

    call get_command_argument(1, codeArgument)
    call get_command_argument(2, mode)
    code = 0
    if (len_trim(codeArgument) > 0) then
        read(codeArgument, *, iostat=readStatus) code
        call assertTrue(readStatus == 0, "Invalid diagnostic code argument")
        call assertTrue(code == 1 .or. any(sharedCodes == code), "Unexpected diagnostic code")
        call assertTrue(mode == 'critical' .or. mode == 'quiet' .or. mode == 'disabled' .or. &
            (mode == 'generic' .and. code == 1), "Unknown diagnostic mode")
    end if
    call initErrorHandling(mode /= 'quiet', mode /= 'disabled')
    call assertTrue(.not. ERROR_HANDLER%errorExists(901), "Base handler must leave code 901 to WaterBody")
    call assertTrue(.not. ERROR_HANDLER%errorExists(902), "Base handler unexpectedly registered Biota error 902")

    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == size(expectedCodes), "base registry size changed")
    call assertTrue(.not. ERROR_HANDLER%errorExists(903), "Reactor error was unexpectedly registered by the base handler")
    call assertTrue(.not. ERROR_HANDLER%errorExists(600), "Soil error was unexpectedly registered by the base handler")

    call assertTrue(.not. ERROR_HANDLER%errorExists(904), "BedSediment error was unexpectedly registered by the base handler")

    do i = 1, size(expectedCodes)
        call assertTrue(count(errors%code == expectedCodes(i)) == 1, "Expected shared code is not present exactly once")
        error = ERROR_HANDLER%getErrorFromCode(expectedCodes(i))
        call assertTrue(error%isCritical .eqv. (expectedCodes(i) /= 0), "Shared error criticality changed")
    end do
    do i = 1, size(sharedCodes)
        error = ERROR_HANDLER%getErrorFromCode(sharedCodes(i))
        call assertTrue(error%message == sharedMessages(i), "Shared error message changed")
    end do
    call assertTrue(.not. ERROR_HANDLER%errorExists(405), "Base handler must leave code 405 to WaterBody")

    error = ERROR_HANDLER%getNoError()
    call assertTrue(error%code == 0 .and. error%message == 'No error.', "No-error definition changed")

    error = ERROR_HANDLER%getErrorFromCode(1)
    call assertTrue(trim(error%message) == "", "default code-1 blank message changed")
    call assertTrue(error%isCritical, "default code-1 criticality changed")

    call assertTrue(.not. ERROR_HANDLER%errorExists(500), "Base handler unexpectedly registered WaterBody error 500")

    error = ERROR_HANDLER%equal(value=1.0, criterion=1.0)
    call assertTrue(error%getCode() == 0, "ERROR_HANDLER is not preserving ErrorCriteria behavior")

    call ERROR_HANDLER%add(error=ErrorInstance(code=999, message="Registration smoke test."))
    call assertTrue(ERROR_HANDLER%errorExists(999), "named ErrorInstance registration failed")
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 16 .and. count(errors%code == 999) == 1, "Named registration did not add one entry")

    if (code /= 0) then
        print '(a)', 'Ready to trigger shared error'
        flush(output_unit)
        if (mode == 'generic') then
            call ERROR_HANDLER%trigger()
        else
            call ERROR_HANDLER%trigger(code=code)
        end if
        print '(a)', 'Completed shared error check'
    end if

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message

        if (.not. condition) error stop message
    end subroutine

end program ErrorHandlingModuleTest
