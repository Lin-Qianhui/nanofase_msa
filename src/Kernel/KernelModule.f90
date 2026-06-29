!> Shared application kernel for precision, constants, IO units, and small
!! dependency-free physical helper functions.
module KernelModule
    implicit none

    ! Double precision reals.
    integer, parameter :: dp = selected_real_kind(15, 307)

    ! Config file IO units
    integer, parameter :: iouConfig = 1
    integer, parameter :: iouBatchConfig = 2
    integer, parameter :: iouVersion = 3
    ! Constants file IO units
    integer, parameter :: iouConstants = 10
    ! Output file IO units
    integer, parameter :: iouOutputSummary = 100
    integer, parameter :: iouOutputWater = 101
    integer, parameter :: iouOutputSediment = 102
    integer, parameter :: iouOutputSoil = 103
    integer, parameter :: iouOutputSSD = 104
    integer, parameter :: iouOutputStats = 105
    ! Checkpoint and logging
    integer, parameter :: iouCheckpoint = 500
    integer, parameter :: iouLog = 501

    ! Terminal color escape sequences.
    character(len=*), parameter :: ESC = char(27)   ! Terminal escape character
    character(len=*), parameter :: COLOR_BLUE = ESC // "[94m"   ! Terminal escape character
    character(len=*), parameter :: COLOR_LIGHT_BLUE = ESC // "[39m"  ! Escape sequence for light blue text
    character(len=*), parameter :: COLOR_GREEN = ESC // "[32m"  ! Escape sequence for green text
    character(len=*), parameter :: COLOR_YELLOW = ESC // "[33m" ! Escape sequence for yellow text
    character(len=*), parameter :: COLOR_RED = ESC // "[91m"    ! Escape sequence for red text
    character(len=*), parameter :: COLOR_RESET = ESC // "[0m"       ! Escape sequence to reset text color

    ! Cross-domain physical constants.
    real(dp), parameter :: g = 9.80665_dp
    real(dp), parameter :: k_B = 1.38064852e-23
    real(dp), parameter :: pi = 4*atan(1.0_dp)
    real(dp), parameter :: n_river = 0.035_dp

contains

    !> Calculate water density at temperature T [deg C], optionally with salinity S [g/kg].
    pure function rho_w(T, S)
        real, intent(in) :: T
        real(dp), intent(in), optional :: S
        real(dp) :: rho_w

        if (present(S)) then
            rho_w = 1000.0_dp*(1-(T+288.9414_dp)/(508929.2_dp*(T+68.12963_dp))*(T-3.9863_dp)**2) &
                    + (0.824493_dp - 0.0040899_dp*T + 0.000076438_dp*T**2 - 0.00000082467_dp*T**3 + 0.0000000053675_dp*T**4)*S &
                    + (-0.005724_dp + 0.00010227_dp*T - 0.0000016546_dp*T**2)*S**(3.0_dp/2.0_dp) &
                    + 0.00048314_dp*S**2
        else
            rho_w = 1000.0_dp*(1-(T+288.9414_dp)/(508929.2_dp*(T+68.12963_dp))*(T-3.9863_dp)**2)
        end if
    end function

    !> Calculate water kinematic viscosity at temperature T [deg C], optionally with salinity S [g/kg].
    pure function nu_w(T, S)
        real, intent(in) :: T
        real(dp), intent(in), optional :: S
        real(dp) :: nu_w

        if (present(S)) then
            nu_w = (2.414e-5_dp * 10.0_dp**(247.8_dp/((T+273.15_dp)-140.0_dp)))/rho_w(T,S)
        else
            nu_w = (2.414e-5_dp * 10.0_dp**(247.8_dp/((T+273.15_dp)-140.0_dp)))/rho_w(T)
        end if
    end function

    !> Calculate water dynamic viscosity at temperature T [deg C].
    pure function mu_w(T)
        real, intent(in) :: T
        real(dp) :: mu_w

        mu_w = (2.414e-5_dp * 10.0_dp**(247.8_dp/((T+273.15_dp)-140.0_dp)))
    end function
end module KernelModule
