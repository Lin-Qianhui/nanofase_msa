!> Shared model diagnostics and FEH integration.
module ErrorHandlingModule
    use ErrorCriteriaModule, only: ErrorCriteria
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: ERROR_HANDLER, initErrorHandling

    type(ErrorCriteria)             :: ERROR_HANDLER                        ! Global error handling

  contains

    !> Initialise the shared error handler with the legacy error registry.
    ! Phase 11 note: this is now the agreed shared list; domain errors register with their owners.
    subroutine initErrorHandling(triggerWarnings, errorOutput)
        logical, intent(in) :: triggerWarnings
        logical, intent(in) :: errorOutput
        type(ErrorInstance) :: errors(6)                   ! ErrorInstances to be added to ErrorHandler

        ! Phase 11 note: 110, 200, 201 and 300 remain shared for compatibility.
        ! Slots 4 and 5 intentionally retain the default blank, critical code-1 instances.
        ! FEH combines them into one code-1 entry, keeping its existing blank message.
        ! General
        errors(1) = ErrorInstance(code=110, message="Invalid object type index in data file.")
        ! File operations
        errors(2) = ErrorInstance(code=200, message="File not found.")
        errors(3) = ErrorInstance(code=201, message="Variable not found in input file.")
        ! Numerical calculations
        errors(6) = ErrorInstance(code=300, message="Newton's method failed to converge.")

        ! Add custom errors to the error handler.
        call ERROR_HANDLER%init(errors=errors, triggerWarnings=triggerWarnings, on=errorOutput)
    end subroutine

end module ErrorHandlingModule
