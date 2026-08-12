-- Daily rollup per platform + service + unit. Keeps `unit` in the grain because
-- quantities across units aren't additive (minutes vs hours vs requests), while
-- cost is always in currency and safely summable.
select
    platform,
    service,
    date,
    month,
    unit,
    sum(quantity)                       as quantity,
    sum(cost)                           as cost,
    count(*)                            as line_items,
    max(currency)                       as currency
from {{ ref('stg_usage_facts') }}
group by platform, service, date, month, unit
