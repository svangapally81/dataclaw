create schema if not exists memory.core;
create schema if not exists memory.marketing;
create schema if not exists memory.events;

drop table if exists memory.events.product_events;
drop table if exists memory.core.orders;
drop table if exists memory.marketing.campaigns;
drop table if exists memory.core.products;
drop table if exists memory.core.customers;

create table memory.core.customers (
    id integer,
    email varchar,
    full_name varchar,
    company varchar,
    plan_slug varchar,
    country_code varchar,
    created_at timestamp,
    deleted_at timestamp
);

insert into memory.core.customers
select
    n,
    if(n % 33 = 0, null, 'user' || cast(n as varchar) || '@dataclaw.test'),
    'Customer ' || cast(n as varchar),
    'Company-' || cast(n % 1000 as varchar),
    case n % 5 when 0 then 'enterprise' when 1 then 'pro' when 2 then 'starter' else 'free' end,
    case n % 5 when 0 then 'US' when 1 then 'GB' when 2 then 'DE' when 3 then 'IN' else 'CA' end,
    current_timestamp - ((n % 700) * interval '1' day),
    if(n % 47 = 0, current_timestamp - ((n % 60) * interval '1' day), null)
from unnest(sequence(1, 10000)) as t(n);

create table memory.core.products (
    id integer,
    sku varchar,
    name varchar,
    category varchar,
    price_cents integer,
    active boolean
);

insert into memory.core.products
select
    n,
    'SKU-' || lpad(cast(n as varchar), 4, '0'),
    case n % 5
        when 0 then 'DataClaw Starter'
        when 1 then 'DataClaw Pro'
        when 2 then 'DataClaw Enterprise'
        when 3 then 'DataClaw Add-on Connector'
        else 'DataClaw Add-on Seat'
    end,
    case n % 3 when 0 then 'plan' when 1 then 'addon' else 'usage' end,
    1900 + (n * 137 % 30000),
    n % 11 <> 0
from unnest(sequence(1, 1000)) as t(n);

create table memory.core.orders (
    id integer,
    customer_id integer,
    status varchar,
    total_cents integer,
    currency varchar,
    placed_at timestamp,
    fulfilled_at timestamp,
    refunded_at timestamp
);

insert into memory.core.orders
select
    n,
    1 + (n * 13 % 10000),
    case
        when n % 100 = 0 then 'stuck_in_3ds'
        when n % 100 in (1, 2) then 'canceled'
        when n % 100 in (3, 4) then 'pending'
        when n % 100 between 5 and 10 then 'refunded'
        else 'fulfilled'
    end,
    2900 + (n * 379 % 95000),
    case n % 5 when 0 then 'USD' when 1 then 'USD' when 2 then 'EUR' when 3 then 'GBP' else 'CAD' end,
    current_timestamp - ((n * 4 % 700) * interval '1' hour),
    if(n % 11 < 8, current_timestamp - (((n * 4 % 700) - 1) * interval '1' hour), null),
    if(n % 100 between 5 and 10, current_timestamp - ((n * 4 % 690) * interval '1' hour), null)
from (
    select base.n + (batch.k * 10000) as n
    from unnest(sequence(1, 10000)) as base(n)
    cross join unnest(sequence(0, 4)) as batch(k)
) as t;

create table memory.marketing.campaigns (
    id integer,
    name varchar,
    platform varchar,
    starts_on date,
    budget_usd decimal(12, 2)
);

insert into memory.marketing.campaigns
select
    n,
    'Campaign-' || cast(n as varchar),
    case n % 5 when 0 then 'google_ads' when 1 then 'meta' when 2 then 'linkedin' when 3 then 'tiktok' else 'email' end,
    cast(current_timestamp - ((n * 5 % 300) * interval '1' day) as date),
    cast(1000 + (n * 1379 % 50000) as decimal(12, 2))
from unnest(sequence(1, 200)) as t(n);

create table memory.events.product_events (
    id integer,
    user_id integer,
    event_type varchar,
    properties varchar,
    created_at timestamp
);

insert into memory.events.product_events
select
    n,
    1 + (n * 7 % 10000),
    case n % 10
        when 0 then 'signup'
        when 1 then 'signed_up'
        when 2 then 'verified_email'
        when 3 then 'created_first_workspace'
        when 4 then 'imported_first_dataset'
        when 5 then 'ran_first_query'
        when 6 then 'checkout_started'
        when 7 then 'checkout_completed'
        when 8 then 'agent_run_completed'
        else 'session_started'
    end,
    '{"source":"trino-seed","version":"3.' || cast(n % 10 as varchar) || '"}',
    current_timestamp - ((n * 5 % 720) * interval '1' minute)
from (
    select base.n + (batch.k * 10000) as n
    from unnest(sequence(1, 10000)) as base(n)
    cross join unnest(sequence(0, 9)) as batch(k)
) as t;
