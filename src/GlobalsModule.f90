module GlobalsModule
    use mo_netcdf
    use datetime_module
    use VersionModule, only: MODEL_VERSION
    use KernelModule, only: dp, ESC, COLOR_BLUE, COLOR_LIGHT_BLUE, COLOR_GREEN, &
        COLOR_YELLOW, COLOR_RED, COLOR_RESET, kernel_g => g, kernel_k_B => k_B, &
        kernel_pi => pi, kernel_n_river => n_river, kernel_rho_w => rho_w, &
        kernel_nu_w => nu_w, kernel_mu_w => mu_w
    use DefaultsModule, only: iouConfig, configDefaults
    use ModelDimensionsModule, only: initModelDimensions, dim_nSoilLayers => nSoilLayers, &
        dim_nSedimentLayers => nSedimentLayers, dim_nSizeClassesSpm => nSizeClassesSpm, &
        dim_nSizeClassesNM => nSizeClassesNM, dim_nFracCompsSpm => nFracCompsSpm, &
        dim_nFormsNM => nFormsNM, dim_nExtraStatesNM => nExtraStatesNM, &
        dim_npDim => npDim, dim_d_spm => d_spm, dim_d_spm_low => d_spm_low, &
        dim_d_spm_upp => d_spm_upp, dim_d_nm => d_nm, &
        dim_sedimentParticleDensities => sedimentParticleDensities
    use ModelConfigModule, only: modelConfig
    use ErrorHandlingModule, only: ERROR_HANDLER
    use ErrorCriteriaModule
    use ErrorInstanceModule
    use ResultModule, only: Result
    implicit none

    public :: ERROR_HANDLER

    type, public :: GlobalsType
        ! Get model version from the version module (which our build script should modify)
        character(len=16)   :: modelVersion = MODEL_VERSION

        ! Data input
        character(len=256)  :: inputFile
        character(len=256)  :: constantsFile
        
        ! Data output 
        character(len=256)  :: outputPath                       !! Path to directory to store output data
        character(len=32)   :: outputHash                       !! Hash to append to output file names. Useful for parallel runs.
        logical             :: writeCSV                         !! Should output data be written as CSV file?
        logical             :: writeNetCDF                      !! Should output data be written as NetCDF file?
        character(len=3)    :: netCDFWriteMode                  !! Should NetCDF output be written on each timestep or at the end of the chunk?
        logical             :: writeCompartmentStats            !! Should a file with summary stats for each compartment (soil, water, sediment) be output?
        logical             :: writeMetadataAsComment           !! Should CSV files be prepended with metadata as a #-delimited comment?
        logical             :: includeWaterbodyBreakdown        !! Should the surface water output include breakdown of waterbodies?
        logical             :: includeSedimentLayerBreakdown    !! Include breakdown of data over sediment layers?
        logical             :: includeSoilLayerBreakdown        !! Include breakdown of data over soil layers?
        character(len=5)    :: soilPECUnits                     !! What units to use for soil PEC - kg/m3 or kg/kg dw?
        character(len=5)    :: sedimentPECUnits                 !! What units to use for sediment PEC - kg/m4 or kg/kg dw?
        logical             :: includeSoilStateBreakdown        !! Should the breakdown of NM state (free vs attached) be included?
        logical             :: includeSedimentFluxes            !! Should sediment fluxes to/from waterbodies be included?
        logical             :: includeSpmSizeClassBreakdown     !! Should the breakdown of SPM size classes be included?
        logical             :: includeSoilErosionYields         !! Should sediment fluxes to/from waterbodies be included?

        ! Run
        character(len=256)  :: runDescription                   !! Short description of model run
        character(len=256)  :: logFilePath                      !! Log file path
        logical             :: writeToLog                       !! Should a log file be used?
        character(len=256)  :: configFilePath                   !! Config file path
        type(datetime)      :: startDate                        !! Datetime object representing the start date
        integer             :: timeStep                         !! The timestep to run the model on [s]
        integer             :: nTimeSteps                       !! The number of timesteps
        real(dp)            :: epsilon = 1e-10                  !! Used as proximity to check whether variable as equal
        integer             :: warmUpPeriod                     !! How long before we start inputting NM (to give flows to reach steady state)?
        logical             :: triggerWarnings                  !! Should error warnings be printed to the console?
        logical             :: errorOutput                      !! Should error handling be enabled?
        logical             :: hasSimulationMask = .false.      !! Are we meant to mask the simulation (i.e. only use a subset of the input dataset)?
        character(len=256)  :: simulationMaskPath = ""          !! Path to NetCDF simulation mask
        logical             :: ignoreNM                         !! If .true., miss out costly NM calculations. Useful for sediment calibration, NM PECs will be invalid
        logical             :: bashColors                       !! Should output to the console use ANSI color codes?

        ! Checkpointing
        character(len=256)  :: checkpointFile                   !! Path to checkpoint file, to save to and/or read from
        logical             :: saveCheckpoint                   !! Should a checkpoint be saved when the run finishes?
        logical             :: saveCheckpointAfterWarmUp        !! Should a checkpoint be saved after the warm up period?
        logical             :: reinstateCheckpoint              !! Should a checkpoint be reinstated before the run starts?
        logical             :: preserveTimestep                 !! Should the final timestep from the checkpoint be used to start the reinstated run?

        ! Steady state
        logical             :: runToSteadyState                 !! Should the model be run until steady state by iterating over current simulation input data?
        character(len=50)   :: steadyStateMode                  !! Mode defines what variable will be used to assess steady state
        real(dp)            :: steadyStateDelta                 !! Delta value used to test whether we're at steady state

        ! Compartments
        integer             :: nSoilLayers                      !! Number of soil layers to be modelled
        integer             :: nSedimentLayers                  !! Number of sediment layers to be modelled
        real                :: minStreamSlope                   !! Minimum stream slope, imposed where calculated stream slope is less than this value [m/m]
        integer             :: minEstuaryTimestep               !! Minimum timestep (displacement) length for modelling estuarine dynamics [s]
        logical             :: includeEstuary                   !! Should we simulate an estuary, or treat everything as a river?
        logical             :: includeBankErosion               !! Should we simulate the inflow of sediment from bank erosion?

        ! Batch run
        integer                         :: nChunks = 1          !! Numbers of chunks to run
        logical                         :: isBatchRun = .false. !! Are we batch running?
        character(len=256), allocatable :: batchInputFiles(:)   !! Paths to input files for each chunk
        character(len=256), allocatable :: batchConstantFiles(:) !! Paths to constants files for each chunk
        type(datetime), allocatable     :: batchStartDates(:)   !! Start dates for each chunk
        integer, allocatable            :: batchNTimesteps(:)   !! Number of timesteps for each chunk
        character(len=256), allocatable :: batchConfigFiles(:)  !! Paths to config files for batches
        integer                         :: nTimestepsInBatch    !! Total number of timesteps in batch run
        type(datetime)                  :: batchStartDate       !! Start date of batch run
        type(datetime)                  :: batchEndDate         !! End date of batch run

        ! Checkpointing
        integer                         :: t0 = 1               !! Used to preserve timestep between checkpoints. Timestep number at start of run

        ! General
        type(NcDataset) :: dataset                          !! The NetCDF dataset

        ! Physical constants
        real(dp) :: g = kernel_g            !! Gravitational acceleration [m/s^2]
        real(dp) :: k_B = kernel_k_B        !! Boltzmann constant [m2 kg s-2 K-1]
        real(dp) :: pi = kernel_pi          !! Pi [-]
        real(dp) :: n_river = kernel_n_river !! Manning's roughness coefficient, for natural streams and major rivers.
                                            !! [Reference](http://www.engineeringtoolbox.com/mannings-roughness-d_799.html).

        ! Temp
        real(dp) :: T = 15.0_dp             !! Temperature [C]

        ! Size class distributions
        real, allocatable :: d_spm(:)                       !! Suspended particulate matter size class diameters [m]
        real, allocatable :: d_spm_low(:)                   !! Lower bound when treating each size class as distribution [m]
        real, allocatable :: d_spm_upp(:)                   !! Upper bound when treating each size class as distribution [m]
        real, allocatable :: d_nm(:)                        !! Nanomaterial size class diameters [m]
        real, allocatable :: sedimentParticleDensities(:)   !! Sediment particle densities [kg m-3]
        integer :: nSizeClassesSpm                          !! Number of sediment particle size classes
        integer :: nSizeClassesNM                           !! Number of nanoparticle size classes
        integer :: nFracCompsSpm                            !! Number of sediment fractional compositions
        integer :: nFormsNM                                 !! Number of NM forms (e.g. pristine, transformed, etc)
        integer :: nExtraStatesNM                           !! Number of NM states other than heteroaggregated to SPM
        integer, allocatable :: defaultDistributionSediment(:) !! Default imposed size distribution for sediment
        integer, allocatable :: defaultDistributionNP(:)    !! Default imposed size distribution for NPs
        integer :: npDim(3)                                 !! Default dimensions for arrays of NM
        integer :: ionicDim                                 !! Default dimensions for ionic metal

      contains
        procedure :: rho_w      ! Density of water
        procedure :: nu_w       ! Kinematic viscosity of water
        procedure :: mu_w       ! Dynamic viscosity of water
    end type

    type(GlobalsType) :: C

  contains

    !> Copy runtime-mutated model-config values into the compatibility facade.
    subroutine syncRuntimeModelConfigToGlobals()
        C%inputFile = modelConfig%inputFile
        C%constantsFile = modelConfig%constantsFile
        C%nTimeSteps = modelConfig%nTimeSteps
        C%startDate = modelConfig%startDate
        C%t0 = modelConfig%t0
    end subroutine

    !> Calculate the density of water at a given temperature \( T \):
    !! $$
    !!      \rho_{\text{w}}(T) = 1000 \left( 1 - \frac{T + 288.9414}{508929.2 (T + 68.12963) (T - 3.9863^2)} \right)
    !! $$
    !! and optionally with a given salinity \( S \):
    !! $$
    !!      \rho_{\text{w,s}}(T,S) = \rho_w + AS + BS^{3/2} + CS^2
    !! $$
    !! where \( A = 0.824493 - 0.0040899T + 0.000076438T^2 -0.00000082467T^3 + 0.0000000053675T^4 \),
    !! \( B = -0.005724 + 0.00010227T - 0.0000016546T^2 \) and \( C = 4.8314 \times 10^{-4} \).
    !! Reference:
    !! [D. R. Maidment, Handbook of Hydrology (2012)](https://books.google.co.uk/books/about/Handbook_of_hydrology.html?id=4_9OAAAAMAAJ)
    function rho_w(me, T, S)
        class(GlobalsType), intent(in) :: me                    !! This `Constants` instance
        real, intent(in) :: T                                   !! Temperature \( T \) [deg C]
        real(dp), intent(in), optional :: S                     !! Salinity \( S \) [g/kg]
        real(dp) :: rho_w                                       !! Density of water \( \rho_w \) [kg/m**3].
        if (present(S)) then
            rho_w = kernel_rho_w(T, S)
        else
            rho_w = kernel_rho_w(T)
        end if
    end function

    !> Calculate the kinematic viscosity of water \( \nu_w \) at given temperature \( T \)
    !! and optionally salinity \( S \):
    !! $$
    !!      \nu_{\text{w}}(T,S) = \frac{1}{\rho_w(T,S)} 2.414\times 10^{-5} \cdot 10^{\frac{247.8}{(T+273.15)-140.0}}
    !! $$
    !! Reference: [T. Al-Shemmeri](http://varunkamboj.typepad.com/files/engineering-fluid-mechanics-1.pdf)
    function nu_w(me, T, S)
        class(GlobalsType), intent(in) :: me                    !! This Globals instance
        real, intent(in) :: T                                   !! Temperature \( T \) [deg C]
        real(dp), intent(in), optional :: S                     !! Salinity \( S \) [g/kg]
        real(dp) :: nu_w                                        !! Kinematic viscosity of water \( \nu_{\text{w}} \)
        if (present(S)) then
            nu_w = kernel_nu_w(T, S)
        else
            nu_w = kernel_nu_w(T)
        end if
    end function
    
    !> Calculate the dynamic viscosity of water \( \mu_w \) at a given temperature \( T \)
    !! $$
    !!      \nu_{\text{w}}(T,S) = 2.414\times 10^{-5} \cdot 10^{\frac{247.8}{(T+273.15)-140.0}}
    !! $$
    !! Reference: [T. Al-Shemmeri](http://varunkamboj.typepad.com/files/engineering-fluid-mechanics-1.pdf)
    function mu_w(me, T)
        class(GlobalsType), intent(in) :: me
        real, intent(in) :: T
        real(dp) :: mu_w
        mu_w = kernel_mu_w(T)
    end function
end module GlobalsModule
