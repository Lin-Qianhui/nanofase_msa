! Test-only state output; production output files and model procedures are unchanged.
program BiotaIntegrationTest
    use KernelModule, only: dp
    use BootstrapModule, only: bootstrap
    use EnvironmentModule, only: Environment
    use ModelConfigModule, only: modelConfig
    use DataInputModule, only: DATASET
    use AbstractBiotaModule, only: AbstractBiota
    implicit none

    type(Environment), target :: env
    integer :: t, k, previous

    ! Arguments 1 and 2 are the normal config and optional batch config paths.
    call bootstrap(env)
    if (modelConfig%runToSteadyState .or. modelConfig%reinstateCheckpoint) &
        error stop 'Biota integration probe supports ordinary and batch runs only'
    call snapshot('created', 1, 0)
    do t = 1, modelConfig%warmUpPeriod
        call env%update(t, t, .true.)
        call snapshot('warmup', 1, t)
    end do
    previous = 0
    do k = 1, modelConfig%nChunks
        if (k > 1) then
            call DATASET%update(k)
            call env%parseNewBatchData()
            call snapshot('batch', k, 0)
        end if
        do t = 1, modelConfig%nTimeSteps
            call env%update(t, t + previous, .false.)
            call snapshot('update', k, t)
        end do
        previous = previous + t - 1
    end do

  contains

    subroutine state(organism, phase, chunk, step, kind, x, y, parent, layer, ordinal)
        class(AbstractBiota), intent(in) :: organism
        character(*), intent(in) :: phase, kind
        integer, intent(in) :: chunk, step, x, y, parent, layer, ordinal
        print '(a,1x,a,2(1x,i0),1x,a,6(1x,i0),2(1x,es26.17e3))', &
            'STATE', phase, chunk, step, kind, x, y, parent, layer, ordinal, organism%biotaIndex, &
            organism%C_active, organism%C_stored
        if (phase == 'created') then
            if (organism%C_active /= DATASET%biotaInitial_C_org(organism%biotaIndex)) &
                error stop 'Integration initial concentration changed'
            if (organism%C_stored /= 0.0_dp) error stop 'Integration stored concentration did not start at zero'
        end if
    end subroutine

    subroutine snapshot(phase, chunk, step)
        character(*), intent(in) :: phase
        integer, intent(in) :: chunk, step
        integer :: x, y, p, l, b, r, soils, rivers, estuaries
        soils = 0
        rivers = 0
        estuaries = 0
        do y = 1, size(env%colGridCells,2)
            do x = 1, size(env%colGridCells,1)
                associate(cell => env%colGridCells(x,y)%item)
                    if (cell%isEmpty) cycle
                    do p = 1, cell%nSoilProfiles
                        associate(profile => cell%colSoilProfiles(p)%item)
                            do l = 1, size(profile%colSoilLayers)
                                associate(layer => profile%colSoilLayers(l)%item)
                                    do b = 1, layer%nBiota
                                        soils = soils + 1
                                        call state(layer%biota(b), phase, chunk, step, 'soil', x, y, p, l, b)
                                    end do
                                end associate
                            end do
                        end associate
                    end do
                    do r = 1, cell%nReaches
                        associate(reach => cell%colRiverReaches(r)%item)
                            do b = 1, reach%nBiota
                                if (cell%reachTypes(r) == 'est') then
                                    estuaries = estuaries + 1
                                else
                                    rivers = rivers + 1
                                end if
                                call state(reach%biota(b), phase, chunk, step, cell%reachTypes(r), x, y, r, 0, b)
                            end do
                        end associate
                    end do
                end associate
            end do
        end do
        print '(a,1x,a,5(1x,i0))', 'COUNTS', phase, chunk, step, soils, rivers, estuaries
    end subroutine
end program BiotaIntegrationTest
