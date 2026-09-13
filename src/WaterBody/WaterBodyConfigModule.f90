!> WaterBody settings, fallback constants, and registered errors.
module WaterBodyConfigModule
    use KernelModule, only: dp
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: WaterBodyConfigType, waterBodyConfig
    public :: defaultSlope, defaultBankErosionAlpha, defaultBankErosionBeta
    public :: defaultMinWaterTemperature, defaultMaxWaterTemperature, defaultMinWaterTemperatureDayOfYear

    real, parameter :: defaultMinWaterTemperature = 4.0             ! Thames River
    real, parameter :: defaultMaxWaterTemperature = 21.0            ! Thames River
    integer, parameter :: defaultMinWaterTemperatureDayOfYear = 32  ! Thames River
    real(dp), parameter :: defaultSlope = 0.0005_dp
    real(dp), parameter :: defaultBankErosionAlpha = 1.0e-9_dp      ! [kg/m5] Loosely based on Lazar et al, 2010: https://doi.org/10.1016/j.scitotenv.2010.02.030
    real(dp), parameter :: defaultBankErosionBeta = 1.0_dp          ! [-] Loosely based on Lazar et al, 2010: https://doi.org/10.1016/j.scitotenv.2010.02.030

    type :: WaterBodyConfigType
        real                :: minStreamSlope                   !! Minimum stream slope, imposed where calculated stream slope is less than this value [m/m]
        integer             :: minEstuaryTimestep               !! Minimum timestep (displacement) length for modelling estuarine dynamics [s]
        logical             :: includeEstuary                   !! Should we simulate an estuary, or treat everything as a river?
        logical             :: includeBankErosion               !! Should we simulate the inflow of sediment from bank erosion?
      contains
        procedure :: init => initWaterBodyConfig
    end type

    type(WaterBodyConfigType) :: waterBodyConfig

  contains

    !> Read the optional WaterBody group from the model configuration file.
    subroutine initWaterBodyConfig(me, configFilePath)
        class(WaterBodyConfigType), intent(inout) :: me
        character(len=*), intent(in) :: configFilePath
        integer :: iou
        integer :: nmlIOStat                                ! IO status for namelist reading
        integer :: min_estuary_timestep
        real :: min_stream_slope
        logical :: include_estuary, include_bank_erosion

        ! Domain config namelists still owned by Globals until their domain phases.
        ! Phase 7 note: this group now belongs to WaterBody; the preceding original comment describes its former owner.
        namelist /water/ min_stream_slope, min_estuary_timestep, include_estuary, include_bank_erosion

        ! Phase 7 note: reset local defaults on each call without giving local variables saved state.
        min_stream_slope = 0.0001                  ! [m/m]
        min_estuary_timestep = 3600                  ! 1 hour [s]
        ! Water
        include_estuary = .true.                  ! Should we model estuaries, or treat them as rivers?
        include_bank_erosion = .true.                  ! Should we include the inflow of sediment from bank erosion?

        ! Phase 7 note: preserve the optional group's original two-read error behaviour.
        open(newunit=iou, file=trim(configFilePath), status="old")
        read(iou, nml=water, iostat=nmlIOStat); rewind(iou)
        if (nmlIOStat .ge. 0) read(iou, nml=water); rewind(iou)
        close(iou)

        me%minStreamSlope = min_stream_slope
        me%minEstuaryTimestep = min_estuary_timestep
        me%includeEstuary = include_estuary
        me%includeBankErosion = include_bank_erosion
        call registerWaterBodyErrors()
    end subroutine

    !> Register the six effective WaterBody errors after the shared handler exists.
    subroutine registerWaterBodyErrors()
        type(ErrorInstance) :: errors(6)
        integer :: i

        ! Phase 7 note: retain the historical 405-then-500 overwrite. Restoring 405 is a separate change.
        ! Grid and geography
        errors(1) = ErrorInstance(code=401, &
            message="Invalid RiverReach inflow reference. Inflow must be from a neighbouring RiverReach.")
        errors(2) = ErrorInstance(code=402, &
            message="Invalid RiverReach inflow reference. If multiple inflows are specified, they must " // &
                        "be inflows to the GridCell and all come from the same GridCell.")
        errors(3) = ErrorInstance(code=403, &
            message="RiverReach cannot have more than 5 inflows.")
        errors(4) = ErrorInstance(code=404, &
            message="RiverReach outflow could not be determined. Reaches must either be specified as " // &
                        "inflow to downstream reach, or have a model domain outflow specified.")
        errors(5) = ErrorInstance(code=405, &
            message="RiverReach lengths specified in input data sum to greater than straight-line river branch " // &
                        "length. Are you sure this is intended?", isCritical=.false.)
        ! River routing
        errors(5) = ErrorInstance(code=500, &
            message="All SPM advected from RiverReach.", isCritical=.false.)
        errors(6) = ErrorInstance(code=501, &
            message="No input data provided for required SubRiver - check nSubRivers is correct.")

        do i = 1, size(errors)
            call ERROR_HANDLER%add(error=errors(i))
        end do
    end subroutine

end module WaterBodyConfigModule
