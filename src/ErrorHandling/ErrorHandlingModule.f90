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
        type(ErrorInstance) :: errors(15)                   ! ErrorInstances to be added to ErrorHandler

        ! General
        errors(1) = ErrorInstance(code=110, message="Invalid object type index in data file.")
        ! File operations
        errors(2) = ErrorInstance(code=200, message="File not found.")
        errors(3) = ErrorInstance(code=201, message="Variable not found in input file.")
        ! Numerical calculations
        errors(6) = ErrorInstance(code=300, message="Newton's method failed to converge.")
        ! Grid and geography
        errors(7) = ErrorInstance(code=401, &
            message="Invalid RiverReach inflow reference. Inflow must be from a neighbouring RiverReach.")
        errors(8) = ErrorInstance(code=402, &
            message="Invalid RiverReach inflow reference. If multiple inflows are specified, they must " // &
                        "be inflows to the GridCell and all come from the same GridCell.")
        errors(9) = ErrorInstance(code=403, &
            message="RiverReach cannot have more than 5 inflows.")
        errors(10) = ErrorInstance(code=404, &
            message="RiverReach outflow could not be determined. Reaches must either be specified as " // &
                        "inflow to downstream reach, or have a model domain outflow specified.")
        errors(11) = ErrorInstance(code=405, &
            message="RiverReach lengths specified in input data sum to greater than straight-line river branch " // &
                        "length. Are you sure this is intended?", isCritical=.false.)
        ! River routing
        errors(11) = ErrorInstance(code=500, &
            message="All SPM advected from RiverReach.", isCritical=.false.)
        errors(12) = ErrorInstance(code=501, &
            message="No input data provided for required SubRiver - check nSubRivers is correct.")
        ! General
        errors(13) = ErrorInstance(code=901, message="Invalid RiverReach type index provided.")
        errors(14) = ErrorInstance(code=902, message="Invalid Biota index provided.")
        errors(15) = ErrorInstance(code=903, message="Invalid Reactor index provided.")

        ! Add custom errors to the error handler.
        call ERROR_HANDLER%init(errors=errors, triggerWarnings=triggerWarnings, on=errorOutput)
    end subroutine

end module ErrorHandlingModule
