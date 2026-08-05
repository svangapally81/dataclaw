import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type NodeObject } from "react-force-graph-2d";

import { useKnowledgeGraphQuery, useLazyKnowledgeGraphQuery } from "../services/api";
import type { KnowledgeNode } from "../types";

type GraphNode = NodeObject & {
  id: string;
  canonical_name: string;
  type: string;
  raw: KnowledgeNode;
};

type GraphLink = {
  source: string;
  target: string;
  relationship: string;
};

const TYPE_COLORS: Record<string, string> = {
  table: "#2563eb",
  column: "#0ea5e9",
  dag: "#ea580c",
  doc: "#16a34a",
  dbt_model: "#7c3aed",
  metric: "#0f766e",
  owner: "#f59e0b",
  dataset: "#db2777",
};

function colorForType(type: string): string {
  return TYPE_COLORS[type] ?? "#64748b";
}

function linkKey(link: GraphLink): string {
  const src = typeof link.source === "string" ? link.source : (link.source as { id: string }).id;
  const tgt = typeof link.target === "string" ? link.target : (link.target as { id: string }).id;
  return `${src}->${tgt}:${link.relationship}`;
}

type Props = {
  root?: string;
  depth?: number;
  onNodeClick: (node: KnowledgeNode) => void;
};

export function KnowledgeGraph({ root, depth = 2, onNodeClick }: Props) {
  type ForceGraphHandle = { centerAt: (x: number, y: number, ms?: number) => void; zoom: (z: number, ms?: number) => void };
  const fgRef = useRef<ForceGraphHandle | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 500 });
  const [search, setSearch] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [graphError, setGraphError] = useState("");

  const { data, isFetching } = useKnowledgeGraphQuery({ root, depth });
  const [fetchSubgraph] = useLazyKnowledgeGraphQuery();

  useEffect(() => {
    if (!data) return;
    setNodes(data.nodes.map((n) => ({ id: n.id, canonical_name: n.canonical_name, type: n.type, raw: n })));
    setLinks(
      data.edges.map((e) => ({ source: e.src_node_id, target: e.dst_node_id, relationship: e.relationship })),
    );
  }, [data]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const w = entry.contentRect.width;
      const h = entry.contentRect.height;
      if (w > 0 && h > 0) setSize({ width: w, height: h });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return;
    const handle = setTimeout(async () => {
      const visible = nodes.find((n) => n.canonical_name.toLowerCase().includes(needle));
      if (visible) {
        if (fgRef.current && typeof visible.x === "number" && typeof visible.y === "number") {
          fgRef.current.centerAt(visible.x, visible.y, 600);
          fgRef.current.zoom(2.5, 600);
        }
        return;
      }
      try {
        const result = await fetchSubgraph({ root: needle, depth: 1 }).unwrap();
        setGraphError("");
        if (result.nodes.length === 0) return;
        setNodes((prev) => {
          const existing = new Set(prev.map((n) => n.id));
          const additions = result.nodes
            .filter((n) => !existing.has(n.id))
            .map((n) => ({ id: n.id, canonical_name: n.canonical_name, type: n.type, raw: n }));
          return additions.length ? [...prev, ...additions] : prev;
        });
        setLinks((prev) => {
          const existing = new Set(prev.map(linkKey));
          const additions: GraphLink[] = [];
          for (const e of result.edges) {
            const candidate = { source: e.src_node_id, target: e.dst_node_id, relationship: e.relationship };
            if (!existing.has(linkKey(candidate))) additions.push(candidate);
          }
          return additions.length ? [...prev, ...additions] : prev;
        });
      } catch {
        setGraphError("Could not load matching graph nodes.");
      }
    }, 350);
    return () => clearTimeout(handle);
  }, [search, nodes, fetchSubgraph]);

  const handleNodeClick = useCallback(
    async (node: NodeObject) => {
      const graphNode = node as GraphNode;
      onNodeClick(graphNode.raw);
      try {
        const result = await fetchSubgraph({ root: graphNode.canonical_name, depth: 1 }).unwrap();
        setGraphError("");
        setNodes((prev) => {
          const existing = new Set(prev.map((n) => n.id));
          const additions = result.nodes
            .filter((n) => !existing.has(n.id))
            .map((n) => ({ id: n.id, canonical_name: n.canonical_name, type: n.type, raw: n }));
          return additions.length ? [...prev, ...additions] : prev;
        });
        setLinks((prev) => {
          const existing = new Set(prev.map(linkKey));
          const additions: GraphLink[] = [];
          for (const e of result.edges) {
            const candidate = { source: e.src_node_id, target: e.dst_node_id, relationship: e.relationship };
            if (!existing.has(linkKey(candidate))) additions.push(candidate);
          }
          return additions.length ? [...prev, ...additions] : prev;
        });
      } catch {
        setGraphError("Could not expand this node.");
      }
    },
    [fetchSubgraph, onNodeClick],
  );

  const highlightLinks = useMemo(() => {
    if (!hoveredId) return new Set<string>();
    const set = new Set<string>();
    for (const link of links) {
      const src = typeof link.source === "string" ? link.source : (link.source as { id: string }).id;
      const tgt = typeof link.target === "string" ? link.target : (link.target as { id: string }).id;
      if (src === hoveredId || tgt === hoveredId) set.add(linkKey(link));
    }
    return set;
  }, [hoveredId, links]);

  const presentTypes = useMemo(() => {
    const set = new Set(nodes.map((n) => n.type));
    return Object.entries(TYPE_COLORS).filter(([type]) => set.has(type));
  }, [nodes]);

  if (data && data.nodes.length === 0 && nodes.length === 0) {
    return (
      <div className="wiki-empty">
        <strong>No graph yet</strong>
        <span>Compile knowledge after wiki pages are available.</span>
      </div>
    );
  }

  return (
    <section className="knowledge-graph-fg" ref={containerRef}>
      <div className="graph-toolbar">
        <input
          className="graph-search-input"
          placeholder="Search nodes — focuses + zooms"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="graph-legend">
          {presentTypes.map(([type, color]) => (
            <span key={type} className="graph-legend-chip">
              <i style={{ background: color }} />
              {type}
            </span>
          ))}
        </div>
        <span className="graph-stats">
          {nodes.length} nodes · {links.length} edges
          {isFetching ? " · refreshing" : null}
        </span>
      </div>
      {graphError ? <p className="connector-error compact">{graphError}</p> : null}
      <div className="graph-canvas">
        <ForceGraph2D
          ref={fgRef as never}
          graphData={{ nodes, links }}
          width={size.width}
          height={Math.max(size.height - 56, 300)}
          backgroundColor="#0a0e1a"
          nodeId="id"
          nodeRelSize={5}
          nodeVal={() => 4}
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const graphNode = node as GraphNode;
            const safeScale = globalScale > 0 && Number.isFinite(globalScale) ? globalScale : 1;
            const fontSize = Math.max(11 / safeScale, 2);
            const label = graphNode.canonical_name ?? "";
            if (!label) return;
            ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = "rgba(226, 232, 240, 0.95)";
            const x = typeof node.x === "number" ? node.x : 0;
            const y = typeof node.y === "number" ? node.y : 0;
            ctx.fillText(label, x, y + 7);
          }}
          nodeColor={(n) => colorForType((n as GraphNode).type)}
          linkColor={(l) => (highlightLinks.has(linkKey(l as unknown as GraphLink)) ? "#22d3ee" : "#334155")}
          linkWidth={(l) => (highlightLinks.has(linkKey(l as unknown as GraphLink)) ? 2.2 : 0.7)}
          linkLabel={(l) => (l as unknown as GraphLink).relationship}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={0.88}
          cooldownTicks={120}
          d3VelocityDecay={0.4}
          onNodeClick={handleNodeClick}
          onNodeDragEnd={(node) => {
            node.fx = node.x;
            node.fy = node.y;
          }}
          onNodeHover={(n) => setHoveredId(n ? (n as GraphNode).id : null)}
        />
      </div>
    </section>
  );
}
