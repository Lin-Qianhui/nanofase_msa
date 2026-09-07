program SoilConfigModuleTest
    use ModelDimensionsModule, only: initModelDimensions, nSoilLayers
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ErrorInstanceModule, only: ErrorInstance
    use SoilConfigModule, only: soilConfig, defaultSoilAttachmentEfficiency, defaultSoilDarcyVelocity
    implicit none

    character(len=1024) :: configFilePath
    type(ErrorInstance), allocatable :: errors(:)
    type(ErrorInstance) :: error
    integer :: configFilePathLength
    integer :: i
    integer :: soilErrorCount

    call get_command_argument(1, configFilePath, configFilePathLength)
    call assertTrue(configFilePathLength > 0, "Soil config fixture path was not provided")

    call initModelDimensions(trim(configFilePath))
    call assertTrue(nSoilLayers == 3, "Soil layer count was not initialised from the fixture")

    call initErrorHandling(.true., .true.)
    call soilConfig%init(trim(configFilePath))

    call assertTrue(allocated(soilConfig%soilLayerDepth), "Soil layer depths were not allocated")
    call assertTrue(size(soilConfig%soilLayerDepth) == 3, "Soil layer depth count changed")
    call assertTrue(all(soilConfig%soilLayerDepth == [0.05, 0.15, 0.20]), &
        "Soil layer depths were not read from the fixture")
    call assertTrue(.not. soilConfig%includeBioturbation, "Required bioturbation setting was not read")
    call assertTrue(soilConfig%includeAttachment, "Required attachment setting was not read")
    call assertTrue(.not. soilConfig%includeClayEnrichment, "Clay enrichment default changed")
    call assertTrue(soilConfig%includeSoilErosion, "Soil erosion default changed")

    call assertTrue(kind(defaultSoilAttachmentEfficiency) == kind(0.0), &
        "Soil attachment efficiency default is no longer default real")
    call assertTrue(kind(defaultSoilDarcyVelocity) == kind(0.0), &
        "Soil Darcy velocity default is no longer default real")
    call assertTrue(defaultSoilAttachmentEfficiency == 0.0, &
        "Soil attachment efficiency default changed")
    call assertTrue(defaultSoilDarcyVelocity == 9e-6, "Soil Darcy velocity default changed")

    errors = ERROR_HANDLER%getErrors()
    call assertTrue(size(errors) == 25, "Soil registration did not add exactly one error")
    call assertTrue(ERROR_HANDLER%errorExists(600), "Soil error code 600 was not registered")

    call assertTrue(.not. ERROR_HANDLER%errorExists(904), "Soil unexpectedly registered the BedSediment error")

    soilErrorCount = 0
    do i = 1, size(errors)
        if (errors(i)%getCode() == 600) soilErrorCount = soilErrorCount + 1
    end do
    call assertTrue(soilErrorCount == 1, "Soil error code 600 was not registered exactly once")

    error = ERROR_HANDLER%getErrorFromCode(600)
    call assertTrue(trim(error%message) == "All water removed from SoilLayer.", &
        "Soil error code 600 message changed")
    call assertTrue(.not. error%isCritical, "Soil error code 600 criticality changed")

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message

        if (.not. condition) error stop message
    end subroutine

end program SoilConfigModuleTest
