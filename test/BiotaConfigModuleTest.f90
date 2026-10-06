program BiotaConfigModuleTest
    use iso_fortran_env, only: output_unit
    use ModelDimensionsModule, only: initModelDimensions
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    use SoilConfigModule, only: soilConfig
    use BedSedimentConfigModule, only: bedSedimentConfig
    use WaterBodyConfigModule, only: waterBodyConfig
    use ReactorConfigModule, only: registerReactorErrors
    use BiotaConfigModule, only: registerBiotaErrors
    implicit none

    character(len=1024) :: dimensionsPath
    character(len=32) :: mode
    type(ErrorInstance), allocatable :: before(:), after(:)
    type(ErrorInstance) :: error
    integer :: i, occurrences

    call get_command_argument(1, dimensionsPath)
    call get_command_argument(2, mode)
    call require(len_trim(dimensionsPath) > 0, 'Dimensions fixture path was not provided')
    call require(mode == 'registry' .or. mode == 'critical' .or. mode == 'disabled_error', 'Unknown test mode')
    call initModelDimensions(trim(dimensionsPath))
    ! Suppressing warnings must not suppress a critical Biota error.
    call initErrorHandling(.false., mode /= 'disabled_error')
    call beforeBiota(16)
    call soilConfig%init(trim(dimensionsPath))
    call beforeBiota(17)
    call bedSedimentConfig%init(trim(dimensionsPath))
    call beforeBiota(18)
    call waterBodyConfig%init(trim(dimensionsPath))
    call beforeBiota(24)
    call registerReactorErrors()
    call beforeBiota(25)

    before = ERROR_HANDLER%getErrors()
    call registerBiotaErrors()
    after = ERROR_HANDLER%getErrors()
    call require(size(after) == 26, 'Biota did not add exactly one error')
    occurrences = 0
    do i = 1, size(after)
        if (after(i)%getCode() == 902) occurrences = occurrences + 1
    end do
    call require(occurrences == 1, 'Biota error was not registered exactly once')
    error = ERROR_HANDLER%getErrorFromCode(902)
    call require(error%message == 'Invalid Biota index provided.', 'Biota error message changed')
    call require(error%isCritical, 'Biota error is no longer critical')
    do i = 1, size(before)
        error = ERROR_HANDLER%getErrorFromCode(before(i)%getCode())
        call require(error%message == before(i)%message, 'Biota registration changed another message')
        call require(error%isCritical .eqv. before(i)%isCritical, 'Biota registration changed another severity')
    end do
    call require(.not. ERROR_HANDLER%errorExists(405), 'Missing code 405 was unexpectedly restored')
    error = ERROR_HANDLER%getErrorFromCode(1)
    call require(error%message == '' .and. error%isCritical, 'Legacy blank error changed')
    error = ERROR_HANDLER%equal(value=1.0, criterion=1.0)
    call require(error%getCode() == 0, 'Shared criteria operations changed')

    print '(a)', 'Registered Biota error'
    flush(output_unit)
    if (mode == 'critical' .or. mode == 'disabled_error') &
        call ERROR_HANDLER%trigger(errors=[ERROR_HANDLER%getErrorFromCode(902)])
    print '(a)', 'Completed Biota check'

  contains

    subroutine beforeBiota(expected)
        integer, intent(in) :: expected
        type(ErrorInstance), allocatable :: errors(:)
        errors = ERROR_HANDLER%getErrors()
        call require(size(errors) == expected, 'Registration count before Biota changed')
        call require(.not. ERROR_HANDLER%errorExists(902), 'Another owner registered Biota error 902')
    end subroutine

    subroutine require(condition, message)
        logical, intent(in) :: condition
        character(*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine
end program BiotaConfigModuleTest
