// Churn Radar report. Reads the JSON files that Steps 4 and 5 produce.
const PKR = n => "PKR " + Math.round(n).toLocaleString("en-US");
const NUM = n => Math.round(n).toLocaleString("en-US");
const PCT = (x, d = 0) => (x * 100).toFixed(d) + "%";
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const ST = (ok, yes = "Verified", no = "Flagged") => `<span class="st ${ok ? "ok" : "bad"}">${ok ? yes : no}</span>`;
const USD_TO_PKR = 280;

let D, NOTE, FACTS;
const charts = {};
const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
document.getElementById("period").textContent = "Week ending " + today;

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === t.dataset.tab));
  // Charts drawn while their tab was hidden have zero size; resize them now that they are visible.
  Object.values(charts).forEach(c => c.resize());
}));

function chart(id, config) {
  if (charts[id]) charts[id].destroy();
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--rule-2");
  Chart.defaults.font.family = "'IBM Plex Sans', Arial, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.tooltip.cornerRadius = 0;
  charts[id] = new Chart(document.getElementById(id), config);
}

// ---------- executive summary ----------
function renderOverview() {
  const k = D.kpis;
  document.getElementById("kpis").innerHTML = [
    ["Subscribers scored", NUM(k.subscribers), `${k.signals} signals each`],
    ["Expected cancellations", NUM(k.expected_churners), PCT(k.expected_churn_rate, 1) + " of the base, next 30 days"],
    ["Revenue at risk", PKR(k.revenue_at_risk_pkr), "per month, whole base"],
    ["High-risk revenue at risk", PKR(k.high_risk_revenue_at_risk_pkr), `top decile, ${NUM(k.high_risk_subscribers)} subscribers`],
  ].map(([l, v, n]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`).join("");

  const ct = D.content.filter(c => c.fans_whose_title_ended > 0);
  document.getElementById("contentTable").innerHTML =
    `<thead><tr><th>Genre</th><th>Ended</th><th>Next release</th><th class="num">In</th><th class="num">Waiting</th><th class="num">High-risk</th></tr></thead><tbody>` +
    ct.map(c => `<tr><td>${esc(c.genre)}</td><td class="wrap" style="min-width:150px">${esc(c.ended_title)}<div class="hint small" style="margin:0">${c.ended_days_ago} days ago</div></td>
      <td class="wrap" style="min-width:130px">${esc(c.next_title)}</td><td class="num">${c.next_release_in_days} d</td>
      <td class="num">${NUM(c.fans_whose_title_ended)}</td><td class="num"><b>${NUM(c.high_risk_waiting)}</b></td></tr>`).join("") + "</tbody>";
  const worst = [...ct].sort((a, b) => b.high_risk_waiting - a.high_risk_waiting)[0];
  document.getElementById("contentNote").textContent = worst ?
    `${worst.genre} followers face the longest exposure: ${NUM(worst.high_risk_waiting)} high-risk fans must wait ${worst.next_release_in_days} days for ${worst.next_title}. ` +
    `Genres with a release within a week show lower risk among waiting fans.` : "";
  document.getElementById("personaTable").innerHTML =
    `<thead><tr><th>Persona</th><th class="num">Subscribers</th><th class="num">Avg risk</th><th class="num">High-risk</th><th class="num">Revenue at risk</th></tr></thead><tbody>` +
    D.personas.map(p => `<tr><td class="wrap" style="min-width:170px"><b>${esc(p.persona)}</b><div class="hint small" style="margin:0">${esc(p.description)}</div></td>
      <td class="num">${NUM(p.subscribers)}</td><td class="num">${PCT(p.avg_risk, 1)}</td><td class="num">${NUM(p.high_risk)}</td>
      <td class="num">${PKR(p.revenue_at_risk_pkr)}</td></tr>`).join("") + "</tbody>";

  chart("reasonsChart", {
    type: "bar",
    data: { labels: D.reason_summary.slice(0, 12).map(r => `${r.label} (${r.group})`),
            datasets: [{ data: D.reason_summary.slice(0, 12).map(r => r.share * 100), backgroundColor: css("--navy"), barThickness: 12 }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false },
               tooltip: { callbacks: { label: c => `${c.raw.toFixed(0)}% of high-risk subscribers` } } },
               scales: { x: { ticks: { callback: v => v + "%" } }, y: { grid: { display: false } } } },
  });
  renderSegment();
}

function renderSegment() {
  const key = document.getElementById("segmentPick").value;
  const rows = D.segments[key];
  chart("segmentChart", {
    data: { labels: rows.map(r => r.segment), datasets: [
      { type: "bar", label: "Revenue at risk (PKR)", data: rows.map(r => r.revenue_at_risk_pkr),
        backgroundColor: css("--navy"), yAxisID: "y", maxBarThickness: 46, order: 2 },
      { type: "line", label: "Average risk", data: rows.map(r => r.avg_risk * 100), borderWidth: 2,
        borderColor: css("--burgundy"), backgroundColor: css("--burgundy"), pointRadius: 3, yAxisID: "y2", order: 1 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
               scales: { x: { grid: { display: false } }, y: { ticks: { callback: v => (v / 1000) + "k" } },
                         y2: { position: "right", grid: { display: false }, ticks: { callback: v => v.toFixed(1) + "%" } } } },
  });
  document.getElementById("segmentTable").innerHTML =
    `<thead><tr><th>Segment</th><th class="num">Subscribers</th><th class="num">Average risk</th><th class="num">Expected leavers</th>
     <th class="num">In top decile</th><th class="num">Revenue at risk</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(r.segment)}</td><td class="num">${NUM(r.subscribers)}</td><td class="num">${PCT(r.avg_risk, 1)}</td>
      <td class="num">${NUM(r.expected_churners)}</td><td class="num">${NUM(r.high_risk)}</td><td class="num">${PKR(r.revenue_at_risk_pkr)}</td></tr>`).join("") + "</tbody>";
}
document.getElementById("segmentPick").addEventListener("change", renderSegment);

// ---------- weekly memorandum ----------
const SPLIT = /(?<=[.!?\]])\s+(?=[A-Z])/;
const judgeOf = c => (c && c.judge ? c.judge.verdict : null);
const okFinal = c => (c.ok_final !== undefined ? c.ok_final : c.ok);
const stripCites = s => s.replace(/\s*\[[^\]]*\]/g, "");

// Turn "... text [F2, F3]." into "... text.2,3" with the numbers as a superscript footnote.
function sentenceHTML(text, check, n) {
  const cites = [...text.matchAll(/\[([^\]]*)\]/g)].map(m => m[1]).join(", ");
  const nums = (cites.match(/F\d+/g) || []).map(f => f.slice(1));
  let body = esc(stripCites(text)).trim();
  const ok = check ? okFinal(check) : true;
  const tip = check ? `Statement ${n}\nNumerical check: ${check.ok ? "passed" : check.problems.join("; ")}\n` +
    `Semantic review: ${judgeOf(check) || "not run"}${check.judge && check.judge.why ? " (" + check.judge.why + ")" : ""}` : "";
  const sup = `<sup class="${ok ? "" : "flag"}" title="${esc(tip)}">${nums.length ? nums.join(",") : "?"}</sup>`;
  body = /[.!?]$/.test(body) ? body + sup : body + "." + sup;
  return `<span class="s ${ok ? "" : "flagged"}">${body}</span>`;
}

function renderNote() {
  const v = NOTE.verification, sents = v.sentences;
  let i = 0;
  const render = part => part.split(SPLIT).filter(Boolean).map(s => { i++; return sentenceHTML(s, sents[i - 1], i); }).join(" ");
  document.getElementById("noteHeadline").textContent = NOTE.headline;
  document.getElementById("noteBody").innerHTML = NOTE.paragraphs.map(p => `<p>${render(p)}</p>`).join("");
  document.getElementById("noteActions").innerHTML = (NOTE.actions || []).map(a => `<li>${render(a)}</li>`).join("");
  document.getElementById("memoDate").textContent = today;

  const total = v.total, flagged = v.flagged_final ?? v.flagged, judged = !!v.judge_meta;
  const faithful = sents.filter(s => judgeOf(s) === "faithful").length;
  const numOk = total - v.flagged, rate = v.unsupported_rate_final ?? v.unsupported_rate;
  const drafts = NOTE.attempts ? NOTE.attempts.length : 1;
  const live = NOTE.meta.mode === "live";

  document.getElementById("memoStatus").innerHTML = !live ? `<span class="st na">Template (no model key configured)</span>`
    : flagged === 0 ? `${ST(true)} &nbsp;${total} of ${total} statements` : `${ST(false)} &nbsp;${flagged} of ${total} statements require review`;

  const st = document.getElementById("statement");
  st.classList.toggle("flagged", flagged > 0);
  st.innerHTML = live ?
    `Of the <b>${total}</b> statements in this memorandum, <b>${total - flagged}</b> were verified against the ${FACTS.length} source facts. ` +
    `The numerical check passed <b>${numOk} of ${total}</b>` +
    (judged ? `; the independent semantic review (${esc(v.judge_meta.model)}) judged <b>${faithful} of ${total}</b> faithful.`
            : `; the semantic review was not available for this run${v.judge_error ? " (" + esc(v.judge_error.slice(0, 80)) + ")" : ""}.`) +
    ` Unsupported-claim rate: <b>${PCT(rate, 1)}</b>, against a target below 2.0%. ` +
    (drafts === 1 ? "Accepted on the first draft." : `Accepted after ${drafts - 1} revision${drafts > 2 ? "s" : ""} by the drafting model.`)
    : "This memorandum was produced from a fixed template because no model key is configured. The numerical check was still applied.";

  document.getElementById("verifySummary").innerHTML = `<div class="kpis small">
    <div class="kpi ${rate < .02 ? "pos" : "neg"}"><div class="label">Unsupported</div><div class="value">${PCT(rate, 1)}</div><div class="note">target &lt; 2.0%</div></div>
    <div class="kpi"><div class="label">Numerical</div><div class="value">${numOk}/${total}</div><div class="note">passed</div></div>
    <div class="kpi"><div class="label">Semantic</div><div class="value">${judged ? faithful + "/" + total : "n/a"}</div><div class="note">faithful</div></div></div>`;

  // Audit trail
  document.getElementById("auditTable").innerHTML =
    `<thead><tr><th class="num">No.</th><th>Statement</th><th>Sources</th><th>Numerical check</th><th>Semantic review</th><th>Result</th></tr></thead><tbody>` +
    sents.map((s, n) => {
      const j = judgeOf(s);
      const jCell = !j ? `<span class="st na">Not run</span>` : j === "unchecked" ? `<span class="st na">Not reached</span>`
        : `${ST(j === "faithful", "Faithful", j[0].toUpperCase() + j.slice(1))}<div class="hint small" style="margin:2px 0 0">${esc(s.judge.why || "")}</div>`;
      return `<tr><td class="num">${n + 1}</td><td class="wrap">${esc(stripCites(s.sentence))}</td>
        <td>${s.cited.length ? s.cited.join(", ") : "none"}</td>
        <td>${ST(s.ok, "Passed", "Failed")}${s.ok ? "" : `<div class="hint small" style="margin:2px 0 0;white-space:normal">${esc(s.problems.join("; "))}</div>`}</td>
        <td style="white-space:normal;min-width:170px">${jCell}</td><td>${ST(okFinal(s))}</td></tr>`;
    }).join("") + "</tbody>";

  // Control test
  const t = NOTE.trap_test;
  document.getElementById("trapTable").innerHTML = t && t.details ?
    `<thead><tr><th>Planted statement</th><th>Numerical</th><th>Semantic</th></tr></thead><tbody>` +
    t.details.map(d => `<tr><td class="wrap">${esc(stripCites(d.sentence))}</td>
      <td>${ST(d.numbers_caught, "Detected", "Missed")}</td>
      <td title="${esc(d.why)}">${ST(d.judge !== "faithful", "Detected", "Missed")}</td></tr>`).join("") +
    `</tbody><tfoot><tr><td>Detected (either check: ${t.caught_both} of ${t.planted})</td><td>${t.caught_numbers_only} of ${t.planted}</td>` +
    `<td>${t.details.filter(d => d.judge !== "faithful").length} of ${t.planted}</td></tr></tfoot>`
    : `<tbody><tr><td>The control test runs only when a model key is configured.</td></tr></tbody>`;

  document.getElementById("factList").innerHTML = FACTS.map(f => `<li><b>${f.id.slice(1)}</b><span>${esc(f.text)}</span></li>`).join("");

  // Run record
  const m = NOTE.meta, j = v.judge_meta, totalUsd = m.total_cost_usd ?? m.cost_usd;
  const rows = live ? [
    ["Drafting model", esc(m.model)], ["Drafting tokens (in / out)", `${NUM(m.input_tokens)} / ${NUM(m.output_tokens)}`],
    ["Drafting cost", `$${m.cost_usd.toFixed(6)}`],
    ...(j ? [["Review model", esc(j.model)], ["Review tokens (in / out)", `${NUM(j.input_tokens)} / ${NUM(j.output_tokens)}`],
             ["Review cost", `$${j.cost_usd.toFixed(6)}${j.price_is_estimate ? " (estimated rate)" : ""}`]] : []),
    ["Drafts required", drafts], ["Latency, final draft", `${m.seconds} s`],
    ["Total cost", `<b>$${totalUsd.toFixed(6)}</b> (≈ PKR ${(totalUsd * USD_TO_PKR).toFixed(2)})`],
    ["Projected cost, 52 weekly memoranda", `$${(totalUsd * 52).toFixed(4)} per year`],
  ] : [["Mode", "Template, no model call"], ["Cost", "$0"]];
  document.getElementById("runTable").innerHTML = "<tbody>" + rows.map(([a, b]) => `<tr><td>${a}</td><td class="num">${b}</td></tr>`).join("") + "</tbody>";
}

document.getElementById("regen").addEventListener("click", async e => {
  const b = e.target; b.disabled = true; b.textContent = "Drafting…";
  try {
    const r = await fetch("/api/weekly_note", { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    NOTE = { ...j.note, trap_test: NOTE.trap_test }; FACTS = j.facts; renderNote();
  } catch (err) {
    document.getElementById("memoStatus").insertAdjacentHTML("beforeend",
      ` <span class="st bad">Live redraft failed: ${esc(err.message.slice(0, 80))}</span>`);
  } finally { b.disabled = false; b.textContent = "Redraft live"; }
});

// ---------- priority contact list ----------
const ACTIONS = {
  watch_change_pct: "Send a personalised selection of content matched to their viewing history.",
  watch_trend_8w_pct: "Start a re-engagement series: new titles in their favourite category over the next four weeks.",
  days_since_active: "Send a win-back message summarising what is new since their last visit.",
  completion_rate: "Recommend shorter formats and highly rated titles in their category.",
  category_concentration: "Introduce one adjacent category they are likely to enjoy, to widen their reasons to stay.",
  fav_content_ended: "Promote the next release in their genre, with dates, and highlights of what just ended.",
  days_to_next_release: "Bridge the gap until the next release with related content and a release reminder.",
  recs_ignored_30d: "Refresh their recommendations; ask two quick taste questions in the app.",
  failed_renewals_30d: "Offer payment assistance: a top-up reminder before renewal, or a move to wallet billing.",
  low_balance_renewals_30d: "Shift the renewal date to just after their usual recharge, or offer a weekly plan.",
  payment_switches_90d: "Confirm their preferred payment method and make it the default.",
  buffering_errors_7d: "Provide streaming guidance and check device or network quality.",
  app_crashes_7d: "Prompt an app update and pass the device details to engineering.",
  video_start_sec: "Suggest a lower starting quality on their network; flag the network to engineering.",
  plan_downgrades_90d: "Check what they miss from the higher plan; offer a short trial of it.",
  past_cancellations: "Treat as a returning customer: a welcome-back message with what has changed.",
  offer_open_rate: "Stop generic offers; use a single personalised message instead.",
  used_discount: "Offer added value (content or a data bundle) rather than a further discount.",
  support_tickets_30d: "Arrange a call-back from support to resolve the open issue.",
  ticket_negative: "Escalate to a senior agent for a personal call-back within 24 hours.",
  tenure_days: "Send an onboarding sequence presenting the strongest titles in the catalogue.",
  sessions_7d: "Send a short trailer for a title likely to interest them.",
  plan_Daily: "Propose an upgrade to a Weekly or Monthly plan at a modest saving.",
};
const FACT_LABELS = {
  watch_change_pct: ["Viewing change vs prior week", v => v.toFixed(0) + "%"],
  watch_trend_8w_pct: ["Viewing trend, 8 weeks (per month)", v => v.toFixed(0) + "%"],
  days_since_active: ["Days since last active", v => v.toFixed(1)],
  completion_rate: ["Completion rate", v => (v * 100).toFixed(0) + "%"],
  category_concentration: ["Share of viewing in one category", v => (v * 100).toFixed(0) + "%"],
  fav_content_ended: ["Followed title has ended", v => (v >= 0.5 ? "Yes" : (v * 100).toFixed(0) + "%")],
  days_to_next_release: ["Days to next release in genre", v => v.toFixed(0)],
  failed_renewals_30d: ["Failed renewals, 30 days", v => v.toFixed(1)],
  low_balance_renewals_30d: ["Low-balance renewals, 30 days", v => v.toFixed(1)],
  buffering_errors_7d: ["Buffering errors, 7 days", v => v.toFixed(1)],
  app_crashes_7d: ["App crashes, 7 days", v => v.toFixed(1)],
  video_start_sec: ["Video start time, seconds", v => v.toFixed(1)],
  support_tickets_30d: ["Support tickets, 30 days", v => v.toFixed(1)],
  ticket_negative: ["Negative ticket", v => (v >= 0.5 ? "Yes" : (v * 100).toFixed(0) + "%")],
  offer_open_rate: ["Offers opened", v => (v * 100).toFixed(0) + "%"],
  tenure_days: ["Tenure, days", v => v.toFixed(0)],
  sessions_7d: ["Sessions, 7 days", v => v.toFixed(1)],
};

function renderWatchFilters() {
  const opts = (sel, vals) => sel.insertAdjacentHTML("beforeend", vals.map(v => `<option>${esc(v)}</option>`).join(""));
  opts(document.getElementById("wPlan"), [...new Set(D.watchlist.map(w => w.plan))].sort());
  opts(document.getElementById("wChannel"), [...new Set(D.watchlist.map(w => w.channel))].sort());
  opts(document.getElementById("wPersona"), D.personas.map(p => p.persona).filter(p => D.watchlist.some(w => w.persona === p)));
  ["wSearch", "wPlan", "wChannel", "wPersona"].forEach(id => document.getElementById(id).addEventListener("input", renderWatch));
}

const riskColor = s => (s >= .3 ? css("--burgundy") : s >= .15 ? css("--gold") : css("--slate"));

function renderWatch() {
  const q = document.getElementById("wSearch").value.trim().toUpperCase();
  const plan = document.getElementById("wPlan").value, ch = document.getElementById("wChannel").value, pe = document.getElementById("wPersona").value;
  const rows = D.watchlist.filter(w => (!q || w.id.includes(q)) && (!plan || w.plan === plan) && (!ch || w.channel === ch) && (!pe || w.persona === pe));
  document.getElementById("watchTable").innerHTML =
    `<thead><tr><th class="num">Rank</th><th>Subscriber</th><th>Probability</th><th>Persona</th><th>Plan</th><th>Channel</th><th class="num">PKR / month</th><th>Principal reason</th></tr></thead><tbody>` +
    rows.map(w => `<tr class="click" data-id="${w.id}"><td class="num">${w.rank}</td><td>${w.id}</td>
      <td><span class="bar" style="width:${w.score * 70}px;background:${riskColor(w.score)}"></span>${PCT(w.score)}</td>
      <td>${esc(w.persona)}</td><td>${esc(w.plan)}</td><td>${esc(w.channel)}</td><td class="num">${w.revenue}</td>
      <td>${w.reasons[0] ? esc(w.reasons[0].text) : "—"}</td></tr>`).join("") + "</tbody>";
  document.querySelectorAll("#watchTable tr.click").forEach(tr => tr.addEventListener("click", () => {
    document.querySelectorAll("#watchTable tr.sel").forEach(x => x.classList.remove("sel"));
    tr.classList.add("sel"); explain(tr.dataset.id);
  }));
}

function explain(id) {
  const w = D.watchlist.find(x => x.id === id);
  const maxW = Math.max(...w.reasons.map(r => r.weight), .01);
  const top = w.reasons[0];
  document.getElementById("explain").innerHTML = `
    <div class="label">Subscriber explanation</div>
    <div class="subject">${w.id}</div>
    <p class="hint" style="margin:0">${esc(w.plan)} plan · ${esc(w.channel)} · ${esc(w.city)} · ${esc(w.genre)} · PKR ${w.revenue} per month<br>Persona: <b>${esc(w.persona)}</b></p>
    <div class="score-line"><span class="big">${PCT(w.score)}</span>
      <span>probability of cancelling within 30 days<br><span class="hint small">Rank ${w.rank} of ${NUM(D.kpis.subscribers)}; ${(w.score / D.kpis.expected_churn_rate).toFixed(1)} times the base average</span></span></div>
    <h3>Principal reasons</h3>
    ${w.reasons.map(r => `<div class="reason">${esc(r.text)} <span class="hint small">· ${esc(r.group)}</span><div class="rbar" style="width:${r.weight / maxW * 100}%"></div></div>`).join("") || "<p class='hint'>No single dominant reason.</p>"}
    <h3>Against the base average</h3>
    <table><thead><tr><th>Measure</th><th class="num">Subscriber</th><th class="num">Average</th></tr></thead><tbody>${Object.entries(FACT_LABELS).map(([k, [lab, f]]) =>
      `<tr><td>${lab}</td><td class="num"><b>${f(w.facts[k])}</b></td><td class="num">${f(D.population_avg[k])}</td></tr>`).join("")}</tbody></table>
    ${top ? `<div class="action-box"><div class="label">Suggested action, subject to approval</div><p>${ACTIONS[top.code]}</p></div>` : ""}`;
}

// ---------- campaign scenarios ----------
function simulate(k, save, disc, take) {
  const ds = D.deciles.slice(0, k);
  const contacted = ds.reduce((a, d) => a + d.subscribers, 0);
  const leavers = ds.reduce((a, d) => a + d.expected_churners, 0);
  const avgRev = ds.reduce((a, d) => a + d.avg_revenue * d.subscribers, 0) / contacted;
  const saved = leavers * save;
  const revSaved = saved * avgRev;
  const stayers = contacted - leavers + saved;
  const cost = stayers * take * avgRev * disc;
  // The same campaign aimed at randomly chosen subscribers, for comparison
  const rLeavers = contacted * D.kpis.expected_churn_rate, rSaved = rLeavers * save;
  const rNet = rSaved * D.kpis.avg_revenue_pkr - (contacted - rLeavers + rSaved) * take * D.kpis.avg_revenue_pkr * disc;
  return { contacted, leavers, saved, revSaved, cost, net: revSaved - cost, rNet };
}

function renderSim() {
  const k = +sTop.value, save = sSave.value / 100, disc = sDisc.value / 100, take = sTake.value / 100;
  vTop.textContent = `${k * 10}% (${NUM(k * D.kpis.subscribers / 10)} subscribers)`;
  vSave.textContent = sSave.value + "%"; vDisc.textContent = sDisc.value + "%"; vTake.textContent = sTake.value + "%";
  const r = simulate(k, save, disc, take);
  document.getElementById("simOut").innerHTML = [
    ["Contacted", NUM(r.contacted), "subscribers"], ["Leavers reached", NUM(r.leavers), PCT(r.leavers / r.contacted) + " of those contacted"],
    ["Retained", NUM(r.saved), "subscribers"], ["Revenue retained", PKR(r.revSaved), "per month"],
    ["Cost of offer", PKR(r.cost), "per month"], ["Net benefit", PKR(r.net), r.net >= 0 ? "positive return" : "negative return", r.net >= 0 ? "pos" : "neg"],
  ].map(([l, v, n, c]) => `<div class="kpi ${c || ""}"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`).join("");
  const xs = [...Array(10).keys()].map(i => i + 1);
  const sims = xs.map(x => simulate(x, save, disc, take));
  chart("simChart", {
    type: "line",
    data: { labels: xs.map(x => `Top ${x * 10}%`), datasets: [
      { label: "Targeted by the model", data: sims.map(s => s.net), borderColor: css("--navy"), backgroundColor: css("--navy"), borderWidth: 2,
        pointRadius: xs.map(x => (x === k ? 5 : 2)) },
      { label: "Chosen at random", data: sims.map(s => s.rNet), borderColor: css("--slate"), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" },
               tooltip: { callbacks: { label: c => `${c.dataset.label}: ${PKR(c.raw)}` } } },
               scales: { x: { grid: { display: false } },
                         y: { title: { display: true, text: "Net benefit, PKR per month" }, ticks: { callback: v => (v / 1000) + "k" } } } },
  });
  const best = sims.reduce((b, s, i) => (s.net > sims[b].net ? i : b), 0);
  document.getElementById("simNote").textContent =
    `On these assumptions the most profitable reach is the top ${(best + 1) * 10}% (net ${PKR(sims[best].net)} per month). ` +
    `The same campaign aimed at randomly chosen subscribers would return ${PKR(r.rNet)}; targeting by the model adds ${PKR(r.net - r.rNet)} per month.`;
}
const [sTop, sSave, sDisc, sTake, vTop, vSave, vDisc, vTake] =
  ["sTop", "sSave", "sDisc", "sTake", "vTop", "vSave", "vDisc", "vTake"].map(id => document.getElementById(id));
[sTop, sSave, sDisc, sTake].forEach(s => s.addEventListener("input", renderSim));

// ---------- model validation ----------
const SHORT = { "Logistic regression (baseline)": "Logistic", "Gradient boosting": "Boosting", "Perfect model (ceiling)": "Ceiling" };
function renderModel() {
  const m = D.model, comp = m.comparison, ceil = m.ceiling;
  const cols = [...Object.keys(comp), "Perfect model (ceiling)"];
  const get = (c, k) => (c === "Perfect model (ceiling)" ? ceil[k] : comp[c][k]);
  const rows = [["AUC", "auc", v => v.toFixed(3)], ["Precision, top decile", "precision_top10", v => PCT(v, 1)],
                ["Recall, top decile", "recall_top10", v => PCT(v, 1)], ["Lift, top decile", "lift_top10", v => v.toFixed(2) + "×"],
                ["Brier score", "brier", v => v.toFixed(4)]];
  document.getElementById("modelTable").innerHTML =
    `<thead><tr><th>Measure</th>${cols.map(c => `<th class="num" title="${esc(c)}">${SHORT[c]}${c === m.name ? " *" : ""}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(([l, k, f]) => `<tr><td>${l}</td>${cols.map(c => `<td class="num">${f(get(c, k))}</td>`).join("")}</tr>`).join("") + "</tbody>";
  const tRows = [["AUC of at least 0.75", m.auc.toFixed(3), m.targets["AUC >= 0.75"]],
                 ["Top-decile precision of at least 40%", PCT(m.precision_top10, 1), m.targets["Precision top 10% >= 40%"]],
                 ["Top band within 5 points of observed", `${PCT(m.top_band_predicted)} vs ${PCT(m.top_band_actual)}`, m.targets["Top band calibrated (within 5 pts)"]]];
  document.getElementById("targets").innerHTML = `<thead><tr><th>Target</th><th class="num">Result</th><th>Status</th></tr></thead><tbody>` +
    tRows.map(([a, b, ok]) => `<tr><td>${a}</td><td class="num">${b}</td><td>${ST(ok, "Met", "Not met")}</td></tr>`).join("") + "</tbody>";
  document.getElementById("ceilingNote").innerHTML =
    `* Model in use. Gradient boosting did not improve AUC by the required 0.01 (${comp["Gradient boosting"].auc} against ${comp[m.name].auc}), so the simpler and more explainable logistic regression was retained. ` +
    `The ceiling is the score of a model that knows the true generating rules: AUC ${ceil.auc} and ${PCT(ceil.precision_top10, 1)} precision. ` +
    `The model in use therefore attains <b>${PCT(m.auc / ceil.auc)} of the attainable AUC</b>, and the 40% precision target was not reachable on this data.`;

  const cal = m.calibration;
  const lim = Math.max(...cal.map(c => Math.max(c.predicted, c.actual))) * 1.1;
  chart("calChart", {
    type: "scatter",
    data: { datasets: [
      { label: "Model in use", data: cal.map(c => ({ x: c.predicted * 100, y: c.actual * 100 })), backgroundColor: css("--navy"),
        borderColor: css("--navy"), pointRadius: 4, showLine: true, borderWidth: 1.5 },
      { label: "Perfect calibration", data: [{ x: 0, y: 0 }, { x: lim * 100, y: lim * 100 }], showLine: true, borderDash: [4, 4],
        borderColor: css("--slate"), borderWidth: 1, pointRadius: 0 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
               scales: { x: { title: { display: true, text: "Predicted churn, %" } }, y: { title: { display: true, text: "Observed churn, %" } } } },
  });

  const NICE = { watch_change_pct: "Change in viewing (week)", watch_trend_8w_pct: "Viewing trend (8 weeks)", days_since_active: "Days inactive",
                 completion_rate: "Completion rate", category_concentration: "One-category viewing", fav_content_ended: "Followed title ended",
                 catalogue_match_titles: "Catalogue match", recs_ignored_30d: "Ignored recommendations", failed_renewals_30d: "Failed renewals",
                 low_balance_renewals_30d: "Low balance at renewal", payment_switches_90d: "Payment method switches", buffering_errors_7d: "Buffering errors",
                 app_crashes_7d: "App crashes", video_start_sec: "Video start time", login_failures_30d: "Login failures",
                 plan_downgrades_90d: "Plan downgrades", past_cancellations: "Past cancellations", used_discount: "Discount history",
                 support_tickets_30d: "Support tickets", ticket_negative: "Negative ticket", ticket_resolved: "Ticket resolved", tenure_days: "Tenure" };
  document.getElementById("ruleTable").innerHTML =
    `<thead><tr><th>Signal</th><th>True effect</th><th class="num">Model coefficient</th><th>Recovered</th></tr></thead><tbody>` +
    D.rule_check.map(r => `<tr><td>${NICE[r.feature] || esc(r.feature)}</td><td>${r.true_effect}</td>
      <td class="num">${r.model_coefficient > 0 ? "+" : ""}${r.model_coefficient.toFixed(3)}</td><td>${ST(r.matches, "Yes", "No")}</td></tr>`).join("") +
    `</tbody><tfoot><tr><td>Recovered</td><td></td><td></td><td>${D.rule_check.filter(r => r.matches).length} of ${D.rule_check.length}</td></tr></tfoot>`;
}

// ---------- load ----------
Promise.all(["data/dashboard.json", "data/weekly_note.json", "data/facts.json"].map(u => fetch(u).then(r => r.json())))
  .then(([d, n, f]) => {
    D = d; NOTE = n; FACTS = f.facts;
    renderOverview(); renderNote(); renderWatchFilters(); renderWatch(); explain(D.watchlist[0].id); renderSim(); renderModel();
  })
  .catch(e => document.querySelector("main").insertAdjacentHTML("afterbegin", `<div class="card">The report data could not be loaded: ${esc(e.message)}</div>`));
