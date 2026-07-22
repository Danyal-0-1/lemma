// ─────────────────────────────────────────────────────────────────────────────
// ChecksTab.tsx — the pre-merge ritual: save commands that prove the project works.
// READING ORDER: frontend #28
//
// WHAT IT DOES: lists saved checks (tests, lint, build) editable in place. Running one
// saves the list, launches it on the backend, and streams its output; the exit code
// becomes a green ✓ / red ✗ badge (from the store, filled by check_* events).
//
// WHY save-then-run: the backend runs the command stored in aicompany.json, so we
// persist your edits first — what you see is exactly what runs.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react";

import { getChecks, putChecks, runCheck, type Check } from "../../lib/api";
import { useAppStore } from "../../store/appStore";

/** Badge shown next to a check based on its latest run. */
function Badge({ checkId }: { checkId: string }) {
  const run = useAppStore((s) => s.checkRuns[checkId]);
  if (!run) return null;
  if (run.status === "running") return <span className="text-warn">running…</span>;
  if (run.status === "pass") return <span className="text-ok">✓ pass</span>;
  return <span className="text-err">✗ fail ({run.exitCode})</span>;
}

/** The Checks tab. */
export default function ChecksTab({ workspaceId, active }: { workspaceId: string; active: boolean }) {
  const checkRuns = useAppStore((s) => s.checkRuns);
  const [checks, setChecks] = useState<Check[]>([]);
  const [dirty, setDirty] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    getChecks(workspaceId)
      .then((loaded) => {
        setChecks(loaded);
        setDirty(false);
      })
      .catch(() => {});
  }, [active, workspaceId]);

  function update(id: string, field: "name" | "command", value: string) {
    setChecks((list) => list.map((c) => (c.id === id ? { ...c, [field]: value } : c)));
    setDirty(true);
  }

  function addCheck() {
    setChecks((list) => [...list, { id: crypto.randomUUID(), name: "new check", command: "" }]);
    setDirty(true);
  }

  function removeCheck(id: string) {
    setChecks((list) => list.filter((c) => c.id !== id));
    setDirty(true);
  }

  async function run(check: Check) {
    // Persist edits first so the backend runs exactly what's shown, then launch it.
    await putChecks(workspaceId, checks);
    setDirty(false);
    setOpenId(check.id);
    await runCheck(workspaceId, check.id);
  }

  const openOutput = openId ? (checkRuns[openId]?.output ?? []) : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line px-2 py-1.5">
        <span className="text-[11px] uppercase text-muted">Checks</span>
        {dirty && (
          <button
            type="button"
            onClick={() => void putChecks(workspaceId, checks).then(() => setDirty(false))}
            className="rounded bg-accent px-2 py-0.5 text-white hover:bg-accent-hover"
          >
            Save
          </button>
        )}
        <button
          type="button"
          onClick={addCheck}
          className="ml-auto rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
        >
          + Add
        </button>
      </div>

      {checks.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-muted">
          Save the commands that prove this project works — tests, lint, build — and run
          them before you trust a diff.
        </div>
      ) : (
        <div className="flex-none divide-y divide-line overflow-y-auto">
          {checks.map((check) => (
            <div key={check.id} className="flex flex-col gap-1 p-2">
              <div className="flex items-center gap-2">
                <input
                  value={check.name}
                  onChange={(e) => update(check.id, "name", e.target.value)}
                  className="w-28 rounded border border-line bg-sidebar px-1.5 py-0.5 text-fg"
                />
                <button
                  type="button"
                  onClick={() => void run(check)}
                  className="rounded bg-accent px-2 py-0.5 text-white hover:bg-accent-hover"
                >
                  ▶ Run
                </button>
                <Badge checkId={check.id} />
                <button
                  type="button"
                  onClick={() => removeCheck(check.id)}
                  className="ml-auto text-muted hover:text-err"
                  title="Remove"
                >
                  ✕
                </button>
              </div>
              <input
                value={check.command}
                onChange={(e) => update(check.id, "command", e.target.value)}
                placeholder="command, e.g. pytest -q"
                className="w-full rounded border border-line bg-sidebar px-1.5 py-0.5 font-mono text-[12px] text-fg placeholder:text-muted"
              />
            </div>
          ))}
        </div>
      )}

      {/* Live output of the most recently run check. */}
      {openId && (
        <pre className="min-h-0 flex-1 overflow-auto border-t border-line bg-black/30 p-2 font-mono text-[12px] text-fg">
          {openOutput.join("\n") || "(no output yet)"}
        </pre>
      )}
    </div>
  );
}
