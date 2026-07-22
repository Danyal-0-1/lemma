// ─────────────────────────────────────────────────────────────────────────────
// Conversation.tsx — the center panel: the crew debate (and later the mentor).
// READING ORDER: frontend #14
//
// WHAT IT DOES (M1): renders the list of turns from the store, each as a bubble with
// a color-coded role chip and streamed markdown. A "Play demo" button triggers the
// scripted backend round so you can watch tokens stream in live.
//
// WHY the role colors + streaming: PROMPT.md §12 specifies per-role colors and
// token-by-token rendering. Because the store appends tokens to the last turn, this
// component just re-renders on each change — React does the rest.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { postDemo, postOneshot } from "../lib/api";
import type { Role } from "../lib/events";
import { useAppStore } from "../store/appStore";

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
  const clearConversation = useAppStore((s) => s.clearConversation);
  const [busy, setBusy] = useState(false);

  // Autoscroll to the newest content whenever turns change (a common chat behavior).
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function handlePlayDemo() {
    setBusy(true);
    // Clear first so re-running the demo starts from an empty conversation.
    clearConversation();
    try {
      await postDemo();
    } finally {
      // The events stream in over /ws; we only needed to fire the trigger.
      setBusy(false);
    }
  }

  async function handleOneshot() {
    setBusy(true);
    clearConversation();
    try {
      // One real (or mock) Generator turn. In mock mode it's free; with a key it
      // streams live tokens and the cost meter moves.
      await postOneshot();
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex h-full flex-col bg-panel">
      {/* Header with the one action available in the idle/ideation phase for M1. */}
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          Conversation
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOneshot}
            disabled={busy}
            title="Stream one real (or mock) Generator turn"
            className="rounded border border-line px-2 py-1 text-fg hover:bg-line disabled:opacity-50"
          >
            ▶ One real turn
          </button>
          <button
            type="button"
            onClick={handlePlayDemo}
            disabled={busy}
            className="rounded bg-accent px-2 py-1 text-white hover:bg-accent-hover disabled:opacity-50"
          >
            ▶ Play demo
          </button>
        </div>
      </div>

      {/* The scrolling transcript. */}
      <div className="flex-1 overflow-y-auto p-4">
        {turns.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="max-w-md text-center text-muted">
              Start an ideation session — the crew will debate here.
              <br />
              <span className="text-[11px]">(or press “Play demo” to see it stream)</span>
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

      {/* The composer becomes interactive in M3 (ideation) / M7 (mentor). */}
      <div className="border-t border-line p-3">
        <textarea
          className="h-16 w-full resize-none rounded border border-line bg-sidebar px-2 py-1.5 text-fg placeholder:text-muted focus:border-accent focus:outline-none"
          placeholder="Describe an idea to start… (composer activates in M3)"
          disabled
        />
      </div>
    </main>
  );
}
