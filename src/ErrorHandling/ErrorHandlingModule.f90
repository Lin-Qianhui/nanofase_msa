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
    subroutine initErrorHandling(triggerWarnings, errorOutput)
        logical, intent(in) :: triggerWarnings
        logical, intent(in) :: errorOutput
        type(ErrorInstance) :: errors(9)                   ! ErrorInstances to be added to ErrorHandler

        ! General
        errors(1) = ErrorInstance(code=110, message="Invalid object type index in data file.")
        ! File operations
        errors(2) = ErrorInstance(code=200, message="File not found.")
        errors(3) = ErrorInstance(code=201, message="Variable not found in input file.")
        ! Numerical calculations
        errors(6) = ErrorInstance(code=300, message="Newton's method failed to converge.")
        ! General
        errors(7) = ErrorInstance(code=901, message="Invalid RiverReach type index provided.")
        errors(8) = ErrorInstance(code=902, message="Invalid Biota index provided.")
        errors(9) = ErrorInstance(code=903, message="Invalid Reactor index provided.")

        ! Add custom errors to the error handler.
        call ERROR_HANDLER%init(errors=errors, triggerWarnings=triggerWarnings, on=errorOutput)
    end subroutine

end module ErrorHandlingModule
