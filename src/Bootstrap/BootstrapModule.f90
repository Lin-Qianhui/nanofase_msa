!> Top-level model startup orchestration.
module BootstrapModule
    use DefaultsModule, only: iouConfig, configDefaults
    use KernelModule, only: iouLog
    use ModelDimensionsModule, only: initModelDimensions, dim_nSoilLayers => nSoilLayers, &
        dim_nSedimentLayers => nSedimentLayers, dim_nSizeClassesSpm => nSizeClassesSpm, &
        dim_nSizeClassesNM => nSizeClassesNM, dim_nFracCompsSpm => nFracCompsSpm, &
        dim_nFormsNM => nFormsNM, dim_nExtraStatesNM => nExtraStatesNM, &
        dim_npDim => npDim, dim_d_spm => d_spm, dim_d_spm_low => d_spm_low, &
        dim_d_spm_upp => d_spm_upp, dim_d_nm => d_nm, &
        dim_sedimentParticleDensities => sedimentParticleDensities
    use ModelConfigModule, only: modelConfig
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ResultModule, only: Result
    use GlobalsModule, only: C
    use SourceConfigModule, only: sourceConfig
    use LoggerModule, only: LOGR
    use UtilModule, only: printWelcome
    use DataInputModule, only: DATASET
    use EnvironmentModule, only: Environment
    use ModelAssemblyModule, only: buildEnvironment
    implicit none
    private

    public :: bootstrap

  contains

    !> Initialise global variables, such as `ERROR_HANDLER`
    !! Initialise model configuration, diagnostics, data and the live object graph.
    subroutine bootstrap(env)
        type(Environment), target, intent(inout) :: env
        type(Result) :: auditResult                         ! Model-config audit result
        type(Result) :: rslt                                !! Result object
        character(len=256) :: configFilePath, batchRunFilePath
        integer :: configFilePathLength, batchRunFilePathLength

        ! Has a path to the config path been provided as a command line argument?
        call get_command_argument(1, configFilePath, configFilePathLength)
        call get_command_argument(2, batchRunFilePath, batchRunFilePathLength)

        ! Resolve the config file, or try and find one at config/config.nml if it can't be found.
        if (configFilePathLength <= 0) configFilePath = "config/config.nml"

        call initModelDimensions(trim(configFilePath))
        if (batchRunFilePathLength > 0) then
            call modelConfig%init(trim(configFilePath), trim(batchRunFilePath))
        else
            call modelConfig%init(trim(configFilePath))
        end if

        call initErrorHandling(modelConfig%triggerWarnings, modelConfig%errorOutput)

        call initLegacyGlobalsFacade(trim(configFilePath))

        ! Auditing the config. Must be done after error handler has been initialised.
        auditResult = modelConfig%audit()
        call ERROR_HANDLER%trigger(errors=.errors.auditResult)

        ! Initialise source-domain config during the staged bootstrap migration
        call sourceConfig%init(modelConfig%configFilePath)
        ! Initialise the logger
        call LOGR%init( &
            logToFile=modelConfig%writeToLog, &
            logToConsole=.true., &
            logFilePath=modelConfig%logFilePath, &
            fileUnit=iouLog &
        )

        ! Welcome, good to have you here!
        call printWelcome()

        ! Load the input data
        call DATASET%init(modelConfig%inputFile, modelConfig%constantsFile)

        ! Create the Environment object and deal with any errors that arise
        rslt = buildEnvironment(env)
        call LOGR%toFile(errors=.errors.rslt)
        call ERROR_HANDLER%trigger(errors=.errors.rslt)
    end subroutine

    !> Populate the compatibility facade and read config for domains that have
    !! not yet taken ownership of their namelist groups.
    subroutine initLegacyGlobalsFacade(configFilePath)
        character(len=*), intent(in) :: configFilePath
        integer :: nmlIOStat                                ! IO status for namelist reading
        integer :: min_estuary_timestep
        real :: min_stream_slope
        real, allocatable :: soil_layer_depth(:), spm_size_classes(:), &
            sediment_particle_densities(:), sediment_layer_depth(:)
        logical :: include_bioturbation, include_attachment, include_bed_sediment, &
            include_clay_enrichment, include_estuary, include_bank_erosion, include_soil_erosion

        ! Domain config namelists still owned by Globals until their domain phases.
        namelist /soil/ soil_layer_depth, include_bioturbation, include_attachment, include_clay_enrichment, include_soil_erosion
        namelist /sediment/ spm_size_classes, include_bed_sediment, sediment_particle_densities, sediment_layer_depth
        namelist /water/ min_stream_slope, min_estuary_timestep, include_estuary, include_bank_erosion

        include_clay_enrichment = configDefaults%includeClayEnrichment
        min_stream_slope = configDefaults%minStreamSlope
        min_estuary_timestep = configDefaults%minEstuaryTimestep
        include_estuary = configDefaults%includeEstuary
        include_bank_erosion = configDefaults%includeBankErosion
        include_soil_erosion = configDefaults%includeSoilErosion

        call syncModelConfigToGlobals()

        open(iouConfig, file=trim(configFilePath), status="old")

        ! Use the allocatable array sizes to allocate those arrays (allocatable arrays
        ! must be allocated before being read in to).
        allocate(soil_layer_depth(dim_nSoilLayers))
        allocate(sediment_layer_depth(dim_nSedimentLayers))
        allocate(spm_size_classes(dim_nSizeClassesSpm))
        allocate(sediment_particle_densities(dim_nFracCompsSpm))

        read(iouConfig, nml=soil); rewind(iouConfig)
        read(iouConfig, nml=sediment); rewind(iouConfig)
        read(iouConfig, nml=water, iostat=nmlIOStat); rewind(iouConfig)
        if (nmlIOStat .ge. 0) read(iouConfig, nml=water); rewind(iouConfig)
        close(iouConfig)

        ! Store dimension and domain data in the Globals facade.
        C%nSizeClassesNM = dim_nSizeClassesNM
        C%nFormsNM = dim_nFormsNM
        C%nExtraStatesNM = dim_nExtraStatesNM
        if (allocated(C%d_nm)) deallocate(C%d_nm)
        allocate(C%d_nm, source=dim_d_nm)

        C%sedimentLayerDepth = sediment_layer_depth
        C%nSizeClassesSpm = dim_nSizeClassesSpm
        C%includeBedSediment = include_bed_sediment
        C%nSedimentLayers = dim_nSedimentLayers
        if (allocated(C%d_spm)) deallocate(C%d_spm)
        allocate(C%d_spm, source=dim_d_spm)
        C%nFracCompsSpm = dim_nFracCompsSpm
        if (allocated(C%sedimentParticleDensities)) deallocate(C%sedimentParticleDensities)
        allocate(C%sedimentParticleDensities, source=dim_sedimentParticleDensities)

        C%nSoilLayers = dim_nSoilLayers
        C%soilLayerDepth = soil_layer_depth
        C%includeBioturbation = include_bioturbation
        C%includeAttachment = include_attachment
        C%includeClayEnrichment = include_clay_enrichment
        C%includeSoilErosion = include_soil_erosion

        C%minStreamSlope = min_stream_slope
        C%minEstuaryTimestep = min_estuary_timestep
        C%includeEstuary = include_estuary
        C%includeBankErosion = include_bank_erosion

        if (allocated(C%d_spm_low)) deallocate(C%d_spm_low)
        if (allocated(C%d_spm_upp)) deallocate(C%d_spm_upp)
        allocate(C%d_spm_low, source=dim_d_spm_low)
        allocate(C%d_spm_upp, source=dim_d_spm_upp)

        ! Array to store default NM and ionic array dimensions. NM:
        !   1: NP size class
        !   2: form (core, shell, coating, corona)
        !   3: state (free, bound, heteroaggregated)
        ! Ionic: Form (free ion, solution, adsorbed)
        C%npDim = dim_npDim
    end subroutine

    !> Copy all model-level config values into the compatibility facade.
    subroutine syncModelConfigToGlobals()
        C%modelVersion = modelConfig%modelVersion

        C%inputFile = modelConfig%inputFile
        C%constantsFile = modelConfig%constantsFile
        C%outputPath = modelConfig%outputPath
        C%outputHash = modelConfig%outputHash

        C%writeCSV = modelConfig%writeCSV
        C%writeNetCDF = modelConfig%writeNetCDF
        C%netCDFWriteMode = modelConfig%netCDFWriteMode
        C%writeMetadataAsComment = modelConfig%writeMetadataAsComment
        C%writeCompartmentStats = modelConfig%writeCompartmentStats
        C%includeWaterbodyBreakdown = modelConfig%includeWaterbodyBreakdown
        C%includeSedimentLayerBreakdown = modelConfig%includeSedimentLayerBreakdown
        C%includeSoilLayerBreakdown = modelConfig%includeSoilLayerBreakdown
        C%soilPECUnits = modelConfig%soilPECUnits
        C%sedimentPECUnits = modelConfig%sedimentPECUnits
        C%includeSoilStateBreakdown = modelConfig%includeSoilStateBreakdown
        C%includeSedimentFluxes = modelConfig%includeSedimentFluxes
        C%includeSoilErosionYields = modelConfig%includeSoilErosionYields
        C%includeSpmSizeClassBreakdown = modelConfig%includeSpmSizeClassBreakdown

        C%runDescription = modelConfig%runDescription
        C%logFilePath = modelConfig%logFilePath
        C%writeToLog = modelConfig%writeToLog
        C%configFilePath = modelConfig%configFilePath
        C%timeStep = modelConfig%timeStep
        C%nTimeSteps = modelConfig%nTimeSteps
        C%epsilon = modelConfig%epsilon
        C%startDate = modelConfig%startDate
        C%triggerWarnings = modelConfig%triggerWarnings
        C%errorOutput = modelConfig%errorOutput
        C%hasSimulationMask = modelConfig%hasSimulationMask
        C%simulationMaskPath = modelConfig%simulationMaskPath
        C%ignoreNM = modelConfig%ignoreNM
        C%warmUpPeriod = modelConfig%warmUpPeriod
        C%bashColors = modelConfig%bashColors

        C%checkpointFile = modelConfig%checkpointFile
        C%saveCheckpoint = modelConfig%saveCheckpoint
        C%saveCheckpointAfterWarmUp = modelConfig%saveCheckpointAfterWarmUp
        C%reinstateCheckpoint = modelConfig%reinstateCheckpoint
        C%preserveTimestep = modelConfig%preserveTimestep

        C%runToSteadyState = modelConfig%runToSteadyState
        C%steadyStateMode = modelConfig%steadyStateMode
        C%steadyStateDelta = modelConfig%steadyStateDelta

        C%nChunks = modelConfig%nChunks
        C%isBatchRun = modelConfig%isBatchRun
        if (allocated(C%batchInputFiles)) deallocate(C%batchInputFiles)
        if (allocated(C%batchConstantFiles)) deallocate(C%batchConstantFiles)
        if (allocated(C%batchStartDates)) deallocate(C%batchStartDates)
        if (allocated(C%batchNTimesteps)) deallocate(C%batchNTimesteps)
        if (allocated(C%batchConfigFiles)) deallocate(C%batchConfigFiles)
        if (allocated(modelConfig%batchInputFiles)) allocate(C%batchInputFiles, source=modelConfig%batchInputFiles)
        if (allocated(modelConfig%batchConstantFiles)) allocate(C%batchConstantFiles, source=modelConfig%batchConstantFiles)
        if (allocated(modelConfig%batchStartDates)) allocate(C%batchStartDates, source=modelConfig%batchStartDates)
        if (allocated(modelConfig%batchNTimesteps)) allocate(C%batchNTimesteps, source=modelConfig%batchNTimesteps)
        if (allocated(modelConfig%batchConfigFiles)) allocate(C%batchConfigFiles, source=modelConfig%batchConfigFiles)
        C%nTimestepsInBatch = modelConfig%nTimestepsInBatch
        C%batchStartDate = modelConfig%batchStartDate
        C%batchEndDate = modelConfig%batchEndDate

        C%t0 = modelConfig%t0
    end subroutine

end module BootstrapModule
