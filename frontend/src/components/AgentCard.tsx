import { Bot } from "lucide-react";

import { AGENT_ICONS } from "../lib/agent-icons";
import type { AgentSummary } from "../types";

function AgentIcon({ iconKey, size = 18 }: { iconKey?: string; size?: number }) {
  const Icon = AGENT_ICONS[(iconKey || "bot") as keyof typeof AGENT_ICONS] ?? Bot;
  return <Icon size={size} />;
}

function truncate(text: string | undefined, max: number) {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max).trimEnd()}...`;
}

export function AgentCard({
  agent,
  onConfigure,
}: {
  agent: AgentSummary;
  onConfigure: () => void;
}) {
  const thresholdText = Object.entries(agent.thresholds ?? {})
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
  return (
    <article className="connector-row">
      <span className="connector-icon">
        <AgentIcon iconKey={agent.icon_key} />
      </span>
      <div>
        <strong>{agent.display_name}</strong>
        <em>{truncate(agent.system_prompt, 90) || (agent.is_system ? "System agent" : "Custom agent")}</em>
        {agent.kind === "background" ? (
          <em>
            Cadence: {agent.cadence_minutes ?? 60}m
            {thresholdText ? ` · Thresholds: ${thresholdText}` : ""}
            {agent.uses_llm_filter ? " · LLM filter on" : ""}
          </em>
        ) : null}
      </div>
      <span className={`connector-status ${agent.enabled ? "ready" : ""}`}>
        {agent.is_system ? "system" : "custom"} · {agent.enabled ? "enabled" : "disabled"}
      </span>
      <button className="ghost" onClick={onConfigure} type="button">
        Configure
      </button>
    </article>
  );
}
