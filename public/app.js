// Churn Radar - executive retention briefing.
// One page app with simple hash routes (#/, #/briefing, #/use/cfo ...), so the back button
// works and every view has its own link. Reads the JSON files that Steps 4 and 5 produce.

// ---------- formatting ----------
const NUM = n => Math.round(n).toLocaleString("en-US");
const PKR = n => "PKR " + Math.round(n).toLocaleString("en-US");
const PKRs = n => (Math.abs(n) >= 1e6 ? "PKR " + (n / 1e6).toFixed(2) + "M" : Math.abs(n) >= 1e3 ? "PKR " + Math.round(n / 1e3) + "k" : PKR(n));
const PCT = (x, d = 0) => (x * 100).toFixed(d) + "%";
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const $ = sel => document.querySelector(sel);
const app = document.getElementById("app");
const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
let D, NOTE, FACTS;
const charts = [];

// ---------- plain-language vocabulary ----------
const THEME = {
  Content: { label: "The show they came for has ended", short: "content ending" },
  Viewing: { label: "Watching less than before", short: "falling viewing" },
  Payment: { label: "Payment problems", short: "payment failures" },
  Support: { label: "A bad support experience", short: "poor support experiences" },
  "Plan history": { label: "Downgraded or cancelled before", short: "past downgrades" },
  Experience: { label: "App or streaming problems", short: "app problems" },
  Marketing: { label: "Only here for discounts", short: "discount dependence" },
  Profile: { label: "New, or on a daily pack", short: "new customers" },
};
const PLAY = {
  "Payment-troubled": "Fix the bill, not the price: renew just after their usual top-up, remind them before renewal, offer wallet billing.",
  "Frustrated by quality": "Apologise and fix: a senior call-back on angry tickets within 24 hours, lower start quality on slow networks.",
  "Seasonal live fans": "Bridge the gap: highlights and classic matches now, and a reminder for the next event's start date.",
  "Fading viewers": "Re-spark interest: a personal 'picked for you' message and one new category to try.",
  "Discount hunters": "Avoid another discount: offer added value instead, such as a data bundle.",
  "Engaged regulars": "No action needed: keep the experience good.",
};
const ACTION = {
  watch_change_pct: "Send a personal 'picked for you' message based on what they used to watch.",
  watch_trend_8w_pct: "Start a four-week re-engagement series in their favourite category.",
  days_since_active: "Send a 'what's new since you've been away' message.",
  completion_rate: "Recommend shorter, highly rated titles in their category.",
  category_concentration: "Introduce one related category they are likely to enjoy.",
  fav_content_ended: "Promote the next release in their genre, with dates, plus highlights of what just ended.",
  days_to_next_release: "Bridge the wait with related content and a release-date reminder.",
  recs_ignored_30d: "Refresh their recommendations; ask two quick taste questions in the app.",
  failed_renewals_30d: "Offer payment help: a reminder before renewal, or a move to wallet billing.",
  low_balance_renewals_30d: "Move their renewal to just after their usual top-up, or offer a weekly plan.",
  payment_switches_90d: "Confirm their preferred payment method and set it as default.",
  buffering_errors_7d: "Check their device and network; share tips for smoother streaming.",
  app_crashes_7d: "Prompt an app update and send the device details to engineering.",
  video_start_sec: "Lower the starting video quality on their network; flag it to engineering.",
  plan_downgrades_90d: "Ask what they miss from the higher plan; offer a short trial of it.",
  past_cancellations: "Treat as a returning customer: a welcome-back message on what has changed.",
  offer_open_rate: "Stop generic offers; send one personal message instead.",
  used_discount: "Offer added value rather than another discount.",
  support_tickets_30d: "Arrange a call-back to resolve their open issue.",
  ticket_negative: "Escalate to a senior agent for a personal call-back within 24 hours.",
  tenure_days: "Send an onboarding message showing the best of the catalogue.",
  sessions_7d: "Send a short trailer for something they are likely to enjoy.",
  plan_Daily: "Offer a Weekly or Monthly plan at a small saving.",
};
const COMPARE = [
  ["days_since_active", "Days since they last watched", v => v.toFixed(0)],
  ["watch_change_pct", "Viewing vs last week", v => (v > 0 ? "+" : "") + v.toFixed(0) + "%"],
  ["completion_rate", "Shows they finish", v => (v * 100).toFixed(0) + "%"],
  ["failed_renewals_30d", "Failed payments this month", v => v.toFixed(v % 1 ? 1 : 0)],
  ["support_tickets_30d", "Support tickets this month", v => v.toFixed(v % 1 ? 1 : 0)],
  ["video_start_sec", "Seconds for a video to start", v => v.toFixed(1)],
  ["tenure_days", "Days as a customer", v => v.toFixed(0)],
];
const riskLabel = s => (s >= 0.5 ? ["Very high", "very-high"] : s >= 0.3 ? ["High", "high"] : s >= 0.15 ? ["Elevated", "elevated"] : ["Watch", "watch"]);

// ---------- campaign maths (shared by home, CFO page and planner) ----------
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
const DEFAULT = { k: 1, save: 0.30, disc: 0.15, take: 0.50 };
const base = () => simulate(DEFAULT.k, DEFAULT.save, DEFAULT.disc, DEFAULT.take);

// ---------- small render helpers ----------
const stat = (label, value, note = "", cls = "") =>
  `<div class="stat ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
function bars(rows, { max, fmt = v => PCT(v), cls = "" } = {}) {
  const m = max ?? Math.max(...rows.map(r => r.value), 0.0001);
  return `<div class="bars" role="list">` + rows.map(r => `
    <div class="bar-row" role="listitem">
      <div class="name">${esc(r.name)}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</div>
      <div class="bar-track" aria-hidden="true"><div class="bar-fill ${r.cls || cls}" style="width:${Math.max(2, r.value / m * 100)}%"></div></div>
      <div class="val">${fmt(r.value)}</div>
    </div>`).join("") + `</div>`;
}
const themeBars = (n = 6) => bars(D.theme_summary.slice(0, n).map(t => ({ name: THEME[t.theme]?.label || t.theme, value: t.share })), { max: 1 });
function newChart(id, cfg) {
  if (!window.Chart) return;
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--line-2");
  charts.push(new Chart(document.getElementById(id), cfg));
}
const icon = p => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const ICONS = {
  ceo: icon('<path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6"/>'),
  cfo: icon('<path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'),
  retention: icon('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
  content: icon('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>'),
  product: icon('<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>'),
  billing: icon('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>'),
};

// ---------- use cases (one per leadership role) ----------
const USE_CASES = {
  ceo: {
    who: "For the CEO", q: "Where are we losing customers, and why?",
    answer: () => {
      const t = D.theme_summary;
      return `About <b>${NUM(D.kpis.expected_churners)}</b> customers (${PCT(D.kpis.expected_churn_rate, 1)}) are likely to leave in the next 30 days, putting <b>${PKRs(D.kpis.revenue_at_risk_pkr)}</b> of monthly revenue at risk. The two biggest causes are <b>${THEME[t[0].theme].short}</b> and <b>${THEME[t[1].theme].short}</b>.`;
    },
    stats: () => {
      const p = [...D.personas].sort((a, b) => b.revenue_at_risk_pkr - a.revenue_at_risk_pkr)[0];
      return [stat("Likely to leave in 30 days", NUM(D.kpis.expected_churners), PCT(D.kpis.expected_churn_rate, 1) + " of customers"),
              stat("Monthly revenue at risk", PKRs(D.kpis.revenue_at_risk_pkr), "about " + PKRs(D.kpis.revenue_at_risk_pkr * 12) + " a year", "bad"),
              stat("Most exposed group", esc(p.persona), PKRs(p.revenue_at_risk_pkr) + " a month at risk")];
    },
    visual: () => `<h3>Why customers in the high-risk group are leaving</h3><p class="muted small">Share of the 10,000 highest-risk customers for whom each issue is a main reason (a customer can have more than one).</p>${themeBars()}`,
    recs: () => {
      const pay = D.personas.find(p => p.persona === "Payment-troubled");
      const sp = D.content.find(c => c.genre === "Sports");
      return [["Fix payment failures with our billing partners", `${NUM(pay.subscribers)} customers have repeated failed renewals; they carry ${PKRs(pay.revenue_at_risk_pkr)} a month at risk. This is a process fix, not a discount.`],
              ["Bridge the gap between big content events", `${NUM(sp.high_risk_waiting)} high-risk sports fans must wait ${sp.next_release_in_days} days for the ${sp.next_title}. Fill the gap with highlights and reminders.`],
              ["Run a targeted retention campaign", `Contacting only the highest-risk 10% is expected to return about ${PKRs(base().net)} a month, where the same offer sent at random would lose money.`]];
    },
    links: [["Read the weekly briefing", "#/briefing"], ["See where the risk is", "#/risk"]],
  },
  cfo: {
    who: "For the CFO", q: "What is churn costing us, and what is the return on acting?",
    answer: () => {
      const b = base();
      return `Churn puts <b>${PKRs(D.kpis.revenue_at_risk_pkr)}</b> of revenue at risk every month. A targeted offer to the highest-risk 10% costs about <b>${PKRs(b.cost)}</b> and protects about <b>${PKRs(b.protectedRev)}</b>: a net gain of <b>${PKRs(b.net)}</b> a month. The same offer sent at random would <b>lose ${PKRs(-b.rNet)}</b>.`;
    },
    stats: () => {
      const b = base();
      return [stat("Revenue at risk, per year", PKRs(D.kpis.revenue_at_risk_pkr * 12), "if nothing is done", "bad"),
              stat("Return on a targeted campaign", (b.roi * 100).toFixed(0) + "%", "net gain divided by the cost of the offer", b.roi >= 0 ? "good" : "bad"),
              stat("Cost per customer kept", PKR(b.cost / b.saved), "discount cost divided by customers retained")];
    },
    visual: () => `<h3>Net monthly gain by how many customers we contact</h3><p class="muted small">Targeting by the model versus choosing customers at random, with the default assumptions (30% saved, 15% off, 50% uptake).</p><div class="chart-box"><canvas id="ucChart" aria-label="Net gain by reach"></canvas></div>`,
    after: () => campaignChart("ucChart", DEFAULT),
    recs: () => [["Start small: the top 10% only", "Returns fall as the campaign widens, because lower-risk customers would mostly have stayed anyway."],
                 ["Measure the real save rate with a control group", "Hold back a random 10% of the target list. Without this, the 30% save rate is an assumption, not a fact."],
                 ["Avoid blanket discounts", "Discount-driven customers churn regardless; offer value (content, data bundles) instead of price cuts."]],
    links: [["Open the campaign planner", "#/planner"], ["Can we trust the numbers?", "#/trust"]],
  },
  retention: {
    who: "For the Head of Retention", q: "Who should we contact this week, and with what?",
    answer: () => `Start with the <b>${NUM(D.kpis.high_risk_subscribers)}</b> highest-risk customers. They carry <b>${PKRs(D.kpis.high_risk_revenue_at_risk_pkr)}</b> a month at risk, and they fall into clear groups, each needing a <b>different conversation</b>, not the same discount.`,
    stats: () => [stat("Customers to contact first", NUM(D.kpis.high_risk_subscribers), "the highest-risk 10%"),
                  stat("Their chance of leaving", PCT(D.deciles[0].avg_score), "on average, vs " + PCT(D.kpis.expected_churn_rate) + " overall", "bad"),
                  stat("Real leavers reached", (D.model.lift_top10).toFixed(1) + "×", "more than contacting people at random", "good")],
    visual: () => `<h3>The groups, and the conversation each needs</h3><div class="grid g2" style="margin-top:12px">` +
      D.personas.filter(p => p.high_risk > 50).map(p => `<div class="card" style="box-shadow:none">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><h3>${esc(p.persona)}</h3><span class="tag high">${NUM(p.high_risk)} high-risk</span></div>
        <p class="muted small" style="margin:4px 0 10px">${esc(p.description)}</p><p style="margin:0">${esc(PLAY[p.persona])}</p></div>`).join("") + `</div>`,
    recs: () => [["Work the list from the top", "The contact list is ordered by chance of leaving, with the main reason and a suggested action for each customer."],
                 ["Match the message to the group", "Payment help, a quality apology or a content reminder will work better than one generic offer."],
                 ["Keep a person in the loop", "Every suggestion needs approval; nothing is sent automatically."]],
    links: [["Open the contact list", "#/contact"], ["Read the weekly briefing", "#/briefing"]],
  },
  content: {
    who: "For the Head of Content", q: "Which shows are keeping or losing our viewers?",
    answer: () => {
      const c = [...D.content].filter(x => x.fans_whose_title_ended).sort((a, b) => b.high_risk_waiting - a.high_risk_waiting);
      const soon = [...c].sort((a, b) => a.next_release_in_days - b.next_release_in_days)[0];
      return `<b>${NUM(c[0].high_risk_waiting)}</b> high-risk ${c[0].genre.toLowerCase()} fans finished the <b>${esc(c[0].ended_title)}</b> and must wait <b>${c[0].next_release_in_days} days</b> for the ${esc(c[0].next_title)}. ${soon.genre} fans, with something new in ${soon.next_release_in_days} days, are far safer. <b>Gaps between big releases drive churn.</b>`;
    },
    stats: () => {
      const c = D.content.filter(x => x.fans_whose_title_ended);
      const long = [...c].sort((a, b) => b.next_release_in_days - a.next_release_in_days)[0];
      return [stat("Fans waiting for their next show", NUM(c.reduce((a, x) => a + x.fans_whose_title_ended, 0)), "their followed title has just ended"),
              stat("Of them, high-risk", NUM(c.reduce((a, x) => a + x.high_risk_waiting, 0)), "likely to leave before the next release", "bad"),
              stat("Longest wait", long.next_release_in_days + " days", long.genre + ": " + esc(long.next_title))];
    },
    visual: () => `<h3>High-risk fans waiting, by genre</h3><p class="muted small">Fans whose followed title just ended and who are now in the highest-risk group.</p>` +
      bars(D.content.filter(c => c.fans_whose_title_ended).sort((a, b) => b.high_risk_waiting - a.high_risk_waiting).map(c => ({
        name: c.genre, sub: `next: ${c.next_title} in ${c.next_release_in_days} days`, value: c.high_risk_waiting, cls: c.next_release_in_days >= 14 ? "bad" : "" })), { fmt: v => NUM(v) }),
    recs: () => [["Fill the sports gap now", "Highlights, classic matches and a countdown to the next event, sent to waiting fans this week."],
                 ["Announce release dates early", "Fans who know something they like is coming are much less likely to leave."],
                 ["Widen narrow viewers", "Customers who watch only one category are riskier; recommend one related category to each."]],
    links: [["See all risk by genre", "#/risk"], ["Read the weekly briefing", "#/briefing"]],
  },
  product: {
    who: "For the Head of Product", q: "Which app and streaming problems drive people away?",
    answer: () => {
      const q = D.personas.find(p => p.persona === "Frustrated by quality");
      const net = D.segments.network, g3 = net.find(n => n.segment === "3G"), wifi = net.find(n => n.segment === "WiFi");
      return `<b>${NUM(q.subscribers)}</b> customers have had a poor experience (buffering, crashes, slow starts or an angry support ticket); <b>${NUM(q.high_risk)}</b> of them are high-risk. Customers on <b>3G</b> leave at <b>${PCT(g3.avg_risk, 1)}</b>, against ${PCT(wifi.avg_risk, 1)} on WiFi.`;
    },
    stats: () => {
      const q = D.personas.find(p => p.persona === "Frustrated by quality");
      const exp = D.theme_summary.find(t => t.theme === "Experience"), sup = D.theme_summary.find(t => t.theme === "Support");
      return [stat("Customers frustrated by quality", NUM(q.subscribers), PKRs(q.revenue_at_risk_pkr) + " a month at risk"),
              stat("High-risk with a bad support experience", PCT(sup ? sup.share : 0), "of the highest-risk group", "bad"),
              stat("High-risk with app problems as a main reason", PCT(exp ? exp.share : 0), "smaller than content or payment issues")];
    },
    visual: () => `<h3>Chance of leaving by network and device</h3>` +
      bars([...D.segments.network.map(s => ({ name: s.segment, sub: "network", value: s.avg_risk })),
            ...D.segments.device.map(s => ({ name: s.segment, sub: "device", value: s.avg_risk }))].sort((a, b) => b.value - a.value), { fmt: v => PCT(v, 1) }),
    recs: () => [["Start videos at a lower quality on slow networks", "Slow starts (over 4 seconds) clearly raise churn, and 3G users suffer most."],
                 ["Reply to angry tickets within 24 hours", "A negative support ticket is one of the strongest single warning signs."],
                 ["Be honest about scale", "App problems matter, but content gaps and payment failures affect far more high-risk customers."]],
    links: [["See where the risk is", "#/risk"], ["Open the contact list", "#/contact"]],
  },
  billing: {
    who: "For Billing & Partnerships", q: "Are payment failures costing us subscribers?",
    answer: () => {
      const p = D.personas.find(x => x.persona === "Payment-troubled"), ch = D.segments.payment_channel[0];
      return `Yes. <b>${NUM(p.subscribers)}</b> customers have repeated failed or low-balance renewals; <b>${NUM(p.high_risk)}</b> are high-risk, carrying <b>${PKRs(p.revenue_at_risk_pkr)}</b> a month. These customers want to stay; <b>the bill is the problem</b>. ${esc(ch.segment)} is the riskiest payment channel.`;
    },
    stats: () => {
      const p = D.personas.find(x => x.persona === "Payment-troubled"), t = D.theme_summary.find(x => x.theme === "Payment");
      return [stat("Customers with repeated billing failures", NUM(p.subscribers), "failed or low-balance renewals"),
              stat("Revenue at risk from them", PKRs(p.revenue_at_risk_pkr), "per month", "bad"),
              stat("High-risk with a payment reason", PCT(t ? t.share : 0), "of the highest-risk group")];
    },
    visual: () => `<h3>Chance of leaving by payment channel</h3>` +
      bars(D.segments.payment_channel.map(s => ({ name: s.segment, sub: PKRs(s.revenue_at_risk_pkr) + " at risk", value: s.avg_risk })), { fmt: v => PCT(v, 1) }),
    recs: () => [["Renew after the customer tops up", "Agree with operators to retry renewal just after the usual recharge, not before it."],
                 ["Remind before renewal", "A short balance reminder a day before renewal prevents avoidable failures."],
                 ["Offer a fallback", "Let customers add a wallet as a backup payment method."]],
    links: [["See where the risk is", "#/risk"], ["Open the campaign planner", "#/planner"]],
  },
};

// ---------- pages ----------
function pageHome() {
  const k = D.kpis, b = base();
  return `
  <section class="hero">
    <div>
      <p class="eyebrow">Week ending ${today}</p>
      <h1><span class="hl">${NUM(k.expected_churners)} customers</span> are likely to leave in the next 30 days.</h1>
      <p class="lead">That puts <b>${PKRs(k.revenue_at_risk_pkr)}</b> of monthly revenue at risk. We know who they are, why they are leaving, and what is most likely to keep them.</p>
      <div class="actions-row"><a class="btn" href="#/briefing">Read this week's briefing</a><a class="btn ghost" href="#/contact">See who to contact</a></div>
    </div>
    <div class="hero-panel" aria-label="If we act this week">
      <div class="label">If we contact the highest-risk 10% this week</div>
      <div class="big">${PKRs(b.net)}</div>
      <div class="label">expected net gain per month, after the cost of the offer</div>
      <div class="row"><span>Customers kept</span><b>${NUM(b.saved)}</b></div>
      <div class="row"><span>Revenue protected</span><b>${PKRs(b.protectedRev)}</b></div>
      <div class="row"><span>Cost of the offer</span><b>${PKRs(b.cost)}</b></div>
    </div>
  </section>

  <section class="section grid g4">
    ${stat("Customers analysed", NUM(k.subscribers), "every paying customer, scored weekly")}
    ${stat("Likely to leave", NUM(k.expected_churners), PCT(k.expected_churn_rate, 1) + " of customers, next 30 days")}
    ${stat("Monthly revenue at risk", PKRs(k.revenue_at_risk_pkr), "about " + PKRs(k.revenue_at_risk_pkr * 12) + " a year", "bad")}
    ${stat("Highest-risk group", NUM(k.high_risk_subscribers), PKRs(k.high_risk_revenue_at_risk_pkr) + " of the risk")}
  </section>

  <section class="section">
    <div class="section-head"><div><h2>What brings you here?</h2><p>Pick your question. Each answer takes a minute to read and ends with clear next steps.</p></div></div>
    <div class="grid g3">
      ${Object.entries(USE_CASES).map(([id, u]) => `
        <a class="role" href="#/use/${id}">
          <span class="icon">${ICONS[id]}</span>
          <span class="who">${u.who.replace("For the ", "").replace("For ", "")}</span>
          <span class="q">${u.q}</span>
          <span class="go">Get the answer &rarr;</span>
        </a>`).join("")}
    </div>
  </section>

  <section class="section grid g2">
    <div class="card">
      <h2>Why customers are leaving</h2>
      <p class="muted small" style="margin-top:6px">Among the 10,000 highest-risk customers. A customer can have more than one reason.</p>
      ${themeBars()}
    </div>
    <div class="card">
      <h2>How this works, in one minute</h2>
      <ol class="recs" style="margin-top:16px">
        <li><div><b>Every customer gets a score</b><span>The chance they will cancel in the next 30 days, based on how they watch, pay and use the app.</span></div></li>
        <li><div><b>Every score comes with reasons</b><span>In plain words, such as "inactive for 11 days" or "4 failed payments".</span></div></li>
        <li><div><b>An AI writes the weekly briefing</b><span>Using only our numbers. Every sentence is checked twice before you see it.</span></div></li>
        <li><div><b>People decide</b><span>The system suggests; the team approves. Nothing is sent to customers automatically.</span></div></li>
      </ol>
    </div>
  </section>`;
}

function pageUseCase(id) {
  const u = USE_CASES[id];
  if (!u) return pageHome();
  return `
  <nav class="crumb" aria-label="Breadcrumb"><a href="#/">Home</a> &rsaquo; ${u.who}</nav>
  <p class="eyebrow">${u.who}</p>
  <h1>${u.q}</h1>
  <div class="answer"><span class="label">The short answer</span>${u.answer()}</div>
  <section class="section grid g3" style="margin-top:24px">${u.stats().join("")}</section>
  <section class="section card">${u.visual()}</section>
  <section class="section card">
    <h2>What we recommend</h2>
    <ol class="recs" style="margin-top:18px">${u.recs().map(([t, d]) => `<li><div><b>${t}</b><span>${d}</span></div></li>`).join("")}</ol>
    <div class="actions-row">${u.links.map(([t, h], i) => `<a class="btn ${i ? "ghost" : ""}" href="${h}">${t} &rarr;</a>`).join("")}</div>
  </section>
  <section class="section"><h2 style="font-size:20px">Other questions</h2>
    <div class="chips" style="margin-top:12px">${Object.entries(USE_CASES).filter(([k]) => k !== id).map(([k, x]) => `<a class="chip" href="#/use/${k}" style="text-decoration:none">${x.who.replace("For the ", "").replace("For ", "")}: ${x.q}</a>`).join("")}</div>
  </section>`;
}

// ---- weekly briefing ----
const SPLIT = /(?<=[.!?\]])\s+(?=[A-Z])/;
const stripCites = s => s.replace(/\s*\[[^\]]*\]/g, "");
const okFinal = c => (c.ok_final !== undefined ? c.ok_final : c.ok);
function renderSentence(text, check) {
  const ids = ((text.match(/\[([^\]]*)\]/g) || []).join(",").match(/F\d+/g) || []).map(f => f.slice(1));
  const ok = check ? okFinal(check) : true;
  let body = esc(stripCites(text)).trim();
  if (!/[.!?]$/.test(body)) body += ".";
  return `<span class="${ok ? "" : "flagged"}" ${ok ? "" : 'title="This statement did not pass our checks"'}>${body}<sup>${ids.join(",")}</sup></span>`;
}
function pageBriefing() {
  return `
  <div class="brief">
    <p class="eyebrow">Weekly briefing &middot; ${today}</p>
    <h1 id="briefTitle"></h1>
    <div class="brief-meta" id="briefMeta"></div>
    <div class="memo" id="memo"></div>
    <div class="actions-row" style="align-items:center;justify-content:space-between">
      <label class="toggle"><input type="checkbox" id="srcToggle"> Show which figure each sentence comes from</label>
      <button class="btn small" id="regen" type="button">Write a fresh briefing</button>
    </div>
  </div>
  <details class="more" id="sourcesBox"><summary>The figures the AI was given</summary><div class="inner">
    <p class="muted small">The AI sees only these totals, never individual customers' names, numbers or IDs.</p><ol class="sources-list" id="facts"></ol></div></details>
  <details class="more"><summary>How was this checked?</summary><div class="inner" id="checks"></div></details>`;
}
function fillBriefing() {
  const v = NOTE.verification, sents = v.sentences;
  let i = 0;
  const part = p => p.split(SPLIT).filter(Boolean).map(s => renderSentence(s, sents[i++])).join(" ");
  $("#briefTitle").textContent = NOTE.headline;
  $("#memo").innerHTML = NOTE.paragraphs.map(p => `<p>${part(p)}</p>`).join("") +
    `<h3>What to do this week</h3><ol>${(NOTE.actions || []).map(a => `<li>${part(a)}</li>`).join("")}</ol>`;
  const flagged = v.flagged_final ?? v.flagged, live = NOTE.meta.mode === "live";
  $("#briefMeta").innerHTML = !live ? `<span class="check-badge bad">Template briefing: no AI key configured</span>`
    : flagged === 0 ? `<span class="check-badge">&#10003; Every statement checked against our data</span><span class="muted small">Written by AI, checked twice: by code and by a second AI</span>`
    : `<span class="check-badge bad">${flagged} statement${flagged > 1 ? "s" : ""} did not pass our checks and ${flagged > 1 ? "are" : "is"} highlighted</span>`;
  $("#facts").innerHTML = FACTS.map(f => `<li>${esc(f.text)}</li>`).join("");
  const t = NOTE.trap_test, j = v.judge_meta, m = NOTE.meta, total = m.total_cost_usd ?? m.cost_usd;
  $("#checks").innerHTML = `
    <ul class="check-list">
      <li><span class="tag ok">Check 1</span><div><b>Numbers check (code).</b> Every sentence must point to one of the figures above, and every number in it must appear in that figure. ${v.total - v.flagged} of ${v.total} sentences passed.</div></li>
      <li><span class="tag ok">Check 2</span><div><b>Meaning check (a second AI).</b> A different AI model${j ? ` (${esc(j.model)})` : ""} reads each sentence next to its figures and confirms the meaning is right, not just the numbers. ${j ? sents.filter(s => s.judge && s.judge.verdict === "faithful").length + " of " + v.total + " sentences confirmed." : "Not available on this run."}</div></li>
      <li><span class="tag ok">Repair</span><div><b>One chance to correct.</b> If either check objects, the AI is told exactly what is wrong and rewrites once. ${NOTE.attempts && NOTE.attempts.length > 1 ? "This briefing needed one correction." : "This briefing passed first time."}</div></li>
      ${t && t.details ? `<li><span class="tag ok">Tested</span><div><b>Do the checks work?</b> We planted ${t.planted} false statements. The two checks together caught <b>${t.caught_both} of ${t.planted}</b>, including ones with correct numbers but wrong meaning.</div></li>` : ""}
      <li><span class="tag watch">Cost</span><div>This briefing cost <b>$${total.toFixed(4)}</b> (about PKR ${(total * 280).toFixed(2)}) and took ${m.seconds} seconds to write.</div></li>
    </ul>
    <details style="margin-top:12px"><summary class="small muted" style="cursor:pointer">Sentence-by-sentence audit</summary>
      <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Statement</th><th>Numbers</th><th>Meaning</th></tr></thead><tbody>
      ${sents.map(s => `<tr><td>${esc(stripCites(s.sentence))}</td><td><span class="tag ${s.ok ? "ok" : "no"}">${s.ok ? "Passed" : "Failed"}</span></td>
        <td><span class="tag ${!s.judge || ["faithful", "unchecked"].includes(s.judge.verdict) ? "ok" : "no"}">${s.judge ? esc(s.judge.verdict) : "n/a"}</span></td></tr>`).join("")}
      </tbody></table></div></details>`;
  $("#srcToggle").onchange = e => $("#memo").classList.toggle("show-sources", e.target.checked);
  $("#regen").onclick = regenerate;
}
async function regenerate(e) {
  const b = e.target; b.disabled = true; b.textContent = "Writing… about 5 seconds";
  try {
    const r = await fetch("/api/weekly_note", { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    NOTE = { ...j.note, trap_test: NOTE.trap_test }; FACTS = j.facts; fillBriefing();
  } catch (err) {
    $("#briefMeta").insertAdjacentHTML("beforeend", `<span class="check-badge bad">Could not write a new briefing: ${esc(err.message.slice(0, 80))}</span>`);
  } finally { b.disabled = false; b.textContent = "Write a fresh briefing"; }
}

// ---- who to contact ----
let contactState = { persona: "", q: "", shown: 25, selected: null };
function pageContact() {
  const groups = D.personas.filter(p => D.watchlist.some(w => w.persona === p.persona));
  return `
  <div class="section-head" style="margin-bottom:22px"><div><p class="eyebrow">Who to contact</p><h1>The 500 customers most likely to leave</h1>
    <p>Ordered by their chance of leaving. Select a customer to see why, and what to say. Every suggestion needs a person's approval.</p></div></div>
  <div class="toolbar">
    <div class="chips" role="group" aria-label="Filter by group">
      <button class="chip" type="button" data-persona="" aria-pressed="true">Everyone</button>
      ${groups.map(p => `<button class="chip" type="button" data-persona="${esc(p.persona)}" aria-pressed="false">${esc(p.persona)}</button>`).join("")}
    </div>
    <input class="search" id="q" type="search" placeholder="Find a customer ID" aria-label="Find a customer ID">
  </div>
  <div class="contact-layout">
    <div class="card" style="padding:8px 8px 14px"><div class="table-wrap"><table>
      <thead><tr><th>Customer</th><th>Chance of leaving</th><th>Main reason</th></tr></thead><tbody id="rows"></tbody></table></div>
      <div style="text-align:center;margin-top:10px"><button class="btn ghost small" id="more" type="button">Show more</button></div></div>
    <aside class="card panel-sticky" id="person" aria-live="polite"></aside>
  </div>`;
}
function contactRows() {
  const s = contactState;
  return D.watchlist.filter(w => (!s.persona || w.persona === s.persona) && (!s.q || w.id.includes(s.q.toUpperCase())));
}
function fillContact() {
  const rows = contactRows(), s = contactState;
  $("#rows").innerHTML = rows.slice(0, s.shown).map(w => {
    const [lab, cls] = riskLabel(w.score);
    return `<tr class="clickable ${s.selected === w.id ? "selected" : ""}" tabindex="0" data-id="${w.id}">
      <td><div class="cell-main">${w.id}</div><div class="cell-sub">${esc(w.persona)} &middot; ${esc(w.plan)}</div></td>
      <td><span class="tag ${cls}">${lab}</span> <span class="cell-sub">${PCT(w.score)}</span></td>
      <td>${w.reasons[0] ? esc(w.reasons[0].text) : "No single main reason"}</td></tr>`;
  }).join("") || `<tr><td colspan="3" class="muted">No customers match.</td></tr>`;
  $("#more").style.display = rows.length > s.shown ? "" : "none";
  document.querySelectorAll("#rows tr.clickable").forEach(tr => {
    const pick = () => { contactState.selected = tr.dataset.id; fillContact(); person(tr.dataset.id); };
    tr.onclick = pick; tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  });
  if (!s.selected && rows[0]) person(rows[0].id);
}
function person(id) {
  const w = D.watchlist.find(x => x.id === id), [lab, cls] = riskLabel(w.score), top = w.reasons[0];
  const col = w.score >= 0.5 ? css("--bad") : css("--warn");
  $("#person").innerHTML = `
    <p class="eyebrow">Customer ${w.id}</p>
    <div class="person-head">
      <div class="ring" style="background:conic-gradient(${col} ${w.score * 360}deg, var(--line-2) 0)"><span>${PCT(w.score)}</span></div>
      <div><span class="tag ${cls}">${lab} risk</span><p style="margin:8px 0 0">${(w.score / D.kpis.expected_churn_rate).toFixed(1)}&times; more likely to leave than the average customer.</p>
      <p class="muted small" style="margin:4px 0 0">${esc(w.plan)} plan &middot; ${esc(w.channel)} &middot; ${esc(w.genre)} fan &middot; PKR ${w.revenue}/month</p></div>
    </div>
    <h3 style="margin-bottom:10px">Why they may leave</h3>
    <ul class="reason-list">${w.reasons.map(r => `<li>${esc(r.text)} <small>&middot; ${esc(THEME[r.group]?.short || r.group)}</small></li>`).join("") || "<li>No single main reason.</li>"}</ul>
    ${top ? `<div class="next-step"><b>Suggested next step</b>${esc(ACTION[top.code] || PLAY[w.persona])}<div class="muted small" style="margin-top:6px">Group: ${esc(w.persona)}. Needs approval before anything is sent.</div></div>` : ""}
    <details style="margin-top:16px"><summary class="small" style="cursor:pointer;font-weight:600">Compared with a typical customer</summary>
      <table style="margin-top:8px"><tbody>${COMPARE.map(([k, l, f]) => `<tr><td>${l}</td><td class="num"><b>${f(w.facts[k])}</b></td><td class="num muted">typical ${f(D.population_avg[k])}</td></tr>`).join("")}</tbody></table></details>`;
}
function wireContact() {
  document.querySelectorAll("[data-persona]").forEach(b => b.onclick = () => {
    document.querySelectorAll("[data-persona]").forEach(x => x.setAttribute("aria-pressed", x === b));
    Object.assign(contactState, { persona: b.dataset.persona, shown: 25, selected: null }); fillContact();
  });
  $("#q").oninput = e => { Object.assign(contactState, { q: e.target.value.trim(), shown: 25, selected: null }); fillContact(); };
  $("#more").onclick = () => { contactState.shown += 25; fillContact(); };
  fillContact();
}

// ---- campaign planner ----
let plan = { ...DEFAULT };
function pagePlanner() {
  const chip = (key, val, label) => `<button class="chip" type="button" data-${key}="${val}" aria-pressed="${plan[key] === val}">${label}</button>`;
  return `
  <div class="section-head" style="margin-bottom:22px"><div><p class="eyebrow">Campaign planner</p><h1>Will a retention offer pay for itself?</h1>
    <p>Choose who to contact and what to offer. The model supplies how many of them are likely to leave; the other assumptions are yours.</p></div></div>
  <div class="planner">
    <div class="card">
      <div class="control"><span class="q">Who do we contact?</span><div class="help">The customers with the highest chance of leaving.</div>
        <div class="chips" role="group" aria-label="Reach">${[1, 2, 3, 5].map(k => chip("k", k, `Top ${k * 10}%`)).join("")}</div></div>
      <div class="control"><span class="q">What do we offer?</span><div class="help">A discount on one month.</div>
        <div class="chips" role="group" aria-label="Discount">${[0, 0.1, 0.15, 0.2, 0.3].map(d => chip("disc", d, d ? (d * 100) + "% off" : "No discount")).join("")}</div></div>
      <div class="control"><label for="save">How many of the likely leavers will we keep? <span class="range-val" id="saveV"></span></label>
        <div class="help">Industry campaigns typically keep 20 to 40%. Measure it with a control group.</div><input type="range" id="save" min="5" max="60" step="5"></div>
      <div class="control"><label for="take">How many who stay will use the discount? <span class="range-val" id="takeV"></span></label>
        <div class="help">Some customers would have stayed anyway and still use the offer.</div><input type="range" id="take" min="10" max="100" step="10"></div>
    </div>
    <div class="card">
      <div class="verdict" id="verdict"></div>
      <div class="grid g2" id="planStats"></div>
      <div class="chart-box"><canvas id="planChart" aria-label="Net monthly gain by reach, model versus random"></canvas></div>
      <p class="muted small" style="margin-top:10px">Solid line: contacting customers chosen by the model. Dashed line: the same campaign sent to customers chosen at random.</p>
    </div>
  </div>`;
}
function campaignChart(id, p) {
  const xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], sims = xs.map(x => simulate(x, p.save, p.disc, p.take));
  newChart(id, {
    type: "line",
    data: { labels: xs.map(x => `Top ${x * 10}%`), datasets: [
      { label: "Chosen by the model", data: sims.map(s => s.net), borderColor: css("--brand-2"), backgroundColor: css("--brand-2"), borderWidth: 2.5, tension: .3, pointRadius: xs.map(x => (x === p.k ? 6 : 2)) },
      { label: "Chosen at random", data: sims.map(s => s.rNet), borderColor: css("--muted"), borderDash: [5, 5], borderWidth: 1.5, tension: .3, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } },
      tooltip: { callbacks: { label: c => `${c.dataset.label}: ${PKRs(c.raw)} a month` } } },
      scales: { x: { grid: { display: false } }, y: { ticks: { callback: v => PKRs(v) } } } },
  });
}
function fillPlanner() {
  const r = simulate(plan.k, plan.save, plan.disc, plan.take);
  $("#saveV").textContent = PCT(plan.save); $("#takeV").textContent = PCT(plan.take);
  $("#save").value = plan.save * 100; $("#take").value = plan.take * 100;
  $("#verdict").innerHTML = r.net >= 0
    ? `Contacting <b style="color:inherit">${NUM(r.contacted)}</b> customers should keep about ${NUM(r.saved)} of them and return a net <b>${PKRs(r.net)}</b> a month.`
    : `This campaign would <b class="neg">lose ${PKRs(-r.net)}</b> a month: the discount costs more than the revenue it protects.`;
  $("#planStats").innerHTML = stat("Cost of the offer", PKRs(r.cost), "per month") + stat("Revenue protected", PKRs(r.protectedRev), NUM(r.saved) + " customers kept") +
    stat("Net gain", PKRs(r.net), "after the cost of the offer", r.net >= 0 ? "good" : "bad") +
    stat("Better than random by", PKRs(r.net - r.rNet), "per month, from targeting by risk");
  charts.splice(0).forEach(c => c.destroy());
  campaignChart("planChart", plan);
}
function wirePlanner() {
  ["k", "disc"].forEach(key => document.querySelectorAll(`[data-${key}]`).forEach(b => b.onclick = () => {
    plan[key] = +b.dataset[key];
    document.querySelectorAll(`[data-${key}]`).forEach(x => x.setAttribute("aria-pressed", +x.dataset[key] === plan[key]));
    fillPlanner();
  }));
  $("#save").oninput = e => { plan.save = e.target.value / 100; fillPlanner(); };
  $("#take").oninput = e => { plan.take = e.target.value / 100; fillPlanner(); };
  fillPlanner();
}

// ---- where the risk is ----
const SEG = { plan: "Plan", payment_channel: "Payment method", favourite_genre: "Favourite genre", signup_source: "How they joined", network: "Network", device: "Device", city: "City" };
let segKey = "plan";
function pageRisk() {
  return `
  <div class="section-head" style="margin-bottom:22px"><div><p class="eyebrow">Where the risk is</p><h1>Which customers are most likely to leave?</h1>
    <p>Compare groups of customers by their chance of leaving and the money at stake.</p></div></div>
  <div class="card">
    <div class="chips" role="group" aria-label="Group customers by">${Object.entries(SEG).map(([k, l]) => `<button class="chip" type="button" data-seg="${k}" aria-pressed="${k === segKey}">${l}</button>`).join("")}</div>
    <div id="segBars" style="margin-top:22px"></div>
  </div>
  <section class="section grid g2">
    <div class="card"><h2>Customer groups</h2><p class="muted small" style="margin-top:6px">Each customer is placed in the first group that fits, starting with problems we can fix.</p>
      <div class="table-wrap"><table><thead><tr><th>Group</th><th class="num">Customers</th><th class="num">At high risk</th><th class="num">Monthly revenue at risk</th></tr></thead><tbody>
      ${D.personas.map(p => `<tr><td><div class="cell-main">${esc(p.persona)}</div><div class="cell-sub">${esc(p.description)}</div></td><td class="num">${NUM(p.subscribers)}</td><td class="num">${NUM(p.high_risk)}</td><td class="num">${PKRs(p.revenue_at_risk_pkr)}</td></tr>`).join("")}
      </tbody></table></div></div>
    <div class="card"><h2>Content timing</h2><p class="muted small" style="margin-top:6px">What each genre's fans just finished, and how long until something new.</p>
      <div class="table-wrap"><table><thead><tr><th>Genre</th><th>Next release</th><th class="num">Fans waiting</th><th class="num">At high risk</th></tr></thead><tbody>
      ${D.content.filter(c => c.fans_whose_title_ended).map(c => `<tr><td><div class="cell-main">${esc(c.genre)}</div><div class="cell-sub">${esc(c.ended_title)} ended ${c.ended_days_ago} days ago</div></td>
        <td><div class="cell-main">${esc(c.next_title)}</div><div class="cell-sub">in ${c.next_release_in_days} days</div></td><td class="num">${NUM(c.fans_whose_title_ended)}</td><td class="num"><b>${NUM(c.high_risk_waiting)}</b></td></tr>`).join("")}
      </tbody></table></div></div>
  </section>`;
}
function fillRisk() {
  const rows = D.segments[segKey];
  $("#segBars").innerHTML = bars(rows.map(s => ({ name: s.segment, sub: `${NUM(s.subscribers)} customers · ${PKRs(s.revenue_at_risk_pkr)} a month at risk`, value: s.avg_risk })),
    { fmt: v => PCT(v, 1) }) + `<p class="muted small" style="margin-top:14px">Bars show the average chance of leaving in the next 30 days. The company average is ${PCT(D.kpis.expected_churn_rate, 1)}.</p>`;
  document.querySelectorAll("[data-seg]").forEach(b => b.onclick = () => {
    segKey = b.dataset.seg; document.querySelectorAll("[data-seg]").forEach(x => x.setAttribute("aria-pressed", x === b)); fillRisk();
  });
}

// ---- can we trust it? ----
function pageTrust() {
  const m = D.model, flagged = Math.round(m.precision_top10 * 10), c = m.ceiling;
  const met = Object.values(m.targets).filter(Boolean).length, tt = NOTE.trap_test;
  return `
  <div class="section-head" style="margin-bottom:22px"><div><p class="eyebrow">Can we trust it?</p><h1>How reliable are these numbers?</h1>
    <p>Straight answers, including where the system falls short.</p></div></div>
  <div class="grid g2">
    <div class="card trust-card"><div class="q">How often is it right?</div>
      <div class="people" aria-hidden="true">${Array.from({ length: 10 }, (_, i) => `<i class="${i < flagged ? "on" : ""}"></i>`).join("")}</div>
      <p class="a">Of every <b>10 customers</b> we flag as highest-risk, about <b>${flagged}</b> really leave. That is <b>${m.lift_top10.toFixed(1)}&times; better</b> than picking customers at random, where only about 1 in 11 would.</p></div>
    <div class="card trust-card"><div class="q">Are the percentages honest?</div><div class="big">${PCT(m.top_band_predicted)} &rarr; ${PCT(m.top_band_actual)}</div>
      <p class="a">When it says the riskiest customers have about a ${PCT(m.top_band_predicted)} chance of leaving, ${PCT(m.top_band_actual)} actually do. <b>It is not over-confident.</b></p></div>
    <div class="card trust-card"><div class="q">Can the AI briefing make things up?</div><div class="big">${tt ? tt.caught_both + " of " + tt.planted : "Checked"}</div>
      <p class="a">Every sentence must point to our data and is checked twice, once by code and once by a second AI. When we planted false statements to test it, ${tt ? `it caught <b>${tt.caught_both} of ${tt.planted}</b>` : "the checks caught them"}.</p></div>
    <div class="card trust-card"><div class="q">Did it meet the goals we set?</div><div class="big">${met} of ${Object.keys(m.targets).length}</div>
      <p class="a">It met the goals for overall accuracy and honest percentages. It missed the goal that 4 in 10 flagged customers should leave; it reaches about 3 in 10. Even a perfect model would only reach ${PCT(c.precision_top10, 0)} on this data, so that goal was set too high.</p></div>
  </div>
  <section class="section card"><h2>What it does not do</h2>
    <ul class="check-list" style="margin-top:10px">
      <li><span class="tag watch">Demo</span><div>All customer records are <b>synthetic</b>. Before real use, the model must be retrained and re-tested on real data inside the company.</div></li>
      <li><span class="tag watch">Reasons</span><div>Reasons show what goes <b>together</b> with leaving, not proof of cause.</div></li>
      <li><span class="tag watch">People</span><div>It <b>recommends</b>; people decide. Nothing is sent to customers automatically.</div></li>
      <li><span class="tag watch">Privacy</span><div>The AI only ever sees <b>totals</b>, never names, phone numbers or customer IDs.</div></li>
      <li><span class="tag watch">Next</span><div>Two improvements need a real campaign first: predicting <b>when</b> someone will leave, and <b>who an offer actually changes</b>.</div></li>
    </ul></section>
  <details class="more"><summary>For analysts: technical results</summary><div class="inner">
    <div class="table-wrap"><table><thead><tr><th>Measure</th>${Object.keys(m.comparison).map(n => `<th class="num">${n === m.name ? n + " (used)" : n}</th>`).join("")}<th class="num">Perfect model</th></tr></thead><tbody>
      ${[["AUC (target 0.75)", "auc", v => v.toFixed(3)], ["Precision, top 10% (target 40%)", "precision_top10", v => PCT(v, 1)], ["Recall, top 10%", "recall_top10", v => PCT(v, 1)],
         ["Lift, top 10%", "lift_top10", v => v.toFixed(2) + "×"], ["Brier score", "brier", v => v.toFixed(4)]].map(([l, k, f]) =>
        `<tr><td>${l}</td>${Object.values(m.comparison).map(r => `<td class="num">${f(r[k])}</td>`).join("")}<td class="num">${f(c[k])}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="muted small" style="margin-top:10px">Held-out test set of 30,000 customers. Gradient boosting is used only if it improves AUC by 0.01 or more; it did not, so the more explainable logistic regression is used. ${D.rule_check.filter(r => r.matches).length} of ${D.rule_check.length} true rules built into the synthetic data were recovered.</p>
    <div class="chart-box"><canvas id="calChart" aria-label="Calibration chart"></canvas></div>
    <p class="muted small">Calibration: each point is a tenth of the test set; on the dashed line, predicted equals observed.</p>
  </div></details>`;
}
function fillTrust() {
  const cal = D.model.calibration, lim = Math.max(...cal.map(c => Math.max(c.predicted, c.actual))) * 110;
  document.querySelector("details.more").addEventListener("toggle", function once() {
    newChart("calChart", { type: "scatter", data: { datasets: [
      { label: "Model", data: cal.map(c => ({ x: c.predicted * 100, y: c.actual * 100 })), backgroundColor: css("--brand-2"), borderColor: css("--brand-2"), showLine: true, pointRadius: 4 },
      { label: "Perfect", data: [{ x: 0, y: 0 }, { x: lim, y: lim }], showLine: true, borderDash: [5, 5], borderColor: css("--muted"), pointRadius: 0 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
        scales: { x: { title: { display: true, text: "Predicted %" } }, y: { title: { display: true, text: "Actually left %" } } } } });
    this.removeEventListener("toggle", once);
  });
}

// ---------- router ----------
const ROUTES = {
  "": [pageHome, null, "Home"], briefing: [pageBriefing, fillBriefing, "Weekly briefing"], contact: [pageContact, wireContact, "Who to contact"],
  planner: [pagePlanner, wirePlanner, "Campaign planner"], risk: [pageRisk, fillRisk, "Where the risk is"], trust: [pageTrust, fillTrust, "Can we trust it?"],
};
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  charts.splice(0).forEach(c => c.destroy());
  let title, after;
  if (parts[0] === "use" && USE_CASES[parts[1]]) {
    app.innerHTML = pageUseCase(parts[1]); after = USE_CASES[parts[1]].after; title = USE_CASES[parts[1]].who;
  } else {
    const [page, fill, t] = ROUTES[parts[0]] || ROUTES[""];
    app.innerHTML = page(); after = fill; title = t;
  }
  const navKey = parts[0] === "use" ? "home" : (ROUTES[parts[0]] ? parts[0] || "home" : "home");
  document.querySelectorAll(".main-nav a").forEach(a =>
    a.dataset.route === navKey ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  document.title = `${title} · Churn Radar`;
  if (after) after();
  window.scrollTo({ top: 0, behavior: "instant" });
  app.focus({ preventScroll: true });
}
window.addEventListener("hashchange", route);
document.querySelector(".skip").addEventListener("click", e => { e.preventDefault(); app.focus(); });

Promise.all(["data/dashboard.json", "data/weekly_note.json", "data/facts.json"].map(u => fetch(u).then(r => r.json())))
  .then(([d, n, f]) => { D = d; NOTE = n; FACTS = f.facts; route(); })
  .catch(e => { app.innerHTML = `<div class="card">The report could not be loaded: ${esc(e.message)}</div>`; });
