-- Per-platform → per-service → per-unit usage & cost totals. Powers the
-- drill-down ("which service/SKU drove the spend?") on each platform page.
{{ config(materialized='table') }}

select
    platform,
    service,
    unit,
    sum(quantity)        as quantity,
    sum(cost)            as cost,
    sum(line_items)      as line_items,
    min(date)            as first_seen,
    max(date)            as last_seen
from {{ ref('int_daily_platform_service') }}
group by platform, service, unit
order by platform, cost desc nulls last, quantity desc nulls last
