! Phase 13: original comments from removed compatibility code.
! This comment-only file is historical documentation and is not compiled.
! Useful field/function comments moved to ModelConfig, ModelDimensions, or Kernel.

! Original src/GlobalsModule.f90:27
! Get model version from the version module (which our build script should modify)
! Original src/GlobalsModule.f90:30
! Data input
! Original src/GlobalsModule.f90:34
! Data output
! Original src/GlobalsModule.f90:52
! Run
! Original src/GlobalsModule.f90:69
! Checkpointing
! Original src/GlobalsModule.f90:76
! Steady state
! Original src/GlobalsModule.f90:81
! Compartments
! Original src/GlobalsModule.f90:85
! Batch run
! Original src/GlobalsModule.f90:97
! Checkpointing
! Original src/GlobalsModule.f90:100
! General
! Original src/GlobalsModule.f90:101
!! The NetCDF dataset
! Original src/GlobalsModule.f90:103
! Physical constants
! Original src/GlobalsModule.f90:110
! Temp
! Original src/GlobalsModule.f90:113
! Size class distributions
! Original src/GlobalsModule.f90:124
!! Default imposed size distribution for sediment
! Original src/GlobalsModule.f90:125
!! Default imposed size distribution for NPs
! Original src/GlobalsModule.f90:127
!! Default dimensions for ionic metal
! Original src/GlobalsModule.f90:130
! Density of water
! Original src/GlobalsModule.f90:131
! Kinematic viscosity of water
! Original src/GlobalsModule.f90:132
! Dynamic viscosity of water
! Original src/GlobalsModule.f90:139
!> Copy runtime-mutated model-config values into the compatibility facade.
! Original src/GlobalsModule.f90:161
!! This `Constants` instance
! Original src/GlobalsModule.f90:162
!! Temperature \( T \) [deg C]
! Original src/GlobalsModule.f90:163
!! Salinity \( S \) [g/kg]
! Original src/GlobalsModule.f90:164
!! Density of water \( \rho_w \) [kg/m**3].
! Original src/GlobalsModule.f90:179
!! This Globals instance
! Original src/GlobalsModule.f90:180
!! Temperature \( T \) [deg C]
! Original src/GlobalsModule.f90:181
!! Salinity \( S \) [g/kg]
! Original src/GlobalsModule.f90:182
!! Kinematic viscosity of water \( \nu_{\text{w}} \)
! Original src/DefaultsModule.f90:1
!> The DefaultsModule holds default values used throughout the model, such as those
! Original src/DefaultsModule.f90:2
!! used in input data or config
! Original src/DefaultsModule.f90:10
! Double precision reals. Private for the moment as it's also in GlobalsModule
! Original src/DefaultsModule.f90:13
! Phase 10: the original declarations and comments moved to ModelDefaultsModule.
! Original src/DefaultsModule.f90:14
! The import exposes the same defaults object for remaining compatibility users.
! Original src/Bootstrap/BootstrapModule.f90:93
!> Populate the compatibility facade and read config for domains that have
! Original src/Bootstrap/BootstrapModule.f90:94
!! not yet taken ownership of their namelist groups.
! Original src/Bootstrap/BootstrapModule.f90:95
! Phase 7 note: all domain reads have moved; this helper only copies dimensions for older consumers.
! Original src/Bootstrap/BootstrapModule.f90:97
! Store dimension and domain data in the Globals facade.
! Original src/Bootstrap/BootstrapModule.f90:120
! Array to store default NM and ionic array dimensions. NM:
! Original src/Bootstrap/BootstrapModule.f90:121
!   1: NP size class
! Original src/Bootstrap/BootstrapModule.f90:122
!   2: form (core, shell, coating, corona)
! Original src/Bootstrap/BootstrapModule.f90:123
!   3: state (free, bound, heteroaggregated)
! Original src/Bootstrap/BootstrapModule.f90:124
! Ionic: Form (free ion, solution, adsorbed)
! Original src/Bootstrap/BootstrapModule.f90:128
!> Copy all model-level config values into the compatibility facade.

! Original src/GlobalsModule.f90:111; unused temperature field
!! Temperature [C]
