import { expect, test, type Page } from "@playwright/test";

const wikiPage = {
  id: "page-1",
  workspace_id: "ws1",
  path: "wiki/notion/data-glossary.md",
  disk_path: "data/wiki/ws1/notion/data-glossary.md",
  tier: 1,
  source_type: "notion",
  source_id: "p1",
  title: "Data Glossary",
  body: "# Data Glossary\n\nDocuments [[orders]] and **customers**.",
  frontmatter: { entities: ["orders", "customers"], owner: "analytics" },
  entities: ["orders", "customers"],
  content_hash: "hash",
  created_at: "2026-05-08T00:00:00Z",
  updated_at: "2026-05-08T00:00:00Z",
};

const graph = {
  nodes: [
    { id: "node-orders", type: "table", canonical_name: "orders", aliases: [], primary_wiki_page_id: "page-1" },
    { id: "node-customers", type: "table", canonical_name: "customers", aliases: [], primary_wiki_page_id: "page-1" },
  ],
  edges: [
    {
      id: "edge-1",
      src_node_id: "node-orders",
      dst_node_id: "node-customers",
      relationship: "references_fk",
      evidence: "customer_id references customers",
      confidence: 0.9,
      source: "fk_match",
    },
  ],
};

async function mockShell(page: Page) {
  await page.route("**/auth/login", (route) =>
    route.fulfill({ json: { email: "admin@dataclaw.local", is_admin: true } }),
  );
  await page.route("**/connectors", (route) => route.fulfill({ json: [] }));
  await page.route("**/connectors/catalog", (route) => route.fulfill({ json: [] }));
  await page.route("**/workspace", (route) =>
    route.fulfill({ json: { tabs: ["Gateway", "Editor"], datasets: [], knowledge_documents: [], lineage: [] } }),
  );
  await page.route("**/agents/dashboard", (route) =>
    route.fulfill({ json: { agent_cards: [], last_hour_feed: [], runs: [], alerts: [] } }),
  );
}

test("Knowledge tab renders empty state, pages, preview, graph, and compile", async ({ page, context }) => {
  await mockShell(page);
  let pages = [];
  await page.route("**/knowledge/pages**", (route) => route.fulfill({ json: pages }));
  await page.route("**/knowledge/graph**", (route) => route.fulfill({ json: graph }));
  await page.route("**/knowledge/compile", (route) => {
    pages = [wikiPage];
    route.fulfill({ json: { nodes_created: 2, nodes_updated: 0, edges_created: 1, runtime_ms: 12 } });
  });

  await page.goto("/?tab=Knowledge");
  const password = page.getByLabel("Admin password");
  if (await password.isVisible()) {
    await password.fill("dataclaw-local-admin");
    await page.getByRole("button", { name: "Sign in" }).click();
  }

  await expect(page.getByText("No pages")).toBeVisible();
  await page.getByRole("button", { name: /Compile knowledge/ }).click();
  await expect(page.getByText("2 nodes, 1 edges")).toBeVisible();
  await expect(page.getByRole("button", { name: "Data Glossary" })).toBeVisible();
  await expect(page.locator(".wiki-page-head").getByRole("heading", { name: "Data Glossary" })).toBeVisible();
  await expect(page.getByText("data/wiki/ws1/notion/data-glossary.md")).toBeVisible();

  const popupPromise = context.waitForEvent("page");
  await page.getByRole("button", { name: /Open preview in new window/ }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/preview=1/);
  await expect(popup.locator(".app-sidebar")).toHaveCount(0);

  await page.getByRole("button", { name: "Graph" }).click();
  await expect(page.locator(".react-flow")).toBeVisible();
  await expect(page.getByText("orders")).toBeVisible();
  await page.getByText("orders").click();
  await expect(page.locator(".segmented").getByRole("button", { name: "Pages" })).toHaveClass(/active/);
});
