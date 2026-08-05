CREATE DATABASE dataclaw_demo;

\connect dataclaw_demo;

CREATE TABLE customers (
  customer_id text PRIMARY KEY,
  segment text NOT NULL,
  arr numeric NOT NULL
);

CREATE TABLE products (
  product_id text PRIMARY KEY,
  family text NOT NULL,
  gross_margin numeric NOT NULL
);

CREATE TABLE orders (
  order_id text PRIMARY KEY,
  customer_id text NOT NULL REFERENCES customers(customer_id),
  product_id text NOT NULL REFERENCES products(product_id),
  net_revenue numeric NOT NULL,
  ordered_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO customers VALUES
  ('demo-acme', 'Enterprise', 248000),
  ('demo-globex', 'Mid-Market', 196500),
  ('demo-initech', 'Commercial', 121900);

INSERT INTO products VALUES
  ('platform', 'Core Platform', 0.82),
  ('governance', 'Governance', 0.76),
  ('connectors', 'Connectivity', 0.69);

INSERT INTO orders VALUES
  ('ord-001', 'demo-acme', 'platform', 148000, now()),
  ('ord-002', 'demo-acme', 'governance', 100000, now()),
  ('ord-003', 'demo-globex', 'platform', 196500, now()),
  ('ord-004', 'demo-initech', 'connectors', 121900, now());
