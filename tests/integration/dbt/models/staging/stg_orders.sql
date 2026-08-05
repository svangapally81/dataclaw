select
  order_id,
  customer_id,
  product_id,
  net_revenue,
  ordered_at
from {{ source('raw', 'orders') }}

