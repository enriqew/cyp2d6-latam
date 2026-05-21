-- fct_drug_impact.sql
-- Gold mart: percentage of patients requiring dose adjustment per drug per population.
--
-- Drugs: codeine, tramadol, tamoxifen, amitriptyline (CPIC A-level for CYP2D6)
-- Affected phenotypes:
--   codeine / tramadol : PM (avoid), UM (avoid)
--   tamoxifen          : PM (consider alternative), IM (standard + monitoring)
--   amitriptyline      : PM (reduce 50%), IM (reduce 25%)

with calls as (
    select * from {{ ref('stg_cyp2d6_calls') }}
),

population_totals as (
    select population, count(*) as n_total
    from calls
    group by population
),

drug_rules as (
    -- codeine
    select 'codeine' as drug, 'PM' as phenotype, 'Avoid — no active metabolite; risk of inefficacy'       as recommendation
    union all select 'codeine', 'UM', 'Avoid — excessive morphine; risk of respiratory depression'
    -- tramadol
    union all select 'tramadol', 'PM', 'Avoid — no active metabolite; risk of inefficacy'
    union all select 'tramadol', 'UM', 'Avoid — excessive active metabolite; risk of CNS toxicity'
    -- tamoxifen
    union all select 'tamoxifen', 'PM', 'Consider alternative — reduced endoxifen formation'
    union all select 'tamoxifen', 'IM', 'Standard dose with increased monitoring'
    -- amitriptyline
    union all select 'amitriptyline', 'PM', 'Reduce dose 50% — risk of tricyclic accumulation'
    union all select 'amitriptyline', 'IM', 'Reduce dose 25% — risk of mild accumulation'
),

affected as (
    select
        r.drug,
        c.population,
        count(distinct c.sample_id) as n_affected
    from calls c
    join drug_rules r on c.phenotype_short = r.phenotype
    group by r.drug, c.population
),

recommendations_agg as (
    select
        r.drug,
        c.phenotype_short as phenotype,
        r.recommendation
    from (select distinct phenotype_short from calls) c
    join drug_rules r on c.phenotype_short = r.phenotype
),

final as (
    select
        a.drug,
        a.population,
        round(100.0 * a.n_affected / t.n_total, 2) as pct_requiring_adjustment,
        a.n_affected,
        t.n_total
    from affected a
    join population_totals t using (population)
    order by a.drug, a.population
)

select * from final
