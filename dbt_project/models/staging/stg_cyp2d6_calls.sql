-- stg_cyp2d6_calls.sql
-- Staging model: normalize raw Aldy call output loaded into DuckDB.
--
-- Assumes the raw Aldy results have been loaded into a source table
-- named `raw_aldy_calls` with the schema produced by aggregate_calls.py:
--   sample_id, population, genotype, allele_1, allele_2,
--   activity_score, phenotype, solutions, status

with source as (
    select * from {{ source('cyp2d6_raw', 'raw_aldy_calls') }}
),

cleaned as (
    select
        sample_id,
        population,

        -- Normalize genotype string
        trim(genotype)                              as genotype,
        trim(allele_1)                              as allele_1,
        trim(allele_2)                              as allele_2,

        -- Aldy-reported activity score (may differ from CPIC recalculation)
        cast(activity_score as double)              as aldy_activity_score,

        -- CPIC phenotype categories (recalculated in gold models)
        case
            when cast(activity_score as double) > 2.0   then 'UM'
            when cast(activity_score as double) >= 1.25 then 'NM'
            when cast(activity_score as double) >= 0.25 then 'IM'
            else                                              'PM'
        end                                         as phenotype_short,

        trim(phenotype)                             as aldy_phenotype_label,
        cast(solutions as integer)                  as n_solutions,
        status

    from source
    where status = 'ok'
)

select * from cleaned
