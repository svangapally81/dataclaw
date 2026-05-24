import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import type { WikiPage } from "../types";

type WikiPageViewProps = {
  page?: WikiPage;
  onLinkClick?: (path: string) => void;
};

function renderWikiLinks(body: string) {
  return body.replace(/\[\[([^\]]+)\]\]/g, (_, target: string) => {
    const path = target.startsWith("wiki/") ? target : `wiki/entities/${target}.md`;
    return `[${target}](wiki://${path})`;
  });
}

export function WikiPageView({ page, onLinkClick }: WikiPageViewProps) {
  if (!page) {
    return (
      <section className="wiki-empty">
        <strong>No page selected</strong>
        <span>Select a wiki page from the tree.</span>
      </section>
    );
  }

  const frontmatter = Object.entries(page.frontmatter ?? {}).filter(([, value]) => {
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== undefined && value !== "";
  });

  return (
    <article className="wiki-page-view">
      <header className="wiki-page-head">
        <div>
          <p className="eyebrow">{page.source_type}</p>
          <h2>{page.title}</h2>
          <span className="wiki-disk-path">{page.disk_path}</span>
        </div>
        <div className="wiki-meta-chips">
          {frontmatter.slice(0, 10).map(([key, value]) => (
            <span className="wiki-chip" key={key}>
              <b>{key}</b>
              {Array.isArray(value) ? value.join(", ") : String(value)}
            </span>
          ))}
        </div>
      </header>

      <div className="markdown-body">
        <ReactMarkdown
          rehypePlugins={[rehypeHighlight]}
          remarkPlugins={[remarkGfm]}
          components={{
            a({ href, children }) {
              if (href?.startsWith("wiki://")) {
                const path = href.replace("wiki://", "");
                return (
                  <button className="wiki-inline-link" onClick={() => onLinkClick?.(path)} type="button">
                    {children}
                  </button>
                );
              }
              return (
                <a href={href} rel="noreferrer noopener" target="_blank">
                  {children}
                </a>
              );
            },
          }}
        >
          {renderWikiLinks(page.body)}
        </ReactMarkdown>
      </div>
    </article>
  );
}
