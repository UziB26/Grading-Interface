-- Regional KPI benchmark query
SELECT
  region,
  COUNT(*) AS total_orders,
  SUM(CASE WHEN CAST(order_value AS REAL) >= 1000 THEN 1 ELSE 0 END) AS high_value_orders,
  ROUND(
    SUM(CASE WHEN CAST(order_value AS REAL) >= 1000 THEN 1 ELSE 0 END) * 100.0
    / COUNT(*),
    2
  ) AS high_value_rate
FROM orders_fact
WHERE order_date >= '2026-01-01'
GROUP BY region
ORDER BY high_value_rate DESC, region;
