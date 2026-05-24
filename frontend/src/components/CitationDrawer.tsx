import { X } from "lucide-react";

import { useKnowledgePageQuery } from "../services/api";
import type { ChatCitation } from "../types";
import { WikiPageView } from "./WikiPageView";

type CitationDrawerProps = {
  citation: ChatCitation | null;
  onClose: () => void;
};

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  const path = citation?.path ?? "";
  const { data: page, isFetching, isError } = useKnowledgePageQuery(path, { skip: !path });

  if (!citation) return null;

  return (
    <aside className="citation-drawer" aria-label="Citation source">
      <header className="citation-drawer-head">
        <div>
          <p className="eyebrow">{citation.connector}</p>
          <h2>{citation.title}</h2>
        </div>
        <button aria-label="Close citation" className="icon-button" onClick={onClose} type="button">
          <X size={16} />
        </button>
      </header>
      <div className="citation-drawer-body">
        {isFetching ? <div className="wiki-empty compact">Loading source</div> : null}
        {isError ? (
          <section className="wiki-empty compact">
            <strong>Source unavailable</strong>
            <span>{path || citation.title}</span>
          </section>
        ) : null}
        {!isFetching && !isError ? <WikiPageView page={page} /> : null}
      </div>
    </aside>
  );
}
