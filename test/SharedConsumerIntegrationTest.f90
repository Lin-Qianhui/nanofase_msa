! Identical reference/candidate probe for input updates and checkpoint state.
program SharedConsumerIntegrationTest
    use KernelModule, only: dp
    use BootstrapModule, only: bootstrap
    use EnvironmentModule, only: Environment
    use ModelConfigModule, only: modelConfig
    use DataInputModule, only: DATASET
    use CheckpointModule, only: Checkpoint
    implicit none

    type(Environment), target :: env
    type(Checkpoint) :: saved
    character(len=64) :: mode
    integer :: k

    ! The first two arguments retain the normal model config/batch convention.
    call get_command_argument(3, mode)
    call bootstrap(env)
    if (index(mode, 'checkpoint') == 1) then
        call saved%init(env, modelConfig%checkpointFile)
        ! Perturb only the in-memory grid; the checkpoint stays unchanged.
        ! Tolerance fixtures contain zero for the first bound and resolution so
        ! tiny differences survive default-real rounding at normal coordinates.
        if (index(mode, 'bounds') > 0 .or. index(mode, 'resolution') > 0) then
            DATASET%gridBounds(1) = 0.0
            DATASET%gridRes(1) = 0.0
        end if
        select case (trim(mode))
        case ('checkpoint_bounds_inside')
            DATASET%gridBounds(1) = real(0.5_dp * modelConfig%epsilon)
        case ('checkpoint_bounds_outside')
            DATASET%gridBounds(1) = real(2.0_dp * modelConfig%epsilon)
        case ('checkpoint_resolution_inside')
            DATASET%gridRes(1) = real(0.5_dp * modelConfig%epsilon)
        case ('checkpoint_resolution_outside')
            DATASET%gridRes(1) = real(2.0_dp * modelConfig%epsilon)
        end select
        call saved%reinstate(preserve_timestep=trim(mode) /= 'checkpoint_reset')
        print '(a,1x,i0)', 'CHECKPOINT_T0', modelConfig%t0
        if (trim(mode) == 'checkpoint_reset') then
            if (modelConfig%t0 /= 1) error stop 'Disabled preservation changed t0'
        else
            if (modelConfig%t0 /= 10) error stop 'Nonzero checkpoint timestep was not restored'
        end if
    else
        do k = 1, modelConfig%nChunks
            if (k > 1) then
                call DATASET%update(k)
                call env%parseNewBatchData()
            end if
            if (size(DATASET%evap, 3) /= modelConfig%nTimeSteps) error stop 'Stale evaporation length'
            if (any(DATASET%evap /= 0.0)) error stop 'Missing evaporation fallback changed'
            print '(a,4(1x,i0),1x,f6.1,1x,a)', 'CHUNK_STATE', k, modelConfig%nTimeSteps, &
                size(DATASET%evap,3), DATASET%nNonMaskedCells, DATASET%shearRate, modelConfig%startDate%isoformat()
            print '(a,1x,a)', 'INPUT_PATH', trim(modelConfig%inputFile)
            print '(a,1x,a)', 'CONSTANTS_PATH', trim(modelConfig%constantsFile)
            print '(a,1x,l1,1x,i0)', 'MASK_STATE', modelConfig%hasSimulationMask, count(DATASET%simulationMask)
        end do
    end if
end program SharedConsumerIntegrationTest
