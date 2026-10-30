"""
STEP 1 - Generate 100,000 synthetic subscribers.

Why synthetic? Phase 1 (row 6b + rules) says real subscriber data must never
go into a hosted demo, a model provider or a public repo. So we create fake
subscribers that BEHAVE like real ones: the same kinds of columns, realistic
ranges, and churn driven by the same signals we see at work.

The trick: we decide the "true" churn rules ourselves (section 4). Later, if the
model rediscovers these rules, we know it is learning real patterns, not noise.

Signals, in 8 groups:
  1. Profile         plan, channel, city, device, network, how they joined
  2. Payment         failed renewals, low balance at renewal, recharges, channel switches
  3. Viewing         this week vs last, 8-week trend, sessions, days away, completion,
                     variety of titles, category concentration, live vs on-demand
  4. Content         did the title they came for just end? next release in their genre?
                     how much of the catalogue fits their taste? ignored recommendations
  5. Experience      buffering, app crashes, slow video start, login failures
  6. Plan history    downgrades, past cancellations
  7. Marketing       offers received and opened, joined on a discount
  8. Support         tickets, sentiment of the ticket text, resolved or not

Run:  .venv/bin/python src/step1_generate_data.py
"""
import numpy as np
import pandas as pd

N = 100_000
SEED = 42                      # fixed seed = same data every run (reproducible)
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------------------
# 0. The content calendar (what each genre's viewers are waiting for)
# ---------------------------------------------------------------------------
# One row per genre: the big title that just ended, and the next big release.
CALENDAR = pd.DataFrame([
    {"genre": "Sports", "ended_title": "T20 International Series", "ended_days_ago": 3,
     "next_title": "National Cup", "next_release_in_days": 24, "watched_ended_share": 0.70},
    {"genre": "Drama",  "ended_title": "Season finale of a prime-time serial", "ended_days_ago": 6,
     "next_title": "New prime-time serial", "next_release_in_days": 5, "watched_ended_share": 0.55},
    {"genre": "Movies", "ended_title": "Eid movie festival", "ended_days_ago": 10,
     "next_title": "Weekly new movie", "next_release_in_days": 2, "watched_ended_share": 0.40},
    {"genre": "Kids",   "ended_title": "Animated series season", "ended_days_ago": 12,
     "next_title": "New animated season", "next_release_in_days": 18, "watched_ended_share": 0.35},
    {"genre": "News",   "ended_title": "(continuous coverage)", "ended_days_ago": 0,
     "next_title": "(continuous coverage)", "next_release_in_days": 0, "watched_ended_share": 0.0},
])
cal = CALENDAR.set_index("genre")

# ---------------------------------------------------------------------------
# 1. Profile
# ---------------------------------------------------------------------------
channels = ["Operator 1", "Operator 2", "Operator 3", "Operator 4", "Wallet", "Card"]
channel = rng.choice(channels, N, p=[0.30, 0.22, 0.18, 0.10, 0.12, 0.08])
carrier = ~np.isin(channel, ["Wallet", "Card"])

plans = {"Daily": 300, "Weekly": 240, "Monthly": 250, "Sports Premium": 450}
plan = rng.choice(list(plans), N, p=[0.30, 0.25, 0.30, 0.15])
monthly_revenue_pkr = np.array([plans[p] for p in plan])

city = rng.choice(["Karachi", "Lahore", "Islamabad", "Faisalabad", "Peshawar", "Other"],
                  N, p=[0.28, 0.24, 0.12, 0.08, 0.08, 0.20])
device = rng.choice(["Android", "iOS", "Smart TV", "Web"], N, p=[0.68, 0.12, 0.10, 0.10])
network = np.where(device == "Smart TV", "WiFi",
                   rng.choice(["4G", "3G", "WiFi"], N, p=[0.55, 0.15, 0.30]))
signup_source = rng.choice(["Operator bundle", "Social ad", "Referral", "Organic", "TV promo"],
                           N, p=[0.30, 0.25, 0.10, 0.25, 0.10])
favourite_genre = rng.choice(["Sports", "Drama", "Movies", "Kids", "News"],
                             N, p=[0.32, 0.30, 0.20, 0.10, 0.08])
favourite_genre = np.where(plan == "Sports Premium", "Sports", favourite_genre)
tenure_days = rng.gamma(shape=2.0, scale=120, size=N).astype(int) + 1

# ---------------------------------------------------------------------------
# 2. Payment behaviour
# ---------------------------------------------------------------------------
# Carrier billing fails when the prepaid balance is low at renewal time.
low_balance_renewals_30d = np.where(carrier, rng.poisson(0.7, N), 0)
failed_renewals_30d = rng.binomial(low_balance_renewals_30d + 1, np.where(carrier, 0.35, 0.15))
recharges_30d = np.where(carrier, rng.poisson(3.0, N), 0)
payment_switches_90d = rng.poisson(0.15, N)

# ---------------------------------------------------------------------------
# 3. Viewing
# ---------------------------------------------------------------------------
watch_min_prev_7d = rng.gamma(shape=2.2, scale=140, size=N)
watch_min_last_7d = np.clip(watch_min_prev_7d * rng.normal(1.0, 0.30, N), 0, None)
watch_trend_8w_pct = np.clip(rng.normal(0, 18, N), -80, 80)          # % change per month, last 8 weeks
days_since_active = np.clip(rng.exponential(3.0, N), 0, 30).astype(int)
sessions_7d = np.clip(rng.poisson(watch_min_last_7d / 45 + 0.5), 0, None)
completion_rate = np.clip(rng.beta(4, 3, N), 0, 1)                    # share of started episodes finished
distinct_titles_30d = np.clip(rng.poisson(7, N), 1, None)
category_concentration = np.clip(rng.beta(5, 2.5, N), 0.2, 1)        # share of viewing in top genre
live_share = np.where(favourite_genre == "Sports", rng.beta(5, 2, N),
                      np.where(favourite_genre == "News", rng.beta(4, 2, N), rng.beta(1.2, 6, N)))
binge_sessions_30d = rng.poisson(np.where(favourite_genre == "Drama", 2.5, 1.0))

# ---------------------------------------------------------------------------
# 4. Content (linked to the calendar)
# ---------------------------------------------------------------------------
fav_content_ended = (rng.random(N) < cal.loc[favourite_genre, "watched_ended_share"].values).astype(int)
days_to_next_release = cal.loc[favourite_genre, "next_release_in_days"].values.astype(int)
catalogue_match_titles = np.clip(rng.normal(np.where(favourite_genre == "Kids", 18, 35), 12, N), 2, 80).astype(int)
recs_ignored_30d = rng.poisson(4, N)

# ---------------------------------------------------------------------------
# 5. Experience
# ---------------------------------------------------------------------------
buffering_errors_7d = rng.poisson(np.where(network == "3G", 3.5, np.where(device == "Smart TV", 2.5, 1.0)))
app_crashes_7d = rng.poisson(np.where(device == "Android", 0.5, 0.25))
video_start_sec = np.round(np.clip(rng.gamma(2, 1.0, N) + np.where(network == "3G", 2.0, 0), 0.3, 15), 1)
login_failures_30d = rng.poisson(0.2, N)

# ---------------------------------------------------------------------------
# 6. Plan history
# ---------------------------------------------------------------------------
plan_downgrades_90d = rng.binomial(1, 0.07, N)
past_cancellations = rng.poisson(np.where(tenure_days > 180, 0.4, 0.15))

# ---------------------------------------------------------------------------
# 7. Marketing
# ---------------------------------------------------------------------------
offers_received_90d = rng.poisson(2.5, N)
offers_opened_90d = rng.binomial(offers_received_90d, rng.beta(2, 3, N))
used_discount = (rng.random(N) < np.where(signup_source == "Social ad", 0.35, 0.12)).astype(int)

# ---------------------------------------------------------------------------
# 8. Support
# ---------------------------------------------------------------------------
support_tickets_30d = rng.poisson(0.3 + 0.15 * failed_renewals_30d + 0.05 * buffering_errors_7d)
sentiment = np.where(support_tickets_30d == 0, "none",
                     rng.choice(["negative", "neutral", "positive"], N, p=[0.45, 0.40, 0.15]))
ticket_resolved = np.where(support_tickets_30d == 0, 1, (rng.random(N) < 0.65).astype(int))

# ---------------------------------------------------------------------------
# 9. The hidden "truth": who actually cancels in the next 30 days
# ---------------------------------------------------------------------------
# A log-odds score. Positive numbers push towards churn. These are the rules
# we will later check the model against. Some are deliberately non-linear
# (thresholds and interactions), which is where a boosting model can help.
watch_drop = np.clip((watch_min_prev_7d - watch_min_last_7d) / (watch_min_prev_7d + 30), -1, 1)
open_rate = np.where(offers_received_90d > 0, offers_opened_90d / np.maximum(offers_received_90d, 1), 0.5)
release_soon = (days_to_next_release <= 7) & (favourite_genre != "News")

log_odds = (
    -4.08
    # viewing
    + 1.8 * watch_drop
    + 1.3 * np.clip(-watch_trend_8w_pct / 50, 0, 1.5)       # slow decline over 8 weeks
    + 0.09 * days_since_active
    - 1.4 * (completion_rate - 0.55)                         # not finishing what they start
    - 0.03 * np.minimum(distinct_titles_30d, 20)
    + 0.7 * (category_concentration > 0.85)                  # one-category viewers
    # content
    + 0.9 * fav_content_ended * (1 + 0.9 * live_share)       # came for one live event, it ended
    - 0.7 * fav_content_ended * release_soon                 # ...unless something new arrives soon
    - 0.02 * np.minimum(catalogue_match_titles, 40)
    + 0.06 * recs_ignored_30d
    # payment
    + 0.40 * failed_renewals_30d
    + 0.30 * low_balance_renewals_30d
    + 0.30 * payment_switches_90d
    # experience
    + 0.06 * buffering_errors_7d
    + 0.15 * app_crashes_7d
    + 0.55 * (video_start_sec > 4)                           # threshold: slow starts annoy people
    + 0.12 * login_failures_30d
    # plan history
    + 0.60 * plan_downgrades_90d
    + 0.30 * past_cancellations
    # marketing
    + 0.30 * used_discount
    + 0.40 * ((offers_received_90d >= 3) & (open_rate < 0.15))   # tuning out
    # support
    + 0.20 * support_tickets_30d
    + 0.65 * (sentiment == "negative")
    - 0.35 * ((support_tickets_30d > 0) & (ticket_resolved == 1))
    # profile
    - 0.0022 * np.minimum(tenure_days, 365)
    + 0.30 * (plan == "Daily")
    + 0.25 * (signup_source == "Operator bundle")
    - 0.30 * (signup_source == "Referral")
    + rng.normal(0, 0.6, N)                                  # real life is noisy
)
churn_probability = 1 / (1 + np.exp(-log_odds))
churned_next_30d = (rng.random(N) < churn_probability).astype(int)

# ---------------------------------------------------------------------------
# 10. Save. No names, no phone numbers - only a made-up ID.
# ---------------------------------------------------------------------------
df = pd.DataFrame({
    "subscriber_id": [f"SUB{i:06d}" for i in range(1, N + 1)],
    # profile
    "payment_channel": channel, "plan": plan, "monthly_revenue_pkr": monthly_revenue_pkr,
    "city": city, "device": device, "network": network, "signup_source": signup_source,
    "favourite_genre": favourite_genre, "tenure_days": tenure_days,
    # payment
    "failed_renewals_30d": failed_renewals_30d, "low_balance_renewals_30d": low_balance_renewals_30d,
    "recharges_30d": recharges_30d, "payment_switches_90d": payment_switches_90d,
    # viewing
    "watch_min_prev_7d": watch_min_prev_7d.round(0), "watch_min_last_7d": watch_min_last_7d.round(0),
    "watch_trend_8w_pct": watch_trend_8w_pct.round(1), "sessions_7d": sessions_7d,
    "days_since_active": days_since_active, "completion_rate": completion_rate.round(2),
    "distinct_titles_30d": distinct_titles_30d, "category_concentration": category_concentration.round(2),
    "live_share": live_share.round(2), "binge_sessions_30d": binge_sessions_30d,
    # content
    "fav_content_ended": fav_content_ended, "days_to_next_release": days_to_next_release,
    "catalogue_match_titles": catalogue_match_titles, "recs_ignored_30d": recs_ignored_30d,
    # experience
    "buffering_errors_7d": buffering_errors_7d, "app_crashes_7d": app_crashes_7d,
    "video_start_sec": video_start_sec, "login_failures_30d": login_failures_30d,
    # plan history
    "plan_downgrades_90d": plan_downgrades_90d, "past_cancellations": past_cancellations,
    # marketing
    "offers_received_90d": offers_received_90d, "offers_opened_90d": offers_opened_90d,
    "used_discount": used_discount,
    # support
    "support_tickets_30d": support_tickets_30d, "ticket_sentiment": sentiment,
    "ticket_resolved": ticket_resolved,
    # target
    "churned_next_30d": churned_next_30d,
})
df.to_csv("data/subscribers.csv.gz", index=False)
CALENDAR.to_csv("data/content_calendar.csv", index=False)
# The hidden truth, kept separately: only used to measure the best score ANY model could get.
pd.DataFrame({"subscriber_id": df.subscriber_id, "true_probability": churn_probability.round(5)}) \
    .to_csv("data/true_probability.csv.gz", index=False)

print(f"Saved {len(df):,} subscribers x {df.shape[1] - 2} signals to data/subscribers.csv.gz")
print(f"Churn rate: {df.churned_next_30d.mean():.1%}   (Phase 1 assumption: ~9%)")
print(f"Average revenue per subscriber: PKR {df.monthly_revenue_pkr.mean():.0f}")
print("\nChurn rate by group (sanity check of the true rules):")
checks = {
    "Favourite title just ended": df.fav_content_ended == 1,
    "  ...and a new release within 7 days": (df.fav_content_ended == 1) & (df.days_to_next_release.between(1, 7)),
    "  ...and next release 18+ days away": (df.fav_content_ended == 1) & (df.days_to_next_release >= 18),
    "2+ failed renewals": df.failed_renewals_30d >= 2,
    "Negative support ticket": df.ticket_sentiment == "negative",
    "Video start slower than 4s": df.video_start_sec > 4,
    "Watches mostly one category (>85%)": df.category_concentration > 0.85,
    "Referral sign-ups": df.signup_source == "Referral",
    "Everyone": df.churned_next_30d >= 0,
}
for label, mask in checks.items():
    print(f"  {label:42s} {df.loc[mask, 'churned_next_30d'].mean():6.1%}   ({mask.sum():,} subscribers)")
print("\nContent calendar:")
print(CALENDAR[["genre", "ended_title", "ended_days_ago", "next_title", "next_release_in_days"]].to_string(index=False))
