import { Bot, Save, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AGENT_ICONS } from "../lib/agent-icons";
import { errorMessage } from "../lib/errors";
import { logoDefinition } from "../lib/logos";
import {
  useAgentQuery,
  useDeleteAgentMutation,
  useUpdateAgentGrantsMutation,
  useUpdateAgentMutation,
} from "../services/api";

type ConnectorGrantRow = {
  slug: string;
  display_name: string;
  logo_key: string;
  read_tools: unknown[];
  write_tools: unknown[];
};

function ConnectorLogo({ logoKey, label }: { logoKey?: string; label: string }) {
  const logo = logoDefinition(logoKey);
  if (!logo) return <Sparkles size={13} />;
  if (logo.kind === "asset") return <img alt="" src={logo.src} />;
  return (
    <svg aria-label={label} role="img" viewBox="0 0 24 24">
      <path d={logo.icon.path} fill={`#${logo.icon.hex}`} />
    </svg>
  );
}

export function AgentConfigModal({
  agentId,
  connectorNames,
  onClose,
}: {
  agentId: string;
  connectorNames: ConnectorGrantRow[];
  onClose: () => void;
}) {
  const agent = useAgentQuery(agentId, { skip: !agentId });
  const [updateAgent] = useUpdateAgentMutation();
  const [updateGrants] = useUpdateAgentGrantsMutation();
  const [deleteAgent] = useDeleteAgentMutation();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const grants = useMemo(() => {
    const bySlug = new Map((agent.data?.grants ?? []).map((grant) => [grant.connector_slug, grant]));
    return connectorNames.map((item) => ({
      connector_slug: item.slug,
      read_enabled: bySlug.get(item.slug)?.read_enabled ?? false,
      write_enabled: bySlug.get(item.slug)?.write_enabled ?? false,
    }));
  }, [agent.data?.grants, connectorNames]);

  const [draftGrants, setDraftGrants] = useState(grants);
  useEffect(() => {
    setDraftGrants(grants);
  }, [grants]);

  async function saveAgent(patch: Record<string, unknown>) {
    setError("");
    try {
      await updateAgent({ id: agentId, patch }).unwrap();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveGrantsAndClose() {
    setError("");
    setSaving(true);
    try {
      await updateGrants({ id: agentId, grants: draftGrants }).unwrap();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!agent.data || agent.data.is_system) return;
    await deleteAgent(agent.data.id);
    onClose();
  }

  const selectedIcon = agent.data?.icon_key ?? "bot";
  const SelectedIcon = AGENT_ICONS[selectedIcon as keyof typeof AGENT_ICONS] ?? Bot;
  const isSystem = agent.data?.is_system ?? false;
  const isBackground = agent.data?.kind === "background";

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        aria-label={agent.data?.display_name ? `Configure ${agent.data.display_name}` : "Configure agent"}
        aria-modal="true"
        className="modal-card agent-config-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header>
          <div className="agent-config-title">
            <span className="connector-icon"><SelectedIcon size={18} /></span>
            <div>
              <strong>Configure {agent.data?.display_name ?? "Agent"}</strong>
              <em>{isSystem ? "System agent" : "Custom agent"} · grant the tools this agent may call.</em>
            </div>
          </div>
          <button aria-label="Close" className="ghost icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="modal-body">
          <div className="modal-fields">
            <label>
              <span>Display name</span>
              <input
                disabled={isSystem}
                defaultValue={agent.data?.display_name ?? ""}
                onBlur={(event) => saveAgent({ display_name: event.target.value })}
              />
            </label>
            <label>
              <span>System prompt</span>
              <textarea
                defaultValue={agent.data?.system_prompt ?? ""}
                onBlur={(event) => saveAgent({ system_prompt: event.target.value })}
                rows={3}
              />
            </label>
            <label className="agent-enabled-row">
              <input
                checked={agent.data?.enabled ?? false}
                onChange={(event) => saveAgent({ enabled: event.target.checked })}
                type="checkbox"
              />
              <span>Enabled</span>
            </label>
            {isBackground ? (
              <>
                <label>
                  <span>Cadence</span>
                  <select
                    defaultValue={agent.data?.cadence_minutes ?? 60}
                    onBlur={(event) => saveAgent({ cadence_minutes: Number(event.target.value) })}
                  >
                    {[5, 10, 15, 30, 60, 360, 1440].map((minutes) => (
                      <option key={minutes} value={minutes}>
                        {minutes < 60 ? `${minutes}m` : `${minutes / 60}h`}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Thresholds</span>
                  <textarea
                    defaultValue={JSON.stringify(agent.data?.thresholds ?? {}, null, 2)}
                    onBlur={(event) => {
                      try {
                        saveAgent({ thresholds: JSON.parse(event.target.value || "{}") });
                      } catch {
                        setError("Thresholds must be valid JSON.");
                      }
                    }}
                    rows={3}
                  />
                </label>
                <label className="agent-enabled-row">
                  <input
                    checked={agent.data?.uses_llm_filter ?? false}
                    onChange={(event) => saveAgent({ uses_llm_filter: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Use LLM filter for borderline signals</span>
                </label>
              </>
            ) : null}
            <div>
              <span className="agent-section-label">Icon</span>
              <div className="agent-icon-picker">
                {Object.entries(AGENT_ICONS).map(([key, Icon]) => (
                  <button
                    aria-label={`Use ${key} icon`}
                    aria-pressed={selectedIcon === key}
                    className={selectedIcon === key ? "active" : ""}
                    key={key}
                    onClick={() => saveAgent({ icon_key: key })}
                    title={key}
                    type="button"
                  >
                    <Icon size={15} />
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="agent-grant-header">
              <span className="agent-section-label">Tool grants</span>
              <div className="grant-toolbar">
                <button
                  onClick={() => setDraftGrants((rows) => rows.map((row) => ({ ...row, read_enabled: true })))}
                  type="button"
                >
                  Grant all read
                </button>
                <button
                  onClick={() => setDraftGrants((rows) => rows.map((row) => ({ ...row, read_enabled: false, write_enabled: false })))}
                  type="button"
                >
                  Revoke all
                </button>
              </div>
            </div>
            <div className="grant-grid">
              <div className="grant-grid-head">
                <span>Connector</span>
                <span>Read</span>
                <span>Write</span>
              </div>
              {draftGrants.map((grant, index) => {
                const item = connectorNames.find((candidate) => candidate.slug === grant.connector_slug);
                const noWrite = (item?.write_tools.length ?? 0) === 0;
                return (
                  <div className="grant-row" key={grant.connector_slug}>
                    <span>
                      <ConnectorLogo label={item?.display_name ?? grant.connector_slug} logoKey={item?.logo_key} />
                      {item?.display_name ?? grant.connector_slug}
                    </span>
                    <label className="grant-toggle">
                      <input
                        aria-label={`Read ${item?.display_name ?? grant.connector_slug}`}
                        checked={grant.read_enabled}
                        onChange={(event) => setDraftGrants((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, read_enabled: event.target.checked } : row))}
                        type="checkbox"
                      />
                    </label>
                    <label className="grant-toggle">
                      <input
                        aria-label={`Write ${item?.display_name ?? grant.connector_slug}`}
                        checked={grant.write_enabled}
                        disabled={noWrite}
                        onChange={(event) => setDraftGrants((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, write_enabled: event.target.checked } : row))}
                        type="checkbox"
                      />
                    </label>
                  </div>
                );
              })}
            </div>
          </div>

          {error ? <p className="error">{error}</p> : null}
        </div>

        <footer>
          {!isSystem ? (
            <button className="ghost danger" onClick={remove} type="button">
              <Trash2 size={14} /> Delete
            </button>
          ) : null}
          <span style={{ flex: 1 }} />
          <button className="ghost" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary" disabled={saving} onClick={saveGrantsAndClose} type="button">
            <Save size={14} /> Save grants
          </button>
        </footer>
      </div>
    </div>
  );
}
