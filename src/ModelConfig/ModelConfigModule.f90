!> Model-wide runtime configuration.
!!
!! This module owns run control, output, checkpoint, steady-state, batch, and
!! data-path configuration. `GlobalsModule` still mirrors these values into `C`
!! as a staged migration facade for existing call sites.
!! Phase 13: the old copying object has been removed; callers use this owner directly.
module ModelConfigModule
    use datetime_module
    use mod_strptime, only: f_strptime
    use VersionModule, only: MODEL_VERSION
    use KernelModule, only: dp
    use ModelDefaultsModule, only: configDefaults
    use ErrorInstanceModule, only: ErrorInstance
    use ResultModule, only: Result
    implicit none
    private

    public :: ModelConfigType, modelConfig

    ! Authoritative model defaults are applied in clearModelConfig() before namelist reads.
    ! Component initializers here are only neutral pre-init state, not default policy.
    type :: ModelConfigType
        ! Version
        character(len=max(16, len(MODEL_VERSION))) :: modelVersion = ""

        ! Data input/output paths
        character(len=256) :: inputFile = ""
        character(len=256) :: constantsFile = ""
        !! Path to directory to store output data
        character(len=256) :: outputPath = ""
        !! Hash to append to output file names. Useful for parallel runs.
        character(len=32)  :: outputHash = ""

        ! Output
        !! Should output data be written as CSV file?
        logical          :: writeCSV = .false.
        !! Should output data be written as NetCDF file?
        logical          :: writeNetCDF = .false.
        !! Should NetCDF output be written on each timestep or at the end of the chunk?
        character(len=3) :: netCDFWriteMode = ""
        !! Should a file with summary stats for each compartment (soil, water, sediment) be output?
        logical          :: writeCompartmentStats = .false.
        !! Should CSV files be prepended with metadata as a #-delimited comment?
        logical          :: writeMetadataAsComment = .false.
        !! Should the surface water output include breakdown of waterbodies?
        logical          :: includeWaterbodyBreakdown = .false.
        !! Include breakdown of data over sediment layers?
        logical          :: includeSedimentLayerBreakdown = .false.
        !! Include breakdown of data over soil layers?
        logical          :: includeSoilLayerBreakdown = .false.
        !! What units to use for soil PEC - kg/m3 or kg/kg dw?
        character(len=5) :: soilPECUnits = ""
        !! What units to use for sediment PEC - kg/m4 or kg/kg dw?
        character(len=5) :: sedimentPECUnits = ""
        !! Should the breakdown of NM state (free vs attached) be included?
        logical          :: includeSoilStateBreakdown = .false.
        !! Should sediment fluxes to/from waterbodies be included?
        logical          :: includeSedimentFluxes = .false.
        !! Should the breakdown of SPM size classes be included?
        logical          :: includeSpmSizeClassBreakdown = .false.
        !! Should sediment fluxes to/from waterbodies be included?
        logical          :: includeSoilErosionYields = .false.

        ! Run
        !! Short description of model run
        character(len=256) :: runDescription = ""
        !! Log file path
        character(len=256) :: logFilePath = ""
        !! Should a log file be used?
        logical            :: writeToLog = .false.
        !! Config file path
        character(len=256) :: configFilePath = ""
        !! Datetime object representing the start date
        type(datetime)     :: startDate
        !! The timestep to run the model on [s]
        integer            :: timeStep = 0
        !! The number of timesteps
        integer            :: nTimeSteps = 0
        !! Used as proximity to check whether variable as equal
        real(dp)           :: epsilon = 0.0_dp
        !! How long before we start inputting NM (to give flows to reach steady state)?
        integer            :: warmUpPeriod = 0
        !! Should error warnings be printed to the console?
        logical            :: triggerWarnings = .false.
        !! Should error handling be enabled?
        logical            :: errorOutput = .false.
        !! Are we meant to mask the simulation (i.e. only use a subset of the input dataset)?
        logical            :: hasSimulationMask = .false.
        !! Path to NetCDF simulation mask
        character(len=256) :: simulationMaskPath = ""
        !! If .true., miss out costly NM calculations. Useful for sediment calibration, NM PECs will be invalid
        logical            :: ignoreNM = .false.
        !! Should output to the console use ANSI color codes?
        logical            :: bashColors = .false.

        ! Checkpointing
        !! Path to checkpoint file, to save to and/or read from
        character(len=256) :: checkpointFile = ""
        !! Should a checkpoint be saved when the run finishes?
        logical            :: saveCheckpoint = .false.
        !! Should a checkpoint be saved after the warm up period?
        logical            :: saveCheckpointAfterWarmUp = .false.
        !! Should a checkpoint be reinstated before the run starts?
        logical            :: reinstateCheckpoint = .false.
        !! Should the final timestep from the checkpoint be used to start the reinstated run?
        logical            :: preserveTimestep = .false.
        !! Used to preserve timestep between checkpoints. Timestep number at start of run
        integer            :: t0 = 0

        ! Steady state
        !! Should the model be run until steady state by iterating over current simulation input data?
        logical           :: runToSteadyState = .false.
        !! Mode defines what variable will be used to assess steady state
        character(len=50) :: steadyStateMode = ""
        !! Delta value used to test whether we're at steady state
        real(dp)          :: steadyStateDelta = 0.0_dp

        ! Batch run
        !! Numbers of chunks to run
        integer                         :: nChunks = 0
        !! Are we batch running?
        logical                         :: isBatchRun = .false.
        !! Paths to input files for each chunk
        character(len=256), allocatable :: batchInputFiles(:)
        !! Paths to constants files for each chunk
        character(len=256), allocatable :: batchConstantFiles(:)
        !! Start dates for each chunk
        type(datetime), allocatable     :: batchStartDates(:)
        !! Number of timesteps for each chunk
        integer, allocatable            :: batchNTimesteps(:)
        !! Paths to config files for batches
        character(len=256), allocatable :: batchConfigFiles(:)
        !! Total number of timesteps in batch run
        integer                         :: nTimestepsInBatch = 0
        !! Start date of batch run
        type(datetime)                  :: batchStartDate
        !! End date of batch run
        type(datetime)                  :: batchEndDate

      contains
        procedure :: init => initModelConfig
        procedure :: audit => auditModelConfig
        procedure :: selectBatchChunk => selectBatchChunkModelConfig
        procedure :: setT0 => setT0ModelConfig
        procedure :: clear => clearModelConfig
    end type

    type(ModelConfigType) :: modelConfig

  contains

    !> Reset model-wide config state before reading a config.
    !! This is the default-ownership boundary for Phase 2: model-level defaults
    !! still held in DefaultsModule are copied from configDefaults here.
    ! Phase 10: configDefaults now comes directly from ModelDefaultsModule.
    subroutine clearModelConfig(me)
        class(ModelConfigType), intent(inout) :: me

        if (allocated(me%batchInputFiles)) deallocate(me%batchInputFiles)
        if (allocated(me%batchConstantFiles)) deallocate(me%batchConstantFiles)
        if (allocated(me%batchStartDates)) deallocate(me%batchStartDates)
        if (allocated(me%batchNTimesteps)) deallocate(me%batchNTimesteps)
        if (allocated(me%batchConfigFiles)) deallocate(me%batchConfigFiles)

        me%modelVersion = MODEL_VERSION

        me%inputFile = ""
        me%constantsFile = ""
        me%outputPath = ""
        me%outputHash = configDefaults%outputHash

        me%writeCSV = configDefaults%writeCSV
        me%writeNetCDF = configDefaults%writeNetCDF
        me%netCDFWriteMode = configDefaults%netCDFWriteMode
        me%writeCompartmentStats = configDefaults%writeCompartmentStats
        me%writeMetadataAsComment = configDefaults%writeMetadataAsComment
        me%includeWaterbodyBreakdown = configDefaults%includeWaterbodyBreakdown
        me%includeSedimentLayerBreakdown = configDefaults%includeSedimentLayerBreakdown
        me%includeSoilLayerBreakdown = configDefaults%includeSoilLayerBreakdown
        me%soilPECUnits = configDefaults%soilPECUnits
        me%sedimentPECUnits = configDefaults%sedimentPECUnits
        me%includeSoilStateBreakdown = configDefaults%includeSoilStateBreakdown
        me%includeSedimentFluxes = configDefaults%includeSedimentFluxes
        me%includeSpmSizeClassBreakdown = configDefaults%includeSpmSizeClassBreakdown
        me%includeSoilErosionYields = configDefaults%includeSoilErosionYields

        me%runDescription = configDefaults%description
        me%logFilePath = ""
        me%writeToLog = configDefaults%writeToLog
        me%configFilePath = ""
        me%timeStep = 0
        me%nTimeSteps = 0
        me%epsilon = configDefaults%epsilon
        me%warmUpPeriod = configDefaults%warmUpPeriod
        me%triggerWarnings = configDefaults%triggerWarnings
        me%errorOutput = configDefaults%errorOutput
        me%simulationMaskPath = configDefaults%simulationMask
        me%hasSimulationMask = trim(me%simulationMaskPath) /= ""
        me%ignoreNM = configDefaults%ignoreNM
        me%bashColors = configDefaults%bashColors

        me%checkpointFile = configDefaults%checkpointFile
        me%saveCheckpoint = configDefaults%saveCheckpoint
        me%saveCheckpointAfterWarmUp = configDefaults%saveCheckpointAfterWarmUp
        me%reinstateCheckpoint = configDefaults%reinstateCheckpoint
        me%preserveTimestep = configDefaults%preserveTimeStep
        me%t0 = 1

        me%runToSteadyState = configDefaults%runToSteadyState
        me%steadyStateMode = configDefaults%steadyStateMode
        me%steadyStateDelta = configDefaults%steadyStateDelta

        me%nChunks = 1
        me%isBatchRun = .false.
        me%nTimestepsInBatch = 0
    end subroutine

    !> Read model-wide config groups and optional batch config.
    subroutine initModelConfig(me, configFilePath, batchRunFilePath)
        class(ModelConfigType), intent(inout) :: me
        character(len=*), intent(in)          :: configFilePath
        character(len=*), intent(in), optional :: batchRunFilePath
        integer :: i, iouConfig, iouBatchConfig, nmlIOStat
        character(len=256) :: input_file, constants_file, output_path, log_file_path, start_date, &
            description, checkpoint_file, batch_description, simulation_mask
        character(len=50) :: mode
        character(len=256), allocatable :: input_files(:), constants_files(:), start_dates(:)
        character(len=5) :: soil_pec_units, sediment_pec_units
        character(len=3) :: netcdf_write_mode
        character(len=32) :: output_hash
        integer, allocatable :: n_timesteps_per_chunk(:)
        integer :: warm_up_period, n_chunks
        integer :: timestep, n_timesteps
        real(dp) :: epsilon, delta
        logical :: error_output, write_csv, write_netcdf, write_metadata_as_comment, &
            include_sediment_layer_breakdown, include_soil_layer_breakdown, include_soil_state_breakdown, &
            save_checkpoint, reinstate_checkpoint, preserve_timestep, trigger_warnings, run_to_steady_state, &
            include_sediment_fluxes, include_soil_erosion_yields, write_to_log, include_spm_size_class_breakdown, &
            include_waterbody_breakdown, write_compartment_stats, ignore_nm, bash_colors, save_checkpoint_after_warm_up

        namelist /data/ input_file, constants_file, output_path
        namelist /output/ write_metadata_as_comment, include_sediment_layer_breakdown, include_soil_layer_breakdown, &
            soil_pec_units, sediment_pec_units, include_soil_state_breakdown, write_csv, include_sediment_fluxes, &
            include_soil_erosion_yields, include_spm_size_class_breakdown, include_waterbody_breakdown, write_compartment_stats, &
            write_netcdf, netcdf_write_mode
        namelist /run/ timestep, n_timesteps, epsilon, error_output, log_file_path, start_date, warm_up_period, &
            description, trigger_warnings, simulation_mask, write_to_log, output_hash, ignore_nm, bash_colors
        namelist /checkpoint/ checkpoint_file, save_checkpoint, reinstate_checkpoint, preserve_timestep, &
            save_checkpoint_after_warm_up
        namelist /steady_state/ run_to_steady_state, mode, delta
        namelist /batch_config/ n_chunks, batch_description
        namelist /chunks/ input_files, constants_files, start_dates, n_timesteps_per_chunk

        call me%clear()
        me%configFilePath = configFilePath

        input_file = me%inputFile
        constants_file = me%constantsFile
        output_path = me%outputPath
        write_to_log = me%writeToLog
        write_csv = me%writeCSV
        write_netcdf = me%writeNetCDF
        netcdf_write_mode = me%netCDFWriteMode
        output_hash = me%outputHash
        description = me%runDescription
        batch_description = me%runDescription
        log_file_path = me%logFilePath
        start_date = ""
        timestep = me%timeStep
        n_timesteps = me%nTimeSteps
        epsilon = me%epsilon
        write_metadata_as_comment = me%writeMetadataAsComment
        include_sediment_layer_breakdown = me%includeSedimentLayerBreakdown
        include_soil_layer_breakdown = me%includeSoilLayerBreakdown
        include_soil_state_breakdown = me%includeSoilStateBreakdown
        include_sediment_fluxes = me%includeSedimentFluxes
        include_spm_size_class_breakdown = me%includeSpmSizeClassBreakdown
        include_soil_erosion_yields = me%includeSoilErosionYields
        soil_pec_units = me%soilPECUnits
        sediment_pec_units = me%sedimentPECUnits
        save_checkpoint = me%saveCheckpoint
        save_checkpoint_after_warm_up = me%saveCheckpointAfterWarmUp
        checkpoint_file = me%checkpointFile
        reinstate_checkpoint = me%reinstateCheckpoint
        preserve_timestep = me%preserveTimestep
        run_to_steady_state = me%runToSteadyState
        delta = me%steadyStateDelta
        mode = me%steadyStateMode
        simulation_mask = me%simulationMaskPath
        include_waterbody_breakdown = me%includeWaterbodyBreakdown
        write_compartment_stats = me%writeCompartmentStats
        ignore_nm = me%ignoreNM
        warm_up_period = me%warmUpPeriod
        bash_colors = me%bashColors
        error_output = me%errorOutput
        trigger_warnings = me%triggerWarnings
        n_chunks = me%nChunks

        open(newunit=iouConfig, file=trim(configFilePath), status="old")
        read(iouConfig, nml=data); rewind(iouConfig)
        read(iouConfig, nml=output); rewind(iouConfig)
        read(iouConfig, nml=run); rewind(iouConfig)
        read(iouConfig, nml=checkpoint, iostat=nmlIOStat); rewind(iouConfig)
        if (nmlIOStat .ge. 0) read(iouConfig, nml=checkpoint); rewind(iouConfig)
        read(iouConfig, nml=steady_state, iostat=nmlIOStat); rewind(iouConfig)
        if (nmlIOStat .ge. 0) read(iouConfig, nml=steady_state)
        close(iouConfig)

        me%inputFile = input_file
        me%constantsFile = constants_file
        me%outputPath = output_path
        me%outputHash = output_hash

        me%writeCSV = write_csv
        me%writeNetCDF = write_netcdf
        me%netCDFWriteMode = netcdf_write_mode
        me%writeMetadataAsComment = write_metadata_as_comment
        me%writeCompartmentStats = write_compartment_stats
        me%includeWaterbodyBreakdown = include_waterbody_breakdown
        me%includeSedimentLayerBreakdown = include_sediment_layer_breakdown
        me%includeSoilLayerBreakdown = include_soil_layer_breakdown
        me%soilPECUnits = soil_pec_units
        me%sedimentPECUnits = sediment_pec_units
        me%includeSoilStateBreakdown = include_soil_state_breakdown
        me%includeSedimentFluxes = include_sediment_fluxes
        me%includeSoilErosionYields = include_soil_erosion_yields
        me%includeSpmSizeClassBreakdown = include_spm_size_class_breakdown

        me%logFilePath = log_file_path
        me%writeToLog = write_to_log
        me%timeStep = timestep
        me%nTimeSteps = n_timesteps
        me%epsilon = epsilon
        me%startDate = f_strptime(start_date)
        me%triggerWarnings = trigger_warnings
        me%errorOutput = error_output
        me%simulationMaskPath = simulation_mask
        me%hasSimulationMask = trim(me%simulationMaskPath) /= ""
        me%ignoreNM = ignore_nm
        me%warmUpPeriod = warm_up_period
        me%bashColors = bash_colors

        me%checkpointFile = checkpoint_file
        me%saveCheckpoint = save_checkpoint
        me%saveCheckpointAfterWarmUp = save_checkpoint_after_warm_up
        me%reinstateCheckpoint = reinstate_checkpoint
        me%preserveTimestep = preserve_timestep

        me%runToSteadyState = run_to_steady_state
        me%steadyStateMode = mode
        me%steadyStateDelta = delta

        if (present(batchRunFilePath)) then
            if (len_trim(batchRunFilePath) > 0) then
                me%isBatchRun = .true.
                open(newunit=iouBatchConfig, file=trim(batchRunFilePath), status="old")
                read(iouBatchConfig, nml=batch_config); rewind(iouBatchConfig)
                me%nChunks = n_chunks
                allocate(input_files(me%nChunks), constants_files(me%nChunks), &
                    start_dates(me%nChunks), n_timesteps_per_chunk(me%nChunks))
                read(iouBatchConfig, nml=chunks)
                close(iouBatchConfig)

                allocate(me%batchInputFiles, source=input_files)
                allocate(me%batchConstantFiles, source=constants_files)
                allocate(me%batchStartDates(me%nChunks))
                allocate(me%batchNTimesteps, source=n_timesteps_per_chunk)
                do i = 1, me%nChunks
                    me%batchStartDates(i) = f_strptime(start_dates(i))
                end do
            end if
        end if

        if (.not. me%isBatchRun) then
            me%runDescription = description
            me%nTimestepsInBatch = me%nTimeSteps
            me%batchStartDate = me%startDate
            me%batchEndDate = me%startDate + timedelta(me%nTimeSteps - 1)
            allocate(me%batchNTimesteps(1))
            me%batchNTimesteps(1) = me%nTimeSteps
        else
            me%runDescription = batch_description
            call me%selectBatchChunk(1)
            me%nTimestepsInBatch = sum(me%batchNTimesteps)
            me%batchStartDate = me%batchStartDates(1)
            me%batchEndDate = me%batchStartDates(me%nChunks) + timedelta(me%batchNTimesteps(me%nChunks) - 1)
        end if
    end subroutine

    !> Return audit errors for model-wide config values.
    function auditModelConfig(me) result(rslt)
        class(ModelConfigType), intent(in) :: me
        type(Result) :: rslt
        ! Steady state mode
        if (me%runToSteadyState) then
            if (trim(me%steadyStateMode) /= "sediment_size_distribution") then
                call rslt%addError(ErrorInstance( &
                    message="Invalid or non-present config file value for &steady_state > mode." &
                ))
            end if
        end if
        ! NetCDF write mode must be itr or end
        if (me%netCDFWriteMode /= "itr" .and. me%netCDFWriteMode /= "end") then
            call rslt%addError(ErrorInstance( &
                message='Invalid config file value for &output > netcdf_write_mode. Should be "itr" or "end"' &
            ))
        end if

        ! Warm up period must be less than or equal to the number of time steps
        if (me%warmUpPeriod > me%nTimeSteps) then
            call rslt%addError(ErrorInstance(message="Warm up period must be less than or equal to the number of " // &
                "time steps in the model run (or first chunk)."))
        end if
        ! CHECKPOINT
        ! Add warning if saving checkpoint at warm up and end of run
        if (me%saveCheckpoint .and. me%saveCheckpointAfterWarmUp) then
            call rslt%addError(ErrorInstance(message="You have specified to save a checkpoint after warm up " // &
                "and at the end of the model run. Only the latter will be saved to file.", isCritical=.false.))
        end if

        call rslt%addToTrace("Auditing config file")
    end function

    !> Select the current batch chunk as the active data/run window.
    subroutine selectBatchChunkModelConfig(me, k)
        class(ModelConfigType), intent(inout) :: me
        integer, intent(in) :: k

        me%inputFile = me%batchInputFiles(k)
        me%constantsFile = me%batchConstantFiles(k)
        me%nTimeSteps = me%batchNTimesteps(k)
        me%startDate = me%batchStartDates(k)
    end subroutine

    !> Record the current starting timestep after checkpoint reinstatement.
    subroutine setT0ModelConfig(me, t)
        class(ModelConfigType), intent(inout) :: me
        integer, intent(in) :: t

        me%t0 = t
    end subroutine

end module ModelConfigModule
