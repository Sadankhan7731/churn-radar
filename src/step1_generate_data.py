"""
STEP 1 - Generate synthetic subscribers.

Why synthetic? Phase 1 (row 6b + rules) says real subscriber data must never
go into a hosted demo, a model provider or a public repo. So we create fake
subscribers that BEHAVE like real ones: the same kinds of columns, realistic
ranges, and churn driven by the same signals we see at work.

The trick: we decide the "true" churn rules ourselves (below). Later, if the
model rediscovers these rules, we know it is learning real patterns, not noise.

Run:  .venv/bin/python src/step1_generate_data.py
"""
import numpy as np
import pandas as pd

N = 20_000
SEED = 42                      # fixed seed = same data every run (reproducible)
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------------------
# 1. Who the subscribers are (descriptive columns)
# ---------------------------------------------------------------------------
# Payment channels: 4 mobile operators (carrier billing), a wallet and cards.
channels = ["Operator 1", "Operator 2", "Operator 3", "Operator 4", "Wallet", "Card"]
channel = rng.choice(channels, N, p=[0.30, 0.22, 0.18, 0.10, 0.12, 0.08])

# Plans and their monthly value in PKR (a daily pack renewed all month ~ PKR 300)
plans = {"Daily": 300, "Weekly": 240, "Monthly": 250, "Sports Premium": 450}
plan = rng.choice(list(plans), N, p=[0.30, 0.25, 0.30, 0.15])
monthly_revenue_pkr = np.array([plans[p] for p in plan])

city = rng.choice(["Karachi", "Lahore", "Islamabad", "Faisalabad", "Peshawar", "Other"],
                  N, p=[0.28, 0.24, 0.12, 0.08, 0.08, 0.20])
device = rng.choice(["Android", "iOS", "Smart TV", "Web"], N, p=[0.68, 0.12, 0.10, 0.10])
favourite_genre = rng.choice(["Sports", "Drama", "Movies", "Kids", "News"],
                             N, p=[0.32, 0.30, 0.20, 0.10, 0.08])
# Sports Premium subscribers are mostly sports fans
favourite_genre = np.where(plan == "Sports Premium", "Sports", favourite_genre)

# ---------------------------------------------------------------------------
# 2. How they behave (the signals the model will learn from)
# ---------------------------------------------------------------------------
tenure_days = rng.gamma(shape=2.0, scale=120, size=N).astype(int) + 1          # most are newish
watch_min_prev_7d = rng.gamma(shape=2.2, scale=140, size=N)                     # minutes, week before last
# This week's watching = last week x a change factor (most people stay similar)
change = rng.normal(1.0, 0.30, N)
watch_min_last_7d = np.clip(watch_min_prev_7d * change, 0, None)
days_since_active = np.clip(rng.exponential(3.0, N), 0, 30).astype(int)
sessions_7d = np.clip(rng.poisson(watch_min_last_7d / 45 + 0.5), 0, None)

# Carrier billing fails when the prepaid balance is low -> more failures on operators
fail_rate = np.where(np.isin(channel, ["Wallet", "Card"]), 0.25, 0.6)
failed_renewals_30d = rng.poisson(fail_rate)
support_tickets_30d = rng.poisson(0.3, N)
buffering_errors_7d = rng.poisson(np.where(device == "Smart TV", 2.5, 1.2))
used_discount = rng.random(N) < 0.18

# ---------------------------------------------------------------------------
# 3. The hidden "truth": who actually cancels in the next 30 days
# ---------------------------------------------------------------------------
# A log-odds score. Positive numbers push towards churn. These are the rules
# we will later check the model against.
watch_drop = np.clip((watch_min_prev_7d - watch_min_last_7d) / (watch_min_prev_7d + 30), -1, 1)
season_over = (favourite_genre == "Sports") & (rng.random(N) < 0.5)   # e.g. cricket series just ended

log_odds = (
    -3.35
    + 2.4 * watch_drop                              # watching less than before
    + 0.12 * days_since_active                      # been away for days
    + 0.55 * failed_renewals_30d                    # billing keeps failing
    + 0.35 * support_tickets_30d                    # had to complain
    + 0.10 * buffering_errors_7d                    # bad streaming experience
    - 0.0025 * np.minimum(tenure_days, 365)         # loyal people stay
    + 0.45 * (plan == "Daily")                      # daily packs are easy to drop
    + 0.60 * season_over                            # sports fans leave after a series
    + 0.30 * used_discount                          # discount hunters
    + rng.normal(0, 0.6, N)                         # real life is noisy
)
churn_probability = 1 / (1 + np.exp(-log_odds))
churned_next_30d = (rng.random(N) < churn_probability).astype(int)

# ---------------------------------------------------------------------------
# 4. Save. Note: no names, no phone numbers - only a made-up ID.
# ---------------------------------------------------------------------------
df = pd.DataFrame({
    "subscriber_id": [f"SUB{i:06d}" for i in range(1, N + 1)],
    "payment_channel": channel,
    "plan": plan,
    "monthly_revenue_pkr": monthly_revenue_pkr,
    "city": city,
    "device": device,
    "favourite_genre": favourite_genre,
    "tenure_days": tenure_days,
    "watch_min_prev_7d": watch_min_prev_7d.round(0),
    "watch_min_last_7d": watch_min_last_7d.round(0),
    "sessions_7d": sessions_7d,
    "days_since_active": days_since_active,
    "failed_renewals_30d": failed_renewals_30d,
    "support_tickets_30d": support_tickets_30d,
    "buffering_errors_7d": buffering_errors_7d,
    "used_discount": used_discount.astype(int),
    "sports_season_over": season_over.astype(int),
    "churned_next_30d": churned_next_30d,
})
df.to_csv("data/subscribers.csv", index=False)
# The hidden truth, kept separately: only used to measure the best score ANY model could get.
pd.DataFrame({"subscriber_id": df.subscriber_id, "true_probability": churn_probability.round(5)}) \
    .to_csv("data/true_probability.csv", index=False)

print(f"Saved {len(df):,} subscribers to data/subscribers.csv")
print(f"Churn rate: {df.churned_next_30d.mean():.1%}   (Phase 1 assumption: ~9%)")
print(f"Average revenue per subscriber: PKR {df.monthly_revenue_pkr.mean():.0f}   (Phase 1: ~250-300)")
print("\nChurn rate by plan:")
print(df.groupby("plan").churned_next_30d.mean().map("{:.1%}".format).to_string())
print("\nChurn rate by number of failed renewals:")
print(df.groupby(df.failed_renewals_30d.clip(upper=3)).churned_next_30d.mean().map("{:.1%}".format).to_string())
print("\nFirst 3 rows:")
print(df.head(3).T.to_string())
