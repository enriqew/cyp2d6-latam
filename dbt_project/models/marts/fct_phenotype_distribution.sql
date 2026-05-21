-- fct_phenotype_distribution.sql
-- Gold mart: UM/NM/IM/PM percentage breakdown by population.

with calls as (
    select * from {{ ref('stg_cyp2d6_calls') }}
),

population_totals as (
    select population, count(*) as n_total
    from calls
    group by population
),

phenotype_counts as (
    select
        phenotype_short  as phenotype,
        population,
        count(*)         as n_samples
    from calls
    group by phenotype_short, population
),

-- Ensure all 4 phenotypes appear for every population (even if zero)
phenotype_cross as (
    select p.population, ph.phenotype
    from population_totals p
    cross join (
        select 'UM' as phenotype union all
        select 'NM' union all
        select 'IM' union all
        select 'PM'
    ) ph
),

final as (
    select
        x.phenotype,
        x.population,
        coalesce(c.n_samples, 0)                                                  as n_samples,
        t.n_total,
        round(
            100.0 * coalesce(c.n_samples, 0) / nullif(t.n_total, 0), 2
        )                                                                          as percentage
    from phenotype_cross x
    left join phenotype_counts  c using (phenotype, population)
    join  population_totals     t using (population)
    order by x.population, x.phenotype
)

select * from final
