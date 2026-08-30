!> Soil-domain runtime configuration and fallback constants.
module SoilConfigModule
    use KernelModule, only: dp
    use ModelDimensionsModule, only: nSoilLayers
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: SoilConfigType, soilConfig
    public :: defaultSoilAttachmentEfficiency, defaultSoilDarcyVelocity

    ! Soil
    real, parameter :: defaultSoilAttachmentEfficiency = 0.0
    real, parameter :: defaultSoilDarcyVelocity = 9e-6_dp           ! [m/s] Tufenkji et al, 2004: https://doi.org/10.1021/es034049r 

    type :: SoilConfigType
        real, allocatable :: soilLayerDepth(:)                !! Soil layer depth [m]
        logical           :: includeBioturbation              !! Should bioturbation be modelled?
        logical           :: includeAttachment                !! Should attachment to soil be included?
        logical           :: includeSoilErosion               !! Should soil erosion be included?
        logical           :: includeClayEnrichment            !! Should clay enrichment be included?
      contains
        procedure :: init => initSoilConfig
    end type

    type(SoilConfigType) :: soilConfig

  contains

    !> Read Soil settings from the model configuration file.
    subroutine initSoilConfig(me, configFilePath)
        class(SoilConfigType), intent(inout) :: me
        character(len=*), intent(in) :: configFilePath
        integer :: iou
        real, allocatable :: soil_layer_depth(:)
        logical :: include_bioturbation, include_attachment, include_clay_enrichment, &
            include_soil_erosion

        namelist /soil/ soil_layer_depth, include_bioturbation, include_attachment, &
            include_clay_enrichment, include_soil_erosion

        include_clay_enrichment = .false.
        include_soil_erosion = .true.              ! Should we model soil erosion?

        allocate(soil_layer_depth(nSoilLayers))
        ! Phase 5 note (not an original comment): use an available file unit and require the config file to already exist.
        open(newunit=iou, file=trim(configFilePath), status="old")
        read(iou, nml=soil)
        close(iou)

        me%soilLayerDepth = soil_layer_depth
        me%includeBioturbation = include_bioturbation
        me%includeAttachment = include_attachment
        me%includeClayEnrichment = include_clay_enrichment
        me%includeSoilErosion = include_soil_erosion

        ! Soil
        call ERROR_HANDLER%add(error=ErrorInstance(code=600, &
            message="All water removed from SoilLayer.", isCritical=.false.))
    end subroutine

end module SoilConfigModule
