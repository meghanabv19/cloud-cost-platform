-- Per-platform, per-day cost + line-item count. The primary series the dashboard
-- charts and the anomaly detector consumes. Cost is summed (currency-additive);
-- usage quantities are intentionally left to the finer-grained service model.
{{ config(materialized='table') }}

select
    platform,
    date,
    month,
    sum(cost)                    as cost,
    sum(line_items)              as line_items,
    max(currency)                as currency
from {{ ref('int_daily_platform_service') }}
group by platform, date, month
order by date, platform
