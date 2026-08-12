-- One row per platform: totals, date span, and whether it reports $ or metrics.
{{ config(materialized='table') }}

select
    platform,
    count(distinct date)                     as active_days,
    min(date)                                as first_seen,
    max(date)                                as last_seen,
    sum(cost)                                as total_cost,
    -- a platform is "metric-only" if it never reports a non-null cost
    bool_and(cost is null)                   as is_metric_only,
    max(currency)                            as currency
from {{ ref('stg_usage_facts') }}
group by platform
order by total_cost desc nulls last, platform
