program WaterBodySlopeTest
    use KernelModule, only: dp
    use WaterBodyConfigModule, only: waterBodyConfig, defaultSlope
    use ErrorHandlingModule, only: initErrorHandling
    use DataInputModule, only: DATASET
    use RiverReachModule, only: RiverReach
    implicit none

    type(RiverReach) :: reach
    character(len=1024) :: configPath

    call get_command_argument(1, configPath)
    call initErrorHandling(.true., .true.)
    call waterBodyConfig%init(trim(configPath))
    allocate(DATASET%gridRes(2), DATASET%dem(3,3))
    DATASET%gridRes = [1000.0, 1000.0]
    DATASET%dem = 100
    reach%isHeadwater = .true.
    reach%x = 2
    reach%y = 2
    reach%outflowArr = [1, 3, 2]

    ! The neighbour lies inside the terrain array, avoiding the separate outlet defect.
    call reach%setReachLengthAndSlope()
    if (reach%length /= 500.0_dp) error stop 'Interior headwater length changed'
    if (reach%slope /= real(waterBodyConfig%minStreamSlope, dp)) error stop 'Flat terrain minimum changed'
    DATASET%dem(2,2) = 10100
    call reach%setReachLengthAndSlope()
    if (reach%slope /= 2.0_dp) error stop 'Slope above the minimum changed'
    DATASET%dem(2,2) = 0
    call reach%setReachLengthAndSlope()
    if (reach%slope /= real(waterBodyConfig%minStreamSlope, dp)) error stop 'Uphill terrain minimum changed'

    ! Also cover the non-headwater geometry, which reads its first inflow neighbour.
    reach%isHeadwater = .false.
    allocate(reach%inflowsArr(1,3))
    reach%inflowsArr(1,:) = [1, 1, 2]
    DATASET%dem = 100
    call reach%setReachLengthAndSlope()
    if (reach%length /= 1000.0_dp) error stop 'Interior reach length changed'
    if (reach%slope /= real(waterBodyConfig%minStreamSlope, dp)) error stop 'Interior reach minimum changed'
    deallocate(DATASET%dem)
    call reach%setReachLengthAndSlope()
    if (reach%slope /= defaultSlope) error stop 'Missing-terrain fallback changed'
end program WaterBodySlopeTest
