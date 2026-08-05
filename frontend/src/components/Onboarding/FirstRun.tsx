import { CheckCircle2, Database, Settings2 } from "lucide-react";

import { useUpdateWorkspaceMutation } from "../../services/api";
import type { Connector, TabName, Workspace } from "../../types";

type Props = {
  connectors: Connector[];
  workspace?: Workspace;
  setTab: (tab: TabName) => void;
  refresh: () => Promise<void>;
};

export function FirstRun({ connectors, workspace, setTab, refresh }: Props) {
  const [updateWorkspace, updateState] = useUpdateWorkspaceMutation();
  if (!workspace || workspace.onboarding_complete) return null;

  const configuredConnectors = connectors.filter((connector) => connector.credential_state === "configured");
  const hasKnowledge = workspace.datasets.length > 0 || workspace.knowledge_documents.length > 0;

  async function complete() {
    await updateWorkspace({ onboarding_complete: true }).unwrap();
    await refresh();
  }

  return (
    <section className="first-run" aria-label="First run setup">
      <div className="first-run-panel">
        <header>
          <strong>Set up DataClaw</strong>
          <button type="button" onClick={complete} disabled={updateState.isLoading}>
            Skip
          </button>
        </header>
        <div className="first-run-steps">
          <button type="button" onClick={() => setTab("Settings")}>
            <Settings2 size={18} />
            <span>
              <strong>LLM provider</strong>
              <em>Use Ollama locally or save an OpenAI key.</em>
            </span>
          </button>
          <button type="button" onClick={() => setTab("Connectors")}>
            <Database size={18} />
            <span>
              <strong>{configuredConnectors.length ? "Connector saved" : "Add a connector"}</strong>
              <em>Sync a warehouse, orchestration tool, or docs source.</em>
            </span>
          </button>
          <button type="button" onClick={complete} disabled={!hasKnowledge || updateState.isLoading}>
            <CheckCircle2 size={18} />
            <span>
              <strong>{hasKnowledge ? "Finish setup" : "Waiting for knowledge"}</strong>
              <em>The compile agent builds the graph after sync.</em>
            </span>
          </button>
        </div>
      </div>
    </section>
  );
}
