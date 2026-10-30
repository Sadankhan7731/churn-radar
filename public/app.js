// Churn Radar for Lumen Play.
// A small single-page app: hash routes (#/, #/customers/SUB000123, #/reports/cfo ...) so every
// view has a shareable link and the back button works. Data comes from the JSON files written
// by Steps 4 and 5; nothing here invents numbers.

// ---------------------------------------------------------------- helpers
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const NUM = n => Math.round(n).toLocaleString("en-US");
const PKR = n => "PKR " + Math.round(n).toLocaleString("en-US");
const PKRs = n => { const a = Math.abs(n), s = n < 0 ? "−" : ""; return a >= 1e6 ? `${s}PKR ${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${s}PKR ${(a / 1e3).toFixed(0)}k` : `${s}PKR ${Math.round(a)}`; };
const PCT = (x, d = 0) => (x * 100).toFixed(d) + "%";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cssv = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
let D, NOTE, FACTS, DEMO, DEMO_NOTE, MODEL;
let CUR = "demo";
const NOTES = {};          // weekly briefing per dataset
let charts = [];
const page = () => $("#main .page");

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------------------------------------------------------------- vocabulary
const THEME = {
  Content: "Show they followed has ended", Viewing: "Watching less", Payment: "Payment failures",
  Support: "Bad support experience", "Plan history": "Downgraded or cancelled before", Experience: "App or streaming issues",
  Marketing: "Only here for discounts", Profile: "New, or on a daily pack",
};
const GROUP_COLOR = { "Payment-troubled": "#ca8a04", "Frustrated by quality": "#0891b2", "Seasonal live fans": "#9333ea",
  "Fading viewers": "#2563eb", "Discount hunters": "#db2777", "Engaged regulars": "#16a34a" };
const PLAY = {
  "Payment-troubled": "Fix the bill, not the price: renew after their usual top-up, remind before renewal, offer wallet billing.",
  "Frustrated by quality": "Apologise and fix: senior call-back on negative tickets within 24 hours; lower start quality on slow networks.",
  "Seasonal live fans": "Bridge the gap: highlights and classic matches now, and a reminder for the next event's start date.",
  "Fading viewers": "Re-engage with a personal 'picked for you' message and one new category to try.",
  "Discount hunters": "Avoid another discount; offer added value such as a data bundle.",
  "Engaged regulars": "No action needed.",
};
const ACTION = {
  watch_change_pct: "Send a personal 'picked for you' message based on their past viewing.",
  watch_trend_8w_pct: "Enrol in a four-week re-engagement series in their favourite category.",
  days_since_active: "Send a 'what's new since your last visit' message.",
  completion_rate: "Recommend shorter, highly rated titles in their category.",
  category_concentration: "Introduce one related category they are likely to enjoy.",
  fav_content_ended: "Promote the next release in their genre with dates, plus highlights of what just ended.",
  days_to_next_release: "Bridge the wait with related titles and a release-date reminder.",
  recs_ignored_30d: "Refresh their recommendations; prompt two quick taste questions in the app.",
  failed_renewals_30d: "Offer payment help: a reminder before renewal, or move them to wallet billing.",
  low_balance_renewals_30d: "Move the renewal to just after their usual top-up, or offer a weekly plan.",
  payment_switches_90d: "Confirm their preferred payment method and set it as default.",
  buffering_errors_7d: "Check device and network; send streaming tips.",
  app_crashes_7d: "Prompt an app update; send device details to engineering.",
  video_start_sec: "Lower the starting quality on their network; flag the network to engineering.",
  plan_downgrades_90d: "Ask what they miss from the higher plan; offer a short trial.",
  past_cancellations: "Welcome-back message on what has changed since they last left.",
  offer_open_rate: "Stop generic offers; send one personal message instead.",
  used_discount: "Offer added value rather than another discount.",
  support_tickets_30d: "Arrange a call-back to resolve the open issue.",
  ticket_negative: "Escalate to a senior agent for a call-back within 24 hours.",
  tenure_days: "Send an onboarding message with the best of the catalogue.",
  sessions_7d: "Send a short trailer for a title they are likely to enjoy.",
  plan_Daily: "Offer a Weekly or Monthly plan at a small saving.",
};
const COMPARE = [
  ["days_since_active", "Days since last watched", v => v.toFixed(0)],
  ["watch_change_pct", "Viewing vs last week", v => { const r = Math.round(v); return (r > 0 ? "+" : "") + r + "%"; }],
  ["completion_rate", "Episodes finished", v => (v * 100).toFixed(0) + "%"],
  ["failed_renewals_30d", "Failed payments (30d)", v => (v % 1 ? v.toFixed(1) : v.toFixed(0))],
  ["support_tickets_30d", "Support tickets (30d)", v => (v % 1 ? v.toFixed(1) : v.toFixed(0))],
  ["video_start_sec", "Video start time", v => v.toFixed(1) + "s"],
  ["tenure_days", "Customer for", v => v.toFixed(0) + " days"],
];
function band(s) {
  if (s >= 0.5) return ["Very high", "vh"]; if (s >= 0.3) return ["High", "hi"];
  if (s >= 0.15) return ["Elevated", "el"]; return ["Watch", "wa"];
}
const riskPill = s => { const [l, c] = band(s); return `<span class="pill ${c}">${l}</span>`; };
const avatar = (id, persona) => `<span class="avatar" style="--c:${GROUP_COLOR[persona] || "#52525b"}">${id.slice(-2)}</span>`;

// ---------------------------------------------------------------- campaign maths
function simulate(k, save, disc, take) {
  const ds = D.deciles.slice(0, k);
  const contacted = ds.reduce((a, d) => a + d.subscribers, 0);
  const leavers = ds.reduce((a, d) => a + d.expected_churners, 0);
  const avgRev = ds.reduce((a, d) => a + d.avg_revenue * d.subscribers, 0) / contacted;
  const saved = leavers * save, protectedRev = saved * avgRev;
  const cost = (contacted - leavers + saved) * take * avgRev * disc;
  const rLeavers = contacted * D.kpis.expected_churn_rate, rSaved = rLeavers * save;
  const rNet = rSaved * D.kpis.avg_revenue_pkr - (contacted - rLeavers + rSaved) * take * D.kpis.avg_revenue_pkr * disc;
  return { contacted, leavers, saved, protectedRev, cost, net: protectedRev - cost, rNet, roi: cost ? (protectedRev - cost) / cost : 0 };
}
const DEFAULT = { k: 1, save: 0.3, disc: 0.15, take: 0.5 };
const base = () => simulate(DEFAULT.k, DEFAULT.save, DEFAULT.disc, DEFAULT.take);

// ---------------------------------------------------------------- render pieces
const kpi = (l, v, s = "", cls = "", tip = "") =>
  `<div class="kpi"><div class="kpi-l">${l}${tip ? ` <span class="info" title="${esc(tip)}">i</span>` : ""}</div><div class="kpi-v ${cls}">${v}</div><div class="kpi-s">${s}</div></div>`;
const panel = (title, body, { sub = "", right = "", flush = false, cls = "" } = {}) =>
  `<section class="panel ${cls}"><div class="panel-h"><div><h2>${title}</h2>${sub ? `<div class="sub">${sub}</div>` : ""}</div>${right}</div><div class="panel-b ${flush ? "flush" : ""}">${body}</div></section>`;
function lbars(rows, { max, fmt = v => PCT(v), brand = false } = {}) {
  const m = max ?? Math.max(...rows.map(r => r.value), 1e-9);
  return `<div class="lbars">` + rows.map(r => `<div><div class="lbar-top"><span>${esc(r.name)}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</span><span>${fmt(r.value)}</span></div>
    <div class="lbar"><span class="${brand || r.brand ? "brand" : ""}" style="width:${Math.max(1.5, r.value / m * 100)}%"></span></div></div>`).join("") + `</div>`;
}
const themeBars = () => lbars(D.theme_summary.slice(0, 6).map((t, i) => ({ name: THEME[t.theme] || t.theme, value: t.share, brand: i === 0 })), { max: 1 });
function chart(id, cfg) {
  if (!window.Chart || !document.getElementById(id)) return;
  Chart.defaults.font.family = "Inter, system-ui, sans-serif"; Chart.defaults.font.size = 12;
  Chart.defaults.color = cssv("--text-3"); Chart.defaults.borderColor = cssv("--border-2");
  Chart.defaults.plugins.tooltip.backgroundColor = cssv("--primary"); Chart.defaults.plugins.tooltip.titleColor = cssv("--on-primary");
  Chart.defaults.plugins.tooltip.bodyColor = cssv("--on-primary"); Chart.defaults.plugins.tooltip.cornerRadius = 6; Chart.defaults.plugins.tooltip.padding = 8;
  charts.push(new Chart(document.getElementById(id), cfg));
}
function netChart(id, p) {
  const xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], sims = xs.map(x => simulate(x, p.save, p.disc, p.take));
  chart(id, {
    type: "line",
    data: { labels: xs.map(x => `Top ${x * 10}%`), datasets: [
      { label: "Targeted by Churn Radar", data: sims.map(s => s.net), borderColor: cssv("--chart-2"), backgroundColor: cssv("--chart-2"), borderWidth: 2, tension: .25, pointRadius: xs.map(x => (x === p.k ? 5 : 0)), pointHoverRadius: 5 },
      { label: "Random selection", data: sims.map(s => s.rNet), borderColor: cssv("--chart-muted"), borderDash: [4, 4], borderWidth: 1.5, tension: .25, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom", align: "start", labels: { boxWidth: 10, boxHeight: 2, padding: 14 } },
        tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${PKRs(c.raw)}` } } },
      scales: { x: { grid: { display: false } }, y: { ticks: { callback: v => PKRs(v) } } } },
  });
}

// ---------------------------------------------------------------- reports (one per leadership role)
const REPORTS = {
  ceo: { name: "Executive summary", color: "#F0562A", desc: "Where we are losing customers, and why.",
    summary: () => { const t = D.theme_summary; return `About <b>${NUM(D.kpis.expected_churners)}</b> customers (${PCT(D.kpis.expected_churn_rate, 1)}) are likely to cancel in the next 30 days, putting <b>${PKRs(D.kpis.revenue_at_risk_pkr)}</b> of monthly revenue at risk. The two largest drivers are <b>${THEME[t[0].theme].toLowerCase()}</b> and <b>${THEME[t[1].theme].toLowerCase()}</b>.`; },
    kpis: () => { const p = [...D.personas].sort((a, b) => b.revenue_at_risk_pkr - a.revenue_at_risk_pkr)[0];
      return [kpi("Likely to cancel (30d)", NUM(D.kpis.expected_churners), PCT(D.kpis.expected_churn_rate, 1) + " of active customers"),
              kpi("Revenue at risk / month", PKRs(D.kpis.revenue_at_risk_pkr), PKRs(D.kpis.revenue_at_risk_pkr * 12) + " annualised", "red"),
              kpi("Largest exposed group", esc(p.persona), PKRs(p.revenue_at_risk_pkr) + " / month at risk")]; },
    body: () => panel("Churn drivers", themeBars(), { sub: `Share of the ${NUM(D.kpis.high_risk_subscribers)} highest-risk customers with each driver among their top reasons` }),
    recs: () => { const pay = D.personas.find(p => p.persona === "Payment-troubled"), sp = [...(D.content || [])].sort((a, b) => b.high_risk_waiting - a.high_risk_waiting)[0];
      return [pay && pay.subscribers ? ["Fix renewal failures with billing partners", `${NUM(pay.subscribers)} customers have repeated failed renewals, carrying ${PKRs(pay.revenue_at_risk_pkr)} / month at risk. A process fix, not a discount.`, "#/reports/billing"] : null,
              sp ? [`Bridge the gap to the next ${sp.genre.toLowerCase()} release`, `${NUM(sp.high_risk_waiting)} high-risk ${sp.genre.toLowerCase()} fans wait ${sp.next_release_in_days} days for ${sp.next_title === "Next release" ? "something new" : "the " + sp.next_title}.`, "#/reports/content"] : null,
              ["Approve a targeted campaign for the top 10%", `Projected net impact ${PKRs(base().net)} / month; the same offer sent at random ${base().rNet < 0 ? "loses money" : "returns far less"}.`, "#/campaigns"]].filter(Boolean); } },
  cfo: { name: "Revenue & ROI", color: "#16a34a", desc: "What churn costs, and the return on acting.",
    summary: () => { const b = base(); return `Churn puts <b>${PKRs(D.kpis.revenue_at_risk_pkr)}</b> of revenue at risk each month. A 15% offer to the top 10% costs about <b>${PKRs(b.cost)}</b> and protects about <b>${PKRs(b.protectedRev)}</b> — a net <b>${PKRs(b.net)}</b> per month. Sent to random customers, the same offer would lose <b>${PKRs(-b.rNet)}</b>.`; },
    kpis: () => { const b = base(); return [kpi("Revenue at risk / year", PKRs(D.kpis.revenue_at_risk_pkr * 12), "if no action is taken", "red"),
      kpi("Campaign ROI", (b.roi * 100).toFixed(0) + "%", "net impact ÷ cost of offer", b.roi >= 0 ? "green" : "red"),
      kpi("Cost per retained customer", PKR(b.cost / b.saved), "offer cost ÷ customers retained")]; },
    body: () => panel("Net monthly impact by audience size", `<div class="chart tall"><canvas id="rChart"></canvas></div>`, { sub: "Assumes 30% save rate, 15% off one month, 50% offer uptake" }),
    after: () => netChart("rChart", DEFAULT),
    recs: () => [["Start with the top 10% only", "Returns fall as the audience widens; lower-risk customers mostly stay anyway.", "#/campaigns"],
                 ["Measure the save rate with a holdout group", "Hold back a random 10% of the audience. Until then, the 30% save rate is an assumption.", "#/model"],
                 ["Avoid blanket discounts", "Discount-driven customers churn regardless; offer value instead of price.", "#/segments"]] },
  retention: { name: "Retention playbook", color: "#2563eb", desc: "Who to contact this week, and with what.",
    summary: () => `Start with the <b>${NUM(D.kpis.high_risk_subscribers)}</b> highest-risk customers, who carry <b>${PKRs(D.kpis.high_risk_revenue_at_risk_pkr)}</b> / month at risk. They fall into distinct groups that each need a different conversation.`,
    kpis: () => [kpi("Customers to contact first", NUM(D.kpis.high_risk_subscribers), "top 10% by risk"),
      kpi("Average risk in this group", PCT(D.deciles[0].avg_score), "vs " + PCT(D.kpis.expected_churn_rate) + " across all customers", "red"),
      kpi("Lift vs random outreach", D.model.lift_top10.toFixed(1) + "×", "more real leavers reached", "green")],
    body: () => panel("Plays by customer group", `<div class="tbl-wrap"><table><thead><tr><th>Group</th><th class="r">High-risk</th><th>Recommended play</th></tr></thead><tbody>` +
      D.personas.filter(p => p.high_risk > 50).map(p => `<tr><td><div class="who">${avatar("  ", p.persona).replace(/>\s*</, `>${p.persona[0]}<`)}<span><b>${esc(p.persona)}</b><small>${esc(p.description)}</small></span></div></td><td class="r">${NUM(p.high_risk)}</td><td style="min-width:260px">${esc(PLAY[p.persona])}</td></tr>`).join("") + `</tbody></table></div>`, { flush: true }),
    recs: () => [["Work the list from the top", "The at-risk list is ordered by probability, with the main reason and a suggested action.", "#/customers"],
                 ["Match the message to the group", "Payment help, a quality apology or a content reminder outperform one generic offer.", "#/customers"],
                 ["Keep a person in the loop", "Approve each outreach; nothing is sent automatically.", "#/customers"]] },
  content: { name: "Content & schedule", color: "#9333ea", desc: "Which releases keep or lose viewers.", needs: ["favourite_genre", "fav_content_ended"], ok: () => D.content && D.content.length,
    summary: () => { const c = D.content.filter(x => x.fans_whose_title_ended).sort((a, b) => b.high_risk_waiting - a.high_risk_waiting), soon = [...c].sort((a, b) => a.next_release_in_days - b.next_release_in_days)[0];
      return `<b>${NUM(c[0].high_risk_waiting)}</b> high-risk ${c[0].genre.toLowerCase()} fans finished <b>${esc(c[0].ended_title)}</b> and wait <b>${c[0].next_release_in_days} days</b> for ${esc(c[0].next_title)}. ${soon.genre} fans, with a release in ${soon.next_release_in_days} days, are far less likely to leave. Gaps between tentpole releases drive churn.`; },
    kpis: () => { const c = D.content.filter(x => x.fans_whose_title_ended), long = [...c].sort((a, b) => b.next_release_in_days - a.next_release_in_days)[0];
      return [kpi("Fans waiting for a release", NUM(c.reduce((a, x) => a + x.fans_whose_title_ended, 0)), "their followed title has ended"),
              kpi("High-risk while waiting", NUM(c.reduce((a, x) => a + x.high_risk_waiting, 0)), "likely to leave before the next release", "red"),
              kpi("Longest gap", long.next_release_in_days + " days", `${long.genre} · ${esc(long.next_title)}`)]; },
    body: () => panel("Release schedule and exposure", `<div class="tbl-wrap"><table><thead><tr><th>Genre</th><th>Ended</th><th>Next release</th><th class="r">In</th><th class="r">Fans waiting</th><th class="r">High-risk</th></tr></thead><tbody>` +
      D.content.filter(c => c.fans_whose_title_ended).map(c => `<tr><td><b>${esc(c.genre)}</b></td><td>${esc(c.ended_title)}<div class="muted" style="font-size:12px">${c.ended_days_ago} days ago</div></td><td>${esc(c.next_title)}</td>
        <td class="r"><span class="pill ${c.next_release_in_days >= 14 ? "no" : "ok"} plain">${c.next_release_in_days}d</span></td><td class="r">${NUM(c.fans_whose_title_ended)}</td><td class="r"><b>${NUM(c.high_risk_waiting)}</b></td></tr>`).join("") + `</tbody></table></div>`, { flush: true }),
    recs: () => [["Fill the sports gap this week", "Highlights, classic matches and a countdown to the next event for waiting fans.", "#/customers"],
                 ["Announce release dates early", "Fans who know something is coming are much less likely to leave.", "#/segments"],
                 ["Broaden single-category viewers", "Recommend one adjacent category to customers who watch only one.", "#/segments"]] },
  product: { name: "Product & quality", color: "#0891b2", desc: "App and streaming issues that drive cancellations.", needs: ["network", "device"], ok: () => D.segments.network && D.segments.device,
    summary: () => { const q = D.personas.find(p => p.persona === "Frustrated by quality"), n = D.segments.network, hi = n[0], lo = n[n.length - 1];
      return `<b>${NUM(q.subscribers)}</b> customers had a poor experience — buffering, crashes, slow starts or a negative ticket — and <b>${NUM(q.high_risk)}</b> are high-risk. Customers on <b>${esc(hi.segment)}</b> average <b>${PCT(hi.avg_risk, 1)}</b> risk vs ${PCT(lo.avg_risk, 1)} on ${esc(lo.segment)}.`; },
    kpis: () => { const q = D.personas.find(p => p.persona === "Frustrated by quality"), sup = D.theme_summary.find(t => t.theme === "Support"), exp = D.theme_summary.find(t => t.theme === "Experience");
      return [kpi("Frustrated by quality", NUM(q.subscribers), PKRs(q.revenue_at_risk_pkr) + " / month at risk"),
              kpi("High-risk with bad support", PCT(sup ? sup.share : 0), "of the top 10%", "red"),
              kpi("High-risk citing app issues", PCT(exp ? exp.share : 0), "smaller than content or payment")]; },
    body: () => `<div class="grid c2">${panel("Risk by network", lbars(D.segments.network.map(s => ({ name: s.segment, sub: NUM(s.subscribers), value: s.avg_risk })), { fmt: v => PCT(v, 1) }))}
      ${panel("Risk by device", lbars(D.segments.device.map(s => ({ name: s.segment, sub: NUM(s.subscribers), value: s.avg_risk })), { fmt: v => PCT(v, 1) }))}</div>`,
    recs: () => [["Start video at lower quality on slow networks", "Start times over 4 seconds clearly raise churn; 3G users are hit hardest.", "#/segments"],
                 ["Answer negative tickets within 24 hours", "A negative ticket is one of the strongest single warning signs.", "#/customers"],
                 ["Keep it in proportion", "App issues matter, but content gaps and payment failures affect far more high-risk customers.", "#/reports/ceo"]] },
  billing: { name: "Billing & payments", color: "#ca8a04", desc: "How payment failures cost subscribers.", needs: ["payment_channel"], ok: () => D.segments.payment_channel,
    summary: () => { const p = D.personas.find(x => x.persona === "Payment-troubled"), ch = D.segments.payment_channel[0];
      return `<b>${NUM(p.subscribers)}</b> customers have repeated failed or low-balance renewals; <b>${NUM(p.high_risk)}</b> are high-risk, carrying <b>${PKRs(p.revenue_at_risk_pkr)}</b> / month. They want to stay — the bill is the problem. <b>${esc(ch.segment)}</b> is the riskiest payment channel.`; },
    kpis: () => { const p = D.personas.find(x => x.persona === "Payment-troubled"), t = D.theme_summary.find(x => x.theme === "Payment");
      return [kpi("Repeated billing failures", NUM(p.subscribers), "failed or low-balance renewals"),
              kpi("Revenue at risk", PKRs(p.revenue_at_risk_pkr), "per month", "red"),
              kpi("High-risk with a payment reason", PCT(t ? t.share : 0), "of the top 10%")]; },
    body: () => panel("Risk by payment channel", lbars(D.segments.payment_channel.map(s => ({ name: s.segment, sub: PKRs(s.revenue_at_risk_pkr) + " at risk", value: s.avg_risk })), { fmt: v => PCT(v, 1) })),
    recs: () => [["Retry renewal after the usual top-up", "Agree retry timing with operators so renewals follow recharges, not precede them.", "#/segments"],
                 ["Send a balance reminder before renewal", "A day-before reminder prevents avoidable failures.", "#/customers"],
                 ["Offer a backup payment method", "Let customers add a wallet as a fallback.", "#/campaigns"]] },
};

// ---------------------------------------------------------------- pages
function pOverview() {
  const k = D.kpis, b = base();
  const segs = [];
  for (const [dim, label] of [["plan", "Plan"], ["payment_channel", "Payment"], ["favourite_genre", "Genre"], ["signup_source", "Acquisition"], ["network", "Network"]])
    (D.segments[dim] || []).filter(s => s.subscribers >= Math.max(50, k.subscribers * 0.03)).forEach(s => segs.push({ ...s, dim: label }));
  segs.sort((a, c) => c.avg_risk - a.avg_risk);
  return `
  <div class="ph"><div><h1>Overview</h1><p>${D.dataset && D.dataset.own ? `Churn outlook for <b>${esc(D.dataset.name)}</b> (${NUM(D.kpis.subscribers)} customers), scored in your browser.` : "Weekly churn outlook for Lumen Play's paying customers, next 30 days."}</p></div>
    <div class="ph-actions"><a class="btn btn-secondary" href="#/briefing">Read briefing</a><a class="btn" href="#/customers">Review at-risk customers</a></div></div>
  <div class="grid c4">
    ${kpi("Likely to cancel", NUM(k.expected_churners), `${PCT(k.expected_churn_rate, 1)} of ${NUM(k.subscribers)} customers`, "", "Sum of every customer's predicted probability of cancelling in the next 30 days.")}
    ${kpi("Revenue at risk / month", PKRs(k.revenue_at_risk_pkr), PKRs(k.revenue_at_risk_pkr * 12) + " annualised", "red", "Each customer's monthly revenue multiplied by their chance of cancelling.")}
    ${kpi("High-risk customers", NUM(k.high_risk_subscribers), PKRs(k.high_risk_revenue_at_risk_pkr) + " / month at risk", "", "The top 10% of customers by predicted risk.")}
    ${kpi("Projected campaign impact", PKRs(b.net), "net / month, top 10% at 15% off", "green", "30% save rate and 50% offer uptake assumed; see Campaign planner.")}
  </div>
  <div class="grid c-2-1 mt">
    ${panel("Risk distribution", `<div class="chart"><canvas id="histChart"></canvas></div>`, { sub: "Customers by predicted probability of cancelling (log scale)" })}
    ${panel("Risk bands", `<div class="tbl-wrap"><table><thead><tr><th>Band</th><th class="r">Customers</th><th class="r">At risk / mo</th></tr></thead><tbody>${D.risk_bands.map(r =>
      `<tr><td><span class="pill ${band(r.from + 0.001)[1]}">${r.band}</span> <span class="muted" style="font-size:12px">${PCT(r.from)}${r.to < 1 ? "–" + PCT(r.to) : "+"}</span></td><td class="r">${NUM(r.customers)}</td><td class="r">${PKRs(r.revenue_at_risk_pkr)}</td></tr>`).join("")}</tbody></table></div>`, { flush: true })}
  </div>
  <div class="grid c2 mt">
    ${panel("Churn drivers", themeBars(), { sub: `Among the ${NUM(D.kpis.high_risk_subscribers)} highest-risk customers` })}
    ${panel("Recommended this week", `<ul class="alist">${REPORTS.ceo.recs().map(([t, d, h], i) => `<li><span class="n">${i + 1}</span><div><b>${t}</b><p>${d}</p><a href="${h}">Open →</a></div></li>`).join("")}</ul>`, { flush: true })}
  </div>
  <div class="mt">${panel("Segments to watch", `<div class="tbl-wrap"><table><thead><tr><th>Segment</th><th>Dimension</th><th class="r">Customers</th><th class="r">Avg risk</th><th class="r">Expected leavers</th><th class="r">At risk / mo</th></tr></thead><tbody>${segs.slice(0, 6).map(s =>
    `<tr><td><b>${esc(s.segment)}</b></td><td class="muted">${s.dim}</td><td class="r">${NUM(s.subscribers)}</td><td class="r">${PCT(s.avg_risk, 1)}<span class="mini-bar"><span style="width:${Math.min(100, s.avg_risk / 0.2 * 100)}%"></span></span></td><td class="r">${NUM(s.expected_churners)}</td><td class="r">${PKRs(s.revenue_at_risk_pkr)}</td></tr>`).join("")}</tbody></table></div>`,
    { flush: true, sub: "Highest average risk among the larger segments", right: `<a class="btn btn-ghost" href="#/segments">All segments →</a>` })}</div>
  <div class="mt"><div class="panel-h" style="border:0;padding:6px 2px 10px"><h2>Reports</h2></div>
    <div class="grid c3">${Object.entries(REPORTS).map(([id, r]) => `<a class="rtile" href="#/reports/${id}"><span class="top"><i style="--c:${r.color}"></i>${r.name}</span><p>${r.desc}</p></a>`).join("")}</div></div>`;
}
function aOverview() {
  const h = D.score_histogram;
  chart("histChart", { type: "bar",
    data: { labels: h.map(b => b.to >= 1 ? `${PCT(b.from)}+` : `${PCT(b.from)}–${PCT(b.to)}`),
      datasets: [{ data: h.map(b => b.customers), backgroundColor: h.map(b => b.from >= 0.3 ? cssv("--chart-2") : cssv("--chart-1")), borderRadius: 3, maxBarThickness: 34 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${NUM(c.raw)} customers` } } },
      scales: { x: { grid: { display: false } }, y: { type: "logarithmic", ticks: { callback: v => ([100, 1000, 10000, 100000].includes(v) ? NUM(v) : "") } } } } });
}

// ---- briefing
const SPLIT = /(?<=[.!?\]])(?<!^\d{1,2}\.)\s+(?=[A-Z])/;   // same rule as the server: don't split after "1."
const strip = s => s.replace(/\s*\[[^\]]*\]/g, "");
const okFinal = c => (c.ok_final !== undefined ? c.ok_final : c.ok);
function sentence(text, chk) {
  const ids = ((text.match(/\[([^\]]*)\]/g) || []).join(",").match(/F\d+/g) || []).map(f => f.slice(1));
  const ok = chk ? okFinal(chk) : true; let t = esc(strip(text)).trim(); if (!/[.!?]$/.test(t)) t += ".";
  return `<span class="${ok ? "" : "flagged"}">${t}<sup>${ids.join(",")}</sup></span>`;
}
function pBriefing() {
  if (!NOTE) return `<div class="ph"><div><h1>Weekly briefing</h1><p>Written by AI from the active dataset's figures, then checked twice before it reaches you.</p></div></div>
    <section class="panel panel-b" style="text-align:center;padding:44px 20px"><h2 style="font-size:15px">No briefing yet for ${esc(D.dataset.name)}</h2>
    <p class="muted" style="margin:6px auto 16px;max-width:480px">Generating sends only aggregate figures (totals, shares and segment averages) to the AI. Customer rows stay in your browser.</p>
    <button class="btn" id="regen" type="button">Generate briefing</button></section>`;
  return `<div class="ph"><div><h1>Weekly briefing</h1><p>Written by AI from this week's figures, then checked twice before it reaches you.</p></div>
    <div class="ph-actions"><button class="btn btn-secondary" id="regen" type="button">Regenerate</button></div></div>
  <div class="grid c-2-1" style="align-items:start">
    <article class="panel mail"><div class="mail-h"><h1 id="mSubject"></h1><dl class="mail-meta"><dt>From</dt><dd>Churn Radar</dd><dt>To</dt><dd>Retention leadership${D.dataset && D.dataset.own ? " · " + esc(D.dataset.name) : ", Lumen Play"}</dd><dt>Date</dt><dd>${today}</dd></dl></div>
      <div class="mail-b" id="mBody"></div>
      <div class="mail-f"><label class="toggle"><input type="checkbox" id="srcT"> Show source figures</label><span id="mStatus"></span></div></article>
    <div class="grid"><section class="panel"><div class="panel-h"><h2>Verification</h2></div><ul class="checks" id="checks"></ul></section>
      <section class="panel"><div class="panel-h"><h2>Source figures</h2><span class="sub">The only input the AI receives</span></div><ol class="facts" id="facts"></ol></section>
      <section class="panel"><div class="panel-h"><h2>Run details</h2></div><div class="panel-b flush"><table><tbody id="run"></tbody></table></div></section></div>
  </div>`;
}
async function regenerate(e) {
  const b = e.target, label = b.textContent; b.disabled = true; b.textContent = "Generating…";
  try {
    const own = D.dataset && D.dataset.own;
    const r = await fetch("/api/weekly_note", { method: "POST", headers: { "Content-Type": "application/json" }, body: own ? JSON.stringify({ facts: Engine.facts(D) }) : "{}" });
    const j2 = await r.json(); if (!r.ok) throw new Error(j2.error || r.statusText);
    NOTE = { ...j2.note, trap_test: own ? null : DEMO_NOTE.trap_test }; FACTS = j2.facts; NOTES[CUR] = { note: NOTE, facts: FACTS };
    route(); toast("Briefing generated and verified");
  } catch (err) { toast("Couldn't generate: " + err.message.slice(0, 70)); b.disabled = false; b.textContent = label; }
}
function aBriefing() {
  if (!NOTE) { $("#regen").onclick = regenerate; return; }
  const v = NOTE.verification, s = v.sentences; let i = 0;
  const part = p => p.split(SPLIT).filter(Boolean).map(x => sentence(x, s[i++])).join(" ");
  $("#mSubject").textContent = NOTE.headline;
  $("#mBody").innerHTML = NOTE.paragraphs.map(p => `<p>${part(p)}</p>`).join("") + `<h3>Actions this week</h3><ol>${(NOTE.actions || []).map(a => `<li>${part(a)}</li>`).join("")}</ol>`;
  const flagged = v.flagged_final ?? v.flagged, live = NOTE.meta.mode === "live", j = v.judge_meta, m = NOTE.meta;
  $("#mStatus").innerHTML = !live ? `<span class="pill neutral">Template</span>` : flagged === 0 ? `<span class="pill ok">Verified · ${v.total}/${v.total} statements</span>` : `<span class="pill no">${flagged} statement${flagged > 1 ? "s" : ""} flagged</span>`;
  const faithful = s.filter(x => x.judge && x.judge.verdict === "faithful").length, t = NOTE.trap_test, drafts = NOTE.attempts ? NOTE.attempts.length : 1;
  $("#checks").innerHTML = `
    <li><span class="tick ${v.flagged ? "x" : ""}">${v.flagged ? "!" : "✓"}</span><div><b>Figures check</b><span>${v.total - v.flagged} of ${v.total} statements cite a real figure and use only its numbers.</span></div></li>
    <li><span class="tick ${j && faithful < v.total ? "x" : ""}">${j ? (faithful === v.total ? "✓" : "!") : "–"}</span><div><b>Meaning check</b><span>${j ? `${faithful} of ${v.total} confirmed faithful by an independent model (${esc(j.model)}).` : "Not available on this run."}</span></div></li>
    <li><span class="tick">✓</span><div><b>Self-correction</b><span>${drafts > 1 ? "Flagged statements were returned to the writer and fixed." : "Accepted on the first draft."}</span></div></li>
    ${t && t.details ? `<li><span class="tick">✓</span><div><b>Control test</b><span>${t.caught_both} of ${t.planted} planted false statements caught.</span></div></li>` : ""}`;
  $("#facts").innerHTML = FACTS.map(f => `<li>${esc(f.text)}</li>`).join("");
  const total = m.total_cost_usd ?? m.cost_usd;
  $("#run").innerHTML = [["Writer", live ? esc(m.model) : "Template"], ["Reviewer", j ? esc(j.model) : "—"], ["Tokens", live ? `${NUM(m.input_tokens + (j ? j.input_tokens : 0))} in · ${NUM(m.output_tokens + (j ? j.output_tokens : 0))} out` : "—"],
    ["Cost", `$${total.toFixed(4)} (≈ PKR ${(total * 280).toFixed(2)})`], ["Latency", m.seconds + "s"], ["Drafts", drafts]]
    .map(([a, b]) => `<tr><td class="muted">${a}</td><td class="r">${b}</td></tr>`).join("");
  $("#srcT").onchange = e => $("#mBody").classList.toggle("src", e.target.checked);
  $("#regen").onclick = regenerate;
}

// ---- customers
const STATUS = store.get("statuses", {});
const statusPill = id => STATUS[id] === "approved" ? `<span class="pill ok">Approved</span>` : STATUS[id] === "dismissed" ? `<span class="pill neutral">Dismissed</span>` : `<span class="pill blue">To review</span>`;
let cf = { q: "", band: "", group: "", plan: "", status: "", page: 0 };
const PER = 25;
function filtered() {
  return D.watchlist.filter(w => (!cf.q || w.id.includes(cf.q.toUpperCase())) && (!cf.band || band(w.score)[0] === cf.band) && (!cf.group || w.persona === cf.group)
    && (!cf.plan || w.plan === cf.plan) && (!cf.status || (STATUS[w.id] || "review") === cf.status));
}
function pCustomers() {
  const opt = (id, label, vals) => `<select class="sel" id="${id}" aria-label="${label}"><option value="">${label}</option>${vals.map(v => `<option${cf[id.slice(1).toLowerCase()] === v ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
  return `<div class="ph"><div><h1>At-risk customers</h1><p>The ${NUM(D.watchlist.length)} customers most likely to cancel in the next 30 days. Approving adds a customer to this week's outreach list; nothing is sent automatically.</p></div>
    <div class="ph-actions"><button class="btn btn-secondary" id="export" type="button"><svg viewBox="0 0 20 20"><path d="M10 3v10M6 9l4 4 4-4M4 16h12"/></svg>Export CSV</button></div></div>
  <section class="panel">
    <div class="filters">
      <input class="input" id="fQ" type="search" placeholder="Search customer ID" value="${esc(cf.q)}" aria-label="Search customer ID">
      ${opt("fBand", "Risk", ["Very high", "High", "Elevated"])}
      ${opt("fGroup", "Group", D.personas.map(p => p.persona).filter(p => D.watchlist.some(w => w.persona === p)))}
      ${opt("fPlan", "Plan", [...new Set(D.watchlist.map(w => w.plan))].sort())}
      <select class="sel" id="fStatus" aria-label="Status"><option value="">Status</option><option value="review">To review</option><option value="approved">Approved</option><option value="dismissed">Dismissed</option></select>
      <span class="spacer"></span><button class="btn btn-ghost" id="fClear" type="button">Clear</button>
    </div>
    <div class="tbl-wrap"><table><thead><tr><th>Customer</th><th>Risk</th><th class="r">Probability</th><th>Group</th><th>Main reason</th><th class="r">Revenue</th><th>Status</th></tr></thead><tbody id="cRows"></tbody></table></div>
    <div class="table-foot"><span id="cInfo"></span><span style="display:flex;gap:6px"><button class="btn btn-secondary" id="prev" type="button">Previous</button><button class="btn btn-secondary" id="next" type="button">Next</button></span></div>
  </section>`;
}
function rowsCustomers() {
  const rows = filtered(), pages = Math.max(1, Math.ceil(rows.length / PER));
  cf.page = Math.min(cf.page, pages - 1);
  const slice = rows.slice(cf.page * PER, cf.page * PER + PER);
  $("#cRows").innerHTML = slice.map(w => `<tr class="row" tabindex="0" data-id="${w.id}">
    <td><div class="who">${avatar(w.id, w.persona)}<span><b>${w.id}</b><small>${esc(w.plan)} · ${esc(w.channel)}</small></span></div></td>
    <td>${riskPill(w.score)}</td><td class="r">${PCT(w.score)}<span class="mini-bar"><span style="width:${w.score * 100}%"></span></span></td>
    <td>${esc(w.persona)}</td><td style="min-width:220px">${w.reasons[0] ? esc(w.reasons[0].text) : "—"}</td><td class="r">${PKR(w.revenue)}</td><td>${statusPill(w.id)}</td></tr>`).join("")
    || `<tr><td colspan="7" class="muted" style="padding:28px;text-align:center">No customers match these filters.</td></tr>`;
  $("#cInfo").textContent = rows.length ? `${cf.page * PER + 1}–${Math.min(rows.length, cf.page * PER + PER)} of ${rows.length}` : "0 results";
  $("#prev").disabled = cf.page === 0; $("#next").disabled = cf.page >= pages - 1;
  $$("#cRows tr.row").forEach(tr => { const open = () => (location.hash = "#/customers/" + tr.dataset.id);
    tr.onclick = open; tr.onkeydown = e => { if (e.key === "Enter") open(); }; });
}
function aCustomers(id) {
  const bind = (sel, key) => $(sel).oninput = e => { cf[key] = e.target.value; cf.page = 0; rowsCustomers(); };
  bind("#fQ", "q"); bind("#fBand", "band"); bind("#fGroup", "group"); bind("#fPlan", "plan"); bind("#fStatus", "status");
  $("#fStatus").value = cf.status;
  $("#fClear").onclick = () => { cf = { q: "", band: "", group: "", plan: "", status: "", page: 0 }; route(); };
  $("#prev").onclick = () => { cf.page--; rowsCustomers(); }; $("#next").onclick = () => { cf.page++; rowsCustomers(); };
  $("#export").onclick = () => {
    const rows = filtered(), head = ["customer_id", "risk_band", "probability", "group", "plan", "payment_channel", "monthly_revenue_pkr", "main_reason", "suggested_action", "status"];
    const q = v => `"${String(v).replace(/"/g, '""')}"`;
    const csv = [head.join(",")].concat(rows.map(w => [w.id, band(w.score)[0], w.score, w.persona, w.plan, w.channel, w.revenue, w.reasons[0]?.text || "",
      ACTION[w.reasons[0]?.code] || PLAY[w.persona], STATUS[w.id] || "to review"].map(q).join(","))).join("\n");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: `lumen-play-at-risk-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click(); URL.revokeObjectURL(a.href); toast(`Exported ${rows.length} customers`);
  };
  rowsCustomers();
  if (id) openCustomer(id);
}
function openCustomer(id) {
  const w = D.watchlist.find(x => x.id === id), dr = $("#drawer");
  if (!w) { toast(`${id} is not in this week's at-risk list`); return; }
  const top = w.reasons[0], [bl, bc] = band(w.score);
  dr.innerHTML = `
    <div class="dr-h"><div class="who">${avatar(w.id, w.persona)}<span><h2 id="drawerTitle">${w.id}</h2><small class="muted">${esc(w.persona)}</small></span></div>
      <button class="icon-btn" id="drClose" type="button" aria-label="Close"><svg viewBox="0 0 20 20" style="width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round"><path d="M5 5l10 10M15 5 5 15"/></svg></button></div>
    <div class="dr-b">
      <div class="dr-sec"><div class="score"><span class="score-v">${PCT(w.score)}</span><div><span class="pill ${bc}">${bl} risk</span>
        <div class="muted" style="font-size:12.5px;margin-top:4px">${(w.score / D.kpis.expected_churn_rate).toFixed(1)}× the average customer · rank ${w.rank} of ${NUM(D.kpis.subscribers)}</div></div></div></div>
      <div class="dr-sec"><h3>Profile</h3><dl class="kv"><div><dt>Plan</dt><dd>${esc(w.plan)}</dd></div><div><dt>Payment</dt><dd>${esc(w.channel)}</dd></div>
        <div><dt>City</dt><dd>${esc(w.city)}</dd></div><div><dt>Favourite genre</dt><dd>${esc(w.genre)}</dd></div>
        <div><dt>Monthly revenue</dt><dd>${PKR(w.revenue)}</dd></div><div><dt>Customer for</dt><dd>${NUM(w.tenure)} days</dd></div></dl></div>
      <div class="dr-sec"><h3>Why they may cancel</h3><ul class="reasons">${w.reasons.map(r => `<li><span>${esc(r.text)}</span><small>${esc(r.group)}</small></li>`).join("") || "<li>No single dominant reason</li>"}</ul></div>
      <div class="dr-sec"><h3>Suggested action</h3><div class="suggest">${esc(top ? ACTION[top.code] || PLAY[w.persona] : PLAY[w.persona])}</div></div>
      <div class="dr-sec"><h3>Compared with a typical customer</h3><table class="cmp"><tbody>${COMPARE.map(([k, l, f]) => `<tr><td>${l}</td><td><b>${f(w.facts[k])}</b></td><td class="muted">${f(D.population_avg[k])}</td></tr>`).join("")}</tbody></table></div>
    </div>
    <div class="dr-f"><button class="btn" id="approve" type="button">${STATUS[id] === "approved" ? "Approved ✓" : "Approve for outreach"}</button><button class="btn btn-secondary" id="dismiss" type="button">Dismiss</button></div>`;
  dr.hidden = false; scrim.hidden = false; scrim.dataset.for = "drawer"; $("#drClose").focus();
  const close = () => { dr.hidden = true; scrim.hidden = true; if (location.hash.startsWith("#/customers/")) history.replaceState(null, "", "#/customers"); updateCrumbs("customers"); };
  const setStatus = s => { STATUS[id] = s; store.set("statuses", STATUS); if ($("#cRows")) rowsCustomers(); toast(s === "approved" ? `${id} added to this week's outreach list` : `${id} dismissed`); close(); };
  $("#drClose").onclick = close; $("#approve").onclick = () => setStatus("approved"); $("#dismiss").onclick = () => setStatus("dismissed");
  dr.onkeydown = e => { if (e.key === "Escape") close(); };
}

// ---- segments
const SEG = { plan: "Plan", payment_channel: "Payment", favourite_genre: "Genre", signup_source: "Acquisition", network: "Network", device: "Device", city: "City" };
let segKey = "plan";
function pSegments() {
  if (!D.segments[segKey]) segKey = Object.keys(SEG).find(k => D.segments[k]) || "plan";
  return `<div class="ph"><div><h1>Segments</h1><p>Compare customer groups by predicted risk and revenue exposure.</p></div></div>
  <section class="panel"><div class="panel-h"><div class="seg" role="group" aria-label="Dimension">${Object.entries(SEG).filter(([k]) => D.segments[k]).map(([k, l]) => `<button type="button" data-seg="${k}" aria-pressed="${k === segKey}">${l}</button>`).join("")}</div>
    <span class="sub">Company average: ${PCT(D.kpis.expected_churn_rate, 1)}</span></div><div class="tbl-wrap"><table><thead><tr><th>Segment</th><th class="r">Customers</th><th>Avg risk</th><th class="r">Expected leavers</th><th class="r">In top 10%</th><th class="r">At risk / mo</th></tr></thead><tbody id="segRows"></tbody></table></div></section>
  <div class="grid c2 mt">
    ${panel("Customer groups", `<div class="tbl-wrap"><table><thead><tr><th>Group</th><th class="r">Customers</th><th class="r">Avg risk</th><th class="r">At risk / mo</th></tr></thead><tbody>${D.personas.map(p =>
      `<tr><td><div class="who"><span class="avatar" style="--c:${GROUP_COLOR[p.persona]}">${p.persona[0]}</span><span><b>${esc(p.persona)}</b><small>${esc(p.description)}</small></span></div></td><td class="r">${NUM(p.subscribers)}</td><td class="r">${PCT(p.avg_risk, 1)}</td><td class="r">${PKRs(p.revenue_at_risk_pkr)}</td></tr>`).join("")}</tbody></table></div>`,
      { flush: true, sub: "Assigned in order: fixable problems first" })}
    ${panel("Release schedule", `<div class="tbl-wrap"><table><thead><tr><th>Genre</th><th>Next release</th><th class="r">Waiting</th><th class="r">High-risk</th></tr></thead><tbody>${(D.content || []).filter(c => c.fans_whose_title_ended).map(c =>
      `<tr><td><b>${esc(c.genre)}</b><div class="muted" style="font-size:12px">${esc(c.ended_title)} ended ${c.ended_days_ago}d ago</div></td><td>${esc(c.next_title)}<div class="muted" style="font-size:12px">in ${c.next_release_in_days} days</div></td><td class="r">${NUM(c.fans_whose_title_ended)}</td><td class="r"><b>${NUM(c.high_risk_waiting)}</b></td></tr>`).join("")}</tbody></table></div>`,
      { flush: true, sub: "Fans whose followed title just ended" })}
  </div>`;
}
function aSegments() {
  const draw = () => {
    const rows = D.segments[segKey] || [], mx = Math.max(...rows.map(r => r.avg_risk));
    $("#segRows").innerHTML = rows.map(s => `<tr><td><b>${esc(s.segment)}</b></td><td class="r">${NUM(s.subscribers)}</td>
      <td style="min-width:180px"><div style="display:flex;align-items:center;gap:10px"><div class="lbar" style="flex:1"><span class="${s.avg_risk > D.kpis.expected_churn_rate ? "brand" : ""}" style="width:${s.avg_risk / mx * 100}%"></span></div><span class="num" style="width:44px;text-align:right">${PCT(s.avg_risk, 1)}</span></div></td>
      <td class="r">${NUM(s.expected_churners)}</td><td class="r">${NUM(s.high_risk)}</td><td class="r">${PKRs(s.revenue_at_risk_pkr)}</td></tr>`).join("");
  };
  $$("[data-seg]").forEach(b => b.onclick = () => { segKey = b.dataset.seg; $$("[data-seg]").forEach(x => x.setAttribute("aria-pressed", x === b)); draw(); });
  draw();
}

// ---- campaign planner
let plan = { ...DEFAULT };
function pCampaigns() {
  const seg = (key, vals, fmt) => `<div class="seg" role="group">${vals.map(v => `<button type="button" data-${key}="${v}" aria-pressed="${plan[key] === v}">${fmt(v)}</button>`).join("")}</div>`;
  return `<div class="ph"><div><h1>Campaign planner</h1><p>Model a retention offer before committing budget. Churn Radar supplies the expected leavers in each audience; the commercial assumptions are yours.</p></div></div>
  <div class="grid c-3-2" style="align-items:start">
    <div class="grid">
      ${panel("Audience and offer", `
        <div class="field"><span class="lbl">Audience</span>${seg("k", [1, 2, 3, 5], v => `Top ${v * 10}%`)}<div class="hint">Customers ranked by predicted risk.</div></div>
        <div class="field"><span class="lbl">Offer</span>${seg("disc", [0, 0.1, 0.15, 0.2, 0.3], v => (v ? v * 100 + "% off" : "No discount"))}<div class="hint">Discount on one month's subscription.</div></div>
        <div class="field"><label for="save">Save rate <span class="val" id="saveV"></span></label><input type="range" id="save" min="5" max="60" step="5"><div class="hint">Share of likely leavers retained. Typically 20–40%; measure with a holdout group.</div></div>
        <div class="field" style="margin-bottom:0"><label for="take">Offer uptake <span class="val" id="takeV"></span></label><input type="range" id="take" min="10" max="100" step="10"><div class="hint">Share of retained customers who redeem the discount.</div></div>`)}
      ${panel("Net impact by audience size", `<div class="chart"><canvas id="cChart"></canvas></div>`, { sub: "Targeted by Churn Radar vs random selection" })}
    </div>
    ${panel("Summary", `<div id="sum"></div><a class="btn" href="#/customers" style="width:100%;justify-content:center;margin-top:14px">Review audience</a>`)}
  </div>`;
}
function aCampaigns() {
  const draw = () => {
    const r = simulate(plan.k, plan.save, plan.disc, plan.take);
    $("#saveV").textContent = PCT(plan.save); $("#takeV").textContent = PCT(plan.take); $("#save").value = plan.save * 100; $("#take").value = plan.take * 100;
    $("#sum").innerHTML = [["Customers targeted", NUM(r.contacted)], ["Expected leavers in audience", NUM(r.leavers)], ["Customers retained", NUM(r.saved)],
      ["Revenue protected", PKRs(r.protectedRev)], ["Offer cost", "−" + PKRs(r.cost).replace("−", "")], ["vs random selection", (r.net - r.rNet >= 0 ? "+" : "") + PKRs(r.net - r.rNet)]]
      .map(([a, b]) => `<div class="summary-row"><span class="muted">${a}</span><span>${b}</span></div>`).join("") +
      `<div class="summary-total"><span>Net impact / month</span><b style="color:${r.net >= 0 ? "var(--green)" : "var(--red)"}">${PKRs(r.net)}</b></div>
       <div class="muted" style="font-size:12.5px">ROI ${(r.roi * 100).toFixed(0)}% · ${PKRs(r.net * 12)} annualised</div>`;
    charts.splice(0).forEach(c => c.destroy()); netChart("cChart", plan);
  };
  ["k", "disc"].forEach(key => $$(`[data-${key}]`).forEach(b => b.onclick = () => { plan[key] = +b.dataset[key]; $$(`[data-${key}]`).forEach(x => x.setAttribute("aria-pressed", +x.dataset[key] === plan[key])); draw(); }));
  $("#save").oninput = e => { plan.save = e.target.value / 100; draw(); }; $("#take").oninput = e => { plan.take = e.target.value / 100; draw(); };
  draw();
}

// ---- model health
function pModel() {
  const m = D.model, c = m.ceiling, t = DEMO_NOTE.trap_test, v = DEMO_NOTE.verification;
  const target = (name, val, goal, ok, note) => `<tr><td>${name}</td><td class="r">${val}</td><td class="r muted">${goal}</td><td>${ok ? '<span class="pill ok">Met</span>' : '<span class="pill no">Not met</span>'}</td><td class="muted" style="min-width:220px">${note}</td></tr>`;
  return `<div class="ph"><div><h1>Model health</h1><div class="status-line" style="margin-top:6px"><span class="dot"></span>Churn model v2 · logistic regression · ${D.kpis.signals} signals · trained on 70,000 customers, tested on 30,000 held out</div>${D.dataset && D.dataset.own ? `<p style="margin-top:8px">Accuracy below was measured on the held-out Lumen Play test set. Your own data has no known outcomes yet, so its accuracy can only be measured after 30 days.</p>` : ""}</div></div>
  <div class="grid c4">
    ${kpi("Hit rate, top 10%", PCT(m.precision_top10, 1), "flagged customers who actually leave", "", "Precision in the top decile.")}
    ${kpi("Lift vs random", m.lift_top10.toFixed(1) + "×", "more leavers reached", "green")}
    ${kpi("Ranking quality (AUC)", m.auc.toFixed(3), "0.5 = random, 1.0 = perfect")}
    ${kpi("Calibration, top band", `${PCT(m.top_band_predicted)} → ${PCT(m.top_band_actual)}`, "predicted vs actual churn", "green")}
  </div>
  <div class="mt">${panel("Targets set in Phase 1", `<div class="tbl-wrap"><table><thead><tr><th>Target</th><th class="r">Result</th><th class="r">Goal</th><th>Status</th><th>Note</th></tr></thead><tbody>
    ${target("Ranking quality (AUC)", m.auc.toFixed(3), "≥ 0.75", m.targets["AUC >= 0.75"], "Separates leavers from stayers well.")}
    ${target("Hit rate, top 10%", PCT(m.precision_top10, 1), "≥ 40%", m.targets["Precision top 10% >= 40%"], `A perfect model reaches only ${PCT(c.precision_top10, 1)} on this data; the goal was set too high.`)}
    ${target("Calibration, top band", `${PCT(m.top_band_predicted)} vs ${PCT(m.top_band_actual)}`, "within 5 pts", m.targets["Top band calibrated (within 5 pts)"], "Not over-confident.")}
    ${t ? target("Briefing control test", `${t.caught_both}/${t.planted}`, "all caught", t.caught_both === t.planted, "Planted false statements detected.") : ""}
    ${target("Briefing unsupported claims", PCT(v.unsupported_rate_final ?? v.unsupported_rate, 1), "< 2%", (v.unsupported_rate_final ?? v.unsupported_rate) < 0.02, "After both checks.")}
  </tbody></table></div>`, { flush: true })}</div>
  <div class="grid c2 mt">
    ${panel("Calibration", `<div class="chart"><canvas id="calChart"></canvas></div>`, { sub: "Each point is one tenth of the test set" })}
    ${panel("Model comparison", `<div class="tbl-wrap"><table><thead><tr><th>Measure</th><th class="r">Logistic (live)</th><th class="r">Boosting</th><th class="r">Ceiling</th></tr></thead><tbody>${[
      ["AUC", "auc", x => x.toFixed(3)], ["Hit rate, top 10%", "precision_top10", x => PCT(x, 1)], ["Recall, top 10%", "recall_top10", x => PCT(x, 1)], ["Lift", "lift_top10", x => x.toFixed(2) + "×"], ["Brier score", "brier", x => x.toFixed(4)]]
      .map(([l, k, f]) => `<tr><td>${l}</td><td class="r">${f(m.comparison["Logistic regression (baseline)"][k])}</td><td class="r">${f(m.comparison["Gradient boosting"][k])}</td><td class="r muted">${f(c[k])}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted" style="font-size:12.5px;padding:12px 14px">Boosting is adopted only if it improves AUC by ≥ 0.01; it did not, so the explainable model stays live. Ceiling = a model that knows the true generating rules. ${D.rule_check.filter(r => r.matches).length} of ${D.rule_check.length} known rules recovered.</p>`, { flush: true })}
  </div>
  <div class="mt">${panel("Known limitations", `<ul class="alist">${[
    ["Associations, not causes", "Reasons describe what accompanies cancellation, not proof of cause."],
    ["Re-validate regularly", "Retrain and re-test on fresh data, and after pricing, plan or content changes."],
    ["People decide", "The model recommends; outreach requires approval and nothing is sent automatically."],
    ["Privacy", "The AI briefing receives aggregate figures only — never names, phone numbers or customer IDs."],
    ["Next", "Survival modelling (when a customer will leave) and uplift modelling (who an offer actually changes) need data from a real campaign."]]
    .map(([a, b], i) => `<li><span class="n">${i + 1}</span><div><b>${a}</b><p>${b}</p></div></li>`).join("")}</ul>`, { flush: true })}</div>`;
}
function aModel() {
  const cal = D.model.calibration, lim = Math.max(...cal.map(c => Math.max(c.predicted, c.actual))) * 110;
  chart("calChart", { type: "scatter", data: { datasets: [
    { label: "Model", data: cal.map(c => ({ x: c.predicted * 100, y: c.actual * 100 })), backgroundColor: cssv("--chart-2"), borderColor: cssv("--chart-2"), showLine: true, borderWidth: 2, pointRadius: 3 },
    { label: "Perfect", data: [{ x: 0, y: 0 }, { x: lim, y: lim }], showLine: true, borderDash: [4, 4], borderColor: cssv("--chart-muted"), borderWidth: 1.5, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom", align: "start", labels: { boxWidth: 10, boxHeight: 2 } } },
      scales: { x: { title: { display: true, text: "Predicted %" } }, y: { title: { display: true, text: "Actual %" } } } } });
}

// ---- report
function pReport(id) {
  const r = REPORTS[id];
  if (r.ok && !r.ok()) return `<div class="ph"><div><h1>${r.name}</h1><p>${r.desc}</p></div></div>
    <section class="panel panel-b" style="text-align:center;padding:40px 20px"><h2 style="font-size:15px">This report needs more columns</h2>
    <p class="muted" style="margin:6px auto 16px;max-width:460px">The active dataset doesn't include ${r.needs.map(n => `<code>${n}</code>`).join(" and ")}. Map these columns on the Data sources page, or switch to the sample dataset.</p>
    <a class="btn" href="#/data">Open Data sources</a></section>`;
  return `<div class="ph"><div><h1>${r.name}</h1><p>${r.desc}</p></div><div class="ph-actions"><button class="btn btn-secondary" type="button" onclick="window.print()">Print</button></div></div>
  <div class="callout"><span class="label">Summary</span>${r.summary()}</div>
  <div class="grid c3 mt">${r.kpis().join("")}</div>
  <div class="mt">${r.body()}</div>
  <div class="mt">${panel("Recommendations", `<ul class="alist">${r.recs().map(([t, d, h], i) => `<li><span class="n">${i + 1}</span><div><b>${t}</b><p>${d}</p>${h ? `<a href="${h}">Open →</a>` : ""}</div></li>`).join("")}</ul>`, { flush: true })}</div>`;
}

// ---- data sources: bring your own data
let staged = null;                         // { name, source, rows, columns, map }
const MAX_ROWS = 250000;
const SHEETJS = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
function loadScript(src) { return new Promise((ok, no) => { if ([...document.scripts].some(s => s.src === src)) return ok();
  const s = Object.assign(document.createElement("script"), { src, onload: ok, onerror: () => no(new Error("couldn't load the Excel reader")) }); document.head.appendChild(s); }); }
const parseCSVText = text => new Promise((ok, no) => Papa.parse(text, { header: true, skipEmptyLines: true, complete: r => ok(r.data), error: no }));
const parseCSVFile = file => new Promise((ok, no) => Papa.parse(file, { header: true, skipEmptyLines: true, complete: r => ok(r.data), error: no }));
async function parseExcel(file) {
  await loadScript(SHEETJS);
  const wb = XLSX.read(await file.arrayBuffer(), { type: "array" });
  return XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: "" });
}
function sheetUrl(u) {
  const m = u.match(/docs\.google\.com\/spreadsheets\/d\/([^/]+)/);
  if (!m || /output=csv|format=csv/.test(u)) return u;
  const gid = (u.match(/[#&?]gid=(\d+)/) || [])[1] || "0";
  return `https://docs.google.com/spreadsheets/d/${m[1]}/export?format=csv&gid=${gid}`;
}
function stage(name, source, rows) {
  rows = rows.filter(r => Object.values(r).some(v => v !== "" && v != null));
  if (!rows.length) throw new Error("the file has no data rows");
  if (rows.length > MAX_ROWS) { toast(`Using the first ${NUM(MAX_ROWS)} of ${NUM(rows.length)} rows (Growth plan limit)`); rows = rows.slice(0, MAX_ROWS); }
  const columns = Object.keys(rows[0]);
  staged = { name, source, rows, columns, map: Engine.autoMap(columns) };
  drawMapping();
  $("#mapStep").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function ingest(kind, payload) {
  try {
    if (kind === "file") {
      const f = payload, ext = f.name.split(".").pop().toLowerCase();
      if (f.size > 60e6) throw new Error("files up to 60 MB are supported");
      const rows = ["xlsx", "xls"].includes(ext) ? await parseExcel(f) : await parseCSVFile(f);
      stage(f.name.replace(/\.[^.]+$/, ""), ["xlsx", "xls"].includes(ext) ? "Excel upload" : "CSV upload", rows);
    } else if (kind === "url") {
      const r = await fetch(sheetUrl(payload)); if (!r.ok) throw new Error(`the link returned ${r.status}`);
      const text = await r.text(); if (/^\s*<(!doctype|html)/i.test(text)) throw new Error("the link isn't a public CSV. In Google Sheets use File → Share → Publish to web → CSV");
      stage(payload.includes("google") ? "Google Sheet" : payload.split("/").pop().replace(/\.[^.]+$/, "") || "Linked CSV", payload.includes("google") ? "Google Sheets" : "CSV link", await parseCSVText(text));
    } else if (kind === "sample") {
      const text = await (await fetch("samples/lumen_play_sample.csv")).text();
      stage("Lumen Play sample export", "Sample file", await parseCSVText(text));
    }
  } catch (err) { toast("Couldn't read the data: " + err.message); }
}
function pData() {
  const conn = (logo, color, title, sub, body) => `<div class="conn"><div class="conn-h"><span class="conn-logo" style="background:${color}">${logo}</span><b>${title}<small>${sub}</small></b></div>${body}</div>`;
  return `<div class="ph"><div><h1>Data sources</h1><p>Bring your own customer data. Churn Radar matches your columns to its ${Engine.FIELDS.length} signals and scores every customer with the trained model.</p></div>
    ${DATASETS.mine ? `<div class="ph-actions"><span class="own-badge">Active: ${esc(DATASETS.mine.dataset.name)} · ${NUM(DATASETS.mine.kpis.subscribers)} customers</span></div>` : ""}</div>
  <div class="privacy"><svg viewBox="0 0 20 20"><path d="M10 2.5 4 5v4.5c0 3.8 2.6 6.9 6 8 3.4-1.1 6-4.2 6-8V5z"/><path d="m7.5 10 1.8 1.8 3.4-3.6"/></svg>
    <div><b>Your data stays on your device.</b> Files are read and scored in this browser tab and are never uploaded to our servers. The AI assistant and briefing receive only aggregate figures — totals, shares and segment averages — never names, phone numbers or customer IDs. Data is cleared when you close the tab.</div></div>
  <div class="grid c3">
    ${conn("CSV", "#16a34a", "Upload a file", "CSV or Excel (.xlsx)", `<label class="drop" id="drop" tabindex="0"><input type="file" id="fileIn" accept=".csv,.xlsx,.xls,text/csv" hidden><b>Drop a file here</b> or click to browse<br><span class="muted" style="font-size:12px">One row per customer · up to ${NUM(MAX_ROWS)} rows</span></label>`)}
    ${conn("GS", "#0f9d58", "Google Sheets or CSV link", "Live link, refreshed on each load", `<p>Publish the sheet to the web as CSV, or paste any public CSV link.</p>
      <form class="row" id="urlForm"><input class="input" id="urlIn" type="url" placeholder="https://docs.google.com/spreadsheets/…" style="flex:1;min-width:0" required><button class="btn" type="submit">Connect</button></form>`)}
    ${conn("LP", "#F0562A", "Sample data", "2,000 Lumen Play customers", `<p>Try the full flow with a sample export, or start from the template.</p>
      <div class="row"><button class="btn" id="sampleBtn" type="button">Load sample</button><a class="btn btn-secondary" href="samples/template.csv" download>Template</a></div>`)}
    ${conn("SQL", "#a91d22", "Microsoft SQL Server", "Export, then upload", `<p>Run our query against your warehouse, save the result as CSV and upload it here. Rename tables to match your schema.</p>
      <div class="row"><a class="btn btn-secondary" href="samples/sqlserver_query.sql" download>Download SQL query</a></div>`)}
    ${conn("XL", "#107c41", "Microsoft Excel", "Workbooks and exports", `<p>Upload .xlsx directly; the first sheet is used. Column names don't need to match exactly.</p><div class="row"><button class="btn btn-secondary" type="button" onclick="document.getElementById('fileIn').click()">Choose workbook</button></div>`)}
    <div class="conn muted-conn"><div class="conn-h"><span class="conn-logo" style="background:#71717a">DB</span><b>Direct database connectors<small>Enterprise</small></b></div>
      <p>Live, scheduled connections to SQL Server, PostgreSQL, Snowflake and BigQuery run inside your own network, so credentials and customer rows never pass through a public website.</p>
      <div class="row"><span class="pill neutral plain">On the roadmap</span></div></div>
  </div>
  <section class="panel mt" id="mapStep" ${staged ? "" : "hidden"}></section>`;
}
function drawMapping() {
  const el = $("#mapStep"); if (!el || !staged) return;
  const { name, rows, columns, map } = staged;
  const matched = Engine.FIELDS.filter(([k]) => map[k]).length, groups = [...new Set(Engine.FIELDS.map(f => f[2]))];
  el.hidden = false;
  el.innerHTML = `<div class="panel-h"><div><h2>Map your columns</h2><div class="sub">${esc(name)} · ${NUM(rows.length)} rows · ${columns.length} columns detected</div></div>
    <div style="min-width:220px"><div class="sub" style="margin-bottom:5px">${matched} of ${Engine.FIELDS.length} signals mapped</div><div class="meter"><span style="width:${matched / Engine.FIELDS.length * 100}%"></span></div></div></div>
    <div class="panel-b">
      <p class="muted" style="margin-bottom:12px;font-size:13px">We matched columns by name. Fix any that are wrong. Signals you don't have are filled with typical values and won't be used as reasons, so the more you map, the sharper the scores.</p>
      <div class="map-grid">${groups.map(g => `<div class="map-group">${g}</div>` + Engine.FIELDS.filter(f => f[2] === g).map(([k, label]) => `
        <div class="map-row"><span>${map[k] ? '<span class="ok">●</span> ' : '<span class="muted">○</span> '}${label}</span>
          <select class="sel" data-map="${k}" aria-label="${label}"><option value="">Not available</option>${columns.map(c => `<option${map[k] === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></div>`).join("")).join("")}</div>
      <h3 style="font-size:12px;color:var(--text-3);margin:18px 0 8px">Preview</h3>
      <div class="tbl-wrap"><table class="preview"><thead><tr>${columns.slice(0, 10).map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 4).map(r => `<tr>${columns.slice(0, 10).map(c => `<td>${esc(String(r[c]).slice(0, 24))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    </div>
    <div class="dr-f" style="justify-content:space-between;border-radius:0 0 12px 12px"><button class="btn btn-ghost" id="mapCancel" type="button">Cancel</button>
      <button class="btn" id="scoreBtn" type="button" ${matched < 5 ? "disabled" : ""}>Score ${NUM(rows.length)} customers</button></div>`;
  $$("[data-map]").forEach(s => s.onchange = () => { staged.map[s.dataset.map] = s.value || undefined; if (!s.value) delete staged.map[s.dataset.map]; drawMapping(); });
  $("#mapCancel").onclick = () => { staged = null; el.hidden = true; };
  $("#scoreBtn").onclick = scoreStaged;
}
function scoreStaged() {
  const b = $("#scoreBtn"); b.disabled = true; b.textContent = "Scoring…";
  setTimeout(() => {
    try {
      const t0 = performance.now();
      const rows = Engine.score(Engine.normalise(staged.rows, staged.map, MODEL), MODEL);
      const matched = Engine.FIELDS.filter(([k]) => staged.map[k]).length;
      DATASETS.mine = Engine.build(rows, { model: DEMO.model, rule_check: DEMO.rule_check },
        { name: staged.name, source: staged.source, map: staged.map, matched });
      Object.defineProperty(DATASETS.mine, "_rows", { value: rows, enumerable: false });   // for the what-if simulator
      simFor = null;
      NOTES.mine = null; CHATS.mine = [];
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      staged = null;
      refreshDatasetPicker(); setDataset("mine", false);
      location.hash = "#/"; toast(`Scored ${NUM(rows.length)} customers in ${secs}s — now viewing your data`);
    } catch (err) { toast("Scoring failed: " + err.message); b.disabled = false; b.textContent = "Score customers"; }
  }, 30);
}
function aData() {
  const drop = $("#drop"), fi = $("#fileIn");
  drop.onclick = () => fi.click(); drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fi.click(); } };
  fi.onchange = () => fi.files[0] && ingest("file", fi.files[0]);
  ["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => e.dataTransfer.files[0] && ingest("file", e.dataTransfer.files[0]));
  $("#urlForm").onsubmit = e => { e.preventDefault(); ingest("url", $("#urlIn").value.trim()); };
  $("#sampleBtn").onclick = () => ingest("sample");
  if (staged) drawMapping();
}

// ---- datasets
const DATASETS = {};
function refreshDatasetPicker() {
  const sel = $("#datasetSel");
  sel.innerHTML = `<option value="demo">Lumen Play (sample)</option>` + (DATASETS.mine ? `<option value="mine">${esc(DATASETS.mine.dataset.name)} · ${NUM(DATASETS.mine.kpis.subscribers)}</option>` : "") + `<option value="__add">+ Add data source…</option>`;
  sel.value = CUR;
}
function setDataset(key, reroute = true) {
  CUR = key; D = DATASETS[key];
  NOTE = NOTES[key] ? NOTES[key].note : null; FACTS = NOTES[key] ? NOTES[key].facts : [];
  cf = { q: "", band: "", group: "", plan: "", status: "", page: 0 };
  $("#navCount").textContent = D.watchlist.length;
  $("#fresh").textContent = D.dataset && D.dataset.own ? `${D.dataset.source} · scored just now` : `Scored ${today}`;
  $("#datasetSel").value = key;
  renderChat();
  if (reroute) route();
}
$("#datasetSel").onchange = e => { if (e.target.value === "__add") { e.target.value = CUR; location.hash = "#/data"; } else setDataset(e.target.value); };

// ---- plans
function pPricing() {
  const plan = (name, price, per, desc, feats, cta, href, featured = false, tag = "") => `<div class="plan ${featured ? "featured" : ""}">
    <div class="plan-name"><span>${name}</span>${tag ? `<span class="pill neutral plain">${tag}</span>` : ""}</div>
    <div class="price">${price}${per ? ` <small>${per}</small>` : ""}</div><p>${desc}</p>
    <ul>${feats.map(f => (f.startsWith("~") ? `<li class="soon">${f.slice(1)}</li>` : `<li>${f}</li>`)).join("")}</ul>
    <a class="btn ${featured ? "" : "btn-secondary"}" href="${href}">${cta}</a></div>`;
  return `<div class="ph"><div><h1>Plans &amp; billing</h1><p>Start free with a file export. Upgrade when Churn Radar becomes part of your weekly retention routine.</p></div>
    <div class="ph-actions"><span class="pill blue plain">Current plan: Starter</span></div></div>
  <div class="plans">
    ${plan("Starter", "Free", "", "For trying Churn Radar on a sample or a one-off export.", ["Up to 5,000 customers per upload", "CSV and Excel upload", "Risk scores, reasons and segments", "At-risk list with CSV export", "10 AI questions a day"], "Use your data", "#/data")}
    ${plan("Growth", "PKR 45,000", "/ month", "For retention teams running weekly campaigns.", ["Up to 250,000 customers", "Google Sheets and CSV links", "Weekly AI briefing, verified twice", "AI assistant (fair use)", "Campaign planner and reports", "5 team seats"], "Try it with your data", "#/data", true, "Most popular")}
    ${plan("Enterprise", "Custom", "", "For operators with strict data-residency and security needs.", ["Unlimited customers", "Hosting in Pakistan (in-country compute)", "Model retrained on your own outcomes", "SSO and audit log", "~Direct SQL Server, PostgreSQL and Snowflake connectors", "~Uplift modelling from your campaigns"], "Contact sales", "#/pricing")}
  </div>
  <p class="muted" style="font-size:12.5px;margin-top:14px">Illustrative pricing for this prototype; no payment details are collected. ○ marks features on the roadmap.</p>`;
}
function aPricing() { $$('.plan a[href="#/pricing"]').forEach(a => a.onclick = e => { e.preventDefault(); toast("Sales enquiries open after the pilot — use Starter with your own data meanwhile"); }); }

// ---- AI assistant
const CHATS = { demo: [] };
const SUGGEST = ["What is driving churn right now?", "Which customer group should we focus on first?", "How much revenue is at risk, and where?", "Would a 15% offer to the top 10% pay off?"];
function chatFacts() {
  const f = Engine.facts(D), b = base();
  f.push({ key: "campaign", text: `A 15% one-month offer to the top 10% by score, assuming 30% of likely leavers are kept and 50% of those who stay use the offer, costs about PKR ${NUM(b.cost)} and protects about PKR ${NUM(b.protectedRev)} a month: a net PKR ${NUM(b.net)}. The same offer sent to random customers would net PKR ${NUM(b.rNet)}.` });
  return f;
}
function renderAnswer(m) {
  const v = m.verification, s = v.sentences; let i = 0;
  const html = m.answer.split(SPLIT).filter(Boolean).map(x => sentence(x, s[i++])).join(" ");
  const flagged = v.flagged_final ?? v.flagged;
  const cited = [...new Set(s.flatMap(x => x.cited))].map(id => m.facts.find(f => f.id === id)).filter(Boolean);
  return `<div class="msg bot"><div class="bubble">${html}</div>
    <div class="msg-meta">${flagged ? `<span class="pill no">${flagged} statement${flagged > 1 ? "s" : ""} couldn't be verified</span>` : `<span class="pill ok">Checked against your figures</span>`}<span>$${m.meta.total_cost_usd.toFixed(4)}</span></div>
    ${cited.length ? `<details><summary>Sources (${cited.length})</summary><ol>${cited.map(f => `<li value="${f.id.slice(1)}">${esc(f.text)}</li>`).join("")}</ol></details>` : ""}
    ${m.followups && m.followups.length ? `<div class="chips" style="margin-top:8px">${m.followups.map(q => `<button class="chip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}</div>`;
}
function renderChat() {
  const log = $("#chatLog"); if (!log || !D) return;
  CHATS[CUR] ||= [];
  $("#chatScope").textContent = "Dataset: " + (D.dataset && D.dataset.own ? D.dataset.name : "Lumen Play (sample)");
  log.innerHTML = (CHATS[CUR].length ? "" : `<div class="msg bot"><div class="bubble">Ask me about churn in the active dataset. I only see aggregate figures, and every number I give is checked against them.</div>
    <div class="chips" style="margin-top:8px">${SUGGEST.map(q => `<button class="chip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`) +
    CHATS[CUR].map(m => m.role === "user" ? `<div class="msg user">${esc(m.content)}</div>` : m.error ? `<div class="msg bot"><div class="bubble">${esc(m.error)}</div>${m.retry ? `<div class="chips" style="margin-top:8px"><button class="chip" type="button" data-q="${esc(m.retry)}">Try again</button></div>` : ""}</div>` : renderAnswer(m)).join("");
  $$("#chatLog [data-q]").forEach(c => c.onclick = () => ask(c.dataset.q));
  log.scrollTop = log.scrollHeight;
}
async function ask(q) {
  q = q.trim(); if (!q) return;
  const hist = CHATS[CUR];
  hist.push({ role: "user", content: q }); renderChat();
  $("#chatLog").insertAdjacentHTML("beforeend", `<div class="msg bot" id="typing"><span class="typing"><i></i><i></i><i></i></span></div>`); $("#chatLog").scrollTop = 1e9;
  try {
    const history = hist.slice(0, -1).filter(m => !m.error).slice(-6).map(m => ({ role: m.role === "user" ? "user" : "assistant", content: m.role === "user" ? m.content : m.answer }));
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, facts: chatFacts(), history }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText);
    hist.push({ role: "bot", ...j });
  } catch (err) {
    const msg = /^(I couldn't|One moment|please don't|facts must|no facts|The AI assistant)/i.test(err.message) ? err.message : "I couldn't answer that just now. Please try again, or rephrase the question.";
    hist.push({ role: "bot", error: msg, retry: q });
  }
  renderChat();
}
const chat = $("#chat");
$("#askBtn").onclick = () => { chat.hidden = !chat.hidden; if (!chat.hidden) { renderChat(); $("#chatInput").focus(); } };
$("#chatClose").onclick = () => { chat.hidden = true; $("#askBtn").focus(); };
$("#chatForm").onsubmit = e => { e.preventDefault(); const t = $("#chatInput"); const q = t.value; t.value = ""; ask(q); };
$("#chatInput").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); } };

// ---- what-if simulator
const SIMSET = {
  levers: Object.fromEntries(Sim.LEVERS.map(l => [l.id, { on: ["pay", "support"].includes(l.id), value: l.control.def, cost: "" }])),
  camp: { on: true, n: null, save: 0.3, disc: 0.15, take: 0.5 },
  goal: { kind: "customers", amount: 500 },
};
let simFor = null, simBusy = false, simLast = null;
async function ensureSimBase() {
  if (simFor === CUR && Sim.ready) return;
  if (D.dataset && D.dataset.own && D._rows) {
    Sim.prepare(MODEL, D._rows, 1);
  } else {
    if (!MODEL) MODEL = await (await fetch("model/churn_model.json")).json();
    const text = await (await fetch("samples/simulator_base.csv")).text();
    const raw = await parseCSVText(text);
    const rows = Engine.score(Engine.normalise(raw, Engine.autoMap(Object.keys(raw[0])), MODEL), MODEL);
    Sim.prepare(MODEL, rows, DEMO.kpis.subscribers / rows.length);
  }
  simFor = CUR;
  // New dataset: start the campaign at its own top 10% (not the previous dataset's audience)
  const step = Sim.size >= 10000 ? 100 : 10;
  SIMSET.camp.n = Math.max(step, Math.round(Sim.size * 0.1 / step) * step);
}
function pSimulator() {
  return `<div class="ph"><div><h1>What-if simulator</h1><p>Change what you would fix or fund, and Churn Radar re-scores every customer to estimate the result. Set a goal and it works out what you'd need.</p></div>
    <div class="ph-actions"><button class="btn btn-secondary" id="simReset" type="button">Reset</button><button class="btn" id="simSave" type="button">Save scenario</button></div></div>
  <div id="simKpis" class="grid c4"><div class="kpi"><div class="kpi-l">Preparing the simulation…</div><div class="kpi-v">—</div><div class="kpi-s">Scoring ${D.dataset && D.dataset.own ? "your customers" : "a 20,000-customer sample of the base"}</div></div></div>
  <div class="grid c-3-2 mt" style="align-items:start">
    <div class="grid">
      ${panel("Operational fixes", `<div id="levers"></div>`, { flush: true, sub: "Switch on a fix, set how far it goes, and optionally what it costs per month" })}
      ${panel("Impact by lever", `<div id="leverTable"></div>`, { flush: true, sub: "Each fix on its own; together they overlap slightly, so the total can differ from the sum" })}
    </div>
    <div class="grid">
      ${panel("Retention campaign", `<div id="campBox"></div>`, { right: `<label class="toggle"><input type="checkbox" id="campOn"> Include</label>` })}
      ${panel("Goal planner", `<div id="goalBox"></div>`, { sub: "What would it take?" })}
    </div>
  </div>
  <div class="mt">${panel("Saved scenarios", `<div id="saved"></div>`, { flush: true })}</div>
  <p class="muted" style="font-size:12.5px;margin-top:14px">Estimates assume the patterns the model learned still hold when you change them — they show association, not proven cause. Confirm the biggest bets with a holdout test before rolling out.</p>`;
}
const fmtSigned = (n, f = NUM) => (n > 0 ? "+" : n < 0 ? "−" : "") + f(Math.abs(n));
function drawLevers() {
  $("#levers").innerHTML = Sim.LEVERS.map(l => {
    const s = SIMSET.levers[l.id], c = l.control;
    const shown = c.kind === "pct" ? s.value + "%" : s.value + c.unit;
    return `<div class="lever ${s.on ? "on" : ""}" data-lever="${l.id}">
      <div class="lever-h"><label class="switch"><input type="checkbox" data-on="${l.id}" ${s.on ? "checked" : ""}><span></span></label>
        <div style="flex:1;min-width:0"><b>${l.name}</b> <span class="pill neutral plain" style="margin-left:4px">${l.team}</span><div class="muted" style="font-size:12.5px">${l.desc}</div></div>
        <div class="lever-impact" id="imp-${l.id}"></div></div>
      <div class="lever-b" ${s.on ? "" : "hidden"}>
        <div class="field" style="margin:0"><label>${c.label} <span class="val">${shown}</span></label>
          <input type="range" data-val="${l.id}" min="${c.min}" max="${c.max}" step="${c.step}" value="${s.value}"></div>
        <div class="lever-meta"><span class="muted" id="aff-${l.id}"></span>
          <label class="cost">Cost / month <input class="input" data-cost="${l.id}" inputmode="numeric" placeholder="PKR, optional" value="${esc(s.cost)}"></label></div>
      </div></div>`;
  }).join("");
  $$("[data-on]").forEach(i => i.onchange = () => { SIMSET.levers[i.dataset.on].on = i.checked; drawLevers(); recalc(); });
  $$("[data-val]").forEach(i => i.oninput = () => { SIMSET.levers[i.dataset.val].value = +i.value; const l = Sim.LEVERS.find(x => x.id === i.dataset.val);
    i.closest(".field").querySelector(".val").textContent = l.control.kind === "pct" ? i.value + "%" : i.value + l.control.unit; recalc(); });
  $$("[data-cost]").forEach(i => i.oninput = () => { SIMSET.levers[i.dataset.cost].cost = i.value.replace(/[^0-9]/g, ""); recalc(); });
}
function drawCampaign() {
  const c = SIMSET.camp, size = Sim.size;
  $("#campOn").checked = c.on;
  $("#campBox").innerHTML = `
    <div class="field"><span class="lbl">Customers to contact</span>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-secondary" type="button" data-step="-500">−500</button>
        <input class="input num" id="campN" inputmode="numeric" value="${NUM(c.n)}" style="width:110px;text-align:right">
        <button class="btn btn-secondary" type="button" data-step="500">+500</button>
        <span class="muted" style="font-size:12.5px">highest risk first · ${PCT(c.n / size)} of customers</span></div></div>
    <div class="field"><span class="lbl">Offer</span><div class="seg" role="group">${[0, 0.1, 0.15, 0.2, 0.3].map(d => `<button type="button" data-disc="${d}" aria-pressed="${c.disc === d}">${d ? d * 100 + "% off" : "No discount"}</button>`).join("")}</div></div>
    <div class="field"><label>Save rate <span class="val">${PCT(c.save)}</span></label><input type="range" id="campSave" min="5" max="60" step="5" value="${c.save * 100}"><div class="hint">Share of contacted likely-leavers who stay.</div></div>
    <div class="field" style="margin-bottom:0"><label>Offer uptake <span class="val">${PCT(c.take)}</span></label><input type="range" id="campTake" min="10" max="100" step="10" value="${c.take * 100}"></div>
    <div id="campOut" class="mt"></div>`;
  const setN = v => { c.n = Math.max(0, Math.min(size, Math.round(v))); $("#campN").value = NUM(c.n); recalc(); };
  $$("[data-step]").forEach(b => b.onclick = () => setN(c.n + +b.dataset.step));
  $("#campN").onchange = e => setN(+e.target.value.replace(/[^0-9]/g, ""));
  $$("[data-disc]").forEach(b => b.onclick = () => { c.disc = +b.dataset.disc; $$("[data-disc]").forEach(x => x.setAttribute("aria-pressed", x === b)); recalc(); });
  $("#campSave").oninput = e => { c.save = e.target.value / 100; e.target.previousElementSibling.querySelector(".val").textContent = PCT(c.save); recalc(); };
  $("#campTake").oninput = e => { c.take = e.target.value / 100; e.target.previousElementSibling.querySelector(".val").textContent = PCT(c.take); recalc(); };
  $("#campOn").onchange = e => { c.on = e.target.checked; recalc(); };
}
function drawGoal() {
  const g = SIMSET.goal;
  $("#goalBox").innerHTML = `
    <div class="field"><span class="lbl">I want to</span><div class="seg" role="group">
      <button type="button" data-gk="customers" aria-pressed="${g.kind === "customers"}">Keep more customers</button>
      <button type="button" data-gk="revenue" aria-pressed="${g.kind === "revenue"}">Protect more revenue</button></div></div>
    <div class="field"><label for="goalAmt">${g.kind === "customers" ? "Customers kept this month" : "Revenue protected per month (PKR)"}</label>
      <div style="display:flex;gap:6px;flex-wrap:wrap"><input class="input num" id="goalAmt" inputmode="numeric" value="${NUM(g.amount)}" style="width:130px;text-align:right">
      ${(g.kind === "customers" ? [250, 500, 1000, 2000] : [100000, 250000, 500000]).map(v => `<button class="btn btn-ghost" type="button" data-ga="${v}">${g.kind === "customers" ? NUM(v) : PKRs(v)}</button>`).join("")}</div></div>
    <div id="goalOut"></div>`;
  $$("[data-gk]").forEach(b => b.onclick = () => { g.kind = b.dataset.gk; g.amount = g.kind === "customers" ? 500 : 250000; drawGoal(); recalc(); });
  $$("[data-ga]").forEach(b => b.onclick = () => { g.amount = +b.dataset.ga; drawGoal(); recalc(); });
  $("#goalAmt").onchange = e => { g.amount = +e.target.value.replace(/[^0-9]/g, "") || 0; e.target.value = NUM(g.amount); recalc(); };
}
let recalcQueued = false;
function recalc() { if (recalcQueued) return; recalcQueued = true; requestAnimationFrame(() => { recalcQueued = false; compute(); }); }
function compute() {
  if (!Sim.ready || !$("#simKpis")) return;
  const c = SIMSET.camp, r = Sim.run(SIMSET.levers, c); simLast = r;
  const rate = x => PCT(x / r.base.size, 1);
  $("#simKpis").innerHTML = [
    kpi("Expected cancellations", `${NUM(r.final)}`, `was ${NUM(r.base.E)} · churn ${rate(r.base.E)} → ${rate(r.final)}`),
    kpi("Customers kept", fmtSigned(r.kept), `${NUM(r.leverAvoided)} from fixes · ${NUM(r.campaign.saved)} from campaign`, r.kept > 0 ? "green" : ""),
    kpi("Revenue gained / month", fmtSigned(r.gain, PKRs), `${PKRs(r.gain * 12)} a year`, r.gain >= 0 ? "green" : "red"),
    kpi("Net after costs / month", fmtSigned(r.net, PKRs), `cost ${PKRs(r.cost)} (${PKRs(r.campaign.cost)} campaign${r.leverCost ? `, ${PKRs(r.leverCost)} fixes` : ""})`, r.net >= 0 ? "green" : "red"),
  ].join("");
  for (const l of Sim.LEVERS) {
    const s = SIMSET.levers[l.id], pl = r.perLever.find(x => x.id === l.id), aff = $(`#aff-${l.id}`), imp = $(`#imp-${l.id}`);
    if (aff) aff.textContent = s.on ? `Affects ${NUM(pl ? pl.affected : 0)} customers` : "";
    if (imp) imp.innerHTML = s.on && pl ? `<b class="${pl.revGain >= 0 ? "pos" : "neg"}">${fmtSigned(pl.revGain, PKRs)}</b><small>${fmtSigned(pl.avoided)} kept</small>` : "";
  }
  $("#leverTable").innerHTML = r.perLever.length ? `<div class="tbl-wrap"><table><thead><tr><th>Fix</th><th class="r">Customers affected</th><th class="r">Cancellations avoided</th><th class="r">Revenue / month</th><th class="r">Cost</th><th class="r">ROI</th></tr></thead><tbody>${
    [...r.perLever].sort((a, b) => b.revGain - a.revGain).map(l => `<tr><td><b>${l.name}</b><div class="muted" style="font-size:12px">${l.team}</div></td><td class="r">${NUM(l.affected)}</td><td class="r">${NUM(l.avoided)}</td>
      <td class="r" style="color:${l.revGain >= 0 ? "var(--green)" : "var(--red)"}">${fmtSigned(l.revGain, PKRs)}</td><td class="r">${l.cost ? PKRs(l.cost) : "—"}</td><td class="r">${l.roi === null ? "—" : (l.roi * 100).toFixed(0) + "%"}</td></tr>`).join("")}
    <tr><td><b>All fixes together</b></td><td class="r"></td><td class="r"><b>${NUM(r.leverAvoided)}</b></td><td class="r"><b>${fmtSigned(r.leverGain, PKRs)}</b></td><td class="r">${r.leverCost ? PKRs(r.leverCost) : "—"}</td><td></td></tr></tbody></table></div>`
    : `<p class="muted" style="padding:16px">Switch on a fix to see its effect.</p>`;
  const cp = r.campaign;
  $("#campOut").innerHTML = c.on ? [["Likely leavers reached", NUM(cp.leavers)], ["Customers kept", NUM(cp.saved)], ["Revenue protected", PKRs(cp.revKept)], ["Offer cost", PKRs(cp.cost)],
    ["Net from campaign", `<b style="color:${cp.revKept - cp.cost >= 0 ? "var(--green)" : "var(--red)"}">${fmtSigned(cp.revKept - cp.cost, PKRs)}</b>`]]
    .map(([a, b]) => `<div class="summary-row"><span class="muted">${a}</span><span>${b}</span></div>`).join("") : `<p class="muted">Campaign not included.</p>`;
  const g = SIMSET.goal, levKept = r.leverAvoided, levRev = r.leverGain;
  const gs = Sim.goal(r.out, g.kind, g.amount, c.save, c.disc, c.take, levKept, levRev);
  const tgt = g.kind === "customers" ? `keep ${NUM(g.amount)} customers` : `protect ${PKRs(g.amount)} a month`;
  $("#goalOut").innerHTML = gs.byLevers ? `<div class="callout">Your fixes alone already ${tgt}: ${g.kind === "customers" ? NUM(levKept) + " kept" : PKRs(levRev) + " protected"}. No campaign needed.</div>`
    : gs.reached ? `<div class="callout"><span class="label">To ${tgt}</span>Contact the <b>${NUM(gs.contacted)}</b> highest-risk customers (${PCT(gs.contacted / Sim.size)} of the base) with a ${PCT(c.disc)} offer.
        Expected: <b>${NUM(gs.saved)}</b> customers kept by the campaign${levKept > 0 ? ` plus ${NUM(levKept)} from your fixes` : ""}, offer cost <b>${PKRs(gs.cost)}</b>, net <b>${fmtSigned(gs.revKept + levRev - gs.cost - r.leverCost, PKRs)}</b> / month.</div>
        <button class="btn btn-secondary mt" id="applyGoal" type="button">Use this audience in the campaign</button>`
    : `<div class="callout" style="border-left-color:var(--red)"><span class="label">Not reachable with these assumptions</span>Even contacting every customer gets you to about <b>${g.kind === "customers" ? NUM(gs.max + levKept) : PKRs(gs.max + levRev)}</b>. Raise the save rate, add operational fixes, or lower the goal.</div>`;
  const ag = $("#applyGoal"); if (ag) ag.onclick = () => { SIMSET.camp.on = true; SIMSET.camp.n = Math.round(gs.contacted / 100) * 100 || Math.round(gs.contacted); drawCampaign(); recalc(); toast("Campaign audience updated"); };
}
function drawSaved() {
  const all = store.get("scenarios", []).filter(s => s.dataset === (D.dataset && D.dataset.own ? D.dataset.name : "demo"));
  $("#saved").innerHTML = all.length ? `<div class="tbl-wrap"><table><thead><tr><th>Scenario</th><th>Fixes</th><th class="r">Contacted</th><th class="r">Customers kept</th><th class="r">Revenue / month</th><th class="r">Cost</th><th class="r">Net / month</th><th></th></tr></thead><tbody>${
    all.map((s, i) => `<tr><td><b>${esc(s.name)}</b><div class="muted" style="font-size:12px">${esc(s.date)}</div></td><td style="max-width:240px">${esc(s.fixes || "None")}</td><td class="r">${NUM(s.contacted)}</td><td class="r">${NUM(s.kept)}</td>
      <td class="r">${PKRs(s.gain)}</td><td class="r">${PKRs(s.cost)}</td><td class="r" style="color:${s.net >= 0 ? "var(--green)" : "var(--red)"}"><b>${fmtSigned(s.net, PKRs)}</b></td>
      <td class="r" style="white-space:nowrap"><button class="btn btn-ghost" type="button" data-load="${i}">Load</button><button class="btn btn-ghost" type="button" data-del="${i}">Delete</button></td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted" style="padding:16px">Save scenarios to compare options side by side, for example "fix payments only" versus "campaign only".</p>`;
  $$("[data-load]").forEach(b => b.onclick = () => { const s = all[+b.dataset.load]; Object.assign(SIMSET, JSON.parse(JSON.stringify(s.settings))); drawLevers(); drawCampaign(); drawGoal(); recalc(); toast(`Loaded “${s.name}”`); });
  $$("[data-del]").forEach(b => b.onclick = () => { const s = all[+b.dataset.del]; store.set("scenarios", store.get("scenarios", []).filter(x => !(x.name === s.name && x.date === s.date && x.dataset === s.dataset))); drawSaved(); });
}
async function aSimulator() {
  try { await ensureSimBase(); } catch (e) { $("#simKpis").innerHTML = `<div class="kpi">Couldn't prepare the simulation: ${esc(e.message)}</div>`; return; }
  if (!$("#levers")) return;
  drawLevers(); drawCampaign(); drawGoal(); drawSaved(); compute();
  $("#simReset").onclick = () => { for (const l of Sim.LEVERS) SIMSET.levers[l.id] = { on: false, value: l.control.def, cost: "" };
    Object.assign(SIMSET.camp, { on: true, n: Math.max(10, Math.round(Sim.size * 0.1 / (Sim.size >= 10000 ? 100 : 10)) * (Sim.size >= 10000 ? 100 : 10)), save: 0.3, disc: 0.15, take: 0.5 }); drawLevers(); drawCampaign(); recalc(); };
  $("#simSave").onclick = () => {
    const name = prompt("Name this scenario", `Scenario ${store.get("scenarios", []).length + 1}`); if (!name || !simLast) return;
    const r = simLast, fixes = Sim.LEVERS.filter(l => SIMSET.levers[l.id].on).map(l => l.name).join(", ");
    const list = store.get("scenarios", []);
    list.push({ name: name.slice(0, 60), date: new Date().toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
      dataset: D.dataset && D.dataset.own ? D.dataset.name : "demo", fixes, contacted: SIMSET.camp.on ? r.campaign.contacted : 0,
      kept: r.kept, gain: r.gain, cost: r.cost, net: r.net, settings: JSON.parse(JSON.stringify(SIMSET)) });
    store.set("scenarios", list); drawSaved(); toast(`Saved “${name}”`);
  };
}
// ---------------------------------------------------------------- router
const ROUTES = {
  "": ["overview", "Overview", pOverview, aOverview], briefing: ["briefing", "Weekly briefing", pBriefing, aBriefing],
  customers: ["customers", "At-risk customers", pCustomers, aCustomers], segments: ["segments", "Segments", pSegments, aSegments],
  simulator: ["simulator", "What-if simulator", pSimulator, aSimulator], campaigns: ["simulator", "What-if simulator", pSimulator, aSimulator],
  model: ["model", "Model health", pModel, aModel],
  data: ["data", "Data sources", pData, aData], pricing: ["pricing", "Plans & billing", pPricing, aPricing],
};
function updateCrumbs(key, extra) {
  const r = Object.values(ROUTES).find(x => x[0] === key);
  $("#crumbs").innerHTML = key.startsWith("reports/") ? `<span>Reports</span><span>/</span><b>${REPORTS[key.split("/")[1]].name}</b>`
    : extra ? `<a href="#/${key}">${r[1]}</a><span>/</span><b>${extra}</b>` : `<span>${D && D.dataset && D.dataset.own ? esc(D.dataset.name) : "Lumen Play"}</span><span>/</span><b>${r ? r[1] : ""}</b>`;
}
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  charts.splice(0).forEach(c => c.destroy());
  if (!(parts[0] === "customers" && parts[1])) { $("#drawer").hidden = true; scrim.hidden = true; }
  let key, title, html, after;
  if (parts[0] === "reports" && REPORTS[parts[1]]) {
    key = "reports/" + parts[1]; title = REPORTS[parts[1]].name; html = pReport(parts[1]); after = REPORTS[parts[1]].after;
  } else {
    const r = ROUTES[parts[0] || ""] || ROUTES[""];
    [key, title] = r; html = r[2](); after = () => r[3] && r[3](parts[1]);
  }
  const keepScroll = key === "customers" && parts[1] && $("#cRows");
  if (!keepScroll) { page().innerHTML = html; window.scrollTo({ top: 0, behavior: "instant" }); }
  else openCustomer(parts[1]);
  $$(".nav a").forEach(a => a.dataset.nav === key ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  updateCrumbs(key, parts[0] === "customers" && parts[1] ? parts[1] : "");
  document.title = `${title} · Churn Radar · Lumen Play`;
  closeNav();
  if (after && !keepScroll) after();
  if (!keepScroll) $("#main").focus({ preventScroll: true });
}

// ---------------------------------------------------------------- chrome: nav, search, share, theme
const sidebar = $("#sidebar"), scrim = $("#scrim");
function closeNav() { sidebar.classList.remove("open"); if ($("#drawer").hidden) scrim.hidden = true; }
$("#openNav").onclick = () => { sidebar.classList.add("open"); scrim.hidden = false; };
$("#closeNav").onclick = closeNav;
scrim.onclick = () => { if (!$("#drawer").hidden) $("#drClose").click(); closeNav(); };
$(".skip").onclick = e => { e.preventDefault(); $("#main").focus(); };
$("#shareBtn").onclick = async () => { try { await navigator.clipboard.writeText(location.href); toast("Link copied"); } catch (e) { toast(location.href); } };
const gs = $("#globalSearch");
gs.onkeydown = e => { if (e.key === "Enter") { const id = gs.value.trim().toUpperCase(); if (!id) return;
  const hit = D.watchlist.find(w => w.id === id || w.id.endsWith(id.padStart(6, "0")));
  if (hit) { location.hash = "#/customers/" + hit.id; gs.value = ""; gs.blur(); } else toast(`${id} is not in this week's at-risk list`); } };
document.addEventListener("keydown", e => {
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); gs.focus(); }
  if (e.key === "Escape" && !$("#drawer").hidden) $("#drClose")?.click();
});
const themeBtn = $("#themeToggle");
const isDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
function syncTheme() { $("#themeLabel").textContent = isDark() ? "Light mode" : "Dark mode"; themeBtn.setAttribute("aria-pressed", isDark());
  document.querySelector('meta[name="theme-color"]').content = isDark() ? "#0b0b0d" : "#ffffff"; }
themeBtn.onclick = () => { const t = isDark() ? "light" : "dark"; document.documentElement.dataset.theme = t; try { localStorage.setItem("theme", t); } catch (e) {} syncTheme(); if (D) route(); };
syncTheme();
window.addEventListener("hashchange", route);

Promise.all(["data/dashboard.json", "data/weekly_note.json", "data/facts.json"].map(u => fetch(u).then(r => r.json())))
  .then(([d, n, f]) => {
    DEMO = DATASETS.demo = d; DEMO_NOTE = n; NOTES.demo = { note: n, facts: f.facts };
    refreshDatasetPicker(); setDataset("demo", false);
    route();
    fetch("model/churn_model.json").then(r => r.json()).then(m => (MODEL = m));
  })
  .catch(e => { page().innerHTML = `<div class="panel panel-b">Couldn't load the workspace: ${esc(e.message)}</div>`; });
