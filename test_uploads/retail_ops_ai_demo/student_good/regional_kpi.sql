-- Student good: equivalent logic with same output
WITH region_rollup AS (
  SELECT
    region,
    COUNT(*) AS total_orders,
    SUM(CASE WHEN CAST(order_value AS REAL) >= 1000 THEN 1 ELSE 0 END) AS high_value_orders
  FROM orders_fact
  WHERE order_date >= '2026-01-01'
  GROUP BY region
)
SELECT
  region,
  total_orders,
  high_value_orders,
  ROUND(high_value_orders * 100.0 / total_orders, 2) AS high_value_rate
FROM region_rollup
ORDER BY high_value_rate DESC, region;
