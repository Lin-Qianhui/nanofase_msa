! Calls the same public procedures in the reference and migrated builds.
program BiotaScienceTest
    use KernelModule, only: dp
    use AbstractBiotaModule, only: AbstractBiota
    use BiotaSoilModule, only: BiotaSoil
    use BiotaWaterModule, only: BiotaWater
    use DataInputModule, only: DATASET
    use ModelConfigModule, only: modelConfig
    use GlobalsModule, only: C, syncRuntimeModelConfigToGlobals
    use ResultModule, only: Result
    use datetime_module, only: datetime
    implicit none

    type(BiotaSoil) :: soil
    type(BiotaWater) :: water

    ! Both owners are set so this unchanged test also runs against Phase 8.
    modelConfig%epsilon = 1.0e-10_dp
    C%epsilon = modelConfig%epsilon
    DATASET%biotaName = [character(len=100) :: 'soil organism', 'water organism']
    DATASET%biotaInitial_C_org = [0.5_dp, 0.75_dp]
    DATASET%biota_k_uptake_np = [0.2_dp, 0.3_dp]
    DATASET%biota_k_uptake_transformed = [0.4_dp, 0.5_dp]
    DATASET%biota_k_uptake_dissolved = [0.6_dp, 0.7_dp]
    DATASET%biota_k_elim_np = [0.1_dp, 0.2_dp]
    DATASET%biota_k_elim_transformed = [0.3_dp, 0.4_dp]
    DATASET%biota_k_elim_dissolved = [0.5_dp, 0.6_dp]
    DATASET%biota_k_growth = [0.02_dp, 0.03_dp]
    DATASET%biota_k_death = [0.04_dp, 0.05_dp]
    DATASET%biotaStoredFraction = [0.25, 0.5]
    DATASET%biotaUptakeFromForm = [character(len=17) :: 'free_and_attached', 'free_and_attached']
    DATASET%biotaHarvestInMonth = [0, 0]
    call exercise(soil, 1, 'soil')
    call exercise(water, 2, 'water')

  contains

    subroutine require(condition, message)
        logical, intent(in) :: condition
        character(*), intent(in) :: message
        if (.not. condition) error stop message
    end subroutine

    subroutine clockValues(day, seconds)
        type(datetime), intent(in) :: day
        integer, intent(in) :: seconds
        modelConfig%startDate = day
        modelConfig%timeStep = seconds
        C%timeStep = seconds
        call syncRuntimeModelConfigToGlobals()
    end subroutine

    subroutine reset(organism, index)
        class(AbstractBiota), intent(inout) :: organism
        integer, intent(in) :: index
        type(Result) :: result
        result = organism%create(index)
        call require(.not. result%hasError(), 'Creation returned an error')
        call require(organism%biotaIndex == index, 'Wrong organism index')
        call require(organism%name == DATASET%biotaName(index), 'Wrong organism name')
        call require(organism%C_active == DATASET%biotaInitial_C_org(index), 'Wrong initial active concentration')
        call require(organism%C_stored == 0.0_dp, 'Stored concentration did not start at zero')
        call require(all([organism%k_uptake_np, organism%k_uptake_transformed, organism%k_uptake_dissolved, &
            organism%k_elim_np, organism%k_elim_transformed, organism%k_elim_dissolved, &
            organism%k_growth, organism%k_death] == &
            [DATASET%biota_k_uptake_np(index), DATASET%biota_k_uptake_transformed(index), &
            DATASET%biota_k_uptake_dissolved(index), DATASET%biota_k_elim_np(index), &
            DATASET%biota_k_elim_transformed(index), DATASET%biota_k_elim_dissolved(index), &
            DATASET%biota_k_growth(index), DATASET%biota_k_death(index)]), 'Input rate changed')
        call require(organism%storedFraction == real(DATASET%biotaStoredFraction(index), dp), 'Stored fraction changed')
        call require(organism%uptakeFromForm == DATASET%biotaUptakeFromForm(index), 'Uptake form changed')
        call require(organism%harvestInMonth == DATASET%biotaHarvestInMonth(index), 'Harvest month changed')
    end subroutine

    subroutine record(organism, kind, label, step)
        class(AbstractBiota), intent(in) :: organism
        character(*), intent(in) :: kind, label
        integer, intent(in) :: step
        print '(a,1x,a,1x,a,1x,i0,2(1x,es26.17e3))', &
            'DIRECT', kind, label, step, organism%C_active, organism%C_stored
    end subroutine

    subroutine advance(organism, kind, label, step, pristine, transformed, dissolved)
        class(AbstractBiota), intent(inout) :: organism
        character(*), intent(in) :: kind, label
        integer :: step
        real(dp) :: pristine(:,:,:), transformed(:,:,:), dissolved
        type(Result) :: result
        result = organism%update(step, pristine, transformed, dissolved)
        call require(.not. result%hasError(), 'Valid update returned an error')
        call record(organism, kind, label, step)
    end subroutine

    subroutine exercise(organism, index, kind)
        class(AbstractBiota), intent(inout) :: organism
        integer, intent(in) :: index
        character(*), intent(in) :: kind
        character(len=17), parameter :: forms(6) = [character(len=17) :: &
            'free', 'attached', 'free_and_attached', 'attached_and_free', 'free_attached', 'attached_free']
        real(dp) :: pristine(2,2,4), transformed(2,2,4), zero(2,2,4), masked(2,2,4), maskedT(2,2,4)
        real(dp) :: values(2,6), full(2), daily(2), material(2,4), fraction(3)
        character(len=32) :: label
        integer :: i, step, first, last

        call clockValues(datetime(2015,1,1), 86400)
        call reset(organism, index)
        call require(index /= 1 .or. organism%ref == 'BiotaSoil_1', 'Soil reference changed')
        call require(index /= 2 .or. organism%ref == 'BiotaWater_2', 'Water reference changed')
        call record(organism, kind, 'created', 0)
        pristine = reshape([(real(i,dp), i=1,16)], shape(pristine))
        transformed = 2.0_dp * pristine + 1.0_dp
        zero = 0.0_dp

        do i = 1, size(forms)
            call reset(organism, index)
            organism%uptakeFromForm = forms(i)
            call advance(organism, kind, trim(forms(i)), 1, pristine, transformed, 3.0_dp)
            values(:,i) = [organism%C_active, organism%C_stored]
        end do
        call require(any(values(:,1) /= values(:,2)), 'Free and attached cases did not differ')
        call require(any(values(:,2) /= values(:,3)), 'Attached and combined cases did not differ')
        do i = 4, 6
            call require(all(values(:,i) == values(:,3)), 'Combined-form aliases differ')
        end do

        ! Check selection independently: put just the expected positions into a
        ! free-only array and compare the resulting concentrations, not the equation.
        do i = 1, 3
            first = 1
            last = 1
            if (i == 2) then
                first = 2
                if (index == 2) first = 3
                last = 2
                if (index == 2) last = 4
            else if (i == 3) then
                last = 2
                if (index == 2) last = 4
            end if
            masked = 0.0_dp
            maskedT = 0.0_dp
            masked(:,:,1) = sum(pristine(:,:,first:last), dim=3)
            maskedT(:,:,1) = sum(transformed(:,:,first:last), dim=3)
            call reset(organism, index)
            organism%uptakeFromForm = 'free'
            call advance(organism, kind, 'selected_' // trim(forms(i)), 1, masked, maskedT, 3.0_dp)
            call require(all([organism%C_active, organism%C_stored] == values(:,i)), 'Wrong uptake positions selected')
        end do

        do i = 1, 4
            call reset(organism, index)
            masked = zero
            maskedT = zero
            if (i == 1 .or. i == 4) masked = pristine
            if (i == 2 .or. i == 4) maskedT = transformed
            write(label,'(a,i0)') 'material_', i
            call advance(organism, kind, trim(label), 1, masked, maskedT, merge(3.0_dp,0.0_dp,i>=3))
            material(:,i) = [organism%C_active, organism%C_stored]
        end do
        do i = 1, 3
            call require(any(material(:,i) /= material(:,4)), 'Material contribution was not exercised')
        end do

        fraction = [0.0_dp, 0.25_dp, 1.0_dp]
        do i = 1, 3
            call reset(organism, index)
            organism%storedFraction = fraction(i)
            write(label,'(a,i0)') 'storage_', i
            call advance(organism, kind, trim(label), 1, pristine, transformed, 3.0_dp)
            if (i == 1) call require(organism%C_stored == 0.0_dp, 'Zero storage fraction accumulated mass')
            if (i > 1) call require(organism%C_stored > 0.0_dp, 'Stored uptake was not exercised')
        end do
        call reset(organism, index)
        organism%k_growth = 0.0_dp
        organism%k_death = 0.0_dp
        organism%C_stored = 0.75_dp
        call advance(organism, kind, 'zero_growth_death', 1, pristine, transformed, 3.0_dp)
        call require(organism%C_stored == 0.75_dp, 'Existing zero-growth/death behaviour changed')

        call reset(organism, index)
        call advance(organism, kind, 'daily', 1, pristine, transformed, 3.0_dp)
        daily = [organism%C_active, organism%C_stored]
        call clockValues(datetime(2015,1,1), 43200)
        call reset(organism, index)
        call advance(organism, kind, 'half_day', 1, pristine, transformed, 3.0_dp)
        call require(any(daily /= [organism%C_active, organism%C_stored]), 'Timestep duration was not exercised')

        ! The existing date calculation advances one day even for a half-day step.
        call clockValues(datetime(2015,1,31), 43200)
        call reset(organism, index)
        organism%harvestInMonth = 2
        do step = 1, 3
            call advance(organism, kind, 'harvest_boundary', step, pristine, transformed, 3.0_dp)
            if (step == 1) call require(organism%C_active > 0.0_dp, 'Harvest occurred before February')
            if (step > 1) call require(organism%C_active == 0.0_dp .and. organism%C_stored == 0.0_dp, &
                'Concentrations were not reset throughout the harvest month')
        end do
        ! Mutate the shared start date without recreating the organism, as a batch does.
        call clockValues(datetime(2015,3,1), 86400)
        call advance(organism, kind, 'new_batch_date', 1, pristine, transformed, 3.0_dp)
        call require(organism%C_active > 0.0_dp .and. organism%C_stored > 0.0_dp, 'New batch date was not observed')
        full = [organism%C_active, organism%C_stored]
        call advance(organism, kind, 'continued', 2, pristine, transformed, 3.0_dp)
        call require(any(full /= [organism%C_active, organism%C_stored]), 'Repeated update was not exercised')
    end subroutine
end program BiotaScienceTest
