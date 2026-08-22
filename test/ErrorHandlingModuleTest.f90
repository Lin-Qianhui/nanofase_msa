program ErrorHandlingModuleTest
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    implicit none

    integer, parameter :: expectedCodes(15) = [ &
        110, 200, 201, 300, 401, 402, 403, 404, 500, 501, 600, 901, 902, 903, 904 &
    ]
    type(ErrorInstance), allocatable :: errors(:)
    type(ErrorInstance) :: error
    integer :: i

    call initErrorHandling(.true., .true.)

    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 26, "legacy registry size changed")

    do i = 1, size(expectedCodes)
        call assertTrue(ERROR_HANDLER%errorExists(expectedCodes(i)), "expected legacy error code is absent")
    end do
    call assertTrue(.not. ERROR_HANDLER%errorExists(405), "overwritten code 405 was unexpectedly restored")

    error = ERROR_HANDLER%getErrorFromCode(1)
    call assertTrue(trim(error%message) == "", "default code-1 blank message changed")
    call assertTrue(error%isCritical, "default code-1 criticality changed")

    error = ERROR_HANDLER%getErrorFromCode(500)
    call assertTrue(.not. error%isCritical, "code 500 criticality changed")
    error = ERROR_HANDLER%getErrorFromCode(600)
    call assertTrue(.not. error%isCritical, "code 600 criticality changed")

    error = ERROR_HANDLER%equal(value=1.0, criterion=1.0)
    call assertTrue(error%getCode() == 0, "ERROR_HANDLER is not preserving ErrorCriteria behavior")

    call ERROR_HANDLER%add(error=ErrorInstance(code=999, message="Registration smoke test."))
    call assertTrue(ERROR_HANDLER%errorExists(999), "named ErrorInstance registration failed")

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message

        if (.not. condition) error stop message
    end subroutine

end program ErrorHandlingModuleTest
