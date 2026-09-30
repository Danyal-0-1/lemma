// ─────────────────────────────────────────────────────────────────────────────
// StatusBar.tsx — the bottom bar: connection dot, phase, cost meter, MOCK badge.
// READING ORDER: frontend #15
//
// WHAT IT DOES: reads live state from the store and reflects it. The dot turns
// green when the WebSocket is open and amber while (re)connecting — this is the
// exact behavior the M1 acceptance test checks (kill backend → amber → green).
// ─────────────────────────────────────────────────────────────────────────────

import type { ConnectionStatus } from "../lib/ws";
import { useLabStore } from "../lab/store";
import { useAppStore } from "../store/appStore";
import { usePreferencesStore } from "../store/preferencesStore";

// Map a connection status to a dot color class and a short label.
const STATUS_META: Record<ConnectionStatus, { dot: string; label: string }> = {
  connecting: { dot: "bg-warn", label: "connecting" },
  open: { dot: "bg-ok", label: "connected" },
  reconnecting: { dot: "bg-warn", label: "reconnecting" },
  closed: { dot: "bg-err", label: "disconnected" },
};

/** The bottom status bar of the shell. */
export default function StatusBar() {
  const status = useAppStore((s) => s.status);
  const phase = useAppStore((s) => s.phase);
  const cost = useAppStore((s) => s.cost);
  const mock = useAppStore((s) => s.mock);
  const hostExecution = useAppStore((s) => s.hostExecutionEnabled);
  const resolvedTheme = usePreferencesStore((s) => s.resolvedTheme);
  const view = useLabStore((s) => s.view);
  const snapshot = useLabStore((s) => s.snapshot);
  const running = useLabStore(
    (s) => Object.values(s.liveRuns).filter((run) => run.status === "running").length,
  );

  const meta = STATUS_META[status];
  const codeView = ["explorer", "search", "source_control", "terminal"].includes(view);

  return (
    <footer className="flex h-6 flex-none items-center gap-4 border-t border-line bg-sidebar px-3 text-[11px] text-muted">
      <span className="flex items-center gap-1.5">
        <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} />
        {meta.label}
      </span>
      {codeView ? (
        <>
          <span>code: {view.replaceAll("_", " ")}</span>
          <span>theme: {resolvedTheme}</span>
        </>
      ) : view === "workbench" ? <span>phase: {phase}</span> : (
        <>
          <span>{snapshot.agents.filter((agent) => agent.status === "active").length} active agents</span>
          <span>{running} live runs</span>
          <span>{snapshot.tasks.filter((task) => task.status === "queued").length} queued</span>
        </>
      )}
      {/* Cost meter — moves as the demo (and later the real crew) reports usage. */}
      <span title={`${cost.tokensIn} in / ${cost.tokensOut} out tokens this session`}>
        ${cost.sessionUsd.toFixed(5)} session · ${cost.dayUsd.toFixed(5)} today
      </span>
      <span className={hostExecution ? "text-warn" : "text-ok"}>
        {hostExecution ? "host tools enabled" : "host tools locked"}
      </span>
      {mock && (
        <span className="ml-auto rounded bg-line px-1.5 py-0.5 font-mono text-warn">MOCK</span>
      )}
    </footer>
  );
}
