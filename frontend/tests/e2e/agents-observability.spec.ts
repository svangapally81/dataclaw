import { expect, test } from "@playwright/test";

const now = new Date().toISOString();

const chatAgent = {
  id: "agent-chat",
  workspace_id: "ws-1",
  name: "chat",
  display_name: "Chat",
  system_prompt: "You are DataClaw.",
  is_system: true,
  enabled: true,
  icon_key: "bot",
  created_at: now,
  updated_at: now,
};

const grants = [
  {
    id: "grant-sqlite",
    agent_id: "agent-chat",
    connector_slug: "sqlite",
    read_enabled: true,
    write_enabled: true,
  },
  {
    id: "grant-airflow",
    agent_id: "agent-chat",
    connector_slug: "airflow",
    read_enabled: true,
    write_enabled: false,
  },
];

const observabilityFeed = {
  total: 2,
  needs_approval: 1,
  events: [
    {
      id: "alert-drop",
      kind: "alert",
      timestamp: now,
      severity: "critical",
      title: "Agent chat wants to DROP_TABLE test_summary",
      detail: "Approval required for DataClaw MCP write SQL.",
      state: "needs_approval",
      requires_approval: true,
      acknowledged_at: null,
      acknowledged_by: null,
      resolved_at: null,
      resolved_by: null,
      actions: ["approve", "acknowledge", "resolve"],
      timeline: [{ step: "policy", status: "requires_approval" }],
    },
    {
      id: "run-docs",
      kind: "agent_run",
      timestamp: now,
      severity: "info",
      title: "docs completed",
      detail: "Docs agent generated column descriptions.",
      state: "completed",
      requires_approval: false,
      actions: [],
      timeline: [],
    },
  ],
};

test("agents grant grid and observability approval actions render in browser", async ({ page }) => {
  let approveSeen = false;
  let rejectSeen = false;

  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({ json: { email: "admin@dataclaw.local", is_admin: true } }),
  );
  await page.route("**/api/v1/connectors", (route) =>
    route.fulfill({
      json: [
        { slug: "sqlite", display_name: "SQLite", category: "data_store", status: "ok", credential_state: "configured" },
      ],
    }),
  );
  await page.route("**/api/v1/workspace", (route) =>
    route.fulfill({ json: { tabs: ["Editor", "Agents", "Gateway"], datasets: [], knowledge_documents: [], lineage: [] } }),
  );
  await page.route("**/api/v1/chat/threads", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/agents/dashboard", (route) =>
    route.fulfill({ json: { agent_cards: [], last_hour_feed: [], runs: [], alerts: [{ id: "alert-drop", severity: "critical", title: "Needs approval", detail: "", resolved: false }] } }),
  );
  await page.route(/.*\/api\/v1\/agents$/, async (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ json: { ...chatAgent, id: "agent-custom", name: "reviewer", display_name: "reviewer", is_system: false } });
    }
    return route.fulfill({ json: [chatAgent] });
  });
  await page.route(/.*\/api\/v1\/agents\/agent-chat(\?.*)?$/, (route) =>
    route.fulfill({ json: { ...chatAgent, grants } }),
  );
  await page.route(/.*\/api\/v1\/agents\/agent-chat\/grants(\?.*)?$/, async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { grants: typeof grants };
      expect(body.grants.some((grant) => grant.connector_slug === "airflow" && grant.write_enabled)).toBeTruthy();
      return route.fulfill({ json: body.grants.map((grant, index) => ({ ...grant, id: `updated-${index}`, agent_id: "agent-chat" })) });
    }
    return route.fulfill({ json: grants });
  });
  await page.route("**/api/v1/mcp/catalog", (route) =>
    route.fulfill({
      json: [
        {
          slug: "sqlite",
          display_name: "SQLite",
          logo_key: "sqlite",
          read_tools: [{ name: "read_list_tables", scope: "read" }],
          write_tools: [{ name: "write_create_table", scope: "write" }],
        },
        {
          slug: "airflow",
          display_name: "Airflow",
          logo_key: "apache-airflow",
          read_tools: [{ name: "read_list_dags", scope: "read" }],
          write_tools: [{ name: "write_trigger_dag", scope: "write" }],
        },
      ],
    }),
  );
  await page.route("**/api/v1/observability/events**", (route) =>
    route.fulfill({ json: observabilityFeed }),
  );
  await page.route("**/api/v1/alerts/alert-drop/approve-and-execute", (route) => {
    approveSeen = true;
    return route.fulfill({ json: { status: "executed", alert: { ...observabilityFeed.events[0], state: "resolved", resolved_by: "admin@dataclaw.local" } } });
  });
  await page.route("**/api/v1/alerts/alert-drop/resolve", (route) => {
    rejectSeen = true;
    return route.fulfill({ json: { ...observabilityFeed.events[0], state: "resolved", resolved_by: "admin@dataclaw.local" } });
  });

  await page.goto("/");

  await page.getByRole("button", { name: "On-demand" }).click();
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  await page.locator(".connector-row", { hasText: "Chat" }).getByRole("button", { name: "Configure" }).click();
  await expect(page.getByText("Configure Chat")).toBeVisible();
  await expect(page.locator(".grant-row", { hasText: "SQLite" })).toBeVisible();
  await expect(page.locator(".grant-row", { hasText: "Airflow" })).toBeVisible();

  await expect(page.getByRole("button", { name: /Save grants/ })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Observability" }).click();
  await expect(page.getByText("Agent chat wants to DROP_TABLE test_summary")).toBeVisible();
  await page.getByText("Agent chat wants to DROP_TABLE test_summary").click();
  await expect(page.getByRole("button", { name: /Approve/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  await page.getByRole("button", { name: /Approve/ }).click();
  await expect.poll(() => approveSeen).toBeTruthy();

  await page.keyboard.press("Escape");
  await page.locator(".event-list button").first().click();
  await page.getByRole("button", { name: "Reject" }).click();
  await expect.poll(() => rejectSeen).toBeTruthy();
});
