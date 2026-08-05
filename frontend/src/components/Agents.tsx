import { useState } from "react";

import { AgentCard } from "./AgentCard";
import { AgentConfigModal } from "./AgentConfigModal";
import { CustomAgentModal } from "./CustomAgentModal";
import {
  useAgentsQuery,
  useMcpCatalogQuery,
} from "../services/api";

type AgentsProps = {
  kind?: "background" | "on_demand";
};

export function Agents({ kind = "on_demand" }: AgentsProps) {
  const agents = useAgentsQuery({ kind });
  const catalog = useMcpCatalogQuery();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <section className="gateway-view">
      <section className="gateway-panel">
        <header>
          <div>
            <h2>Agents</h2>
            <p>
              Configure prompts, schedules, thresholds, and per-connector tool grants for{" "}
              {kind === "background" ? "background" : "on-demand"} agents.
            </p>
          </div>
          <div className="agent-create">
            <button className="ghost" onClick={() => setCreating(true)} type="button">
              New agent
            </button>
          </div>
        </header>

        <div className="connector-list">
          {(agents.data ?? []).map((agent) => (
            <AgentCard agent={agent} key={agent.id} onConfigure={() => setActiveId(agent.id)} />
          ))}
          {agents.data && agents.data.length === 0 ? (
            <p className="connector-empty">No agents yet. Create one above.</p>
          ) : null}
        </div>
      </section>

      {activeId ? (
        <AgentConfigModal
          agentId={activeId}
          connectorNames={catalog.data ?? []}
          onClose={() => setActiveId(null)}
        />
      ) : null}
      {creating ? (
        <CustomAgentModal
          kind={kind}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setActiveId(id);
          }}
        />
      ) : null}
    </section>
  );
}
