#!/usr/bin/env node
/**
 * Headless front-end check for the BI report.
 *
 *   python app.py &                                  # any server that serves the app
 *   npm i jsdom                                      # one dev dependency, nothing else
 *   BASE=http://127.0.0.1:5050 node scripts/frontend_dom_test.mjs
 *
 * jsdom cannot rasterise a canvas, so Chart.js is replaced by a stub that records every
 * chart config the page builds. That proves: the page scripts run without errors, every
 * declared chart is constructed with labels + numeric series, horizontal charts really get
 * indexAxis:"y", the slicers and reset/export links keep the active query string, the funnel
 * and "what the data tells us" sections render, and the empty state degrades gracefully.
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

async function page(path, { wait = 700 } = {}) {
  const res = await fetch(BASE + path);
  const html = await res.text();
  const problems = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => { if (!/not implemented/i.test(e.message)) problems.push("jsdomError: " + e.message); });
  vc.on("error", (...a) => problems.push("console.error: " + a.join(" ")));
  const dom = new JSDOM(html, { url: BASE + path, runScripts: "outside-only", pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  w.Chart = ChartStub;
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

console.log("Overview /overview");
created.length = 0;
{
  const { d, problems, payload } = await page("/overview");
  const canvases = d.querySelectorAll("[data-chart]").length;
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check(`all ${canvases} charts constructed`, created.length === canvases && canvases > 0, `got ${created.length}`);
  const values = [...d.querySelectorAll(".kpi .k-value")].map(v => v.textContent.trim());
  check("6 headline KPIs rendered", values.length === 6, `${values.length}`);
  check("revenue KPI = ₹10.12M", values.includes("₹10.12M"), values.join(","));
  check("sessions KPI = 25,000", values.includes("25,000"), values.join(","));
  check("conversion KPI = 22.46%", values.includes("22.46%"), values.join(","));
  check("abandonment KPI = 65.15%", values.includes("65.15%"), values.join(","));
  check("every chart has labels + series", created.every((c) => c.cfg.data.labels.length > 0
        && c.cfg.data.datasets.length > 0 && c.cfg.data.datasets.every((s) => s.data.length > 0)));
  const horizontal = created.filter((c) => c.cfg.options.indexAxis === "y");
  const wantIds = Object.values(payload.charts || {}).filter((c) => c.horizontal).map((c) => c.id);
  check("declared horizontal charts rendered sideways",
        wantIds.every((id) => created.find((c) => c.el.dataset.chart === id)?.cfg.options.indexAxis === "y"),
        `declared=${wantIds.length} built=${horizontal.length}`);
  check("tooltip formatter wired", created.every((c) => typeof c.cfg.options.plugins.tooltip.callbacks.label === "function"));
  check("funnel steps rendered", d.querySelectorAll(".funnel .fstep").length === 3,
        `${d.querySelectorAll(".funnel .fstep").length}`);
  check("key findings shown", d.querySelectorAll(".callout").length === 4,
        `${d.querySelectorAll(".callout").length}`);
  check("what-the-data-tells-us section", d.querySelectorAll(".tell").length >= 1,
        `${d.querySelectorAll(".tell").length}`);
  check("export link present", !!d.querySelector("[data-export]"));
  check("reset link present", !!d.querySelector("[data-reset]"));
  const selects = d.querySelectorAll("[data-filterbar] select[data-filter-key]");
  const controls = d.querySelectorAll("[data-filterbar] [data-filter-key]");
  check("filter bar has ≥14 controls", controls.length >= 14, `${controls.length}`);
  check("filter options are real values", [...selects].every((s) => s.options.length > 1));
  const keys = [...controls].map(s => s.dataset.filterKey);
  ["cat", "pay", "utype", "seg", "dbucket", "pband"].forEach(k =>
    check(`slicer ${k} present`, keys.includes(k), keys.join(",")));
  check("no lakh (L) notation remains", !/₹\d+\.\d+ L/.test(d.body.textContent));
  check("title is the report title", /E-Commerce Customer Behavior & Purchase Analysis/.test(d.querySelector(".report-head h1")?.textContent || ""));
}

console.log("Overview with filter /overview?cat=2");
{
  const { d, problems } = await page("/overview?cat=2");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("active filter chip shown", !!d.querySelector(".chip"), "no .chip");
  check("export link carries filters", d.querySelector("[data-export]")?.href.includes("cat=2"),
        d.querySelector("[data-export]")?.href);
}

console.log("Customers /customers");
created.length = 0;
{
  const { d, problems } = await page("/customers");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("charts built", created.length >= 5, `${created.length}`);
  check("segment table shown", d.querySelectorAll("table").length >= 1, `${d.querySelectorAll("table").length}`);
  const segs = [...d.querySelectorAll("table.data tbody td.key")].map(t => t.textContent.trim());
  check("four segments present", ["High value", "Mid value", "Core value", "Window shoppers"]
        .every(s => segs.includes(s)), segs.join("|"));
  check("high-value 836 customers shown", /836/.test(d.body.textContent));
  check("47.21% revenue share shown", /47\.21%/.test(d.body.textContent));
  check("50.53% never purchased shown", /50\.53%/.test(d.body.textContent));
  check("27.75% repeat shown", /27\.75%/.test(d.body.textContent));
  check("tells rendered", d.querySelectorAll(".tell").length >= 2, `${d.querySelectorAll(".tell").length}`);
}

console.log("Conversion /conversion");
created.length = 0;
{
  const { d, problems } = await page("/conversion");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("funnel steps rendered", d.querySelectorAll(".funnel .fstep").length === 3,
        `${d.querySelectorAll(".funnel .fstep").length}`);
  check("funnel values: 25,000 / 16,117 / 5,616",
        /25,000/.test(d.body.textContent) && /16,117/.test(d.body.textContent)
        && /5,616/.test(d.body.textContent));
  check("user type comparison shown", /25\.65%/.test(d.body.textContent) && /18\.55%/.test(d.body.textContent));
  check("duration callout shown", /20\.24%/.test(d.body.textContent) && /23\.62%/.test(d.body.textContent));
  check("discount AOV decline shown", /₹1,992/.test(d.body.textContent) && /₹1,382/.test(d.body.textContent));
  check("discount insight present", /Discounts are not solving conversion/.test(d.body.textContent));
}

console.log("Category & price /categories");
created.length = 0;
{
  const { d, problems } = await page("/categories");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("category 2 revenue shown", /₹2,037,576\.79|₹20\.38 L/.test(d.body.textContent));
  check("category 6 conversion shown", /24\.68%/.test(d.body.textContent));
  check("price band 63.6% shown", /63\.6%/.test(d.body.textContent));
  check("data quality note shown", /SKU-level analysis is excluded/.test(d.body.textContent),
        "no SKU note");
  check("no product ranking table", !/[Tt]op products|[Bb]est[- ]selling|product table/i.test(d.body.textContent));
}

console.log("Empty state /overview?cat=99");
{
  const { d, problems } = await page("/overview?cat=99");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("empty note shown", /No rows match these filters/.test(d.body.textContent),
        (d.querySelector(".note-title")?.textContent || "no note").trim());
  check("empty note names the dataset span", /25,000 sessions/.test(d.body.textContent));
  check("no crash text", !/Traceback|NoneType/.test(d.body.textContent));
}

console.log("Segment slicer /customers?seg=high");
{
  const { d, problems } = await page("/customers?seg=high");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("segment chip shown", /High value/.test(d.body.textContent), "no segment chip");
  check("segment filter applied (836 in range)", /836/.test(d.body.textContent));
}

console.log("Discount + price slicers /categories?dbucket=3&pband=2");
{
  const { d, problems } = await page("/categories?dbucket=3&pband=2");
  check("no JS errors", problems.length === 0, problems.slice(0, 3).join(" | "));
  check("discount bucket chip shown", /21–30%/.test(d.body.textContent), "no dbucket chip");
  check("price band chip shown", /₹1,001–1,500/.test(d.body.textContent), "no pband chip");
}

console.log(`\n${passes} passed, ${fails} failed ${fails ? "✗" : "✓"}`);
process.exit(fails ? 1 : 0);
