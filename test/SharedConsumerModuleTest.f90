! These checks initialise the owning modules without writing the old C object.
program SharedConsumerModuleTest
    use KernelModule, only: dp, COLOR_GREEN
    use ModelDefaultsModule, only: configDefaults, ConfigDefaultsType
    use DefaultsModule, only: legacyDefaults => configDefaults
    use ModelConfigModule, only: modelConfig
    use ModelDimensionsModule, only: npDim, nSizeClassesNM, nSizeClassesSpm
    use UtilModule, only: isZero, isLessThanZero, divideCheckZero, flushToZero, &
        freeNM, attachedNM, heteroaggregatedNM
    use LoggerModule, only: Logger
    use AbstractGridCellModule, only: AbstractGridCell
    use GridCellModule, only: GridCell
    implicit none

    type(ConfigDefaultsType) :: originalDefaults
    type(Logger) :: output
    class(AbstractGridCell), allocatable :: cell
    character(len=1024) :: explicitPath, omittedPath
    real(dp) :: values(7), cube(1,1,1), e
    real(dp), allocatable :: mass(:,:,:), result(:)
    logical :: scalarExpected(7), arrayExpected(7), negativeExpected(7)
    integer :: i, n

    call get_command_argument(1, explicitPath)
    call get_command_argument(2, omittedPath)

    ! Compatibility exports must refer to the same object, not copied defaults.
    configDefaults%epsilon = 0.125_dp
    call require(legacyDefaults%epsilon == 0.125_dp, 'Defaults compatibility export is a copy')
    legacyDefaults%epsilon = originalDefaults%epsilon
    call require(configDefaults%epsilon == originalDefaults%epsilon, 'Defaults alias did not write the owner')

    call modelConfig%init(trim(explicitPath))
    call require(modelConfig%epsilon == 0.125_dp .and. modelConfig%timeStep == 43200, 'Explicit run values')
    call require(modelConfig%saveCheckpoint .and. modelConfig%reinstateCheckpoint, 'Explicit checkpoint values')
    call require(modelConfig%hasSimulationMask .and. modelConfig%ignoreNM, 'Explicit mask and ignore controls')
    call require(modelConfig%writeNetCDF .and. .not. modelConfig%writeCSV, 'Explicit output selection')
    call require(modelConfig%netCDFWriteMode == 'itr', 'Explicit NetCDF mode')
    call require(modelConfig%soilPECUnits == 'kg/m3' .and. modelConfig%sedimentPECUnits == 'kg/m3', 'Explicit units')
    call require(modelConfig%outputHash == '_test' .and. modelConfig%runToSteadyState, 'Explicit hash and steady state')
    call modelConfig%setT0(9)
    call modelConfig%init(trim(omittedPath))
    call defaults()
    call modelConfig%init(trim(explicitPath))
    call modelConfig%init(trim(omittedPath))
    call defaults()

    ! Binary fractions make equality-at-tolerance independent of decimal rounding.
    modelConfig%epsilon = 0.25_dp
    e = modelConfig%epsilon
    values = [-0.5_dp, -0.25_dp, -0.125_dp, 0.0_dp, 0.125_dp, 0.25_dp, 0.5_dp]
    scalarExpected = [.false., .false., .true., .true., .true., .false., .false.]
    arrayExpected = [.false., .true., .true., .true., .true., .true., .false.]
    negativeExpected = [.true., .true., .false., .false., .false., .false., .false.]
    do i = 1, size(values)
        call require(isZero(values(i)) .eqv. scalarExpected(i), 'Double scalar zero boundary')
        call require(isZero(real(values(i))) .eqv. scalarExpected(i), 'Default-real zero boundary')
        cube = values(i)
        call require(isZero(cube) .eqv. arrayExpected(i), 'Array zero boundary')
        call require(isLessThanZero(values(i)) .eqv. negativeExpected(i), 'Double negative boundary')
        call require(isLessThanZero(real(values(i))) .eqv. negativeExpected(i), 'Default-real negative boundary')
        call require(flushToZero(values(i)) == merge(0.0_dp, values(i), scalarExpected(i)), 'Double flush')
        call require(flushToZero(real(values(i))) == real(merge(0.0_dp, values(i), scalarExpected(i))), 'Real flush')
    end do
    call require(.not. isZero(0.125_dp, epsilon=0.0625_dp), 'Explicit double tolerance')
    call require(.not. isZero(0.125, epsilon=0.0625_dp), 'Explicit real tolerance')
    cube = 0.125_dp
    call require(.not. isZero(cube, epsilon=0.0625_dp), 'Explicit array tolerance')
    call require(isLessThanZero(-0.125_dp, epsilon=0.0625_dp), 'Explicit negative tolerance')
    call require(isLessThanZero(-0.125, epsilon=0.0625_dp), 'Explicit real negative tolerance')
    call require(divideCheckZero(1.0_dp, 0.0_dp) == 0.0_dp, 'Double zero denominator')
    call require(divideCheckZero(0.0, 1.0) == 0.0, 'Real zero numerator')
    call require(divideCheckZero(0.125_dp, 1.0_dp) == 0.0_dp, 'Small numerator')
    call require(divideCheckZero(1.0, 0.125) == 0.0, 'Small real denominator')
    call require(divideCheckZero(0.5_dp, 0.25_dp) == 2.0_dp, 'Boundary denominator')
    call require(divideCheckZero(0.5, 0.25) == 2.0, 'Real boundary denominator')
    call require(divideCheckZero(1.0_dp, 0) == 0.0_dp, 'Integer zero denominator')
    call require(divideCheckZero(1.0, 0) == 0.0, 'Real/integer zero denominator')
    call require(divideCheckZero(1.0_dp, 2) == 0.5_dp, 'Double/integer division')
    call require(divideCheckZero(1.0, 2) == 0.5, 'Real/integer division')
    modelConfig%epsilon = 0.0625_dp
    call require(.not. isZero(0.125_dp), 'Utility cached an earlier tolerance')
    call require(flushToZero(0.125_dp) == 0.125_dp, 'Flush cached an earlier tolerance')

    allocate(GridCell :: cell)
    cell%nReaches = 0
    do n = 1, 3, 2
        nSizeClassesNM = n
        nSizeClassesSpm = n
        npDim = [n,1,n+2]
        allocate(mass(n,1,n+2))
        do i = 1, n+2
            mass(:,1,i) = real(i,dp)
        end do
        call require(size(freeNM(mass)) == n .and. all(freeNM(mass) == 1.0_dp), 'Free NM owner dimensions')
        call require(all(attachedNM(mass) == 2.0_dp), 'Attached NM owner dimensions')
        ! The existing utility sums across particle sizes (dim=1), not states.
        ! Preserve that behavior here; correcting the science is separate work.
        call require(all(heteroaggregatedNM(mass) == [(real(n*i,dp), i=3,n+2)]), 'Aggregated NM owner dimensions')
        result = cell%get_m_spm()
        call require(size(result) == n .and. all(result == 0.0_dp), 'Abstract GridCell result dimensions')
        result = cell%get_j_spm_outflow()
        call require(size(result) == n .and. all(result == 0.0_dp), 'Abstract GridCell outflow dimensions')
        deallocate(mass)
    end do

    ! The CMake wrapper checks the exact color prefix and retained reset sequence.
    modelConfig%bashColors = .true.
    call output%add('LOGGER_OWNER_ON', COLOR_GREEN)
    modelConfig%bashColors = .false.
    call output%add('LOGGER_OWNER_OFF', COLOR_GREEN)
    print *, 'Shared consumer owner checks passed'

  contains

    subroutine require(condition, message)
        logical, intent(in) :: condition
        character(*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine

    subroutine defaults()
        call require(modelConfig%epsilon == 1e-10_dp, 'Default epsilon')
        call require(modelConfig%timeStep == 86400 .and. modelConfig%nTimeSteps == 10, 'Required timing')
        call require(modelConfig%runDescription == 'NanoFASE model run', 'Default description')
        call require(modelConfig%writeToLog .and. modelConfig%bashColors, 'Default log controls')
        call require(.not. modelConfig%triggerWarnings .and. modelConfig%errorOutput, 'Default error controls')
        call require(modelConfig%warmUpPeriod == 0 .and. .not. modelConfig%ignoreNM, 'Default run switches')
        call require(.not. modelConfig%hasSimulationMask .and. modelConfig%simulationMaskPath == '', 'Default mask')
        call require(modelConfig%outputHash == '', 'Default hash')
        call require(modelConfig%writeCSV .and. .not. modelConfig%writeNetCDF, 'Default output selection')
        call require(modelConfig%netCDFWriteMode == 'end', 'Default NetCDF mode')
        call require(modelConfig%writeMetadataAsComment .and. .not. modelConfig%writeCompartmentStats, 'Default metadata')
        call require(modelConfig%includeWaterbodyBreakdown, 'Default waterbody breakdown')
        call require(modelConfig%includeSedimentLayerBreakdown .and. modelConfig%includeSoilLayerBreakdown, 'Default layers')
        call require(.not. modelConfig%includeSedimentFluxes .and. .not. modelConfig%includeSoilErosionYields, 'Default fluxes')
        call require(.not. modelConfig%includeSoilStateBreakdown .and. &
            .not. modelConfig%includeSpmSizeClassBreakdown, 'Default state breakdown')
        call require(modelConfig%soilPECUnits == 'kg/kg' .and. modelConfig%sedimentPECUnits == 'kg/kg', 'Default units')
        call require(.not. modelConfig%saveCheckpoint .and. .not. modelConfig%saveCheckpointAfterWarmUp, 'Default save')
        call require(.not. modelConfig%reinstateCheckpoint .and. .not. modelConfig%preserveTimestep, 'Default restore')
        call require(modelConfig%checkpointFile == './checkpoint.dat' .and. modelConfig%t0 == 1, 'Default checkpoint state')
        call require(.not. modelConfig%runToSteadyState, 'Default steady state')
        call require(modelConfig%steadyStateMode == 'sediment_size_distribution', 'Default steady mode')
        ! Preserve the default-real literal converted to double precision.
        call require(modelConfig%steadyStateDelta == real(1e-5,dp), 'Default steady delta precision')
        call require(.not. modelConfig%isBatchRun .and. modelConfig%nChunks == 1, 'Default batch controls')
        call require(modelConfig%nTimestepsInBatch == 10 .and. size(modelConfig%batchNTimesteps) == 1, 'Single-run counts')
        call require(.not. allocated(modelConfig%batchInputFiles), 'Stale batch inputs')
        call require(.not. allocated(modelConfig%batchConfigFiles), 'Unused batch configs became allocated')
    end subroutine
end program SharedConsumerModuleTest
