// What-if simulator. Re-scores customers under a scenario using the same logistic-regression
// formula as the live model, so every number is the model's estimate, not a rule of thumb.
// Because the model is linear in its signals, a change to a signal moves each customer's
// log-odds by  weight x (new - old) / spread,  which we add to their baseline score.
const Sim = (() => {
  let M, rows = [], S = 1, W = {}, CAT = {}, revMonthly = 250;

  function prepare(model, data, scale) {
    M = model; S = scale; rows = data;
    W = Object.fromEntries(model.numeric.map(f => [f.name, f]));
    CAT = Object.fromEntries(model.categorical.map(c => [c.name, c.weights]));
    const monthly = rows.filter(r => r.plan === "Monthly");
    revMonthly = monthly.length ? monthly.reduce((a, r) => a + r.monthly_revenue_pkr, 0) / monthly.length : 250;
    for (const r of rows) r._z0 = Math.log(r.churn_score / (1 - r.churn_score));
  }
  const dz = (f, from, to) => (W[f] ? W[f].weight * (to - from) / W[f].scale : 0);
  const sig = z => 1 / (1 + Math.exp(-z));

  // Each lever: who it affects, and how it changes their log-odds (and revenue, for plan moves).
  const LEVERS = [
    { id: "pay", name: "Fix failed payments", team: "Billing", desc: "Retry renewals after top-ups, balance reminders, wallet fallback.",
      control: { kind: "pct", label: "Failed and low-balance renewals prevented", min: 10, max: 90, step: 5, def: 40 },
      hits: r => r.failed_renewals_30d > 0 || r.low_balance_renewals_30d > 0,
      dz: (r, x) => dz("failed_renewals_30d", r.failed_renewals_30d, r.failed_renewals_30d * (1 - x)) + dz("low_balance_renewals_30d", r.low_balance_renewals_30d, r.low_balance_renewals_30d * (1 - x)) },
    { id: "start", name: "Faster video start", team: "Product", desc: "Adaptive start quality and CDN tuning on slow networks.",
      control: { kind: "value", label: "Cap start time at", unit: "s", min: 2, max: 6, step: 0.5, def: 3 },
      hits: (r, v) => r.video_start_sec > v,
      dz: (r, v) => dz("video_start_sec", r.video_start_sec, Math.min(r.video_start_sec, v)) },
    { id: "buffer", name: "Cut buffering and crashes", team: "Product", desc: "Player fixes and device-specific crash work.",
      control: { kind: "pct", label: "Reduction in buffering and crashes", min: 10, max: 80, step: 5, def: 30 },
      hits: r => r.buffering_errors_7d > 0 || r.app_crashes_7d > 0,
      dz: (r, x) => dz("buffering_errors_7d", r.buffering_errors_7d, r.buffering_errors_7d * (1 - x)) + dz("app_crashes_7d", r.app_crashes_7d, r.app_crashes_7d * (1 - x)) },
    { id: "support", name: "Resolve angry tickets fast", team: "Support", desc: "Senior call-back within 24 hours on negative tickets.",
      control: { kind: "pct", label: "Negative tickets turned around", min: 10, max: 90, step: 5, def: 50 },
      hits: r => r.ticket_negative >= 0.5,
      dz: (r, x) => dz("ticket_negative", r.ticket_negative, r.ticket_negative * (1 - x)) + dz("ticket_resolved", r.ticket_resolved, r.ticket_resolved + (1 - r.ticket_resolved) * x) },
    { id: "content", name: "Bring the next release forward", team: "Content", desc: "Schedule, highlights or acquisitions to close content gaps.",
      control: { kind: "value", label: "Next release within", unit: " days", min: 0, max: 21, step: 1, def: 7 },
      hits: (r, v) => r.fav_content_ended >= 0.5 && r.days_to_next_release > v,
      dz: (r, v) => dz("days_to_next_release", r.days_to_next_release, Math.min(r.days_to_next_release, v)) },
    { id: "engage", name: "Win back falling viewing", team: "Marketing", desc: "Personal recommendations and re-engagement journeys.",
      control: { kind: "pct", label: "Share of the viewing decline recovered", min: 10, max: 80, step: 5, def: 30 },
      hits: r => r.watch_change_pct < 0 || r.watch_trend_8w_pct < 0,
      dz: (r, x) => dz("watch_change_pct", r.watch_change_pct, r.watch_change_pct < 0 ? r.watch_change_pct * (1 - x) : r.watch_change_pct)
                  + dz("watch_trend_8w_pct", r.watch_trend_8w_pct, r.watch_trend_8w_pct < 0 ? r.watch_trend_8w_pct * (1 - x) : r.watch_trend_8w_pct) },
    { id: "plan", name: "Move Daily packs to Monthly", team: "Pricing", desc: "Upgrade offer for daily-pack customers. Changes revenue per customer too.",
      control: { kind: "pct", label: "Daily-pack customers who switch", min: 5, max: 60, step: 5, def: 20 },
      hits: r => r.plan === "Daily",
      dz: (r, x) => x * (((CAT.plan || {}).Monthly ?? 0) - ((CAT.plan || {}).Daily ?? 0)),
      rev: (r, x) => r.monthly_revenue_pkr + x * (revMonthly - r.monthly_revenue_pkr) },
  ];

  const ctl = (lever, v) => (lever.control.kind === "pct" ? v / 100 : v);

  // Apply a set of levers; returns per-customer new probability and revenue.
  function applyLevers(settings, only) {
    const active = LEVERS.filter(l => settings[l.id] && settings[l.id].on && (!only || l.id === only));
    let E0 = 0, E1 = 0, keep0 = 0, keep1 = 0, affected = 0;
    const out = new Array(rows.length);
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i]; let z = r._z0, rev = r.monthly_revenue_pkr, hit = false;
      for (const l of active) {
        const v = ctl(l, settings[l.id].value);
        if (l.hits(r, v)) { z += l.dz(r, v); if (l.rev) rev = l.rev(r, v); hit = true; }
      }
      const p0 = r.churn_score, p1 = hit ? sig(z) : p0;
      E0 += p0; E1 += p1; keep0 += r.monthly_revenue_pkr * (1 - p0); keep1 += rev * (1 - p1); affected += hit;
      out[i] = { p: p1, rev };
    }
    return { out, E0: E0 * S, E1: E1 * S, revGain: (keep1 - keep0) * S, affected: affected * S };
  }

  // Campaign on top of the levers: contact the N highest-risk customers (N in full-base units).
  function campaign(out, N, save, disc, take) {
    const order = out.map((o, i) => i).sort((a, b) => out[b].p - out[a].p);
    const n = Math.min(order.length, Math.round(N / S));
    let leavers = 0, revKept = 0, revSum = 0;
    for (let k = 0; k < n; k++) { const o = out[order[k]]; leavers += o.p; revKept += o.p * save * o.rev; revSum += o.rev; }
    const avgRev = n ? revSum / n : 0, saved = leavers * save;
    const cost = (n - leavers + saved) * take * avgRev * disc;
    return { contacted: n * S, leavers: leavers * S, saved: saved * S, revKept: revKept * S, cost: cost * S };
  }

  // Goal seek: smallest audience whose campaign (on top of the levers) meets the target.
  function goal(out, kind, target, save, disc, take, alreadyKept, alreadyRev) {
    const order = out.map((o, i) => i).sort((a, b) => out[b].p - out[a].p);
    let leavers = 0, revKept = 0, revSum = 0;
    const need = kind === "customers" ? target - alreadyKept : target - alreadyRev;
    if (need <= 0) return { reached: true, contacted: 0, cost: 0, byLevers: true };
    for (let k = 0; k < order.length; k++) {
      const o = out[order[k]]; leavers += o.p; revKept += o.p * save * o.rev; revSum += o.rev;
      const got = (kind === "customers" ? leavers * save : revKept) * S;
      if (got >= need) {
        const n = k + 1, saved = leavers * save, cost = (n - leavers + saved) * take * (revSum / n) * disc * S;
        return { reached: true, contacted: n * S, saved: saved * S, revKept: revKept * S, cost };
      }
    }
    return { reached: false, max: (kind === "customers" ? leavers * save : revKept) * S, contacted: order.length * S };
  }

  function run(settings, camp) {
    const all = applyLevers(settings);
    const perLever = LEVERS.filter(l => settings[l.id] && settings[l.id].on).map(l => {
      const one = applyLevers(settings, l.id), cost = +settings[l.id].cost || 0;
      return { id: l.id, name: l.name, team: l.team, affected: one.affected, avoided: one.E0 - one.E1, revGain: one.revGain, cost,
        roi: cost ? (one.revGain - cost) / cost : null };
    });
    const c = camp.on ? campaign(all.out, camp.n, camp.save, camp.disc, camp.take) : { contacted: 0, leavers: 0, saved: 0, revKept: 0, cost: 0 };
    const leverCost = perLever.reduce((a, l) => a + l.cost, 0);
    const kept = all.E0 - all.E1 + c.saved, gain = all.revGain + c.revKept, cost = leverCost + c.cost;
    return { base: { E: all.E0, size: rows.length * S }, afterLevers: all.E1, final: all.E1 - c.saved, kept, gain, cost, net: gain - cost,
      leverGain: all.revGain, leverAvoided: all.E0 - all.E1, leverCost, campaign: c, perLever, out: all.out };
  }

  const affectedCount = (lever, v) => rows.reduce((a, r) => a + (lever.hits(r, ctl(lever, v)) ? 1 : 0), 0) * S;
  return { prepare, run, goal, LEVERS, affectedCount, get size() { return rows.length * S; }, get ready() { return rows.length > 0; } };
})();
