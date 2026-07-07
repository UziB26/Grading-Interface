SELECT
  region,
  COUNT(*) AS total_leads,
  COUNT(DISTINCT CASE WHEN status = 'won' THEN lead_id END) AS won_leads,
  ROUND(
    COUNT(DISTINCT CASE WHEN status = 'won' THEN lead_id END) * 100.0
    / NULLIF(COUNT(DISTINCT lead_id), 0),
    2
  ) AS win_rate_pct
FROM crm_leads
WHERE snapshot_date >= DATE '2026-01-01'
GROUP BY region
ORDER BY win_rate_pct DESC;
