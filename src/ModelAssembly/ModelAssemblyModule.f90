!> Top-level model assembly for constructing and wiring the live object graph.
module ModelAssemblyModule
    use GlobalsModule, only: ERROR_HANDLER
    use KernelModule, only: COLOR_GREEN, COLOR_RESET
    use LoggerModule, only: LOGR
    use ResultModule, only: Result
    use ErrorInstanceModule, only: ErrorInstance
    use DataInputModule, only: DATASET
    use EnvironmentModule, only: Environment
    use GridCellModule, only: GridCell
    use SoilProfileModule, only: SoilProfile
    use RiverReachModule, only: RiverReach
    use EstuaryReachModule, only: EstuaryReach
    use ReachModule, only: ReachPointer
    implicit none
    private

    public :: buildEnvironment

  contains

    !> Create the `Environment`, which sets up the grid and river structure.
    !! The `Environment` instance must be a target so that `SubRiver` inflows
    !! can point to another `SubRiver` object:
    !! ([see here](https://stackoverflow.com/questions/45761050/pointing-to-a-objects-type-variable-fortran/))
    function buildEnvironment(env) result(r)
        type(Environment), target, intent(inout) :: env
            !! This `Environment` instace. Must be target so children can be pointed at.
        type(Result) :: r                                       !! `Result` object to return any error(s) in
        integer :: x, y                                         ! Iterators

        env%nGridCells = 0
        ! Allocate grid cells array to be the shape of the grid
        allocate(env%colGridCells(DATASET%gridShape(1), DATASET%gridShape(2)))
        ! Loop over grid and create cells
        do y = 1, DATASET%gridShape(2)
            do x = 1, DATASET%gridShape(1)
                allocate(GridCell :: env%colGridCells(x,y)%item)
                select type (cell => env%colGridCells(x,y)%item)
                type is (GridCell)
                    ! If this grid cell isn't masked, create it
                    if (.not. DATASET%gridMask(x,y)) then
                        call r%addErrors(.errors. buildGridCell(cell, x, y))
                        env%nGridCells = env%nGridCells + 1
                    ! If it is masked, still create it but tell it that it's empty
                    else
                        call r%addErrors(.errors. buildGridCell(cell, x, y, isEmpty=.true.))
                    end if
                end select
            end do
        end do

        ! Child creation still preserves the legacy create behaviour: helper
        ! functions log, trigger and clear their own construction errors before
        ! returning, so r only carries errors intentionally left for this level.
        if (.not. r%hasCriticalError()) then
            call wireReachTopology(env)

            ! Finally, perform any creation operations that required proper cell linking (e.g. snapping point sources
            ! to the correct cells)
            do y = 1, DATASET%gridShape(2)
                do x = 1, DATASET%gridShape(1)
                    call env%colGridCells(x,y)%item%finaliseCreate()
                    env%nWaterbodies = env%nWaterbodies + env%colGridCells(x,y)%item%nReaches
                end do
            end do

            ! Allocate the routedReaches to the number of waterbodies, and set the stream order for all the reaches
            allocate(env%routedReaches(env%nWaterbodies))
            call determineStreamOrder(env)

        end if

        ! Environment%create is now only Environment-owned array initialisation.
        ! Keep collecting its Result here for the compatibility create contract.
        call r%addErrors(.errors. env%create())

        call r%addToTrace('Creating the Environment')           ! Add this procedure to the trace
        call LOGR%toFile(errors=.errors.r)
        call ERROR_HANDLER%trigger(errors= .errors. r)          ! Trigger any errors present
        call r%clear()                                          ! Remove any errors so we don't trigger them twice
        call LOGR%toConsole('Creating the Environment: '//COLOR_GREEN//'success'//COLOR_RESET)
    end function

    !> Create the startup-only child objects contained in a GridCell.
    function buildGridCell(cell, x, y, isEmpty) result(rslt)
        class(GridCell), target, intent(inout) :: cell
        integer, intent(in)                    :: x, y
        logical, optional, intent(in)          :: isEmpty
        type(Result)                           :: rslt
        type(SoilProfile)                      :: soilProfile          ! The soil profile contained in this GridCell

        if (present(isEmpty)) then
            call rslt%addErrors(.errors. cell%create(x, y, isEmpty))
        else
            call rslt%addErrors(.errors. cell%create(x, y))
        end if

        ! Only carry on if there's stuff to be simulated for this GridCell
        if (.not. cell%isEmpty) then

            ! If cell not empty, then create just one soil profile
            cell%nSoilProfiles = 1

            ! Parse the input data for this cell
            call cell%parseInputData()

            ! Create two diffuse sources, atmospheric and soil. Water will be
            ! dealt with separately by waterbody classes
            allocate(cell%diffuseSources(2))
            call cell%diffuseSources(1)%create(cell%x, cell%y, 1, 'soil')
            call cell%diffuseSources(2)%create(cell%x, cell%y, 2, 'atmospheric')

            ! Create a soil profile and add to this GridCell
            call rslt%addErrors(.errors. &
                soilProfile%create( &
                    cell%x, &
                    cell%y, &
                    1, &
                    cell%n_river, &
                    cell%area, &
                    cell%q_precip_timeseries, &
                    cell%q_evap_timeseries &
                ) &
            )
            allocate(cell%colsoilprofiles(1)%item, source=soilprofile)
            allocate(cell%distributionsediment, source=cell%colsoilprofiles(1)%item%distributionsediment)

            ! only proceed if there are no critical errors (which might be caused by parseinputdata())
            if (.not. rslt%hascriticalerror()) then
                ! add riverreaches to the gridcell (if any are present in the data file)
                call rslt%adderrors(.errors. createReaches(cell))
            end if
        end if

        call rslt%addToTrace("Creating " // trim(cell%ref))
        call LOGR%toFile(errors = .errors. rslt)
        call ERROR_HANDLER%trigger(errors = .errors. rslt)
        call rslt%clear()                  ! Clear errors from the Result object so they're not reported twice
        if (.not. cell%isEmpty) then
            call LOGR%toConsole(" > Creating " // trim(cell%ref) // ": "//COLOR_GREEN//"success"//COLOR_RESET)
            call LOGR%toFile("Creating " // trim(cell%ref) // ": success")
        else
            call LOGR%toConsole(" > Creating " // trim(cell%ref) // ": "//COLOR_GREEN//"empty"//COLOR_RESET)
            call LOGR%toFile("Creating " // trim(cell%ref) // ": empty")
        end if
    end function

    !> Create the reaches within this grid cell
    function createReaches(cell) result(rslt)
        class(GridCell), target, intent(inout) :: cell    !! This GridCell instance
        type(Result) :: rslt                              !! The Result object to return any errors in
        integer :: i
        ! Loop through waterbodies and create them
        do i = 1, cell%nReaches
            ! What type of waterbody is this?
            if (cell%reachTypes(i) == 'riv') then
                allocate(RiverReach::cell%colRiverReaches(i)%item)
            else if (cell%reachTypes(i) == 'est') then
                allocate(EstuaryReach::cell%colRiverReaches(i)%item)
            else
                call rslt%addError(ErrorInstance( &
                    message="Trying to create waterbody of unknown type " // trim(cell%reachTypes(i)) // "." &
                ))
            end if
            ! Call creation method
            call rslt%addErrors(.errors. &
                cell%colRiverReaches(i)%item%create(cell%x, cell%y, i, cell%distributionSediment) &
            )
        end do
    end function

    subroutine wireReachTopology(env)
        type(Environment), target, intent(inout) :: env
        integer :: x, y, w, i, ix, iy, iw                       ! Iterators
        type(ReachPointer), allocatable :: tmpHeadwaters(:)     ! Temporary headwaters array

        ! Now we need to create links between waterbodies, which wasn't possible before all cells
        ! and their waterbodies were created. We do this by pointing reach%inflows and reach%outflow
        ! to correct waterbody object.
        do y = 1, DATASET%gridShape(2)
            do x = 1, DATASET%gridShape(1)
                if (.not. env%colGridCells(x,y)%item%isEmpty) then
                    do w = 1, env%colGridCells(x,y)%item%nReaches      ! Loop through the reaches
                        associate (reach => env%colGridCells(x,y)%item%colRiverReaches(w)%item)
                            ! Loop through the inflows for this reach
                            do i = 1, reach%nInflows
                                iw = reach%inflowsArr(i,1)
                                ix = reach%inflowsArr(i,2)
                                iy = reach%inflowsArr(i,3)
                                ! We've already checked the inflows are in the model domain, so set this
                                ! reach's inflow to the correct river
                                reach%inflows(i)%item => env%colGridCells(ix,iy)%item%colRiverReaches(iw)%item
                                ! Set the outflow of this reach's inflow to this reach
                                reach%inflows(i)%item%outflow%item => reach
                                ! Check if this reach is a grid cell inflow (and thus the inflow reach is a grid cell outflow)
                                if (ix /= x .or. iy /= y) then
                                    reach%inflows(i)%item%isGridCellOutflow = .true.
                                    reach%isGridCellInflow = .true.
                                end if
                                ! If the inflow is a river and this reach is an estuary, set the estuary to
                                ! be the tidal limit
                                if (reach%ref(1:3) == 'Est' .and. reach%inflows(i)%item%ref(1:3) == 'Riv') then
                                    reach%isTidalLimit = .true.
                                end if
                            end do
                            ! If this is a headwater, add to headwaters array to start routing from
                            if (reach%isHeadwater) then
                                env%nHeadwaters = env%nHeadwaters + 1                 ! Extend nHeadwater by one
                                allocate(tmpHeadwaters(env%nHeadwaters))         ! Move around the allocation to add extra element
                                if (env%nHeadwaters > 1) then
                                    tmpHeadwaters(1:env%nHeadwaters-1) = env%headwaters
                                end if
                                call move_alloc(tmpHeadwaters, env%headwaters)
                                env%headwaters(env%nHeadwaters)%item => &
                                    env%colGridCells(x,y)%item%colRiverReaches(w)%item ! Point to this reach
                            end if
                        end associate
                    end do
                end if
            end do
        end do
    end subroutine

    subroutine determineStreamOrder(env)
        type(Environment), intent(inout) :: env   !! This Environment instance
        integer             :: streamOrder      !! Index to keep track of stream order
        type(ReachPointer)  :: reach            ! Pointer to the reach we're updating
        logical             :: goDownstream     ! Flag to determine whether to go to next downstream reach
        integer             :: i, j, rr, x, y   ! Iterators

        streamOrder = 1
        ! Loop through the headwaters and route from these downstream
        do i = 1, env%nHeadwaters
            reach%item => env%headwaters(i)%item
            ! Add this headwater to the routed reaches array and fill its stream order
            env%routedReaches(streamOrder)%item => reach%item
            reach%item%streamOrder = streamOrder
            reach%item%isUpdated = .true.
            streamOrder = streamOrder + 1
            ! Check this reach has an outflow, before moving on to the outflow and updating that,
            ! and so on downstream until we hit a reach that has inflows that haven't been updated.
            ! If this is the case, we exit the loop and another headwater's downstream routing
            ! will pick up where the current headwater's routing has stopped. We also check that
            ! there is a downstream reach. The goDownstream flag is in charge of telling the loop
            ! whether to proceed or not.
            if (associated(reach%item%outflow%item)) then
                reach%item => reach%item%outflow%item
                goDownstream = .true.
                do while (goDownstream)
                    env%routedReaches(streamOrder)%item => reach%item
                    reach%item%streamOrder = streamOrder
                    reach%item%isUpdated = .true.
                    if (.not. associated(reach%item%outflow%item)) then
                        goDownstream = .false.
                    else
                        ! Point reach to the next downstream reach
                        reach%item => reach%item%outflow%item
                        ! Check all of the next reach's inflows have been updated,
                        ! otherwise the do loop will stop and another headwater's
                        ! downstream routing will pick up where we've left off
                        do j = 1, reach%item%nInflows
                            if (.not. reach%item%inflows(j)%item%isUpdated) then
                                goDownstream = .false.
                            end if
                        end do
                    end if
                    streamOrder = streamOrder + 1
                end do
            end if
        end do
        ! Reset the isUpdated flag
        ! TODO tidy up
        do y = 1, size(env%colGridCells, 2)                             ! Loop through the rows
            do x = 1, size(env%colGridCells, 1)                         ! Loop through the columns
                if (.not. env%colGridCells(x,y)%item%isEmpty) then
                    do rr = 1, env%colGridCells(x,y)%item%nReaches
                        env%colGridCells(x,y)%item%colRiverReaches(rr)%item%isUpdated = .false.
                    end do
                end if
            end do
        end do

    end subroutine

end module ModelAssemblyModule
