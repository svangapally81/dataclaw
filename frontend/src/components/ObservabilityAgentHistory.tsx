import { Bot, Clock, XCircle } from "lucide-react";

import { AGENT_ICONS } from "../lib/agent-icons";
import type { ObservabilityEvent } from "../types";

type Props = {
  events: ObservabilityEvent[];
};

export function ObservabilityAgentHistory({ events }: Props) {
  const runsByAgent = new Map<string, ObservabilityEvent[]>();
  for (const event of events) {
    if (event.kind !== "agent_run") continue;
    const name = event.agent_name || event.title.split(" — ")[0] || "Agent";
    const runs = runsByAgent.get(name) ?? [];
    runs.push(event);
    runsByAgent.set(name, runs);
  }
  const groups = [...runsByAgent.entries()].map(([agent, runs]) => ({
    agent,
    runs: runs.slice(0, 20),
  }));

  return (
    <section className="agent-history-panel">
      <header>
        <div>
          <h2>Agent history</h2>
          <p>Last runs, durations, failures, and tool-call counts by agent.</p>
        </div>
      </header>
      {groups.length === 0 ? (
        <p className="connector-empty">No agent runs have been recorded yet.</p>
      ) : (
        <div className="agent-history-grid">
          {groups.map(({ agent, runs }) => (
            <AgentRunTable agent={agent} key={agent} runs={runs} />
          ))}
        </div>
      )}
    </section>
  );
}

function AgentRunTable({ agent, runs }: { agent: string; runs: ObservabilityEvent[] }) {
  const latest = runs[0];
  const AgentIcon = AGENT_ICONS[(latest?.agent_icon_key || "bot") as keyof typeof AGENT_ICONS] ?? Bot;
  const sparkline = runs
    .filter((run) => (run.duration_ms ?? 0) > 0)
    .map((run) => ({ id: run.id, duration: run.duration_ms ?? 0 }));
  const maxDuration = Math.max(1, ...sparkline.map((point) => point.duration));

  return (
    <article className="agent-history-card">
      <header>
        <span className="event-glyph"><AgentIcon size={14} /></span>
        <div>
          <strong>{agent}</strong>
          <em>{runs.length} recent {runs.length === 1 ? "run" : "runs"}</em>
        </div>
      </header>
      {sparkline.length > 0 ? (
        <div className="agent-sparkline" aria-label="Run duration sparkline">
          {sparkline.slice(0, 12).map((point) => (
            <span key={point.id} style={{ height: `${Math.max(10, (point.duration / maxDuration) * 100)}%` }} />
          ))}
        </div>
      ) : null}
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>When</th>
            <th>Duration</th>
            <th>Tools</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td><StatusBadge state={run.state} /></td>
              <td>{new Date(run.timestamp).toLocaleString()}</td>
              <td>{formatDuration(run.duration_ms)}</td>
              <td>{run.tool_calls?.length ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.some((run) => run.error_message) ? (
        <p className="agent-history-error"><XCircle size={13} /> {runs.find((run) => run.error_message)?.error_message}</p>
      ) : null}
    </article>
  );
}

function StatusBadge({ state }: { state: string }) {
  return (
    <span className={`run-status ${state}`}>
      <Clock size={11} /> {state.replaceAll("_", " ")}
    </span>
  );
}

function formatDuration(durationMs?: number | null): string {
  if (!durationMs) return "n/a";
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}
