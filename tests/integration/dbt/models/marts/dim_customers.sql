select
  customer_id,
  segment,
  arr
from {{ source('raw', 'customers') }}

