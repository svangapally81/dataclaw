import embed from "vega-embed";
import { useEffect, useRef } from "react";
import type { Result } from "vega-embed";

export function ChatChart({ spec }: { spec: Record<string, unknown> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    let cancelled = false;
    let embedded: Result | null = null;
    let mutableSpec: Record<string, unknown>;
    try {
      mutableSpec = structuredClone(spec);
    } catch (err) {
      if (ref.current) ref.current.textContent = "Unable to render chart.";
      console.error("vega-embed failed:", err instanceof Error ? err.message : "Unable to clone chart spec");
      return () => {
        cancelled = true;
        if (ref.current) ref.current.replaceChildren();
      };
    }
    embed(ref.current, mutableSpec, { actions: false, renderer: "svg" })
      .then((result) => {
        embedded = result;
      })
      .catch((err) => {
        if (!cancelled && ref.current) ref.current.textContent = "Unable to render chart.";
        console.error("vega-embed failed:", err instanceof Error ? err.message : "Unable to render chart");
      });
    return () => {
      cancelled = true;
      embedded?.view.finalize();
      if (ref.current) ref.current.replaceChildren();
    };
  }, [spec]);
  return <div className="chat-chart" ref={ref} />;
}
