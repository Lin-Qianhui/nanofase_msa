!> Reactor fallback constants and its registered error.
module ReactorConfigModule
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: default_k_diss_pristine, default_k_diss_transformed, default_k_transform_pristine
    public :: defaultShearRate, registerReactorErrors

    ! Defaults for constants
    real, parameter :: default_k_diss_pristine = 0.0
    real, parameter :: default_k_diss_transformed = 0.0
    real, parameter :: default_k_transform_pristine = 0.0
    real, parameter :: defaultShearRate = 10.0                      ! Arvidsson et al, 2009: https://doi.org/10.1080/10807039.2011.538639

  contains

    !> Register the existing Reactor error after the shared handler is initialised.
    subroutine registerReactorErrors()
        call ERROR_HANDLER%add(error=ErrorInstance(code=903, message="Invalid Reactor index provided."))
    end subroutine

end module ReactorConfigModule
