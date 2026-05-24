select
  date_trunc('day', ordered_at) as ordered_day,
  customer_id,
  count(*) as order_count,
  sum(net_revenue) as net_revenue
from {{ ref('stg_orders') }}
group by 1, 2

