!> Preserve a known mass-loss defect during Phase 8; this is not a science-correctness test.
program ReactorLegacyMassTest
    use KernelModule, only: dp
    use ModelDimensionsModule, only: nSizeClassesNM, nSizeClassesSpm, npDim, d_nm, d_spm
    use ModelConfigModule, only: modelConfig
    use ReactorModule, only: Reactor
    use ResultModule, only: Result
    implicit none

    type(Reactor) :: reactorObject
    type(Result) :: outcome
    real(dp) :: collisions(1,2)

    nSizeClassesNM = 1
    nSizeClassesSpm = 2
    npDim = [1,1,4]
    modelConfig%timeStep = 1
    d_nm = [1e-8]
    d_spm = [1e-6,2e-6]
    reactorObject%T_water = 20.0
    reactorObject%G = 10.0
    reactorObject%alpha_hetero = 1.0_dp
    reactorObject%W_settle_np = [0.0_dp]
    reactorObject%W_settle_spm = [0.0_dp,0.0_dp]
    allocate(reactorObject%k_hetero(1,2))
    allocate(reactorObject%m_np(1,1,4), reactorObject%m_transformed(1,1,4))
    reactorObject%m_np = 0.0_dp
    reactorObject%m_transformed = 0.0_dp
    reactorObject%m_np(1,1,1) = 100.0_dp
    reactorObject%m_transformed(1,1,1) = 50.0_dp
    collisions = reactorObject%calculateCollisionRate(reactorObject%T_water, reactorObject%G, &
        reactorObject%W_settle_np, reactorObject%W_settle_spm)
    ! Set both attachment rates to one so that all free mass is redistributed.
    reactorObject%C_spm_particle = 1.0_dp/collisions(1,:)
    outcome = reactorObject%heteroaggregation()

    call assertTrue(all(abs(reactorObject%k_hetero - 1.0_dp) < 1e-12_dp), "Equal-rate setup failed")
    ! The existing loop scales the same mass twice, losing 25% in this example.
    ! A separate science correction must replace these expectations with conserved mass.
    call assertTrue(all(abs(reactorObject%m_np(1,1,:) - [0.0_dp,0.0_dp,50.0_dp,25.0_dp]) < 1e-12_dp), &
        "Known pristine mass-loss result changed")
    call assertTrue(all(abs(reactorObject%m_transformed(1,1,:) - [0.0_dp,0.0_dp,25.0_dp,12.5_dp]) < 1e-12_dp), &
        "Known transformed mass-loss result changed")
    print *, 'Pristine total:', sum(reactorObject%m_np)
    print *, 'Transformed total:', sum(reactorObject%m_transformed)

  contains

    subroutine assertTrue(condition, message)
        logical, intent(in) :: condition
        character(len=*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine

end program ReactorLegacyMassTest
