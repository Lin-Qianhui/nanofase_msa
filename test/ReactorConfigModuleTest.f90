program ReactorConfigModuleTest
    use iso_fortran_env, only: output_unit
    use ModelDimensionsModule, only: initModelDimensions
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    use SoilConfigModule, only: soilConfig
    use BedSedimentConfigModule, only: bedSedimentConfig
    use WaterBodyConfigModule, only: waterBodyConfig
    use ReactorConfigModule, only: default_k_diss_pristine, default_k_diss_transformed, &
        default_k_transform_pristine, defaultShearRate, registerReactorErrors
    implicit none

    character(len=1024) :: dimensionsPath
    character(len=32) :: mode
    type(ErrorInstance), allocatable :: errorsBefore(:), errorsAfter(:)
    type(ErrorInstance) :: error
    integer :: i, occurrences

    call get_command_argument(1, dimensionsPath)
    call get_command_argument(2, mode)
    call assertTrue(len_trim(dimensionsPath) > 0, "Dimensions fixture path was not provided")
    call assertTrue(mode == 'defaults' .or. mode == 'critical' .or. mode == 'disabled_error', "Unknown test mode")

    call assertTrue(kind(default_k_diss_pristine) == kind(0.0) .and. default_k_diss_pristine == 0.0, &
        "Pristine dissolution default or precision changed")
    call assertTrue(kind(default_k_diss_transformed) == kind(0.0) .and. default_k_diss_transformed == 0.0, &
        "Transformed dissolution default or precision changed")
    call assertTrue(kind(default_k_transform_pristine) == kind(0.0) .and. default_k_transform_pristine == 0.0, &
        "Transformation default or precision changed")
    call assertTrue(kind(defaultShearRate) == kind(0.0) .and. defaultShearRate == 10.0, &
        "Shear-rate default or precision changed")

    call initModelDimensions(trim(dimensionsPath))
    ! Suppressing warnings must not suppress the critical Reactor error.
    call initErrorHandling(.false., mode /= 'disabled_error')
    call checkBeforeReactor(17)
    call soilConfig%init(trim(dimensionsPath))
    call checkBeforeReactor(18)
    call bedSedimentConfig%init(trim(dimensionsPath))
    call checkBeforeReactor(19)
    call waterBodyConfig%init(trim(dimensionsPath))
    call checkBeforeReactor(25)

    errorsBefore = ERROR_HANDLER%getErrors()
    call registerReactorErrors()
    errorsAfter = ERROR_HANDLER%getErrors()
    call assertTrue(size(errorsAfter) == 26, "Reactor did not add exactly one error")
    occurrences = 0
    do i = 1, size(errorsAfter)
        if (errorsAfter(i)%getCode() == 903) occurrences = occurrences + 1
    end do
    call assertTrue(occurrences == 1, "Reactor error was not registered exactly once")
    error = ERROR_HANDLER%getErrorFromCode(903)
    call assertTrue(error%message == 'Invalid Reactor index provided.', "Reactor error message changed")
    call assertTrue(error%isCritical, "Reactor error is no longer critical")
    do i = 1, size(errorsBefore)
        error = ERROR_HANDLER%getErrorFromCode(errorsBefore(i)%getCode())
        call assertTrue(error%message == errorsBefore(i)%message, "Reactor registration changed another error message")
        call assertTrue(error%isCritical .eqv. errorsBefore(i)%isCritical, &
            "Reactor registration changed another error's critical status")
    end do
    call assertTrue(.not. ERROR_HANDLER%errorExists(405), "Overwritten code 405 was unexpectedly restored")
    error = ERROR_HANDLER%getErrorFromCode(1)
    call assertTrue(error%message == '' .and. error%isCritical, "Legacy blank error changed")
    error = ERROR_HANDLER%equal(value=1.0, criterion=1.0)
    call assertTrue(error%getCode() == 0, "Shared criteria operations changed")

    print '(a)', 'Registered Reactor error'
    flush(output_unit)
    if (mode == 'critical' .or. mode == 'disabled_error') then
        call ERROR_HANDLER%trigger(errors=[ERROR_HANDLER%getErrorFromCode(903)])
    end if
    print '(a)', 'Completed Reactor check'

  contains

    subroutine checkBeforeReactor(expectedCount)
        integer, intent(in) :: expectedCount
        type(ErrorInstance), allocatable :: errors(:)
        errors = ERROR_HANDLER%getErrors()
        call assertTrue(size(errors) == expectedCount, "Registration count before Reactor changed")
        call assertTrue(.not. ERROR_HANDLER%errorExists(903), "Another owner registered Reactor error 903")
    end subroutine

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine

end program ReactorConfigModuleTest
