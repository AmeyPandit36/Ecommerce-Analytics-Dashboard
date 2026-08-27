#!/usr/bin/env node
/**
 * Headless front-end check for the dashboard.
 *
 *   python app.py &                                  # any server that serves the app
 *   npm i jsdom                                      # one dev dependency, nothing else
 *   BASE=http://127.0.0.1:5050 node scripts/frontend_dom_test.mjs
 *
 * jsdom cannot rasterise a canvas, so Chart.js is replaced by a stub that records every
 * chart config the page builds. That is enough to prove the interesting properties: the page
 * scripts run without errors, every declared chart is constructed with labels + numeric series,
 * horizontal charts really get indexAxis:"y", the product table drives /api/products for
 * search/sort/pagination, filter chips and the export link keep the active query string, and the
 * AI analyst renders answers (and honest refusals) end to end.
 */
import { JSDOM, VirtualConsole } from "jsdom";
import { readFileSync } from "node:fs";

const BASE = (process.env.BASE || "http://127.0.0.1:5050").replace(/\/$/, "");
const ROOT = process.env.ROOT || "/home/user/Ecommerce-Analytics-Dashboard";
const APP_JS = readFileSync(`${ROOT}/public/static/app.js`, "utf8");

const created = [];
class ChartStub {
  constructor(el, cfg) { this.el = el; this.cfg = cfg; this.data = cfg.data; this.options = cfg.options; created.push({ el, cfg }); }
  destroy() { this.destroyed = true; }
  resize() {} update() {} static register() {}
}
ChartStub.defaults = { font: {}, color: "", borderColor: "", backgroundColor: "",
  plugins: { legend: {}, tooltip: {}, title: {} }, scales: {}, elements: {} };

async function page(path, { wait = 800 } = {}) {
  const res = await fetch(BASE + path);
  const html = await res.text();
  const problems = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => { if (!/not implemented/i.test(e.message)) problems.push("jsdomError: " + e.message); });
  vc.on("error", (...a) => problems.push("console.error: " + a.join(" ")));
  const dom = new JSDOM(html, { url: BASE + path, runScripts: "outside-only", pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  w.Chart = ChartStub;
  w.fetch = async (url, opts) => {
    const r = await fetch(new URL(url, BASE).href, opts);
    const body = await r.text();
    return { ok: r.ok, status: r.status, headers: r.headers, text: async () => body, json: async () => JSON.parse(body) };
  };
  w.addEventListener("error", (e) => problems.push("window error: " + e.message));
  w.addEventListener("unhandledrejection", (e) => problems.push("rejection: " + (e.reason && e.reason.message)));
  const spec = html.match(/id="page-data" type="application\/json">([\s\S]*?)<\/script>/);
  const payload = spec ? JSON.parse(spec[1]) : { charts: {} };
  w.eval(APP_JS);
  await new Promise((r) => setTimeout(r, wait));
  return { w, d: w.document, problems, res, payload };
}

let fails = 0, passes = 0;
const check = (label, ok, extra = "") => {
  if (ok) { passes++; console.log("  ✓ " + label); }
  else { fails++; console.log("  ✗ " + label + (extra ? " — " + extra : "")); }
};
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

console.log("Overview /dashboard?cat=2");
created.length = 0;
{
  const { d, problems, payload } = await page("/dashboard?cat=2");
  const canvases = d.querySelectorAll("[data-chart]").length;
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check(`all ${canvases} charts constructed`, created.length === canvases && canvases > 0, `got ${created.length}`);
  const values = [...d.querySelectorAll(".kpi .k-value")];
  check("KPI values rendered", values.length >= 6, `${values.length} cards`);
  check("no n/a KPIs under cat=2", values.every((k) => k.textContent.trim() && k.textContent.trim() !== "n/a"),
        values.map(v => v.textContent.trim()).join(","));
  check("every chart has labels + series", created.every((c) => c.cfg.data.labels.length > 0
        && c.cfg.data.datasets.length > 0 && c.cfg.data.datasets.every((s) => s.data.length > 0)));
  const horizontal = created.filter((c) => c.cfg.options.indexAxis === "y");
  const wantIds = Object.values(payload.charts || {}).filter((c) => c.horizontal).map((c) => c.id);
  check("declared horizontal charts rendered sideways",
        wantIds.every((id) => created.find((c) => c.el.dataset.chart === id)?.cfg.options.indexAxis === "y"),
        `declared=${wantIds.length} built=${horizontal.length}`);
  check("horizontal value axis starts at zero", horizontal.every((c) => c.cfg.options.scales.x.beginAtZero === true));
  check("label-heavy charts use the horizontal variant",
        !created.some((c) => c.cfg.data.labels.length > 10 && c.cfg.options.indexAxis !== "y"
                             && c.cfg.type === "bar" && c.cfg.data.datasets.length === 1));
  check("vertical charts keep indexAxis=x", created.filter((c) => c.cfg.options.indexAxis !== "y")
        .every((c) => c.cfg.options.indexAxis === "x"));
  check("tooltip formatter wired", created.every((c) => typeof c.cfg.options.plugins.tooltip.callbacks.label === "function"));
  check("insight cards shown", d.querySelectorAll(".insights .insight, .insights article").length >= 3,
        `${d.querySelectorAll(".insights .insight, .insights article").length}`);
  check("export link carries filters", d.querySelector("[data-export]")?.href.includes("cat=2"),
        d.querySelector("[data-export]")?.href);
  check("active filter chip shown", !!d.querySelector(".chip"), "no .chip");
  check("reset link present", !!d.querySelector("[data-reset]"));
  const selects = d.querySelectorAll("[data-filterbar] select[data-filter-key]");
  check("filter bar has ≥8 controls", selects.length >= 8, `${selects.length}`);
  check("filter options are real values", [...selects].every((s) => s.options.length > 1));
}

console.log("Sales /sales — interactive product table");
created.length = 0;
{
  const { d, w, problems } = await page("/sales");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("charts built", created.length >= 5, `${created.length}`);
  const root = d.querySelector("[data-product-table]");
  check("table root exists", !!root);
  const headCells = root.querySelectorAll("thead th[data-field]");
  check("sortable headers rendered", headCells.length >= 5, `${headCells.length}`);
  let rows = root.querySelectorAll("tbody tr");
  check("first page has 12 rows", rows.length === 12, `${rows.length}`);
  check("count line filled", /\d/.test(root.querySelector("[data-count]")?.textContent || ""));
  const firstCell = rows[0]?.querySelector("td")?.textContent;
  root.querySelector('[data-pager] button[data-go="2"]').click();
  await tick(700);
  const rows2 = root.querySelectorAll("tbody tr");
  check("page 2 loads different rows", rows2.length > 0 && rows2[0].querySelector("td").textContent !== firstCell,
        `${rows2.length} rows`);
  const search = root.querySelector("[data-search]");
  search.value = "42";
  search.dispatchEvent(new w.Event("input", { bubbles: true }));
  await tick(800);
  check("search hits server and repopulates", root.querySelectorAll("tbody tr").length > 0);
  check("search term echoed in count", /42/.test(root.querySelector("[data-count]")?.textContent || ""),
        root.querySelector("[data-count]")?.textContent);
  root.querySelector('[data-clear-search]').click();
  await tick(700);
  check("clear search restores rows", root.querySelectorAll("tbody tr").length === 12);
  const idHeader = root.querySelector('thead th[data-field="product_id"]');
  idHeader.click();
  await tick(700);
  check("sort indicator set", idHeader.classList.contains("sorted"), idHeader.className);
  check("sort arrow rendered", /[▲▼]/.test(idHeader.querySelector(".sort-ind")?.textContent || ""),
        idHeader.querySelector(".sort-ind")?.textContent);
  const per = root.querySelector("[data-per]");
  per.value = "8";
  per.dispatchEvent(new w.Event("change", { bubbles: true }));
  await tick(700);
  check("rows-per-page honoured", root.querySelectorAll("tbody tr").length === 8,
        `${root.querySelectorAll("tbody tr").length}`);
  check("no error row", !/Could not load products/.test(root.textContent));
  check("table cells escaped", !/<script|onerror=/i.test(root.innerHTML));
}

console.log("Journey /journey?month=3");
created.length = 0;
{
  const { d, problems, payload } = await page("/journey?month=3");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("funnel steps rendered", d.querySelectorAll(".funnel .step").length >= 3,
        `${d.querySelectorAll(".funnel .step").length}`);
  check("funnel bars have width", [...d.querySelectorAll(".funnel .fill")].every((f) => /width:\s*\d/.test(f.getAttribute("style"))));
  check("multi-series behaviour charts", created.some((c) => c.cfg.data.datasets.length >= 3),
        `${created.length} charts`);
  const horiz = Object.values(payload.charts).filter((c) => c.horizontal).map((c) => c.id);
  check("every horizontal chart got indexAxis=y",
        horiz.every((id) => created.find((c) => c.el.dataset.chart === id)?.cfg.options.indexAxis === "y"),
        `horizontal ids: ${horiz}`);
  check("5+ charts on journey", created.length >= 5, `${created.length}`);
}

console.log("Empty state /sales?cat=99");
{
  const { d, problems } = await page("/sales?cat=99");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("empty note shown", /No rows match these filters/.test(d.body.textContent),
        (d.querySelector(".note .t")?.textContent || "no note").trim());
  check("empty note offers reset", /Reset filters/.test(d.querySelector(".note")?.textContent || ""));
  check("empty note names the dataset span", /25,000 sessions/.test(d.querySelector(".note")?.textContent || ""));
  check("no crash text", !/Traceback|NoneType/.test(d.body.textContent));
}

console.log("AI analyst /ai-analyst?cat=5");
created.length = 0;
{
  const { d, w, problems } = await page("/ai-analyst?cat=5", { wait: 500 });
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  const chips = d.querySelectorAll("[data-ask]");
  check("example chips present", chips.length >= 8, `${chips.length}`);
  chips[0].click();
  await tick(1200);
  const answer = d.querySelector("[data-answers] .answer");
  check("answer card rendered", !!answer);
  check("answer headline non-empty", (answer?.querySelector(".headline")?.textContent || "").length > 20,
        answer?.querySelector(".headline")?.textContent);
  check("body/evidence/chart present", !!answer?.querySelector(".body") || !!answer?.querySelector("canvas"));
  check("method + limitations shown", /How this was computed/.test(answer?.textContent || "")
        && /Limitations/.test(answer?.textContent || ""));
  check("confidence pill is 'computed from data'", /computed from data/.test(answer?.textContent || ""),
        answer?.querySelector(".pill")?.textContent);
  check("filters echoed on answer", /cat|Category/i.test(d.body.textContent));
  const followup = answer?.querySelector("[data-followup]");
  check("follow-up buttons rendered", !!followup);
  followup?.click();
  await tick(1200);
  check("follow-up produced a second answer", d.querySelectorAll("[data-answers] .answer").length >= 2,
        `${d.querySelectorAll("[data-answers] .answer").length}`);
  const input = d.querySelector('[data-ask-form] input[name=question]');
  input.value = "who is the chief executive officer?";
  const form = d.querySelector("[data-ask-form]");
  if (typeof form.requestSubmit === "function") form.requestSubmit();
  else form.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  await tick(1400);
  const last = d.querySelector("[data-answers] .answer");
  check("unsupported question refused, not invented", /not|cannot|could not|unable|No question|outside/i.test(last?.textContent || ""),
        last?.textContent?.slice(0, 90));
  check("refusal has no fabricated numbers", !/₹[\d]/.test(last?.querySelector(".headline")?.textContent || ""),
        last?.querySelector(".headline")?.textContent);
  check("no lingering spinner", !d.querySelector("[data-answers] .busy"));
  check("chart from answer rendered", created.length >= 1, `${created.length}`);
}

console.log("Data quality /data-quality");
created.length = 0;
{
  const { d, problems, payload } = await page("/data-quality");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("column profile has 29 rows", d.querySelectorAll("table tbody tr").length >= 29,
        `${d.querySelectorAll("table tbody tr").length}`);
  check("dq charts built", created.length >= 2, `${created.length}`);
  check("profile covers dtype/missing/outliers", ["Type", "Missing", "Distinct", "Outliers"]
        .every((h) => new RegExp(h).test(d.body.textContent)));
  const horizDQ = Object.values(payload.charts || {}).filter((c) => c.horizontal).map((c) => c.id);
  check("quality hbars sideways",
        horizDQ.length >= 1 && horizDQ.every((id) => created.find((c) => c.el.dataset.chart === id)?.cfg.options.indexAxis === "y"),
        `ids=${horizDQ}`);
  const labels = [...d.querySelectorAll(".kpi .k-label span")].map((e) => e.textContent.trim());
  check("quality KPIs complete", ["Rows", "Columns", "Missing cells", "Duplicate rows"]
        .every((k) => labels.includes(k)), labels.join("|"));
}

console.log("Customers /customers");
created.length = 0;
{
  const { d, problems } = await page("/customers");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("segment table shown", d.querySelectorAll("table").length >= 2, `${d.querySelectorAll("table").length}`);
  check("charts built", created.length >= 3, `${created.length}`);
  check("segmentation transparency note", /High|Medium|Low/.test(d.body.textContent));
}

console.log(`\n${passes} passed, ${fails} failed ${fails ? "✗" : "✓"}`);
process.exit(fails ? 1 : 0);
