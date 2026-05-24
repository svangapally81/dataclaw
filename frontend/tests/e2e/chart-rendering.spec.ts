import { expect, test, type Page } from "@playwright/test";

type ChartCase = {
  prompt: string;
  label: string;
  spec: Record<string, unknown>;
};

const baseEncoding = {
  color: { field: "category", type: "nominal" },
};

const CHARTS: ChartCase[] = [
  {
    prompt: "Show me daily revenue for the last 30 days as a line chart.",
    label: "line chart",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ date: "2026-04-16", revenue: 1200 }, { date: "2026-04-17", revenue: 1500 }] },
      mark: "line",
      encoding: { x: { field: "date", type: "temporal" }, y: { field: "revenue", type: "quantitative" } },
    },
  },
  {
    prompt: "Compare order counts by status as a bar chart.",
    label: "bar chart",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ status: "paid", count: 42 }, { status: "stuck_in_3ds", count: 7 }] },
      mark: "bar",
      encoding: { x: { field: "status", type: "nominal" }, y: { field: "count", type: "quantitative" } },
    },
  },
  {
    prompt: "What's the distribution of customers by country? Map it.",
    label: "country distribution fallback",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ country: "US", customers: 120 }, { country: "GB", customers: 80 }] },
      mark: "bar",
      encoding: { y: { field: "country", type: "nominal" }, x: { field: "customers", type: "quantitative" } },
    },
  },
  {
    prompt: "Show subscription plan breakdown as a pie chart.",
    label: "pie chart",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ plan: "starter", customers: 30 }, { plan: "pro", customers: 70 }] },
      mark: "arc",
      encoding: { theta: { field: "customers", type: "quantitative" }, color: { field: "plan", type: "nominal" } },
    },
  },
  {
    prompt: "Show me cohort retention as a heatmap.",
    label: "heatmap",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ cohort: "Jan", month: "M1", retention: 0.82 }, { cohort: "Jan", month: "M2", retention: 0.61 }] },
      mark: "rect",
      encoding: {
        x: { field: "month", type: "ordinal" },
        y: { field: "cohort", type: "nominal" },
        color: { field: "retention", type: "quantitative" },
      },
    },
  },
  {
    prompt: "Plot order placement time-of-day distribution as a histogram.",
    label: "histogram",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ hour: 8 }, { hour: 8 }, { hour: 9 }, { hour: 16 }] },
      mark: "bar",
      encoding: { x: { bin: true, field: "hour", type: "quantitative" }, y: { aggregate: "count", type: "quantitative" } },
    },
  },
  {
    prompt: "Show top 5 products by revenue with their categories color-coded.",
    label: "grouped bar",
    spec: {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ product: "Espresso", category: "dark", revenue: 500 }, { product: "Yirgacheffe", category: "light", revenue: 420 }] },
      mark: "bar",
      encoding: { x: { field: "product", type: "nominal" }, y: { field: "revenue", type: "quantitative" }, ...baseEncoding },
    },
  },
];

const emptyDashboard = { agent_cards: [], last_hour_feed: [], runs: [], alerts: [] };

async function mockAppShell(page: Page) {
  let messages: unknown[] = [];

  await page.route("**/auth/login", (route) =>
    route.fulfill({ json: { email: "admin@dataclaw.local", is_admin: true } }),
  );
  await page.route("**/connectors", (route) =>
    route.fulfill({
      json: [
        {
          slug: "postgres",
          display_name: "PostgreSQL",
          category: "data_store",
          status: "configured",
          credential_state: "configured",
          sync_state: "synced",
          logo_key: "postgresql",
        },
      ],
    }),
  );
  await page.route("**/connectors/catalog", (route) => route.fulfill({ json: [] }));
  await page.route("**/workspace", (route) =>
    route.fulfill({
      json: {
        id: "ws-chart",
        name: "Chart test",
        onboarding_complete: true,
        tabs: ["Gateway", "Editor", "Knowledge", "Settings"],
        datasets: [{ id: "ds1", name: "PostgreSQL", source_type: "postgres", schema_name: "core", tables: [] }],
        knowledge_documents: [],
        lineage: [],
      },
    }),
  );
  await page.route("**/agents/dashboard", (route) => route.fulfill({ json: emptyDashboard }));
  await page.route("**/worker/status", (route) =>
    route.fulfill({ json: { status: "ok", worker_status: "running", last_seen_at: "2026-05-15T00:00:00Z", age_seconds: 1 } }),
  );
  await page.route("**/llm/providers", (route) =>
    route.fulfill({ json: [{ slug: "openai", configured: true, values: { model: "gpt-test" }, secrets_set: [], secret_previews: {} }] }),
  );
  await page.route("**/llm/catalog", (route) =>
    route.fulfill({
      json: [
        {
          slug: "openai",
          display_name: "OpenAI",
          logo_key: "openai",
          docs_url: "https://platform.openai.com/docs",
          description: "Test provider",
          default_model: "gpt-test",
          wired: true,
          fields: [{ name: "model", label: "Model", secret: false, required: true, placeholder: "", options: ["gpt-test"] }],
        },
      ],
    }),
  );
  await page.route("**/chat/threads", (route) => route.fulfill({ json: [{ id: "thread-chart", title: "Chart matrix", created_at: "2026-05-15T00:00:00Z", updated_at: "2026-05-15T00:00:00Z" }] }));
  await page.route("**/chat/threads/thread-chart", (route) =>
    route.fulfill({
      json: {
        id: "thread-chart",
        title: "Chart matrix",
        created_at: "2026-05-15T00:00:00Z",
        updated_at: "2026-05-15T00:00:00Z",
        message_count: messages.length,
        messages,
      },
    }),
  );
  await page.route("**/ide/chat", async (route) => {
    const body = route.request().postDataJSON() as { question?: string };
    const chart = CHARTS.find((item) => item.prompt === body.question);
    if (!chart) {
      await route.fulfill({ status: 400, json: { detail: "Unknown chart prompt" } });
      return;
    }
    structuredClone(chart.spec);
    const response = {
      answer: `Rendered ${chart.label}.`,
      provider: "test",
      llm_status: "ok",
      status: "ok",
      thread_id: "thread-chart",
      thread_title: "Chart matrix",
      citations: [{ title: "core.orders", connector: "postgres" }],
      chart_spec: chart.spec,
      retrieval_trace: { results: [{ source: "core.orders", layer: "wiki", score: 0.99 }] },
    };
    messages = [
      ...messages,
      {
        id: `assistant-${messages.length + 1}`,
        role: "assistant",
        content: response.answer,
        provider: response.provider,
        llm_status: response.llm_status,
        citations: response.citations,
        rows: [],
        chart_spec: response.chart_spec,
        retrieval_trace: response.retrieval_trace,
        created_at: "2026-05-15T00:00:00Z",
      },
    ];
    await route.fulfill({
      headers: { "content-type": "text/event-stream" },
      body: [
        'event: thread\ndata: {"thread_id":"thread-chart","run_id":"run-chart"}',
        `event: delta\ndata: ${JSON.stringify({ content: response.answer })}`,
        `event: done\ndata: ${JSON.stringify(response)}`,
        "",
      ].join("\n\n"),
    });
  });
}

test("Scenario 7 renders every supported chart without leaking specs to console", async ({ page }) => {
  const consoleMessages: string[] = [];
  page.on("console", (message) => {
    if (["error", "info", "log"].includes(message.type())) {
      consoleMessages.push(`[${message.type()}] ${message.text()}`);
    }
  });

  await mockAppShell(page);
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Ask about your data" })).toBeVisible();

  for (const chart of CHARTS) {
    const composer = page.getByRole("textbox", { name: "Ask about your data" });
    await composer.fill(chart.prompt);
    await composer.press("Enter");
    await expect(page.getByText(`Rendered ${chart.label}.`).last()).toBeVisible();
    await expect(page.locator(".chat-chart svg")).toHaveCount(CHARTS.indexOf(chart) + 1);
    await expect(page.getByText("Unable to render chart.")).toHaveCount(0);
  }

  expect(consoleMessages.filter((line) => line.includes("vega-embed failed"))).toEqual([]);
  expect(consoleMessages.filter((line) => line.includes("$schema") || line.includes("chart_spec"))).toEqual([]);
});
