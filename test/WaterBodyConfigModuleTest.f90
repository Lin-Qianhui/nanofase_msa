program WaterBodyConfigModuleTest
    use iso_fortran_env, only: output_unit
    use KernelModule, only: dp
    use ModelDimensionsModule, only: initModelDimensions
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    use SoilConfigModule, only: soilConfig
    use BedSedimentConfigModule, only: bedSedimentConfig
    use WaterBodyConfigModule, only: waterBodyConfig, defaultSlope, defaultBankErosionAlpha, defaultBankErosionBeta, &
        defaultMinWaterTemperature, defaultMaxWaterTemperature, defaultMinWaterTemperatureDayOfYear
    implicit none

    character(len=1024) :: dimensionsPath, waterPath
    character(len=32) :: mode
    integer, parameter :: codes(6) = [401, 402, 403, 404, 500, 501]
    character(len=256), parameter :: messages(6) = [character(len=256) :: &
        "Invalid RiverReach inflow reference. Inflow must be from a neighbouring RiverReach.", &
        "Invalid RiverReach inflow reference. If multiple inflows are specified, they must " // &
            "be inflows to the GridCell and all come from the same GridCell.", &
        "RiverReach cannot have more than 5 inflows.", &
        "RiverReach outflow could not be determined. Reaches must either be specified as " // &
            "inflow to downstream reach, or have a model domain outflow specified.", &
        "All SPM advected from RiverReach.", &
        "No input data provided for required SubRiver - check nSubRivers is correct." &
    ]
    type(ErrorInstance), allocatable :: errors(:)
    type(ErrorInstance) :: error
    real :: expectedSlope
    integer :: expectedTimestep, i, j, occurrences
    logical :: expectedEstuary, expectedBank

    call get_command_argument(1, dimensionsPath)
    call get_command_argument(2, mode)
    call get_command_argument(3, waterPath)
    call assertTrue(len_trim(waterPath) > 0, "WaterBody fixture path was not provided")
    call initModelDimensions(trim(dimensionsPath))
    call initErrorHandling(mode /= 'quiet_warning', mode /= 'disabled_error')
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 17, "Base registry count changed")
    do i = 1, size(codes)
        call assertTrue(.not. ERROR_HANDLER%errorExists(codes(i)), "Base handler registered a WaterBody error")
    end do
    call soilConfig%init(trim(dimensionsPath))
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 18, "Soil registry count changed")
    call bedSedimentConfig%init(trim(dimensionsPath))
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 19, "BedSediment registry count changed")

    ! Values already stored in the object must not replace the input defaults.
    waterBodyConfig%minStreamSlope = 0.9
    waterBodyConfig%minEstuaryTimestep = 9
    waterBodyConfig%includeEstuary = .false.
    waterBodyConfig%includeBankErosion = .false.
    print '(a)', 'Reading WaterBody configuration'
    flush(output_unit)
    call waterBodyConfig%init(trim(waterPath))
    call assertTrue(mode /= 'unknown' .and. mode /= 'malformed', "Invalid WaterBody input was accepted")

    expectedSlope = 0.0001
    expectedTimestep = 3600
    expectedEstuary = .true.
    expectedBank = .true.
    if (mode == 'explicit' .or. index(mode, 'omit_') == 1) then
        expectedSlope = 0.002
        expectedTimestep = 1800
        expectedEstuary = .false.
        expectedBank = .false.
    end if
    if (mode == 'omit_slope') expectedSlope = 0.0001
    if (mode == 'omit_timestep') expectedTimestep = 3600
    if (mode == 'omit_estuary') expectedEstuary = .true.
    if (mode == 'omit_bank') expectedBank = .true.
    if (mode == 'partial') expectedBank = .false.
    call assertTrue(waterBodyConfig%minStreamSlope == expectedSlope, "Minimum stream slope changed")
    call assertTrue(waterBodyConfig%minEstuaryTimestep == expectedTimestep, "Minimum estuary timestep changed")
    call assertTrue(waterBodyConfig%includeEstuary .eqv. expectedEstuary, "Estuary setting changed")
    call assertTrue(waterBodyConfig%includeBankErosion .eqv. expectedBank, "Bank erosion setting changed")
    call assertTrue(kind(waterBodyConfig%minStreamSlope) == kind(0.0), "Minimum slope changed precision")
    call assertTrue(kind(waterBodyConfig%minEstuaryTimestep) == kind(0), "Estuary timestep changed integer kind")
    call assertTrue(kind(defaultSlope) == dp .and. defaultSlope == 0.0005_dp, "Fallback slope changed")
    call assertTrue(kind(defaultBankErosionAlpha) == dp .and. defaultBankErosionAlpha == 1.0e-9_dp, &
        "Bank erosion alpha fallback changed")
    call assertTrue(kind(defaultBankErosionBeta) == dp .and. defaultBankErosionBeta == 1.0_dp, &
        "Bank erosion beta fallback changed")
    call assertTrue(kind(defaultMinWaterTemperature) == kind(0.0) .and. defaultMinWaterTemperature == 4.0, &
        "Minimum temperature fallback changed")
    call assertTrue(kind(defaultMaxWaterTemperature) == kind(0.0) .and. defaultMaxWaterTemperature == 21.0, &
        "Maximum temperature fallback changed")
    call assertTrue(kind(defaultMinWaterTemperatureDayOfYear) == kind(0) .and. &
        defaultMinWaterTemperatureDayOfYear == 32, "Minimum-temperature day fallback changed")

    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 25, "WaterBody did not add exactly six errors")
    do i = 1, size(codes)
        occurrences = 0
        do j = 1, size(errors)
            if (errors(j)%getCode() == codes(i)) occurrences = occurrences + 1
        end do
        call assertTrue(occurrences == 1, "WaterBody error was not registered exactly once")
        error = ERROR_HANDLER%getErrorFromCode(codes(i))
        call assertTrue(error%message == messages(i), "WaterBody error message changed")
        call assertTrue(error%isCritical .eqv. (codes(i) /= 500), "WaterBody error criticality changed")
    end do
    call assertTrue(.not. ERROR_HANDLER%errorExists(405), "Overwritten code 405 was unexpectedly restored")
    do i = 901, 904
        if (i == 903) cycle
        call assertTrue(ERROR_HANDLER%errorExists(i), "WaterBody registration lost an existing error")
    end do
    call assertTrue(.not. ERROR_HANDLER%errorExists(903), "WaterBody unexpectedly registered the Reactor error")
    call assertTrue(ERROR_HANDLER%errorExists(600), "WaterBody registration lost the Soil error")
    error = ERROR_HANDLER%getErrorFromCode(1)
    call assertTrue(error%message == '' .and. error%isCritical, "Legacy blank error changed")
    error = ERROR_HANDLER%equal(value=1.0, criterion=1.0)
    call assertTrue(error%getCode() == 0, "Shared criteria operations changed")

    if (mode == 'warning' .or. mode == 'quiet_warning') then
        call ERROR_HANDLER%trigger(errors=[ERROR_HANDLER%getErrorFromCode(500)])
    else if (mode == 'critical' .or. mode == 'disabled_error') then
        call ERROR_HANDLER%trigger(errors=[ERROR_HANDLER%getErrorFromCode(401)])
    end if
    print '(a)', 'Completed WaterBody check'

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine

end program WaterBodyConfigModuleTest
