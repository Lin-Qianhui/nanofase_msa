!> Top-level model startup orchestration.
module BootstrapModule
    use KernelModule, only: iouLog
    use ModelDimensionsModule, only: initModelDimensions
    use ModelConfigModule, only: modelConfig
    use ErrorHandlingModule, only: ERROR_HANDLER, initErrorHandling
    use ResultModule, only: Result
    use SoilConfigModule, only: soilConfig
    use BedSedimentConfigModule, only: bedSedimentConfig
    use WaterBodyConfigModule, only: waterBodyConfig
    use ReactorConfigModule, only: registerReactorErrors
    use BiotaConfigModule, only: registerBiotaErrors
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

        call soilConfig%init(modelConfig%configFilePath)
        call bedSedimentConfig%init(modelConfig%configFilePath)

        call waterBodyConfig%init(modelConfig%configFilePath)
        call registerReactorErrors()
        call registerBiotaErrors()

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

end module BootstrapModule
