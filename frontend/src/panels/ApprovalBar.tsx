// ─────────────────────────────────────────────────────────────────────────────
// ApprovalBar.tsx — the human gate: Approve / Request changes / Reject.
// READING ORDER: frontend #18
//
// WHAT IT DOES: shown only when the crew is waiting for a decision. Approve is the
// single accented action (PROMPT.md §12 rule 2 — at the gate, the approval bar is the
// only emphasized element). "Request changes" reveals a textarea whose feedback loops
// back through the crew for another round.
//
// WHY it reads from the store: the `awaiting_approval` event set both the question and
// the active session id, so this component just needs those two values to act.
// ─────────────────────────────────────────────────────────────────────────────

import { useState } from "react";

import { postApproval } from "../lib/api";
import { useAppStore } from "../store/appStore";

/** The docked approval bar. Renders nothing unless a decision is pending. */
export default function ApprovalBar() {
  const approval = useAppStore((s) => s.awaitingApproval);
  const sessionId = useAppStore((s) => s.activeSessionId);
  const [showChanges, setShowChanges] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  // Phase-aware chrome: if there's nothing to approve, this bar doesn't exist.
  if (!approval || !sessionId) return null;

  async function decide(decision: "approve" | "changes" | "reject", note?: string) {
    setBusy(true);
    try {
      await postApproval(sessionId!, decision, note);
    } finally {
      setBusy(false);
      setShowChanges(false);
      setFeedback("");
    }
  }

  return (
    <div className="border-t border-line bg-sidebar p-3">
      <p className="mb-2 text-fg">{approval.question}</p>

      {showChanges ? (
        <div className="flex flex-col gap-2">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="What should change? The crew will debate again with this feedback."
            className="h-20 w-full resize-none rounded border border-line bg-panel px-2 py-1.5 text-fg placeholder:text-muted focus:border-accent focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => decide("changes", feedback)}
              disabled={busy || !feedback.trim()}
              className="rounded bg-accent px-3 py-1.5 text-white hover:bg-accent-hover disabled:opacity-50"
            >
              Send changes
            </button>
            <button
              type="button"
              onClick={() => setShowChanges(false)}
              className="rounded border border-line px-3 py-1.5 text-fg hover:bg-line"
            >
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          {/* Approve is the ONLY accented control while at the gate. */}
          <button
            type="button"
            onClick={() => decide("approve")}
            disabled={busy}
            className="rounded bg-accent px-3 py-1.5 text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => setShowChanges(true)}
            disabled={busy}
            className="rounded border border-line px-3 py-1.5 text-fg hover:bg-line"
          >
            Request changes
          </button>
          <button
            type="button"
            onClick={() => decide("reject")}
            disabled={busy}
            className="rounded border border-line px-3 py-1.5 text-err hover:bg-line"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
