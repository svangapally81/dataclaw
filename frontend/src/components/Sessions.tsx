import { MessageSquare, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { errorMessage } from "../lib/errors";
import {
  useChatThreadsQuery,
  useCreateChatThreadMutation,
  useDeleteChatThreadMutation,
} from "../services/api";

type SessionsProps = {
  activeThreadId: string | null;
  setActiveThreadId: (value: string | null) => void;
};

export function Sessions({ activeThreadId, setActiveThreadId }: SessionsProps) {
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const threadsQuery = useChatThreadsQuery();
  const [createThread] = useCreateChatThreadMutation();
  const [deleteThread] = useDeleteChatThreadMutation();
  const threads = threadsQuery.data ?? [];

  const needle = filter.trim().toLowerCase();
  const filtered = needle
    ? threads.filter((thread) => thread.title.toLowerCase().includes(needle))
    : threads;

  async function handleNewChat() {
    if (creating) return;
    setError("");
    setCreating(true);
    try {
      const created = await createThread({ title: "New chat" }).unwrap();
      setActiveThreadId(created.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    setError("");
    try {
      await deleteThread(id).unwrap();
      if (activeThreadId === id) setActiveThreadId(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <aside className="sessions">
      <header className="sessions-head">
        <h3>SESSIONS</h3>
        <button
          aria-label="New chat"
          className="sessions-new"
          disabled={creating}
          onClick={handleNewChat}
          type="button"
        >
          <Plus size={14} />
        </button>
      </header>

      {error ? <p className="sessions-error">{error}</p> : null}

      <div className="sessions-filter">
        <Search size={12} />
        <input
          aria-label="Filter sessions"
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter sessions..."
          value={filter}
        />
      </div>

      <div className="sessions-list">
        {filtered.length === 0 ? (
          <p className="sessions-empty">
            {threads.length === 0
              ? "No sessions yet. Start a new chat to begin."
              : "No matches."}
          </p>
        ) : (
          filtered.map((thread) => {
            const active = thread.id === activeThreadId;
            return (
              <div
                className={`sessions-item ${active ? "active" : ""}`}
                key={thread.id}
              >
                <button
                  className="sessions-item-link"
                  onClick={() => setActiveThreadId(thread.id)}
                  title={thread.title}
                  type="button"
                >
                  <MessageSquare size={12} />
                  <span>{thread.title}</span>
                </button>
                <button
                  aria-label={`Delete ${thread.title}`}
                  className="sessions-item-delete"
                  onClick={() => handleDelete(thread.id)}
                  type="button"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
