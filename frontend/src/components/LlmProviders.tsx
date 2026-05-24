import { Bot } from "lucide-react";
import { useMemo, useState } from "react";

import { ConfigureModal } from "./ConfigureModal";
import { useLlmCatalogQuery, useLlmProvidersQuery } from "../services/api";
import type { LlmCatalogItem } from "../types";

type LlmProvidersProps = {
  search: string;
};

export function LlmProviders({ search }: LlmProvidersProps) {
  const catalogQuery = useLlmCatalogQuery();
  const providersQuery = useLlmProvidersQuery();
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  const catalog = catalogQuery.data ?? [];
  const records = useMemo(
    () => new Map((providersQuery.data ?? []).map((record) => [record.slug, record])),
    [providersQuery.data],
  );
  const activeProvider: LlmCatalogItem | undefined = catalog.find((item) => item.slug === activeSlug);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return catalog;
    return catalog.filter((item) =>
      `${item.display_name} ${item.description}`.toLowerCase().includes(query),
    );
  }, [catalog, search]);

  async function refresh() {
    await Promise.all([catalogQuery.refetch(), providersQuery.refetch()]);
  }

  return (
    <>
      <div className="connector-list">
        {filtered.map((item) => {
          const record = records.get(item.slug);
          const configured = record?.configured ?? false;
          const modelLabel = record?.values.model || item.default_model;
          const subtitle = configured
            ? `${modelLabel} · ${item.description}`
            : item.description;
          return (
            <article className="connector-row" key={item.slug}>
              <span className="connector-icon">
                <Bot size={18} />
              </span>
              <div>
                <strong>{item.display_name}</strong>
                <em>{subtitle}</em>
              </div>
              <span className={`connector-status ${configured ? "ready" : ""}`}>
                {configured ? "configured" : "available"}
              </span>
              <button className="ghost" onClick={() => setActiveSlug(item.slug)} type="button">
                Configure
              </button>
            </article>
          );
        })}
        {filtered.length === 0 ? (
          <p className="connector-empty">
            {catalog.length === 0 ? "Loading providers…" : "No providers match this search."}
          </p>
        ) : null}
      </div>

      {activeProvider ? (
        <ConfigureModal
          kind="llm"
          provider={activeProvider}
          current={records.get(activeProvider.slug)}
          onClose={() => setActiveSlug(null)}
          onConfigured={refresh}
        />
      ) : null}
    </>
  );
}
