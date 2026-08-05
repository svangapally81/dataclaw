import { Network } from "lucide-react";

type RetrievalTraceProps = {
  trace?: Record<string, unknown> | null;
};

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

export function RetrievalTrace({ trace }: RetrievalTraceProps) {
  if (!trace || Object.keys(trace).length === 0) return null;

  const candidates = asList(trace.candidate_node_ids);
  const expanded = asList(trace.expanded_node_ids);
  const edges = asList(trace.edge_ids);
  const connectors = asList(trace.connector_slugs);

  if (candidates.length === 0 && expanded.length === 0 && edges.length === 0) return null;

  return (
    <details className="retrieval-trace">
      <summary>
        <Network size={13} />
        <span>Retrieval trace</span>
      </summary>
      <div className="retrieval-trace-grid">
        <TraceGroup title="Hop 1 candidates" values={candidates} />
        <TraceGroup title="Hop 2 expanded" values={expanded} />
        <TraceGroup title="Traversed edges" values={edges} />
        {connectors.length > 0 ? <TraceGroup title="Source filters" values={connectors} /> : null}
      </div>
    </details>
  );
}

function TraceGroup({ title, values }: { title: string; values: string[] }) {
  return (
    <section className="retrieval-trace-group">
      <strong>{title}</strong>
      {values.length > 0 ? (
        <ul>
          {values.slice(0, 12).map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      ) : (
        <span>None</span>
      )}
    </section>
  );
}
