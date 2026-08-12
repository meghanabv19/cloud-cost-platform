-- Total spend across ALL platforms per day (the cross-platform headline series).
{{ config(materialized='table') }}

select
    date,
    month,
    sum(cost)                 as total_cost,
    count(distinct platform)  as platforms_reporting,
    max(currency)             as currency
from {{ ref('int_daily_platform_service') }}
group by date, month
order by date
