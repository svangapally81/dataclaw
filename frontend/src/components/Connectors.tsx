import { Cloud, Database, FileText, Search, Workflow } from "lucide-react";
import { useMemo, useState } from "react";

import { ConfigureModal } from "./ConfigureModal";
import { useConnectorCatalogQuery } from "../services/api";
import type { Connector, ConnectorCatalogItem, ConnectorStability, Dashboard } from "../types";

const STABILITY_META: Record<
  ConnectorStability,
  { label: string; cls: string; description: string }
> = {
  stable: {
    label: "Stable",
    cls: "stability-stable",
    description: "Read + write exercised live with audit/approval verified.",
  },
  stable_read_only: {
    label: "Stable (read-only)",
    cls: "stability-read-only",
    description: "Reads production-ready. Writes pending adapter work.",
  },
  beta: {
    label: "Beta",
    cls: "stability-beta",
    description: "Usable but expect rough edges — especially live-write paths.",
  },
  known_issue: {
    label: "Known issue",
    cls: "stability-known-issue",
    description: "Disabled by default; opt-in via EXPERIMENTAL_ENABLE_<slug>.",
  },
  unsupported: {
    label: "Unsupported",
    cls: "stability-unsupported",
    description: "Adapter retained for back-compat only.",
  },
};

const DEFAULT_VISIBLE_TIERS: ConnectorStability[] = ["stable", "stable_read_only", "beta"];

type ConnectorsProps = {
  connectors: Connector[];
  dashboard?: Dashboard;
  refresh: () => Promise<void>;
};

const CONNECTOR_CATEGORIES = [
  { key: "data_store", label: "Data stores", icon: Database },
  { key: "knowledge_base", label: "Documents", icon: FileText },
  { key: "etl_orchestration", label: "ETL", icon: Workflow },
] as const;

function statusLabel(connector?: Connector) {
  if (connector?.sync_state === "syncing") return "syncing…";
  if (connector?.sync_state === "synced") return "synced";
  if (connector?.sync_state === "sync_failed") return "sync failed";
  if (connector?.credential_state === "configured") return "configured";
  if (connector?.status && connector.status !== "credential_required" && connector.status !== "not_configured") {
    return connector.status.replaceAll("_", " ");
  }
  return "available";
}

function statusClass(connector?: Connector) {
  if (connector?.sync_state === "syncing") return "syncing";
  if (connector?.sync_state === "synced") return "ready";
  if (connector?.sync_state === "sync_failed") return "failed";
  if (connector?.credential_state === "configured") return "ready";
  return "";
}

export function Connectors({ connectors, refresh }: ConnectorsProps) {
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(CONNECTOR_CATEGORIES[0].key);
  const [activeItem, setActiveItem] = useState<ConnectorCatalogItem | null>(null);
  const [showAllTiers, setShowAllTiers] = useState(false);
  const [tipDismissed, setTipDismissed] = useState(
    () => localStorage.getItem("dc-onboarding-tip-dismissed") === "1",
  );

  const catalogQuery = useConnectorCatalogQuery();
  const catalog = catalogQuery.data ?? [];
  const connectorBySlug = useMemo(
    () => new Map(connectors.map((connector) => [connector.slug, connector])),
    [connectors],
  );

  const hiddenTierCount = useMemo(() => {
    return catalog.filter(
      (item) =>
        item.category === activeCategory &&
        item.stability &&
        !DEFAULT_VISIBLE_TIERS.includes(item.stability),
    ).length;
  }, [catalog, activeCategory]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return catalog.filter((item) => {
      if (item.category !== activeCategory) return false;
      // Hide known_issue + unsupported by default unless the user toggles.
      if (!showAllTiers && item.stability && !DEFAULT_VISIBLE_TIERS.includes(item.stability)) {
        return false;
      }
      if (!query) return true;
      return `${item.display_name} ${item.sync_behavior}`.toLowerCase().includes(query);
    });
  }, [catalog, activeCategory, search, showAllTiers]);

  return (
    <section className="gateway-view">
      <section className="gateway-panel">
        <header>
          <div>
            <h2>Connectors</h2>
            <p>Configure data sources, docs, pipelines, and model providers.</p>
          </div>
          <label className="integration-search">
            <Search size={15} />
            <input
              aria-label="Search connectors"
              placeholder="Search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </header>

        {!tipDismissed ? (
          <div className="connector-tip">
            <span>Tip: connect docs and pipelines before data stores for richer table descriptions.</span>
            <button
              onClick={() => {
                localStorage.setItem("dc-onboarding-tip-dismissed", "1");
                setTipDismissed(true);
              }}
              type="button"
            >
              Got it
            </button>
          </div>
        ) : null}

        <div className="category-tabs" role="tablist">
          {CONNECTOR_CATEGORIES.map((category) => {
            const Icon = category.icon ?? Cloud;
            return (
              <button
                aria-pressed={category.key === activeCategory}
                className={category.key === activeCategory ? "active" : ""}
                key={category.key}
                onClick={() => setActiveCategory(category.key)}
                type="button"
              >
                <Icon size={14} /> {category.label}
              </button>
            );
          })}
        </div>

        <div className="connector-list">
          {filtered.map((item) => {
            const connector = connectorBySlug.get(item.slug);
            const Icon = (CONNECTOR_CATEGORIES.find((c) => c.key === item.category)?.icon) ?? Database;
            const tier = item.stability ? STABILITY_META[item.stability] : null;
            const firstIssue = item.known_issues?.[0];
            return (
              <article className="connector-row" key={item.slug}>
                <span className="connector-icon">
                  <Icon size={18} />
                </span>
                <div>
                  <div className="connector-row-title">
                    <strong>{item.display_name}</strong>
                    {tier ? (
                      <span
                        className={`stability-chip ${tier.cls}`}
                        title={item.stability_notes || tier.description}
                      >
                        {tier.label}
                      </span>
                    ) : null}
                  </div>
                  <em>{item.sync_behavior}</em>
                  {connector?.sync_state === "sync_failed" && connector.last_sync_error ? (
                    <p className="connector-error">{connector.last_sync_error}</p>
                  ) : null}
                  {connector?.credential_state === "configured" &&
                  (!connector.sync_state || connector.sync_state === "never_synced") ? (
                    <p className="connector-hint">Configured. Click Sync to load tables.</p>
                  ) : null}
                  {firstIssue ? (
                    <p className="connector-issue" title={item.known_issues.join("\n")}>
                      Known issue: {firstIssue}
                    </p>
                  ) : null}
                </div>
                <span className={`connector-status ${statusClass(connector)}`} title={connector?.last_sync_error ?? undefined}>
                  {statusLabel(connector)}
                </span>
                <button className="ghost" onClick={() => setActiveItem(item)} type="button">
                  Configure
                </button>
              </article>
            );
          })}
          {filtered.length === 0 ? (
            <p className="connector-empty">No connectors match this search.</p>
          ) : null}
          {hiddenTierCount > 0 ? (
            <label className="connector-show-all">
              <input
                type="checkbox"
                checked={showAllTiers}
                onChange={(e) => setShowAllTiers(e.target.checked)}
              />
              Show {hiddenTierCount} more (known-issue or unsupported)
            </label>
          ) : null}
        </div>
      </section>

      {activeItem ? (
        <ConfigureModal
          kind="connector"
          catalogItem={activeItem}
          onClose={() => setActiveItem(null)}
          onConfigured={refresh}
        />
      ) : null}
    </section>
  );
}
