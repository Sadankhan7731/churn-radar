// Churn Radar engine: runs entirely in the browser.
// Reads a customer file, maps its columns to the model's signals, scores every customer with
// the exported logistic-regression formula, and rebuilds the same summaries Step 4 produces
// in Python. Customer rows never leave the device; only aggregate facts go to the AI.
const Engine = (() => {
  // ---------------------------------------------------------------- fields the model understands
  const FIELDS = [
    ["subscriber_id", "Customer ID", "Profile", ["customer_id", "id", "subscriber", "msisdn_hash", "account_id", "user_id"]],
    ["plan", "Plan", "Profile", ["plan_name", "package", "subscription_plan", "product"]],
    ["payment_channel", "Payment channel", "Profile", ["channel", "payment_method", "billing_channel", "operator", "payment_type"]],
    ["monthly_revenue_pkr", "Monthly revenue", "Profile", ["monthly_revenue", "revenue", "arpu", "monthly_price", "price", "mrr"]],
    ["city", "City", "Profile", ["region", "location"]],
    ["device", "Device", "Profile", ["device_type", "platform", "os"]],
    ["network", "Network", "Profile", ["network_type", "connection"]],
    ["signup_source", "How they joined", "Profile", ["acquisition_source", "source", "channel_acquired", "acquisition_channel"]],
    ["favourite_genre", "Favourite genre", "Profile", ["genre", "top_genre", "favorite_genre", "category"]],
    ["tenure_days", "Days as a customer", "Profile", ["tenure", "days_since_signup", "customer_age_days", "age_days"]],
    ["watch_min_last_7d", "Minutes watched, last 7 days", "Viewing", ["watch_minutes_7d", "minutes_last_week", "watch_time_7d", "viewing_minutes"]],
    ["watch_min_prev_7d", "Minutes watched, previous 7 days", "Viewing", ["watch_minutes_prev_7d", "minutes_prev_week", "watch_time_prev_7d"]],
    ["watch_trend_8w_pct", "Viewing trend, 8 weeks (%)", "Viewing", ["watch_trend", "viewing_trend_pct", "trend_8w"]],
    ["sessions_7d", "Sessions, last 7 days", "Viewing", ["sessions", "sessions_last_week", "logins_7d"]],
    ["days_since_active", "Days since last active", "Viewing", ["days_inactive", "recency_days", "days_since_last_watch", "last_active_days"]],
    ["completion_rate", "Completion rate", "Viewing", ["completion", "episode_completion"]],
    ["distinct_titles_30d", "Distinct titles, 30 days", "Viewing", ["titles_30d", "unique_titles"]],
    ["category_concentration", "Share of viewing in top category", "Viewing", ["genre_concentration", "top_genre_share"]],
    ["live_share", "Share of live viewing", "Viewing", ["live_ratio", "live_pct"]],
    ["binge_sessions_30d", "Binge sessions, 30 days", "Viewing", ["binges"]],
    ["fav_content_ended", "Followed title has ended (0/1)", "Content", ["content_ended", "series_ended", "season_ended"]],
    ["days_to_next_release", "Days to next release in genre", "Content", ["next_release_days", "days_until_release"]],
    ["catalogue_match_titles", "Catalogue titles matching taste", "Content", ["catalog_match", "catalogue_match"]],
    ["recs_ignored_30d", "Recommendations ignored, 30 days", "Content", ["ignored_recommendations"]],
    ["failed_renewals_30d", "Failed renewals, 30 days", "Payment", ["failed_payments", "failed_renewals", "payment_failures"]],
    ["low_balance_renewals_30d", "Low-balance renewals, 30 days", "Payment", ["low_balance", "insufficient_balance"]],
    ["recharges_30d", "Recharges, 30 days", "Payment", ["topups_30d", "recharges"]],
    ["payment_switches_90d", "Payment method switches, 90 days", "Payment", ["payment_switches"]],
    ["buffering_errors_7d", "Buffering errors, 7 days", "Experience", ["buffering", "rebuffers"]],
    ["app_crashes_7d", "App crashes, 7 days", "Experience", ["crashes"]],
    ["video_start_sec", "Video start time (seconds)", "Experience", ["start_time", "startup_time", "ttff"]],
    ["login_failures_30d", "Login failures, 30 days", "Experience", ["login_failures"]],
    ["plan_downgrades_90d", "Plan downgrades, 90 days", "Plan history", ["downgrades"]],
    ["past_cancellations", "Past cancellations", "Plan history", ["previous_cancellations", "prior_churn"]],
    ["offers_received_90d", "Offers received, 90 days", "Marketing", ["offers_sent", "campaigns_received"]],
    ["offers_opened_90d", "Offers opened, 90 days", "Marketing", ["offers_opened", "campaigns_opened"]],
    ["used_discount", "Joined on a discount (0/1)", "Marketing", ["discount", "promo_user"]],
    ["support_tickets_30d", "Support tickets, 30 days", "Support", ["tickets", "complaints", "support_tickets"]],
    ["ticket_sentiment", "Last ticket sentiment", "Support", ["sentiment"]],
    ["ticket_resolved", "Last ticket resolved (0/1)", "Support", ["resolved"]],
  ];
  const CATEGORICAL = ["plan", "payment_channel", "city", "device", "network", "signup_source", "favourite_genre", "ticket_sentiment"];
  const RATES = ["completion_rate", "category_concentration", "live_share"];
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

  function autoMap(columns) {
    const map = {}, used = new Set(), cols = columns.map(c => ({ raw: c, n: norm(c) }));
    for (const [key, , , syn] of FIELDS) {
      const cands = [key, ...syn].map(norm);
      const hit = cols.find(c => !used.has(c.raw) && cands.includes(c.n)) || cols.find(c => !used.has(c.raw) && cands.some(x => x.length > 4 && c.n.includes(x)));
      if (hit) { map[key] = hit.raw; used.add(hit.raw); }
    }
    return map;
  }

  // ---------------------------------------------------------------- parsing
  function toNumber(v, key) {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "number") return isFinite(v) ? (RATES.includes(key) && v > 1 ? v / 100 : v) : null;
    const s = String(v).trim().toLowerCase();
    if (["yes", "true", "y"].includes(s)) return 1;
    if (["no", "false", "n"].includes(s)) return 0;
    const pct = s.endsWith("%");
    const n = parseFloat(s.replace(/[^0-9.\-]/g, ""));
    if (!isFinite(n)) return null;
    return pct || (RATES.includes(key) && n > 1) ? n / 100 : n;
  }
  function normalise(rawRows, map, model) {
    const means = Object.fromEntries(model.numeric.map(f => [f.name, f.mean]));
    return rawRows.map((r, i) => {
      const o = {};
      for (const [key] of FIELDS) {
        const col = map[key];
        const v = col ? r[col] : undefined;
        if (key === "subscriber_id") o.subscriber_id = v !== undefined && v !== "" ? String(v) : `ROW${String(i + 1).padStart(6, "0")}`;
        else if (CATEGORICAL.includes(key)) o[key] = v === undefined || v === null || v === "" ? null : String(v).trim();
        else { const n = toNumber(v, key); o[key] = n === null ? (means[key] ?? 0) : n; o["_has_" + key] = n !== null; }
      }
      if (o.ticket_sentiment) o.ticket_sentiment = o.ticket_sentiment.toLowerCase();
      if (!map.monthly_revenue_pkr) o.monthly_revenue_pkr = means.monthly_revenue_pkr ?? 290;
      // Same rounding as training (Step 2), so browser and Python scores match exactly
      o.watch_change_pct = map.watch_min_last_7d && map.watch_min_prev_7d ? Math.round((o.watch_min_last_7d - o.watch_min_prev_7d) / (o.watch_min_prev_7d + 30) * 1000) / 10 : means.watch_change_pct ?? 0;
      o.offer_open_rate = map.offers_received_90d && map.offers_opened_90d ? Math.round(o.offers_opened_90d / Math.max(o.offers_received_90d, 1) * 100) / 100 : means.offer_open_rate ?? 0.4;
      o.ticket_negative = o.ticket_sentiment === "negative" ? 1 : 0;
      if (!map.ticket_sentiment) o.ticket_negative = means.ticket_negative ?? 0;
      return o;
    });
  }

  // ---------------------------------------------------------------- scoring + reasons
  const R = {
    watch_change_pct: ["Watch time down {v}% vs last week", r => r.watch_change_pct <= -20, r => Math.abs(r.watch_change_pct).toFixed(0), "Viewing", "Watching much less than last week"],
    watch_trend_8w_pct: ["Viewing falling {v}% a month for 8 weeks", r => r.watch_trend_8w_pct <= -15, r => Math.abs(r.watch_trend_8w_pct).toFixed(0), "Viewing", "Slow decline over 8 weeks"],
    days_since_active: ["Inactive for {v} days", r => r.days_since_active >= 5, r => r.days_since_active.toFixed(0), "Viewing", "Inactive 5+ days"],
    completion_rate: ["Finishes only {v}% of what they start", r => r.completion_rate <= 0.4, r => (r.completion_rate * 100).toFixed(0), "Viewing", "Not finishing what they start"],
    category_concentration: ["Watches almost only one category ({v}%)", r => r.category_concentration > 0.85, r => (r.category_concentration * 100).toFixed(0), "Viewing", "Watches only one category"],
    fav_content_ended: ["The {g} title they followed has just ended", r => r.fav_content_ended >= 0.5 && r._has_fav_content_ended, () => 1, "Content", "Followed title just ended"],
    days_to_next_release: ["Next {g} release is {v} days away", r => r.fav_content_ended >= 0.5 && r.days_to_next_release >= 14 && r._has_days_to_next_release, r => r.days_to_next_release.toFixed(0), "Content", "Long wait for next release"],
    recs_ignored_30d: ["Ignored {v} recommendations this month", r => r.recs_ignored_30d >= 7, r => r.recs_ignored_30d.toFixed(0), "Content", "Ignoring recommendations"],
    failed_renewals_30d: ["{v} failed renewal(s) in 30 days", r => r.failed_renewals_30d >= 1 && r._has_failed_renewals_30d, r => r.failed_renewals_30d.toFixed(0), "Payment", "Failed renewals"],
    low_balance_renewals_30d: ["Low balance at {v} renewal(s)", r => r.low_balance_renewals_30d >= 1 && r._has_low_balance_renewals_30d, r => r.low_balance_renewals_30d.toFixed(0), "Payment", "Low balance at renewal"],
    payment_switches_90d: ["Switched payment method {v} time(s)", r => r.payment_switches_90d >= 1 && r._has_payment_switches_90d, r => r.payment_switches_90d.toFixed(0), "Payment", "Switching payment method"],
    buffering_errors_7d: ["{v} buffering errors this week", r => r.buffering_errors_7d >= 4, r => r.buffering_errors_7d.toFixed(0), "Experience", "Heavy buffering"],
    app_crashes_7d: ["App crashed {v} time(s) this week", r => r.app_crashes_7d >= 2, r => r.app_crashes_7d.toFixed(0), "Experience", "App crashes"],
    video_start_sec: ["Videos take {v}s to start", r => r.video_start_sec > 4, r => r.video_start_sec.toFixed(1), "Experience", "Slow video start"],
    plan_downgrades_90d: ["Downgraded their plan recently", r => r.plan_downgrades_90d >= 1 && r._has_plan_downgrades_90d, () => 1, "Plan history", "Recent downgrade"],
    past_cancellations: ["Has cancelled {v} time(s) before", r => r.past_cancellations >= 1 && r._has_past_cancellations, r => r.past_cancellations.toFixed(0), "Plan history", "Cancelled before"],
    offer_open_rate: ["Opens only {v}% of our offers", r => r.offers_received_90d >= 3 && r.offer_open_rate < 0.15 && r._has_offers_received_90d, r => (r.offer_open_rate * 100).toFixed(0), "Marketing", "Ignoring our offers"],
    used_discount: ["Joined or stayed on a discount", r => r.used_discount >= 0.5 && r._has_used_discount, () => 1, "Marketing", "Discount history"],
    support_tickets_30d: ["{v} support ticket(s) in 30 days", r => r.support_tickets_30d >= 1 && r._has_support_tickets_30d, r => r.support_tickets_30d.toFixed(0), "Support", "Raised a support ticket"],
    ticket_negative: ["Last support ticket was angry or negative", r => r.ticket_negative === 1 && r.ticket_sentiment, () => 1, "Support", "Negative support ticket"],
    tenure_days: ["New customer ({v} days)", r => r.tenure_days <= 60 && r._has_tenure_days, r => r.tenure_days.toFixed(0), "Profile", "New (under 60 days)"],
    sessions_7d: ["Only {v} session(s) this week", r => r.sessions_7d <= 1 && r._has_sessions_7d, r => r.sessions_7d.toFixed(0), "Viewing", "Barely opening the app"],
    plan_Daily: ["On a Daily pack (easiest to drop)", r => r.plan === "Daily", () => 1, "Profile", "On a Daily pack"],
  };

  function score(rows, model) {
    const num = Object.fromEntries(model.numeric.map(f => [f.name, f]));
    const cat = Object.fromEntries(model.categorical.map(c => [c.name, c.weights]));
    const planW = cat.plan || {}, planShare = {};
    rows.forEach(r => { if (r.plan) planShare[r.plan] = (planShare[r.plan] || 0) + 1; });
    const avgPlan = Object.entries(planShare).reduce((a, [p, n]) => a + (planW[p] || 0) * n / rows.length, 0);
    for (const r of rows) {
      let z = model.intercept;
      const contrib = {};
      for (const f of model.numeric) { const c = f.weight * (r[f.name] - f.mean) / f.scale; z += c; contrib[f.name] = c; }
      for (const c of model.categorical) z += (r[c.name] != null && c.weights[r[c.name]] !== undefined) ? c.weights[r[c.name]] : 0;
      contrib.plan_Daily = r.plan === "Daily" ? (planW.Daily || 0) - avgPlan : 0;
      contrib.days_to_next_release = Math.max(0, contrib.days_to_next_release || 0) * (r.fav_content_ended >= 0.5 ? 1 : 0);
      r.churn_score = 1 / (1 + Math.exp(-z));
      r._contrib = contrib;
    }
    return rows;
  }
  function reasons(r, k = 3) {
    const out = [];
    for (const [code, w] of Object.entries(r._contrib).filter(([c]) => R[c]).sort((a, b) => b[1] - a[1])) {
      const [text, isTrue, val, group] = R[code];
      if (w > 0 && isTrue(r)) out.push({ code, group, weight: +w.toFixed(3), text: text.replace("{v}", val(r)).replace("{g}", String(r.favourite_genre || "").toLowerCase() || "favourite") });
      if (out.length === k) break;
    }
    return out;
  }

  // ---------------------------------------------------------------- summaries (mirror of Step 4)
  const PERSONAS = [
    ["Payment-troubled", "Want to stay but billing keeps failing", r => r.failed_renewals_30d + r.low_balance_renewals_30d >= 2 && (r._has_failed_renewals_30d || r._has_low_balance_renewals_30d)],
    ["Frustrated by quality", "Buffering, crashes, slow starts or an angry ticket", r => (r.video_start_sec > 4 && r._has_video_start_sec) || (r.app_crashes_7d >= 2 && r._has_app_crashes_7d) || (r.ticket_negative === 1 && r.ticket_sentiment)],
    ["Seasonal live fans", "Came for a live event that has just ended", r => r.fav_content_ended >= 0.5 && r._has_fav_content_ended && r.live_share >= 0.6],
    ["Fading viewers", "Watching steadily less for weeks", r => (r.watch_trend_8w_pct <= -15 && r._has_watch_trend_8w_pct) || r.watch_change_pct <= -40],
    ["Discount hunters", "Joined on an offer and ignore other messages", r => r.used_discount >= 0.5 && r._has_used_discount && r.offer_open_rate < 0.3],
    ["Engaged regulars", "Everyone else: watching and paying normally", () => true],
  ];
  const FACT_COLS = ["watch_change_pct", "watch_trend_8w_pct", "days_since_active", "completion_rate", "category_concentration", "fav_content_ended",
    "days_to_next_release", "failed_renewals_30d", "low_balance_renewals_30d", "buffering_errors_7d", "app_crashes_7d", "video_start_sec",
    "support_tickets_30d", "ticket_negative", "offer_open_rate", "tenure_days", "sessions_7d"];
  const sum = (a, f) => a.reduce((s, x) => s + f(x), 0);

  function build(rows, base, meta) {
    const n = rows.length;
    rows.sort((a, b) => b.churn_score - a.churn_score);
    rows.forEach((r, i) => { r.rank = i + 1; r.band = i < n * 0.1 ? "High" : i < n * 0.3 ? "Medium" : "Low";
      r.revenue_at_risk = r.churn_score * r.monthly_revenue_pkr; r.persona = PERSONAS.find(p => p[2](r))[0]; });
    const high = rows.filter(r => r.band === "High");
    const counts = {}, theme = {};
    high.forEach(r => { const rs = reasons(r); rs.forEach(x => (counts[x.code] = (counts[x.code] || 0) + 1)); new Set(rs.map(x => x.group)).forEach(g => (theme[g] = (theme[g] || 0) + 1)); });
    const reason_summary = Object.entries(counts).map(([code, c]) => ({ code, label: R[code][4], group: R[code][3], count: c, share: +(c / high.length).toFixed(3) })).sort((a, b) => b.count - a.count);
    const theme_summary = Object.entries(theme).map(([t, c]) => ({ theme: t, share: +(c / high.length).toFixed(3), people: c })).sort((a, b) => b.share - a.share);
    const segment = key => {
      const g = {};
      rows.forEach(r => { const k = r[key]; if (k == null) return; (g[k] ||= []).push(r); });
      return Object.entries(g).map(([s, rs]) => ({ segment: s, subscribers: rs.length, avg_risk: +(sum(rs, r => r.churn_score) / rs.length).toFixed(3),
        expected_churners: Math.round(sum(rs, r => r.churn_score)), revenue_at_risk_pkr: Math.round(sum(rs, r => r.revenue_at_risk)), high_risk: rs.filter(r => r.band === "High").length }))
        .sort((a, b) => b.avg_risk - a.avg_risk);
    };
    const segments = {};
    for (const key of ["plan", "payment_channel", "favourite_genre", "signup_source", "network", "device", "city"]) {
      if (meta.map[key]) segments[key] = segment(key);
    }
    const personas = PERSONAS.map(([p, desc]) => { const g = rows.filter(r => r.persona === p);
      return { persona: p, description: desc, subscribers: g.length, avg_risk: g.length ? +(sum(g, r => r.churn_score) / g.length).toFixed(3) : 0,
        high_risk: g.filter(r => r.band === "High").length, revenue_at_risk_pkr: Math.round(sum(g, r => r.revenue_at_risk)) }; });
    let content = [];
    if (meta.map.favourite_genre && meta.map.fav_content_ended) {
      const byG = {};
      rows.forEach(r => { if (r.favourite_genre) (byG[r.favourite_genre] ||= []).push(r); });
      content = Object.entries(byG).map(([genre, g]) => { const ended = g.filter(r => r.fav_content_ended >= 0.5);
        const days = ended.map(r => r.days_to_next_release).sort((a, b) => a - b), med = days.length ? days[Math.floor(days.length / 2)] : 0;
        return { genre, ended_title: "Their followed title", ended_days_ago: 0, next_title: "Next release", next_release_in_days: Math.round(med), fans: g.length,
          fans_whose_title_ended: ended.length, high_risk_waiting: ended.filter(r => r.band === "High").length,
          avg_risk_waiting: ended.length ? +(sum(ended, r => r.churn_score) / ended.length).toFixed(3) : 0, revenue_at_risk_waiting_pkr: Math.round(sum(ended, r => r.revenue_at_risk)) }; })
        .filter(c => c.fans_whose_title_ended > 0);
    }
    const deciles = Array.from({ length: 10 }, (_, d) => { const g = rows.slice(Math.floor(n * d / 10), Math.floor(n * (d + 1) / 10));
      return { decile: d + 1, subscribers: g.length, avg_score: +(sum(g, r => r.churn_score) / Math.max(g.length, 1)).toFixed(3),
        expected_churners: +sum(g, r => r.churn_score).toFixed(3), avg_revenue: +(sum(g, r => r.monthly_revenue_pkr) / Math.max(g.length, 1)).toFixed(3) }; });
    const BANDS = [["Very high", 0.5, 1.01], ["High", 0.3, 0.5], ["Elevated", 0.15, 0.3], ["Watch", 0, 0.15]];
    const risk_bands = BANDS.map(([band, lo, hi]) => { const g = rows.filter(r => r.churn_score >= lo && r.churn_score < hi);
      return { band, from: lo, to: Math.min(hi, 1), customers: g.length, expected_leavers: Math.round(sum(g, r => r.churn_score)), revenue_at_risk_pkr: Math.round(sum(g, r => r.revenue_at_risk)) }; });
    const edges = [0, .05, .1, .15, .2, .25, .3, .35, .4, .45, .5, 1.01];
    const score_histogram = edges.slice(0, -1).map((lo, i) => ({ from: lo, to: Math.min(edges[i + 1], 1), customers: rows.filter(r => r.churn_score >= lo && r.churn_score < edges[i + 1]).length }));
    const watchlist = rows.slice(0, Math.min(500, n)).map(r => ({ id: r.subscriber_id, score: +r.churn_score.toFixed(3), rank: r.rank, plan: r.plan || "—", channel: r.payment_channel || "—",
      city: r.city || "—", genre: r.favourite_genre || "—", persona: r.persona, revenue: Math.round(r.monthly_revenue_pkr), tenure: Math.round(r.tenure_days),
      reasons: reasons(r), facts: Object.fromEntries(FACT_COLS.map(f => [f, +r[f]])) }));
    const population_avg = Object.fromEntries(FACT_COLS.map(f => [f, +(sum(rows, r => +r[f]) / n).toFixed(2)]));
    const expected = sum(rows, r => r.churn_score);
    const kpis = { subscribers: n, expected_churners: Math.round(expected), expected_churn_rate: +(expected / n).toFixed(3), high_risk_subscribers: high.length,
      revenue_at_risk_pkr: Math.round(sum(rows, r => r.revenue_at_risk)), high_risk_revenue_at_risk_pkr: Math.round(sum(high, r => r.revenue_at_risk)),
      avg_revenue_pkr: Math.round(sum(rows, r => r.monthly_revenue_pkr) / n), signals: meta.matched };
    return { ...base, kpis, reason_summary, theme_summary, segments, personas, content, deciles, risk_bands, score_histogram, watchlist, population_avg,
      dataset: { name: meta.name, source: meta.source, rows: n, matched: meta.matched, total: FIELDS.length, own: true } };
  }

  // ---------------------------------------------------------------- facts for the AI (mirror of build_facts)
  function facts(d) {
    const k = d.kpis, out = [], pct = x => Math.round(x * 100);
    const add = (key, text) => out.push({ key, text });
    add("base", `${k.subscribers.toLocaleString("en-US")} paying subscribers were scored this week.`);
    add("expected", `About ${k.expected_churners.toLocaleString("en-US")} subscribers are expected to cancel in the next 30 days (${pct(k.expected_churn_rate)}% of the base).`);
    add("revenue", `Total monthly revenue at risk is PKR ${k.revenue_at_risk_pkr.toLocaleString("en-US")}.`);
    add("high_risk", `The high-risk group is the top ${k.high_risk_subscribers.toLocaleString("en-US")} subscribers (top 10%), with PKR ${k.high_risk_revenue_at_risk_pkr.toLocaleString("en-US")} of revenue at risk.`);
    d.reason_summary.slice(0, 5).forEach((r, i) => add("reason" + (i + 1), `'${r.label}' (${r.group.toLowerCase()}) is a top reason for ${pct(r.share)}% of the high-risk group.`));
    [...(d.content || [])].sort((a, b) => b.high_risk_waiting - a.high_risk_waiting).slice(0, 3).forEach((c, i) =>
      add("content" + (i + 1), c.ended_title === "Their followed title"
        ? `${c.genre}: ${c.fans_whose_title_ended.toLocaleString("en-US")} fans' followed title has ended; the typical wait for the next ${c.genre.toLowerCase()} release is ${c.next_release_in_days} days. ${c.high_risk_waiting.toLocaleString("en-US")} of these fans are high-risk.`
        : `${c.genre}: ${c.fans_whose_title_ended.toLocaleString("en-US")} fans followed '${c.ended_title}', which ended ${c.ended_days_ago} days ago; the next release, '${c.next_title}', arrives in ${c.next_release_in_days} days. ${c.high_risk_waiting.toLocaleString("en-US")} of these fans are high-risk.`));
    [...d.personas].filter(p => p.subscribers).sort((a, b) => b.revenue_at_risk_pkr - a.revenue_at_risk_pkr).slice(0, 2).forEach((p, i) =>
      add("persona" + (i + 1), `The '${p.persona}' group (${p.description.toLowerCase()}) has ${p.subscribers.toLocaleString("en-US")} subscribers, ${p.high_risk.toLocaleString("en-US")} of them high-risk, with PKR ${p.revenue_at_risk_pkr.toLocaleString("en-US")} of monthly revenue at risk.`));
    for (const [col, label] of [["plan", "plan"], ["payment_channel", "payment channel"]]) {
      const s = d.segments[col] && d.segments[col][0];
      if (s) add("riskiest_" + col, `The riskiest ${label} is ${s.segment}: average churn risk ${pct(s.avg_risk)}%, PKR ${s.revenue_at_risk_pkr.toLocaleString("en-US")} at risk.`);
    }
    if (!d.dataset || !d.dataset.own) add("lift", `If the team contacts the top 10% by score, about ${pct(d.model.precision_top10)}% of them are real leavers, ${d.model.lift_top10} times better than contacting people at random.`);
    return out;
  }

  return { FIELDS, autoMap, normalise, score, build, facts };
})();
