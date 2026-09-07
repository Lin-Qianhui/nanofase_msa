!> Bed-sediment runtime configuration and sediment fallback constants.
module BedSedimentConfigModule
    use KernelModule, only: dp
    use ModelDimensionsModule, only: nSedimentLayers, nSizeClassesSpm, nFracCompsSpm
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorInstanceModule, only: ErrorInstance
    implicit none
    private

    public :: BedSedimentConfigType, bedSedimentConfig
    public :: defaultSedimentTransport_a, defaultSedimentTransport_b, defaultSedimentTransport_c
    public :: defaultSedimentEnrichment_k, defaultSedimentEnrichment_a
    public :: defaultDepositionAlpha, defaultDepositionBeta

    real(dp), parameter :: defaultSedimentTransport_a = 2.0e-9_dp
    real(dp), parameter :: defaultSedimentTransport_b = 0.0_dp
    real(dp), parameter :: defaultSedimentTransport_c = 0.2_dp
    real(dp), parameter :: defaultSedimentEnrichment_k = 1.0_dp
    real(dp), parameter :: defaultSedimentEnrichment_a = 0.0_dp
    real(dp), parameter :: defaultDepositionAlpha = 38.1_dp         ! Zhiyao et al, 2008: https://doi.org/10.1016/S1674-2370(15)30017-X
    real(dp), parameter :: defaultDepositionBeta =  0.93_dp         ! Zhiyao et al, 2008: https://doi.org/10.1016/S1674-2370(15)30017-X

    type :: BedSedimentConfigType
        real, allocatable :: sedimentLayerDepth(:)            !! Sediment layer depth [m]
        logical :: includeBedSediment                         !! Should the bed sediment be included?
      contains
        procedure :: init => initBedSedimentConfig
    end type

    type(BedSedimentConfigType) :: bedSedimentConfig

  contains

    !> Read sediment settings from the model configuration file.
    subroutine initBedSedimentConfig(me, configFilePath)
        class(BedSedimentConfigType), intent(inout) :: me
        character(len=*), intent(in) :: configFilePath
        integer :: iou
        real, allocatable :: spm_size_classes(:), sediment_particle_densities(:), &
            sediment_layer_depth(:)
        logical :: include_bed_sediment

        ! Phase 6 note: a namelist read needs every member of the group. The size
        ! classes and particle densities are temporary buffers here; their stored
        ! values continue to belong to ModelDimensionsModule.
        namelist /sediment/ spm_size_classes, include_bed_sediment, sediment_particle_densities, sediment_layer_depth

        ! Use the allocatable array sizes to allocate those arrays (allocatable arrays
        ! must be allocated before being read in to).
        allocate(sediment_layer_depth(nSedimentLayers))
        allocate(spm_size_classes(nSizeClassesSpm))
        allocate(sediment_particle_densities(nFracCompsSpm))

        ! Phase 6 note: use an available file unit and require the configuration file to exist.
        open(newunit=iou, file=trim(configFilePath), status="old")
        read(iou, nml=sediment)
        close(iou)

        me%sedimentLayerDepth = sediment_layer_depth
        me%includeBedSediment = include_bed_sediment

        call ERROR_HANDLER%add(error=ErrorInstance(code=904, message="Invalid BedSedimentLayer index provided."))
    end subroutine

end module BedSedimentConfigModule
