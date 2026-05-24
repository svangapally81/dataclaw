import { expect, test } from "@playwright/test";

const POSTGRES_CATALOG = {
  slug: "postgres",
  display_name: "PostgreSQL",
  category: "data_store",
  logo_key: "postgresql",
  docs_url: "https://www.postgresql.org/docs/",
  local_verification: "demo",
  sync_behavior: "Real local test connection, schema introspection, and read-only queries.",
  production_notes: "Uses SQLAlchemy asyncpg with read-only enforcement.",
  recommended: true,
  credential_schema: [
    { name: "database_url", label: "Database URL", secret: true, required: false, placeholder: "" },
  ],
};

test("renders Gateway + Editor with empty knowledge base until sync", async ({ page }) => {
  await page.route("**/auth/login", (route) =>
    route.fulfill({ json: { email: "admin@dataclaw.local", is_admin: true } }),
  );
  await page.route("**/connectors", (route) =>
    route.fulfill({
      json: [{ slug: "postgres", display_name: "PostgreSQL", category: "data_store", status: "demo", credential_state: "not_configured" }],
    }),
  );
  await page.route("**/connectors/catalog", (route) =>
    route.fulfill({ json: [POSTGRES_CATALOG] }),
  );
  await page.route("**/workspace", (route) =>
    route.fulfill({
      json: { tabs: ["Gateway", "Editor"], datasets: [], knowledge_documents: [], lineage: [] },
    }),
  );
  await page.route("**/agents/dashboard", (route) =>
    route.fulfill({ json: { agent_cards: [], last_hour_feed: [], runs: [], alerts: [] } }),
  );
  await page.route("**/connectors/postgres/test", (route) =>
    route.fulfill({ json: { slug: "postgres", status: "ok", mode: "real", message: "PostgreSQL connection succeeded." } }),
  );

  await page.goto("/");
  await page.getByLabel("Admin password").fill("dataclaw-local-admin");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("tab", { name: /Gateway/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Editor/ })).toBeVisible();
  await expect(page.getByText("Empty", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Connectors" })).toBeVisible();
  await page.locator(".connector-row", { hasText: "PostgreSQL" }).getByRole("button", { name: "Configure" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText("Connection succeeded")).toBeVisible();

  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("tab", { name: /Editor/ }).click();
  await expect(page.getByRole("heading", { name: /Ask DataClaw anything/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Show me daily revenue/ })).toBeVisible();
});
