import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { errorMessage } from "../lib/errors";
import { useConnectorsQuery, useCreateAgentMutation } from "../services/api";

export function CustomAgentModal({
  kind,
  onClose,
  onCreated,
}: {
  kind: "background" | "on_demand";
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [sqlQuery, setSqlQuery] = useState("");
  const [targetConnectorId, setTargetConnectorId] = useState("");
  const [cadence, setCadence] = useState(60);
  const [error, setError] = useState("");
  const connectors = useConnectorsQuery();
  const [createAgent, createState] = useCreateAgentMutation();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function create() {
    if (!name.trim()) return;
    setError("");
    try {
      const target = (connectors.data ?? []).find((connector) => connector.id === targetConnectorId);
      const created = await createAgent({
        name,
        display_name: name,
        system_prompt: prompt,
        sql_query: kind === "background" ? sqlQuery : undefined,
        kind,
        cadence_minutes: kind === "background" ? cadence : undefined,
        thresholds: kind === "background" ? { rows_gt: 0 } : undefined,
        target_connector_id: kind === "background" ? targetConnectorId || null : undefined,
        grants:
          kind === "background" && target
            ? [{ connector_slug: target.slug, read_enabled: true, write_enabled: false }]
            : undefined,
      }).unwrap();
      onCreated(created.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        aria-label="Create custom agent"
        aria-modal="true"
        className="modal-card"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header>
          <strong>New {kind === "background" ? "background" : "on-demand"} agent</strong>
          <button aria-label="Close" className="ghost icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>
        <div className="modal-body modal-fields">
          <label>
            <span>Name</span>
            <input autoFocus onChange={(event) => setName(event.target.value)} value={name} />
          </label>
          <label>
            <span>System prompt</span>
            <textarea onChange={(event) => setPrompt(event.target.value)} rows={4} value={prompt} />
          </label>
          {kind === "background" ? (
            <>
              <label>
                <span>Target connector</span>
                <select onChange={(event) => setTargetConnectorId(event.target.value)} value={targetConnectorId}>
                  <option value="">Select a connector</option>
                  {(connectors.data ?? [])
                    .filter((connector) => connector.category === "data_store")
                    .map((connector) => (
                      <option key={connector.id} value={connector.id}>
                        {connector.display_name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                <span>SQL query</span>
                <textarea onChange={(event) => setSqlQuery(event.target.value)} rows={4} value={sqlQuery} />
              </label>
              <label>
                <span>Cadence</span>
                <select onChange={(event) => setCadence(Number(event.target.value))} value={cadence}>
                  {[5, 10, 15, 30, 60, 360, 1440].map((minutes) => (
                    <option key={minutes} value={minutes}>
                      {minutes < 60 ? `${minutes}m` : `${minutes / 60}h`}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : null}
          {error ? <p className="error">{error}</p> : null}
        </div>
        <footer>
          <button className="ghost" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary" disabled={createState.isLoading} onClick={create} type="button">
            <Plus size={14} /> Create
          </button>
        </footer>
      </div>
    </div>
  );
}
