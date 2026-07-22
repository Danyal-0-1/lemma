// ─────────────────────────────────────────────────────────────────────────────
// Conversation.tsx — the center panel: the crew debate + the composer.
// READING ORDER: frontend #14
//
// WHAT IT DOES (M3): renders the streamed turns, and shows the RIGHT bottom control
// for the current moment (phase-aware chrome, PROMPT.md §12):
//   • idle       → a composer to start a session from a seed idea,
//   • debating   → a "crew is working" line with a Cancel button,
//   • at the gate → the ApprovalBar (Approve / Request changes / Reject).
//
// WHY only one control shows at a time: it keeps the one obvious next action visible
// and everything else out of the way — the Conductor-simple principle.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { postCancel, postDemo, postOneshot, postSession } from "../lib/api";
import type { Role } from "../lib/events";
import { useAppStore } from "../store/appStore";
import ApprovalBar from "./ApprovalBar";

// Display name + Tailwind text-color class for each speaker (colors from theme.css).
const ROLE_META: Record<Role, { label: string; className: string }> = {
  generator: { label: "Generator", className: "text-role-generator" },
  researcher: { label: "Researcher", className: "text-role-researcher" },
  critic: { label: "Critic", className: "text-role-critic" },
  pm: { label: "PM", className: "text-role-pm" },
  mentor: { label: "Mentor", className: "text-role-mentor" },
  system: { label: "System", className: "text-muted" },
};

/** The center column of the three-panel shell. */
export default function Conversation() {
  const turns = useAppStore((s) => s.turns);
  const phase = useAppStore((s) => s.phase);
  const awaiting = useAppStore((s) => s.awaitingApproval);
  const activeSessionId = useAppStore((s) => s.activeSessionId);
  const clearConversation = useAppStore((s) => s.clearConversation);
  const setActiveSession = useAppStore((s) => s.setActiveSession);

  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  // Autoscroll to the newest content whenever turns change.
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  // The crew is "working" while in the ideation phase and not yet at the gate.
  const debating = phase === "ideation" && awaiting === null;

  async function handleStart() {
    const seed = draft.trim();
    if (!seed) return;
    setBusy(true);
    clearConversation();
    try {
      const { session_id } = await postSession(seed);
      setActiveSession(session_id);
      setDraft("");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (activeSessionId) await postCancel(activeSessionId);
  }

  async function runTrigger(trigger: () => Promise<unknown>) {
    setBusy(true);
    clearConversation();
    try {
      await trigger();
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex h-full flex-col bg-panel">
      {/* Header: dev shortcuts (a single real turn, or the scripted demo). */}
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          Conversation
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => runTrigger(postOneshot)}
            disabled={busy || debating}
            title="Stream one real (or mock) Generator turn"
            className="rounded border border-line px-2 py-1 text-fg hover:bg-line disabled:opacity-50"
          >
            ▶ One turn
          </button>
          <button
            type="button"
            onClick={() => runTrigger(postDemo)}
            disabled={busy || debating}
            className="rounded border border-line px-2 py-1 text-fg hover:bg-line disabled:opacity-50"
          >
            ▶ Demo
          </button>
        </div>
      </div>

      {/* The scrolling transcript. */}
      <div className="flex-1 overflow-y-auto p-4">
        {turns.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="max-w-md text-center text-muted">
              Start an ideation session — the crew will debate here.
            </p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {turns.map((turn) => {
              const meta = ROLE_META[turn.role];
              return (
                <div key={turn.id} className="rounded border border-line bg-sidebar/40 p-3">
                  <div className={`mb-1 text-[11px] font-semibold uppercase ${meta.className}`}>
                    {meta.label}
                    {turn.streaming && <span className="ml-2 text-muted">▍</span>}
                  </div>
                  <div className="md text-fg">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.text}</ReactMarkdown>
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Bottom control — exactly one, chosen by phase. */}
      {awaiting ? (
        <ApprovalBar />
      ) : debating ? (
        <div className="flex items-center justify-between border-t border-line px-3 py-3 text-muted">
          <span>The crew is debating…</span>
          <button
            type="button"
            onClick={handleCancel}
            className="rounded border border-line px-3 py-1.5 text-fg hover:bg-line"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="border-t border-line p-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter starts the session; Shift+Enter inserts a newline.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleStart();
              }
            }}
            placeholder="Describe an idea to start… (Enter to begin, Shift+Enter for a newline)"
            disabled={busy}
            className="h-16 w-full resize-none rounded border border-line bg-sidebar px-2 py-1.5 text-fg placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-50"
          />
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={handleStart}
              disabled={busy || !draft.trim()}
              className="rounded bg-accent px-3 py-1.5 text-white hover:bg-accent-hover disabled:opacity-50"
            >
              Start session
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
