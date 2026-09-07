program BedSedimentConfigModuleTest
    use iso_fortran_env, only: output_unit
    use KernelModule, only: dp
    use ModelDimensionsModule, only: initModelDimensions, nSedimentLayers, nSizeClassesSpm, nFracCompsSpm, &
        npDim, d_spm, d_spm_low, d_spm_upp, sedimentParticleDensities
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    use SoilConfigModule, only: soilConfig
    use BedSedimentConfigModule, only: bedSedimentConfig, defaultDepositionAlpha, defaultDepositionBeta, &
        defaultSedimentTransport_a, defaultSedimentTransport_b, defaultSedimentTransport_c, &
        defaultSedimentEnrichment_k, defaultSedimentEnrichment_a
    implicit none

    character(len=1024) :: dimensionsPath, sedimentPath
    character(len=16) :: mode
    real :: originalSizes(2), originalLow(2), originalUpper(2), originalDensities(4)
    integer :: originalNpDim(3), i, bedErrorCount
    type(ErrorInstance), allocatable :: errors(:)
    type(ErrorInstance) :: error

    call get_command_argument(1, dimensionsPath)
    call get_command_argument(2, mode)
    call get_command_argument(3, sedimentPath)
    call assertTrue(len_trim(dimensionsPath) > 0, "Dimensions fixture path was not provided")
    call assertTrue(len_trim(sedimentPath) > 0, "Sediment fixture path was not provided")
    call assertTrue(mode == 'on' .or. mode == 'off' .or. mode == 'missing', "Unknown test mode")

    call initModelDimensions(trim(dimensionsPath))
    call assertTrue(nSedimentLayers == 3, "Sediment layer count changed")
    call assertTrue(nSizeClassesSpm == 2, "SPM size-class count changed")
    call assertTrue(nFracCompsSpm == 4, "Sediment composition count changed")
    originalSizes = d_spm
    originalLow = d_spm_low
    originalUpper = d_spm_upp
    originalDensities = sedimentParticleDensities
    originalNpDim = npDim

    call initErrorHandling(.true., .true.)
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 24, "Base registry count changed")
    call assertTrue(.not. ERROR_HANDLER%errorExists(904), "Base handler registered code 904")
    call soilConfig%init(trim(dimensionsPath))
    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 25, "Soil registration count changed")

    if (mode == 'missing') then
        print '(a)', 'Reading required BedSediment group'
        flush(output_unit)
        call bedSedimentConfig%init(trim(sedimentPath))
        print '(a)', 'UNEXPECTED_SUCCESS'
        stop
    end if

    call bedSedimentConfig%init(trim(sedimentPath))
    call assertTrue(allocated(bedSedimentConfig%sedimentLayerDepth), "Sediment layer depths were not allocated")
    call assertTrue(size(bedSedimentConfig%sedimentLayerDepth) == 3, "Sediment depth array has the wrong size")
    call assertTrue(kind(bedSedimentConfig%sedimentLayerDepth) == kind(0.0), "Sediment depths changed precision")
    if (mode == 'on') then
        call assertTrue(bedSedimentConfig%includeBedSediment, "Enabled sediment switch was not read")
        call assertTrue(all(bedSedimentConfig%sedimentLayerDepth == [0.01, 0.02, 0.03]), "Enabled depths changed")
    else
        call assertTrue(.not. bedSedimentConfig%includeBedSediment, "Disabled sediment switch was not read")
        call assertTrue(all(bedSedimentConfig%sedimentLayerDepth == [0.04, 0.05, 0.06]), "Disabled depths changed")
    end if

    call assertTrue(nSedimentLayers == 3 .and. nSizeClassesSpm == 2 .and. nFracCompsSpm == 4, &
        "Sediment config changed dimension counts")
    call assertTrue(all(d_spm == originalSizes), "Sediment config overwrote size classes")
    call assertTrue(all(d_spm_low == originalLow) .and. all(d_spm_upp == originalUpper), &
        "Sediment config changed size-class bounds")
    call assertTrue(all(sedimentParticleDensities == originalDensities), "Sediment config overwrote particle densities")
    call assertTrue(all(npDim == originalNpDim), "Sediment config changed nanomaterial dimensions")

    call assertTrue(kind(defaultDepositionAlpha) == dp .and. kind(defaultDepositionBeta) == dp, &
        "Deposition defaults changed precision")
    call assertTrue(kind(defaultSedimentTransport_a) == dp .and. kind(defaultSedimentTransport_b) == dp .and. &
        kind(defaultSedimentTransport_c) == dp, "Transport defaults changed precision")
    call assertTrue(kind(defaultSedimentEnrichment_k) == dp .and. kind(defaultSedimentEnrichment_a) == dp, &
        "Enrichment defaults changed precision")
    call assertTrue(defaultDepositionAlpha == 38.1_dp .and. defaultDepositionBeta == 0.93_dp, &
        "Deposition defaults changed values")
    call assertTrue(defaultSedimentTransport_a == 2.0e-9_dp .and. defaultSedimentTransport_b == 0.0_dp .and. &
        defaultSedimentTransport_c == 0.2_dp, "Transport defaults changed values")
    call assertTrue(defaultSedimentEnrichment_k == 1.0_dp .and. defaultSedimentEnrichment_a == 0.0_dp, &
        "Enrichment defaults changed values")

    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 26, "BedSediment registration did not add exactly one error")
    bedErrorCount = 0
    do i = 1, size(errors)
        if (errors(i)%getCode() == 904) bedErrorCount = bedErrorCount + 1
    end do
    call assertTrue(bedErrorCount == 1, "Code 904 was not registered exactly once")
    error = ERROR_HANDLER%getErrorFromCode(904)
    call assertTrue(trim(error%message) == "Invalid BedSedimentLayer index provided.", "Code 904 message changed")
    call assertTrue(error%isCritical, "Code 904 critical status changed")
    call assertTrue(ERROR_HANDLER%errorExists(600), "BedSediment registration lost the Soil error")
    call assertTrue(ERROR_HANDLER%errorExists(901), "BedSediment registration lost code 901")
    call assertTrue(.not. ERROR_HANDLER%errorExists(405), "BedSediment registration restored missing code 405")

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message

        if (.not. condition) error stop message
    end subroutine

end program BedSedimentConfigModuleTest
