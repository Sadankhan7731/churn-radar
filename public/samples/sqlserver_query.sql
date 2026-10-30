-- Churn Radar: export one row per active paying customer, then save the result as CSV
-- and upload it on the Data sources page. Rename the tables/columns to match your schema.
-- Only include the columns you have; missing ones are filled with typical values.
SELECT
    c.customer_id                              AS subscriber_id,
    c.payment_channel,                         -- e.g. 'Operator 1', 'Wallet', 'Card'
    c.plan_name                                AS plan,
    c.monthly_price_pkr                        AS monthly_revenue_pkr,
    c.city, c.device_type AS device, c.network_type AS network, c.acquisition_source AS signup_source,
    v.favourite_genre,
    DATEDIFF(day, c.signup_date, GETDATE())    AS tenure_days,
    b.failed_renewals_30d, b.low_balance_renewals_30d, b.recharges_30d, b.payment_switches_90d,
    v.watch_min_prev_7d, v.watch_min_last_7d, v.watch_trend_8w_pct, v.sessions_7d,
    DATEDIFF(day, v.last_active_date, GETDATE()) AS days_since_active,
    v.completion_rate, v.distinct_titles_30d, v.category_concentration, v.live_share, v.binge_sessions_30d,
    v.fav_content_ended, v.days_to_next_release, v.catalogue_match_titles, v.recs_ignored_30d,
    q.buffering_errors_7d, q.app_crashes_7d, q.video_start_sec, q.login_failures_30d,
    h.plan_downgrades_90d, h.past_cancellations,
    m.offers_received_90d, m.offers_opened_90d, m.used_discount,
    s.support_tickets_30d, s.last_ticket_sentiment   AS ticket_sentiment, s.last_ticket_resolved AS ticket_resolved
FROM customers c
LEFT JOIN viewing_weekly   v ON v.customer_id = c.customer_id
LEFT JOIN billing_monthly  b ON b.customer_id = c.customer_id
LEFT JOIN app_quality      q ON q.customer_id = c.customer_id
LEFT JOIN plan_history     h ON h.customer_id = c.customer_id
LEFT JOIN marketing        m ON m.customer_id = c.customer_id
LEFT JOIN support_summary  s ON s.customer_id = c.customer_id
WHERE c.status = 'active';
