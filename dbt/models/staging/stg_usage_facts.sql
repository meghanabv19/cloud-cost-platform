-- Light cleaning of the raw fact table: stable types, trimmed strings,
-- a coalesced service label, and a month bucket for rollups.
with src as (
    select * from {{ source('warehouse', 'usage_facts') }}
)
select
    row_key,
    platform,
    coalesce(nullif(trim(resource), ''), 'unknown')      as resource,
    coalesce(nullif(trim(service), ''), platform)        as service,
    nullif(trim(sku), '')                                as sku,
    nullif(trim(project), '')                            as project,
    nullif(trim(region), '')                             as region,
    cast(date as date)                                   as date,
    date_trunc('month', cast(date as date))              as month,
    quantity,
    coalesce(nullif(trim(unit), ''), 'unit')             as unit,
    cost,                       -- may be null (metric-only sources)
    coalesce(currency, 'USD')                            as currency,
    meta,
    ingested_at
from src
