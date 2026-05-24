import { CheckCircle2, ExternalLink, Loader2, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../lib/errors";
import {
  useConnectorRecordQuery,
  useSyncConnectorMutation,
  useTestLlmProviderMutation,
  useTestConnectorMutation,
  useUpdateLlmProviderMutation,
} from "../services/api";
import type {
  ConnectorCatalogItem,
  ConnectorTestResponse,
  LlmCatalogItem,
  LlmProviderRecord,
} from "../types";

type CommonProps = {
  onClose: () => void;
  onConfigured: () => Promise<void> | void;
};

type ConnectorMode = CommonProps & {
  kind: "connector";
  catalogItem: ConnectorCatalogItem;
};

type LlmMode = CommonProps & {
  kind: "llm";
  provider: LlmCatalogItem;
  current?: LlmProviderRecord;
};

type ConfigureModalProps = ConnectorMode | LlmMode;

export function ConfigureModal(props: ConfigureModalProps) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") props.onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props]);

  return props.kind === "llm" ? <LlmModalBody {...props} /> : <ConnectorModalBody {...props} />;
}

function ConnectorModalBody({ catalogItem, onClose, onConfigured }: ConnectorMode) {
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ConnectorTestResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"test" | "sync" | null>(null);
  const [syncNotice, setSyncNotice] = useState("");

  const { data: record } = useConnectorRecordQuery(catalogItem.slug);
  const [testConnector] = useTestConnectorMutation();
  const [syncConnector] = useSyncConnectorMutation();

  useEffect(() => {
    if (record?.configured && record.values) {
      setCredentials((prev) => ({ ...record.values, ...prev }));
    }
  }, [record?.configured, record?.values]);

  const missingRequired = useMemo(() => {
    return catalogItem.credential_schema
      .filter((field) => {
        if (!field.required) return false;
        if (field.secret && record?.secrets_set?.includes(field.name)) return false;
        return !credentials[field.name]?.trim();
      })
      .map((field) => field.label);
  }, [catalogItem.credential_schema, credentials, record]);

  function update(name: string, value: string) {
    setCredentials((prev) => ({ ...prev, [name]: value }));
  }

  function payloadCredentials() {
    const payload: Record<string, string> = {};
    for (const field of catalogItem.credential_schema) {
      const entered = credentials[field.name];
      if (field.secret) {
        if (entered?.trim()) payload[field.name] = entered.trim();
      } else if (entered !== undefined) {
        payload[field.name] = entered;
      }
    }
    return payload;
  }

  async function handleTest() {
    setBusy("test");
    setError("");
    try {
      const response = await testConnector({ slug: catalogItem.slug, credentials: payloadCredentials() }).unwrap();
      setResult(response);
      if (response.status === "ok") {
        await onConfigured();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleSync() {
    setError("");
    setBusy("sync");
    setSyncNotice(`Sync started for ${catalogItem.display_name}. This can take a minute — the tile updates when it finishes.`);
    try {
      await syncConnector(catalogItem.slug).unwrap();
      await onConfigured();
      window.setTimeout(() => onClose(), 1400);
    } catch (err) {
      setSyncNotice("");
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const showSync = result?.status === "ok" || result?.status === "mock_tested";
  const isReady = catalogItem.credential_schema.length === 0;

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={`Configure ${catalogItem.display_name}`}>
        <header>
          <div>
            <strong>Configure {catalogItem.display_name}</strong>
            <em>{catalogItem.sync_behavior}</em>
          </div>
          <button aria-label="Close" className="ghost icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="modal-body">
          {catalogItem.stability && catalogItem.stability !== "stable" ? (
            <div className={`modal-stability-banner stability-${catalogItem.stability.replace("_", "-")}`}>
              <strong>
                {catalogItem.stability === "stable_read_only" && "Read-only (stable)"}
                {catalogItem.stability === "beta" && "Beta"}
                {catalogItem.stability === "known_issue" && "Known issue"}
                {catalogItem.stability === "unsupported" && "Unsupported"}
              </strong>
              <p>{catalogItem.stability_notes}</p>
              {catalogItem.known_issues && catalogItem.known_issues.length > 0 ? (
                <ul>
                  {catalogItem.known_issues.map((issue, i) => (
                    <li key={i}>{issue}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {catalogItem.credential_schema.length === 0 ? (
            <p className="modal-note">
              {isReady
                ? "No credentials required — this connector runs against your local environment."
                : "This connector validates with mock responses locally; live credentials are required for production."}
            </p>
          ) : (
            <div className="modal-fields">
              {catalogItem.credential_schema.map((field) => {
                const preview = field.secret ? record?.secret_previews?.[field.name] : null;
                const placeholder = preview
                  ? `Saved (${preview}) — enter a new value to replace`
                  : field.placeholder;
                return (
                  <label key={field.name}>
                    <span>
                      {field.label}
                      {field.required ? " *" : ""}
                    </span>
                    <input
                      aria-label={field.label}
                      autoComplete="off"
                      placeholder={placeholder}
                      type={field.secret ? "password" : "text"}
                      value={credentials[field.name] ?? ""}
                      onChange={(event) => update(field.name, event.target.value)}
                    />
                  </label>
                );
              })}
            </div>
          )}

          {result ? (
            <div className={`modal-result ${result.status}`}>
              <strong>{result.status === "ok" ? "Connection succeeded" : result.status.replaceAll("_", " ")}</strong>
              <p>{result.message}</p>
            </div>
          ) : null}

          {error ? <p className="error">{error}</p> : null}
          {syncNotice ? <p className="modal-notice">{syncNotice}</p> : null}

          <p className="modal-note">
            <ExternalLink size={13} />
            <a href={catalogItem.docs_url} rel="noreferrer noopener" target="_blank">
              {catalogItem.display_name} documentation
            </a>
            <span className="modal-note-detail">{catalogItem.production_notes}</span>
          </p>
        </div>

        <footer>
          <button className="ghost" onClick={onClose} type="button">
            Cancel
          </button>
          <button
            className="ghost"
            disabled={busy !== null || (catalogItem.credential_schema.length > 0 && missingRequired.length > 0)}
            onClick={handleTest}
            type="button"
          >
            {busy === "test" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
            Test connection
          </button>
          <button
            className="primary"
            disabled={busy !== null || !showSync}
            onClick={handleSync}
            type="button"
          >
            {busy === "sync" ? <Loader2 className="spin" size={14} /> : null}
            Save and sync
          </button>
        </footer>
      </div>
    </div>
  );
}

function LlmModalBody({ provider, current, onClose, onConfigured }: LlmMode) {
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...(current?.values ?? {}) }));
  const [result, setResult] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"test" | "save" | "clear" | null>(null);
  const [testProvider] = useTestLlmProviderMutation();
  const [updateProvider] = useUpdateLlmProviderMutation();

  function update(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  const missingRequired = useMemo(() => {
    return provider.fields
      .filter((field) => {
        if (!field.required) return false;
        if (field.secret && current?.secrets_set.includes(field.name)) return false;
        return !values[field.name]?.trim();
      })
      .map((field) => field.label);
  }, [provider.fields, values, current]);

  function payloadValues() {
    const payload: Record<string, string | null> = {};
    for (const field of provider.fields) {
      if (field.secret) {
        if (values[field.name]?.trim()) payload[field.name] = values[field.name].trim();
      } else if (values[field.name] !== undefined) {
        payload[field.name] = values[field.name];
      }
    }
    return payload;
  }

  async function handleTest() {
    setBusy("test");
    setError("");
    setResult(null);
    try {
      setResult(await testProvider({ slug: provider.slug, values: payloadValues() }).unwrap());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleSave() {
    setBusy("save");
    setError("");
    try {
      await updateProvider({ slug: provider.slug, values: payloadValues() }).unwrap();
      await onConfigured();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleClear() {
    setBusy("clear");
    setError("");
    try {
      const payload: Record<string, string | null> = {};
      for (const field of provider.fields) payload[field.name] = null;
      await updateProvider({ slug: provider.slug, values: payload }).unwrap();
      await onConfigured();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={`Configure ${provider.display_name}`}>
        <header>
          <div>
            <strong>Configure {provider.display_name}</strong>
            <em>{provider.description}</em>
          </div>
          <button aria-label="Close" className="ghost icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="modal-body">
          <div className="modal-fields">
            {provider.fields.map((field) => {
              const preview = field.secret ? current?.secret_previews[field.name] : null;
              const placeholder = preview
                ? `Saved (${preview}) — enter a new value to replace`
                : field.placeholder;
              const value = values[field.name] ?? "";
              return (
                <label key={field.name}>
                  <span>
                    {field.label}
                    {field.required ? " *" : ""}
                  </span>
                  {field.options && field.options.length > 0 ? (
                    <select
                      aria-label={field.label}
                      onChange={(event) => update(field.name, event.target.value)}
                      value={value || provider.default_model || field.options[0]}
                    >
                      {field.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      aria-label={field.label}
                      autoComplete="off"
                      placeholder={placeholder}
                      type={field.secret ? "password" : "text"}
                      value={value}
                      onChange={(event) => update(field.name, event.target.value)}
                    />
                  )}
                </label>
              );
            })}
          </div>

          {!provider.wired ? (
            <p className="modal-note modal-note-warn">
              Stored for future use — the chat agent does not yet call this provider.
            </p>
          ) : null}

          {result ? (
            <div className={`modal-result ${result.status}`}>
              <strong>{result.status === "ok" ? "Connection succeeded" : "Connection failed"}</strong>
              <p>{result.message}</p>
            </div>
          ) : null}

          {error ? <p className="error">{error}</p> : null}

          <p className="modal-note">
            <ExternalLink size={13} />
            <a href={provider.docs_url} rel="noreferrer noopener" target="_blank">
              {provider.display_name} documentation
            </a>
          </p>
        </div>

        <footer>
          <button className="ghost" onClick={onClose} type="button">
            Cancel
          </button>
          {current?.configured ? (
            <button className="ghost" disabled={busy !== null} onClick={handleClear} type="button">
              Clear
            </button>
          ) : null}
          <button
            className="ghost"
            disabled={busy !== null || missingRequired.length > 0}
            onClick={handleTest}
            type="button"
          >
            {busy === "test" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
            Test connection
          </button>
          <button
            className="primary"
            disabled={busy !== null || missingRequired.length > 0}
            onClick={handleSave}
            type="button"
          >
            {busy === "save" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
            Save
          </button>
        </footer>
      </div>
    </div>
  );
}
