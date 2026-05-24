if db_id('dataclaw_integration') is null
begin
    create database dataclaw_integration;
end;
go

use dataclaw_integration;
go

if schema_id('core') is null exec('create schema core');
if schema_id('marketing') is null exec('create schema marketing');
if schema_id('events') is null exec('create schema events');
go

drop table if exists events.product_events;
drop table if exists core.orders;
drop table if exists marketing.campaigns;
drop table if exists core.products;
drop table if exists core.customers;
go

create table core.customers (
    id int not null primary key,
    email nvarchar(255) null,
    full_name nvarchar(255) not null,
    company nvarchar(255) null,
    plan_slug nvarchar(50) not null,
    country_code char(2) null,
    created_at datetime2 not null,
    deleted_at datetime2 null
);

create table core.products (
    id int not null primary key,
    sku nvarchar(80) not null,
    name nvarchar(255) not null,
    category nvarchar(80) not null,
    price_cents int not null,
    active bit not null
);

create table core.orders (
    id int not null primary key,
    customer_id int not null,
    status nvarchar(40) not null,
    total_cents int not null,
    currency char(3) not null,
    placed_at datetime2 not null,
    fulfilled_at datetime2 null,
    refunded_at datetime2 null
);
create index orders_customer_id_idx on core.orders(customer_id);
create index orders_placed_at_idx on core.orders(placed_at);

create table marketing.campaigns (
    id int not null primary key,
    name nvarchar(255) not null,
    platform nvarchar(80) not null,
    starts_on date not null,
    budget_usd decimal(12,2) null
);

create table events.product_events (
    id int not null primary key,
    user_id int null,
    event_type nvarchar(80) not null,
    properties nvarchar(max) null,
    created_at datetime2 not null
);
create index product_events_userid_idx on events.product_events(user_id);
create index product_events_event_type_idx on events.product_events(event_type);
go

with seq(n) as (
    select 1
    union all
    select n + 1 from seq where n < 10000
)
insert into core.customers (id, email, full_name, company, plan_slug, country_code, created_at, deleted_at)
select
    n,
    case when n % 33 = 0 then null else concat('user', n, '@dataclaw.test') end,
    concat('Customer ', n),
    concat('Company-', n % 1000),
    case n % 5 when 0 then 'enterprise' when 1 then 'pro' when 2 then 'starter' else 'free' end,
    case n % 5 when 0 then 'US' when 1 then 'GB' when 2 then 'DE' when 3 then 'IN' else 'CA' end,
    dateadd(day, -(n % 700), sysdatetime()),
    case when n % 47 = 0 then dateadd(day, -(n % 60), sysdatetime()) else null end
from seq
option (maxrecursion 0);
go

with seq(n) as (
    select 1
    union all
    select n + 1 from seq where n < 1000
)
insert into core.products (id, sku, name, category, price_cents, active)
select
    n,
    concat('SKU-', right(concat('0000', n), 4)),
    case n % 5
        when 0 then 'DataClaw Starter'
        when 1 then 'DataClaw Pro'
        when 2 then 'DataClaw Enterprise'
        when 3 then 'DataClaw Add-on Connector'
        else 'DataClaw Add-on Seat'
    end,
    case n % 3 when 0 then 'plan' when 1 then 'addon' else 'usage' end,
    1900 + (n * 137 % 30000),
    case when n % 11 = 0 then 0 else 1 end
from seq
option (maxrecursion 0);
go

with seq(n) as (
    select 1
    union all
    select n + 1 from seq where n < 50000
)
insert into core.orders (id, customer_id, status, total_cents, currency, placed_at, fulfilled_at, refunded_at)
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
    dateadd(hour, -(n * 4 % 700), sysdatetime()),
    case when n % 11 < 8 then dateadd(hour, -((n * 4 % 700) - 1), sysdatetime()) else null end,
    case when n % 100 between 5 and 10 then dateadd(hour, -(n * 4 % 690), sysdatetime()) else null end
from seq
option (maxrecursion 0);
go

with seq(n) as (
    select 1
    union all
    select n + 1 from seq where n < 200
)
insert into marketing.campaigns (id, name, platform, starts_on, budget_usd)
select
    n,
    concat('Campaign-', n),
    case n % 5 when 0 then 'google_ads' when 1 then 'meta' when 2 then 'linkedin' when 3 then 'tiktok' else 'email' end,
    cast(dateadd(day, -(n * 5 % 300), sysdatetime()) as date),
    1000 + (n * 1379 % 50000)
from seq
option (maxrecursion 0);
go

with seq(n) as (
    select 1
    union all
    select n + 1 from seq where n < 100000
)
insert into events.product_events (id, user_id, event_type, properties, created_at)
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
    concat('{"source":"sql-server-seed","version":"3.', n % 10, '"}'),
    dateadd(minute, -(n * 5 % 720), sysdatetime())
from seq
option (maxrecursion 0);
go
