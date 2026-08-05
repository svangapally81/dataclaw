import { useCallback, useEffect, useMemo, useState } from "react";
import { Provider } from "react-redux";
import { createRoot } from "react-dom/client";

import { Workspace } from "./components/Workspace";
import { errorMessage } from "./lib/errors";
import {
  useLazyConnectorsQuery,
  useLazyDashboardQuery,
  useLazyWorkspaceQuery,
  useLoginMutation,
} from "./services/api";
import { store } from "./store";
import type { TabName, TableAsset } from "./types";
import "./styles/app.css";

const DEFAULT_EMAIL = "admin@dataclaw.local";
const DEFAULT_PASSWORD = "dataclaw-local-admin";

function App() {
  const [authed, setAuthed] = useState(false);
  const [bootError, setBootError] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<TabName>(() => {
    const param = new URLSearchParams(window.location.search).get("tab");
    return param === "Knowledge" ? "Knowledge" : "Editor";
  });
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [selectedTableId, setSelectedTableId] = useState<string | null>(null);

  const [login] = useLoginMutation();
  const [loadConnectors, connectorsQuery] = useLazyConnectorsQuery();
  const [loadWorkspace, workspaceQuery] = useLazyWorkspaceQuery();
  const [loadDashboard, dashboardQuery] = useLazyDashboardQuery();
  const connectors = connectorsQuery.data ?? [];
  const workspace = workspaceQuery.data;
  const dashboard = dashboardQuery.data;

  const refresh = useCallback(async () => {
    await Promise.all([
      loadConnectors().unwrap(),
      loadWorkspace().unwrap(),
      loadDashboard().unwrap(),
    ]);
  }, [loadConnectors, loadWorkspace, loadDashboard]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const response = await login({ email: DEFAULT_EMAIL, password: DEFAULT_PASSWORD }).unwrap();
        if (response.bootstrap_admin_created) {
          setNotice("First admin created from environment settings. Change the password before inviting users.");
        }
        await refresh();
        if (!cancelled) setAuthed(true);
      } catch (err) {
        if (!cancelled) setBootError(errorMessage(err));
      }
    }
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [login, refresh]);

  const anySyncing = connectors.some((c) => c.sync_state === "syncing");
  useEffect(() => {
    if (!anySyncing) return;
    const id = setInterval(() => {
      loadConnectors();
    }, 3000);
    return () => clearInterval(id);
  }, [anySyncing, loadConnectors]);

  const selectedTable: TableAsset | undefined = useMemo(() => {
    const tables = workspace?.datasets.flatMap((dataset) => dataset.tables) ?? [];
    return tables.find((table) => table.id === selectedTableId) ?? tables[0];
  }, [workspace, selectedTableId]);

  if (!authed) {
    return (
      <main className="boot-screen">
        <div className="boot-card">
          <strong>DataClaw</strong>
          <p>{bootError ? `Could not connect: ${bootError}` : "Connecting…"}</p>
        </div>
      </main>
    );
  }

  return (
    <Workspace
      connectors={connectors}
      workspace={workspace}
      dashboard={dashboard}
      selectedTable={selectedTable}
      tab={tab}
      setTab={setTab}
      activeThreadId={activeThreadId}
      setActiveThreadId={setActiveThreadId}
      setSelectedTableId={setSelectedTableId}
      refresh={refresh}
      error={error}
      setError={setError}
      notice={notice}
    />
  );
}

createRoot(document.getElementById("root")!).render(
  <Provider store={store}>
    <App />
  </Provider>,
);
