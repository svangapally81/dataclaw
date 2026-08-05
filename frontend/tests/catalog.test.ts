import { describe, expect, it } from "vitest";
import { expectedConnectorSlugs, workspaceTabs } from "../src/lib/catalog";

describe("DataClaw product contract", () => {
  it("keeps the four sidebar tabs", () => {
    expect(workspaceTabs).toEqual(["Editor", "Connectors", "Settings", "Gateway"]);
  });

  it("keeps the agreed enterprise connector catalog", () => {
    expect(expectedConnectorSlugs).toContain("sqlite");
    expect(expectedConnectorSlugs).toContain("notion");
    expect(expectedConnectorSlugs).toContain("snowflake");
    expect(expectedConnectorSlugs).toContain("databricks");
    expect(expectedConnectorSlugs).toContain("fivetran");
    expect(expectedConnectorSlugs).toContain("openai");
    expect(expectedConnectorSlugs).toHaveLength(20);
  });
});
