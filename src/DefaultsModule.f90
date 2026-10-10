!> The DefaultsModule holds default values used throughout the model, such as those
!! used in input data or config
module DefaultsModule
    use KernelModule, only: dp, iouConfig, iouBatchConfig, iouVersion, iouConstants, &
        iouOutputSummary, iouOutputWater, iouOutputSediment, iouOutputSoil, iouOutputSSD, &
        iouOutputStats, iouCheckpoint, iouLog
    use ModelDefaultsModule, only: ConfigDefaultsType, configDefaults
    implicit none

    ! Double precision reals. Private for the moment as it's also in GlobalsModule
    private :: dp

    ! Phase 10: the original declarations and comments moved to ModelDefaultsModule.
    ! The import exposes the same defaults object for remaining compatibility users.

end module DefaultsModule
