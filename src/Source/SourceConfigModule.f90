!> Source-domain runtime configuration.
module SourceConfigModule
    implicit none
    private

    public :: SourceConfigType, sourceConfig

    type :: SourceConfigType
        logical :: includePointSources              !! Should point sources be included?
      contains
        procedure :: init => initSourceConfig
    end type

    type(SourceConfigType) :: sourceConfig

  contains

    !> Read source-domain configuration.
    subroutine initSourceConfig(me, configFilePath)
        class(SourceConfigType), intent(inout) :: me
        character(len=*), intent(in) :: configFilePath
        integer :: iou
        logical :: include_point_sources

        namelist /sources/ include_point_sources

        open(newunit=iou, file=trim(configFilePath), status="old")
        read(iou, nml=sources)
        close(iou)

        me%includePointSources = include_point_sources
    end subroutine

end module SourceConfigModule
