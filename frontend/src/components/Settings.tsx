import { Bot, Search } from "lucide-react";
import { useState } from "react";

import { LlmProviders } from "./LlmProviders";

const TABS = [{ key: "llm", label: "LLM provider", icon: Bot }] as const;

type SettingsTab = (typeof TABS)[number]["key"];

export function Settings() {
  const [tab, setTab] = useState<SettingsTab>("llm");
  const [search, setSearch] = useState("");

  return (
    <section className="gateway-view">
      <section className="gateway-panel">
        <header>
          <div>
            <h2>Settings</h2>
            <p>Workspace configuration. Credentials are encrypted at rest with the master key.</p>
          </div>
          <label className="integration-search">
            <Search size={15} />
            <input
              aria-label="Search settings"
              placeholder="Search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </header>

        <div className="category-tabs" role="tablist">
          {TABS.map((entry) => {
            const Icon = entry.icon;
            return (
              <button
                aria-pressed={entry.key === tab}
                className={entry.key === tab ? "active" : ""}
                key={entry.key}
                onClick={() => setTab(entry.key)}
                type="button"
              >
                <Icon size={14} /> {entry.label}
              </button>
            );
          })}
        </div>

        {tab === "llm" ? <LlmProviders search={search} /> : null}
      </section>
    </section>
  );
}
