SELECT
  region,
  COUNT(*) AS total_leads
FROM crm_leads
WHERE snapshot_date >= DATE '2026-01-01'
ORDER BY region;
