-- fct_allele_frequencies.sql
-- Gold mart: per-allele frequencies by population.
--
-- Each sample contributes 2 alleles (diploid). Frequency = count / (2 * n_samples).

with calls as (
    select * from {{ ref('stg_cyp2d6_calls') }}
),

-- Unpivot allele_1 and allele_2 into a single allele column
alleles_long as (
    select sample_id, population, allele_1 as allele from calls
    union all
    select sample_id, population, allele_2 as allele from calls
),

population_totals as (
    select
        population,
        count(distinct sample_id) as n_samples,
        count(*)                  as n_allele_observations  -- 2 * n_samples
    from alleles_long
    group by population
),

allele_counts as (
    select
        allele,
        population,
        count(*) as n_allele_obs
    from alleles_long
    group by allele, population
),

carrier_counts as (
    select
        allele,
        population,
        count(distinct sample_id) as n_carriers
    from (
        select sample_id, population, allele_1 as allele from calls
        where allele_1 = allele_1  -- identity join placeholder
        union
        select sample_id, population, allele_2 as allele from calls
    ) carriers
    group by allele, population
),

final as (
    select
        a.allele,
        a.population,
        round(cast(a.n_allele_obs as double) / t.n_allele_observations, 4) as frequency,
        c.n_carriers,
        t.n_samples                                                          as n_total
    from allele_counts a
    join population_totals t  using (population)
    join carrier_counts   c  using (allele, population)
    order by a.population, frequency desc
)

select * from final
