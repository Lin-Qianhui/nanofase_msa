!> Biota's registered error; organism inputs remain in the constants-file reader.
module BiotaConfigModule
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: registerBiotaErrors

  contains

    !> Register the existing Biota error after the shared handler is initialised.
    subroutine registerBiotaErrors()
        call ERROR_HANDLER%add(error=ErrorInstance(code=902, message="Invalid Biota index provided."))
    end subroutine

end module BiotaConfigModule
