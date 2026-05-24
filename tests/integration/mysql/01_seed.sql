alter user 'dataclaw'@'%' identified with mysql_native_password by 'dataclaw';
flush privileges;

set session cte_max_recursion_depth = 100000;

create table if not exists customers (
  id int primary key,
  email varchar(255),
  full_name varchar(255) not null,
  company varchar(255),
  plan_slug varchar(50) not null,
  country_code char(2),
  created_at timestamp not null,
  deleted_at timestamp null
);

create table if not exists products (
  id int primary key,
  sku varchar(80) not null,
  name varchar(255) not null,
  category varchar(80) not null,
  price_cents int not null,
  active boolean not null
);

create table if not exists orders (
  id int primary key,
  customer_id int not null,
  status varchar(40) not null,
  total_cents int not null,
  currency char(3) not null,
  placed_at timestamp not null,
  fulfilled_at timestamp null,
  refunded_at timestamp null,
  index orders_customer_id_idx (customer_id),
  index orders_placed_at_idx (placed_at)
);

create table if not exists campaigns (
  id int primary key,
  name varchar(255) not null,
  platform varchar(80) not null,
  starts_on date not null,
  budget_usd decimal(12,2)
);

create table if not exists product_events (
  id int primary key,
  user_id int,
  event_type varchar(80) not null,
  properties json,
  created_at timestamp not null,
  index product_events_userid_idx (user_id),
  index product_events_event_type_idx (event_type)
);

insert into customers (id, email, full_name, company, plan_slug, country_code, created_at, deleted_at)
with recursive seq(n) as (
  select 1
  union all
  select n + 1 from seq where n < 10000
)
select
  n,
  case when n % 33 = 0 then null else concat('user', n, '@dataclaw.test') end,
  concat('Customer ', n),
  concat('Company-', n % 1000),
  case n % 5 when 0 then 'enterprise' when 1 then 'pro' when 2 then 'starter' else 'free' end,
  case n % 5 when 0 then 'US' when 1 then 'GB' when 2 then 'DE' when 3 then 'IN' else 'CA' end,
  timestampadd(day, -(n % 700), current_timestamp),
  case when n % 47 = 0 then timestampadd(day, -(n % 60), current_timestamp) else null end
from seq
on duplicate key update email = values(email), full_name = values(full_name), plan_slug = values(plan_slug);

insert into products (id, sku, name, category, price_cents, active)
with recursive seq(n) as (
  select 1
  union all
  select n + 1 from seq where n < 1000
)
select
  n,
  concat('SKU-', lpad(n, 4, '0')),
  case n % 5
    when 0 then 'DataClaw Starter'
    when 1 then 'DataClaw Pro'
    when 2 then 'DataClaw Enterprise'
    when 3 then 'DataClaw Add-on Connector'
    else 'DataClaw Add-on Seat'
  end,
  case n % 3 when 0 then 'plan' when 1 then 'addon' else 'usage' end,
  1900 + (n * 137 % 30000),
  n % 11 != 0
from seq
on duplicate key update name = values(name), price_cents = values(price_cents), active = values(active);

insert into orders (id, customer_id, status, total_cents, currency, placed_at, fulfilled_at, refunded_at)
with recursive seq(n) as (
  select 1
  union all
  select n + 1 from seq where n < 50000
)
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
  timestampadd(hour, -(n * 4 % 700), current_timestamp),
  case when n % 11 < 8 then timestampadd(hour, -((n * 4 % 700) - 1), current_timestamp) else null end,
  case when n % 100 between 5 and 10 then timestampadd(hour, -(n * 4 % 690), current_timestamp) else null end
from seq
on duplicate key update status = values(status), total_cents = values(total_cents), placed_at = values(placed_at);

insert into campaigns (id, name, platform, starts_on, budget_usd)
with recursive seq(n) as (
  select 1
  union all
  select n + 1 from seq where n < 200
)
select
  n,
  concat('Campaign-', n),
  case n % 5 when 0 then 'google_ads' when 1 then 'meta' when 2 then 'linkedin' when 3 then 'tiktok' else 'email' end,
  date(timestampadd(day, -(n * 5 % 300), current_timestamp)),
  1000 + (n * 1379 % 50000)
from seq
on duplicate key update name = values(name), budget_usd = values(budget_usd);

insert into product_events (id, user_id, event_type, properties, created_at)
with recursive seq(n) as (
  select 1
  union all
  select n + 1 from seq where n < 100000
)
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
  json_object('source', 'mysql-seed', 'version', concat('3.', n % 10)),
  timestampadd(minute, -(n * 5 % 720), current_timestamp)
from seq
on duplicate key update event_type = values(event_type), properties = values(properties), created_at = values(created_at);
