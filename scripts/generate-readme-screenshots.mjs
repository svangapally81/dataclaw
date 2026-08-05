import playwright from "../frontend/node_modules/playwright/index.js";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = playwright;
const outDir = resolve("docs/screenshots");

const baseCss = `
  * { box-sizing: border-box; }
  body {
    margin: 0;
    width: 1280px;
    height: 800px;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f6f7f9;
    color: #1d2433;
  }
  .app { display: grid; grid-template-columns: 230px 1fr; height: 800px; }
  aside { background: #111827; color: #dbe4f0; padding: 28px 20px; }
  .brand { font-size: 23px; font-weight: 760; margin-bottom: 36px; color: #fff; }
  nav div { padding: 12px 14px; border-radius: 8px; margin-bottom: 8px; color: #9fb0c7; }
  nav .active { background: #263247; color: #fff; }
  main { padding: 34px 40px; overflow: hidden; }
  h1 { margin: 0 0 6px; font-size: 30px; letter-spacing: 0; }
  .sub { color: #647084; margin-bottom: 26px; }
  .band { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 14px 35px rgba(15,23,42,.08); }
  .grid { display: grid; gap: 16px; }
  .toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
  .pill { border-radius: 999px; padding: 7px 11px; background: #edf7ee; color: #237346; font-weight: 700; font-size: 12px; }
  .muted { color: #647084; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px; border-top: 1px solid #e8edf5; }
  .row:first-child { border-top: 0; }
  .button { background: #2563eb; color: white; padding: 9px 14px; border-radius: 7px; font-weight: 700; }
`;

const screens = {
  "brain.png": `
    <div class="app"><aside><div class="brand">DataClaw</div><nav><div>Editor</div><div>Connectors</div><div class="active">Knowledge</div><div>Monitoring</div><div>Settings</div></nav></aside>
    <main><h1>Brain graph</h1><div class="sub">Compiled lineage, docs, and pipeline relationships.</div>
    <div class="band" style="height:630px; position:relative; overflow:hidden;">
      ${["orders","customers","daily_orders_refresh","fct_revenue_daily","metrics_handbook","customer_360","payments","ltv"].map((n,i)=>`<div style="position:absolute; left:${170+(i%4)*210}px; top:${105+Math.floor(i/4)*210}px; width:128px; height:128px; border-radius:64px; background:${i%3===0?"#2563eb":i%3===1?"#14b8a6":"#f59e0b"}; color:white; display:flex; align-items:center; justify-content:center; text-align:center; padding:14px; font-weight:760; box-shadow:0 12px 24px rgba(15,23,42,.18);">${n}</div>`).join("")}
      <svg width="100%" height="100%" style="position:absolute; inset:0;"><g stroke="#94a3b8" stroke-width="3" opacity=".55" fill="none"><path d="M300 170 C430 150 520 150 640 170"/><path d="M640 170 C745 170 820 170 930 170"/><path d="M260 230 C300 340 330 410 380 505"/><path d="M640 230 C640 340 640 410 640 505"/><path d="M920 230 C860 340 820 410 770 505"/><path d="M430 565 C520 590 650 590 745 565"/></g></svg>
    </div></main></div>`,
  "chat.png": `
    <div class="app"><aside><div class="brand">DataClaw</div><nav><div class="active">Editor</div><div>Connectors</div><div>Knowledge</div><div>Monitoring</div></nav></aside>
    <main><h1>Chat with citations</h1><div class="sub">OpenAI tool use grounded in synced wiki pages and live SQL.</div>
    <div class="band" style="padding:24px; height:630px;">
      <div style="background:#eef4ff; padding:18px; border-radius:8px; width:72%; margin-left:auto;">What does the data glossary say about LTV?</div>
      <div style="margin-top:20px; background:#fff; border:1px solid #dbe5f3; padding:20px; border-radius:8px; width:82%; line-height:1.55;">LTV is lifetime value based on recognized revenue, refund exposure, and support cost adjustments. The current handbook links it to customer_360 and monthly revenue marts.</div>
      <div class="grid" style="grid-template-columns:repeat(3,1fr); margin-top:22px;">
        <div class="band" style="padding:18px;"><strong>wiki/notion/metrics-handbook.md</strong><br><span class="muted">citation</span></div>
        <div class="band" style="padding:18px;"><strong>wiki/postgres/customers.md</strong><br><span class="muted">citation</span></div>
        <div class="band" style="padding:18px;"><strong>SQL rows: 12</strong><br><span class="muted">tool result</span></div>
      </div>
    </div></main></div>`,
  "connectors.png": `
    <div class="app"><aside><div class="brand">DataClaw</div><nav><div>Editor</div><div class="active">Connectors</div><div>Knowledge</div><div>Monitoring</div></nav></aside>
    <main><div class="toolbar"><div><h1>Connectors</h1><div class="sub">20 production connectors, configured by credentials.</div></div><div class="button">Search</div></div>
    <div class="band">${["SQLite","PostgreSQL","MySQL","Airflow","Dagster","Fivetran","Google Docs / Drive","GitHub"].map((n,i)=>`<div class="row"><div><strong>${n}</strong><br><span class="muted">${i<3?"Sync schemas, columns, row counts, and query metadata.":"Sync jobs, docs, runs, failures, and lineage context."}</span></div><span class="pill">${i<4?"configured":"available"}</span></div>`).join("")}</div></main></div>`,
  "observability.png": `
    <div class="app"><aside><div class="brand">DataClaw</div><nav><div>Editor</div><div>Connectors</div><div>Knowledge</div><div class="active">Monitoring</div></nav></aside>
    <main><h1>Observability</h1><div class="sub">Mock flag enabled with curated alert and agent-run events.</div>
    <div class="grid" style="grid-template-columns:1fr 1fr 1fr; margin-bottom:16px;"><div class="band" style="padding:18px;"><strong>1 critical</strong><br><span class="muted">needs approval</span></div><div class="band" style="padding:18px;"><strong>2 warnings</strong><br><span class="muted">open</span></div><div class="band" style="padding:18px;"><strong>6 events</strong><br><span class="muted">mock payload</span></div></div>
    <div class="band">${["daily_orders_refresh failed in Airflow","Schema drift in core.orders","Slow query detected - weekly_customer_360.sql","dbt test not_null_orders_customer_id failed","freshness_agent: 47 tables checked"].map((n,i)=>`<div class="row"><div><strong>${n}</strong><br><span class="muted">${i===0?"critical alert":i<3?"warning/info alert":"agent run"}</span></div><span class="pill" style="background:${i===0?"#fee2e2":"#eef2ff"}; color:${i===0?"#b91c1c":"#334155"}">${i===0?"needs approval":i===3?"resolved":"open"}</span></div>`).join("")}</div></main></div>`,
  "wiki.png": `
    <div class="app"><aside><div class="brand">DataClaw</div><nav><div>Editor</div><div>Connectors</div><div class="active">Knowledge</div><div>Monitoring</div></nav></aside>
    <main><h1>Knowledge wiki</h1><div class="sub">Tier-1 markdown pages written from connector syncs.</div>
    <div class="grid" style="grid-template-columns:310px 1fr;"><div class="band">${["postgres/orders.md","postgres/customers.md","airflow/daily-orders-refresh.md","notion/metrics-handbook.md","dbt/fct-revenue-daily.md"].map((n,i)=>`<div class="row" style="justify-content:flex-start;"><span class="pill">${i+1}</span><strong>${n}</strong></div>`).join("")}</div>
    <div class="band" style="padding:28px; line-height:1.55;"><h1 style="font-size:24px;">orders</h1><p class="muted">Source: postgres | Tier: 1 | Entities: customers, payments, revenue</p><p>The orders table records checkout state transitions, payment totals, and fulfillment timing. It is produced by daily_orders_refresh and described by the metrics handbook.</p><pre style="background:#0f172a;color:#dbeafe;padding:18px;border-radius:8px;">produces: [[customer_360]]\\ndepends_on: [[customers]], [[payments]]</pre></div></div></main></div>`,
};

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
for (const [filename, body] of Object.entries(screens)) {
  await page.setContent(`<style>${baseCss}</style>${body}`);
  await page.screenshot({ path: resolve(outDir, filename), type: "png" });
}
await browser.close();
