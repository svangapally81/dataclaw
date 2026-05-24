import { ExternalLink, GitBranch, Library, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { errorMessage } from "../lib/errors";
import { useCompileKnowledgeMutation, useKnowledgePagesQuery } from "../services/api";
import type { KnowledgeNode, WikiPage } from "../types";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { WikiPageView } from "./WikiPageView";

type Mode = "Pages" | "Graph";

function groupPages(pages: WikiPage[]) {
  return pages.reduce<Record<string, WikiPage[]>>((acc, page) => {
    acc[page.source_type] = [...(acc[page.source_type] ?? []), page];
    return acc;
  }, {});
}

export function Knowledge() {
  const [mode, setMode] = useState<Mode>("Pages");
  const [query, setQuery] = useState("");
  const [selectedPath, setSelectedPath] = useState(() => new URLSearchParams(window.location.search).get("path") ?? "");
  const [graphRoot, setGraphRoot] = useState("");
  const [toast, setToast] = useState("");
  const { data: pages = [], isFetching, refetch } = useKnowledgePagesQuery({ tier: 1 });
  const [compile, compileState] = useCompileKnowledgeMutation();

  const filtered = useMemo(() => {
    const needle = query.toLowerCase();
    if (!needle) return pages;
    return pages.filter((page) => {
      return (
        page.title.toLowerCase().includes(needle) ||
        page.path.toLowerCase().includes(needle) ||
        page.entities.some((entity) => entity.toLowerCase().includes(needle))
      );
    });
  }, [pages, query]);
  const selectedInFiltered = selectedPath ? filtered.find((page) => page.path === selectedPath) : undefined;
  const selected = selectedInFiltered ?? (!selectedPath ? filtered[0] : undefined);
  const selectedFilteredOut = Boolean(selectedPath && pages.some((page) => page.path === selectedPath) && !selectedInFiltered);
  const grouped = groupPages(filtered);

  async function runCompile() {
    try {
      const result = await compile().unwrap();
      setToast(`${result.nodes_created + result.nodes_updated} nodes, ${result.edges_created} edges`);
      await refetch();
    } catch (err) {
      setToast(`Compile failed — ${errorMessage(err)}`);
    }
  }

  function openPreview() {
    if (!selected) return;
    const url = `/?tab=Knowledge&path=${encodeURIComponent(selected.path)}&preview=1`;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function handleNodeClick(node: KnowledgeNode) {
    const page = pages.find((item) => item.id === node.primary_wiki_page_id);
    if (page) setSelectedPath(page.path);
  }

  return (
    <section className="gateway-view">
      <section className="gateway-panel">
        <header>
          <div>
            <h2>Brain</h2>
            <p>Wiki summaries and the compiled knowledge graph from your connected sources.</p>
          </div>
          <div className="knowledge-actions">
            {toast ? <span className="knowledge-toast">{toast}</span> : null}
            <button
              className="primary"
              disabled={compileState.isLoading}
              onClick={runCompile}
              type="button"
            >
              <RefreshCw size={14} className={compileState.isLoading ? "spin" : ""} />
              Compile knowledge
            </button>
          </div>
        </header>

        <div className="category-tabs" role="tablist">
          <button
            aria-pressed={mode === "Pages"}
            className={mode === "Pages" ? "active" : ""}
            onClick={() => setMode("Pages")}
            type="button"
          >
            <Library size={14} /> Pages
          </button>
          <button
            aria-pressed={mode === "Graph"}
            className={mode === "Graph" ? "active" : ""}
            onClick={() => setMode("Graph")}
            type="button"
          >
            <GitBranch size={14} /> Graph
          </button>
        </div>

        {mode === "Pages" ? (
          <div className="knowledge-pages">
            <aside className="wiki-tree">
              <label className="search-box">
                <Search size={14} />
                <input
                  placeholder="Search pages or entities"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              {isFetching ? <span className="tree-status">Refreshing pages</span> : null}
              {selectedFilteredOut ? (
                <span className="tree-status">Selected page no longer matches filter.</span>
              ) : null}
              {Object.entries(grouped).length === 0 ? (
                <div className="wiki-empty compact">
                  <strong>No pages</strong>
                  <span>Sync a connector to generate wiki pages.</span>
                </div>
              ) : (
                Object.entries(grouped).map(([source, sourcePages]) => (
                  <div className="tree-group" key={source}>
                    <strong>{source}/</strong>
                    {sourcePages.map((page) => (
                      <button
                        className={selected?.path === page.path ? "active" : ""}
                        key={page.path}
                        onClick={() => setSelectedPath(page.path)}
                        type="button"
                      >
                        {page.title}
                      </button>
                    ))}
                  </div>
                ))
              )}
            </aside>
            <section className="wiki-reader">
              <div className="wiki-reader-actions">
                <button className="ghost" disabled={!selected} onClick={openPreview} type="button">
                  <ExternalLink size={14} /> Open preview in new window
                </button>
              </div>
              <WikiPageView page={selected} onLinkClick={setSelectedPath} />
            </section>
          </div>
        ) : (
          <div className="knowledge-graph-pane">
            <KnowledgeGraph root={graphRoot || undefined} depth={2} onNodeClick={handleNodeClick} />
          </div>
        )}
      </section>
    </section>
  );
}
