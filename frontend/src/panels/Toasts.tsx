// ─────────────────────────────────────────────────────────────────────────────
// Toasts.tsx — transient error notifications, top-right.
// READING ORDER: frontend #30
//
// WHAT IT DOES: renders the store's `toasts` (pushed when an `error` event arrives).
// Each auto-dismisses after a few seconds, or you can close it. Errors ALSO appear in
// the conversation feed — the toast is just the "you should notice this now" nudge (§7).
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react";

import { useAppStore } from "../store/appStore";

// How long a toast stays before it fades itself out.
const TOAST_MS = 6000;

/** One toast that removes itself after a timeout. */
function ToastItem({ id, message }: { id: string; message: string }) {
  const dismiss = useAppStore((s) => s.dismissToast);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused) return undefined;
    const timer = window.setTimeout(() => dismiss(id), TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [id, dismiss, paused]);

  return (
    <div
      className="pointer-events-auto flex max-w-xs items-start gap-2 rounded border border-err bg-sidebar px-3 py-2 text-fg shadow-lg"
      role="alert"
      aria-atomic="true"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false);
      }}
    >
      <span className="text-err" aria-hidden="true">⚠️</span>
      <span className="flex-1 break-words">{message}</span>
      <button
        type="button"
        onClick={() => dismiss(id)}
        className="flex-none text-muted hover:text-fg"
        aria-label="Dismiss notification"
      >
        <span aria-hidden="true">✕</span>
      </button>
    </div>
  );
}

/** The toast stack. Renders nothing when there are no toasts. */
export default function Toasts() {
  const toasts = useAppStore((s) => s.toasts);
  return (
    <div
      className="pointer-events-none fixed right-3 top-10 z-50 flex flex-col gap-2"
      role="region"
      aria-label="Notifications"
      aria-live="assertive"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} id={toast.id} message={toast.message} />
      ))}
    </div>
  );
}
