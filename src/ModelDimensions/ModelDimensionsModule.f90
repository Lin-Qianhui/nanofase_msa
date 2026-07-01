!> Foundation model dimensions shared across science domains.
!!
!! This module owns the model-size state that is assigned from the config file
!! and then used to allocate domain arrays. `GlobalsModule` still mirrors these
!! values into `C` as a compatibility facade during the staged migration, but
!! new code should import dimensions from here when possible.
module ModelDimensionsModule
    implicit none
    private

    public :: initModelDimensions
    public :: nSoilLayers, nSedimentLayers, nSizeClassesSpm, nSizeClassesNM
    public :: nFracCompsSpm, nFormsNM, nExtraStatesNM, npDim
    public :: d_spm, d_spm_low, d_spm_upp, d_nm, sedimentParticleDensities

    ! Config-assigned layer counts used by soil and sediment compartments.
    integer :: nSoilLayers                      !! Number of soil layers to be modelled
    integer :: nSedimentLayers                  !! Number of sediment layers to be modelled

    ! Config-assigned size/state dimensions for SPM and nanomaterial arrays.
    integer :: nSizeClassesSpm                  !! Number of suspended particulate matter size classes
    integer :: nSizeClassesNM                   !! Number of nanomaterial size classes
    integer :: nFracCompsSpm                    !! Number of sediment fractional compositions
    integer :: nFormsNM                         !! Number of NM forms, e.g. pristine or transformed
    integer :: nExtraStatesNM                   !! Number of NM states not represented by SPM heteroaggregation
    integer :: npDim(3)                         !! Default NM array dimensions: size, form, SPM plus extra states

    ! Keep these arrays as default real to preserve the original GlobalsType ABI
    ! and checkpoint/output behaviour during Phase 1.
    real, allocatable :: d_spm(:)                       !! SPM size class diameters [m]
    real, allocatable :: d_spm_low(:)                   !! Lower bound for each SPM size class [m]
    real, allocatable :: d_spm_upp(:)                   !! Upper bound for each SPM size class [m]
    real, allocatable :: d_nm(:)                        !! Nanomaterial size class diameters [m]
    real, allocatable :: sedimentParticleDensities(:)   !! Sediment particle densities [kg m-3]

  contains

    !> Read the model-wide dimensions that size arrays throughout the model.
    !!
    !! The config file is read in three passes because the first namelist gives
    !! the array extents needed before the `nanomaterial` and `sediment`
    !! namelists can be read into allocatable variables.
    subroutine initModelDimensions(configFilePath)
        character(len=*), intent(in) :: configFilePath
        integer :: iou
        integer :: n_soil_layers, n_sediment_layers, n_nm_size_classes, n_spm_size_classes
        integer :: n_fractional_compositions, n_nm_forms, n_nm_extra_states
        logical :: include_bed_sediment
        real, allocatable :: nm_size_classes(:), spm_size_classes(:), sediment_particle_densities(:)
        real, allocatable :: sediment_layer_depth(:)

        namelist /allocatable_array_sizes/ n_soil_layers, n_nm_size_classes, n_spm_size_classes, &
            n_fractional_compositions, n_sediment_layers
        namelist /nanomaterial/ n_nm_forms, n_nm_extra_states, nm_size_classes
        ! `sediment` is group-wide in Fortran namelist input: variables present
        ! in the config must be declared here even when this module only keeps
        ! the model dimensions. `include_bed_sediment` and
        ! `sediment_layer_depth` are therefore local dummies.
        namelist /sediment/ spm_size_classes, include_bed_sediment, sediment_particle_densities, sediment_layer_depth

        call clearModelDimensions()

        open(newunit=iou, file=trim(configFilePath), status="old")

        read(iou, nml=allocatable_array_sizes)
        rewind(iou)

        nSoilLayers = n_soil_layers
        nSedimentLayers = n_sediment_layers
        nSizeClassesNM = n_nm_size_classes
        nSizeClassesSpm = n_spm_size_classes
        nFracCompsSpm = n_fractional_compositions

        ! Allocate local namelist buffers now that their extents are known.
        ! Ownership transfers to module variables below through allocate(source=).
        allocate(nm_size_classes(nSizeClassesNM))
        allocate(spm_size_classes(nSizeClassesSpm))
        allocate(sediment_particle_densities(nFracCompsSpm))
        allocate(sediment_layer_depth(nSedimentLayers))

        read(iou, nml=nanomaterial)
        rewind(iou)
        read(iou, nml=sediment)
        close(iou)

        nFormsNM = n_nm_forms
        nExtraStatesNM = n_nm_extra_states
        allocate(d_nm, source=nm_size_classes)
        allocate(d_spm, source=spm_size_classes)
        allocate(sedimentParticleDensities, source=sediment_particle_densities)

        call deriveSpmBounds()
        npDim = [nSizeClassesNM, nFormsNM, nSizeClassesSpm + nExtraStatesNM]
    end subroutine

    !> Reset all module-owned dimension state before reading a config.
    !!
    !! This keeps repeated calls to `initModelDimensions` deterministic in tests
    !! and batch initialisation paths by avoiding stale allocations and stale
    !! scalar values from a previous config.
    subroutine clearModelDimensions()
        if (allocated(d_spm)) deallocate(d_spm)
        if (allocated(d_spm_low)) deallocate(d_spm_low)
        if (allocated(d_spm_upp)) deallocate(d_spm_upp)
        if (allocated(d_nm)) deallocate(d_nm)
        if (allocated(sedimentParticleDensities)) deallocate(sedimentParticleDensities)

        nSoilLayers = 0
        nSedimentLayers = 0
        nSizeClassesSpm = 0
        nSizeClassesNM = 0
        nFracCompsSpm = 0
        nFormsNM = 0
        nExtraStatesNM = 0
        npDim = 0
    end subroutine

    !> Derive lower and upper SPM size-class bounds from class diameters.
    !!
    !! The historical `GlobalsModule` logic treats neighbouring diameters as
    !! class mid-points. Interior bounds are halfway between adjacent diameters,
    !! the first lower bound is zero, and the final upper bound is one metre.
    subroutine deriveSpmBounds()
        integer :: n

        allocate(d_spm_low(nSizeClassesSpm))
        allocate(d_spm_upp(nSizeClassesSpm))

        do n = 1, nSizeClassesSpm
            if (n == nSizeClassesSpm) then
                d_spm_upp(n) = 1
            else
                d_spm_upp(n) = d_spm(n+1) - (d_spm(n+1)-d_spm(n))/2
            end if
        end do

        do n = 1, nSizeClassesSpm
            if (n == 1) then
                d_spm_low(n) = 0
            else
                d_spm_low(n) = d_spm_upp(n-1)
            end if
        end do
    end subroutine

end module ModelDimensionsModule
