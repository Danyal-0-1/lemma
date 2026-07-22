// ─────────────────────────────────────────────────────────────────────────────
// SpecTab.tsx — inspect the Spec (and watch the idea evolve) in the right pane.
// READING ORDER: frontend #21
//
// WHAT IT DOES: shows the crew's artifacts. Two views:
//   • Spec  — a version switcher + the Spec as a JSON tree, with a "Raw" toggle that
//             shows it in Monaco (read-only JSON), plus an Export button.
//   • Ideas — a version switcher over the IdeaDoc, so you can scrub through how the
//             idea changed round to round (the "IdeaDoc evolution").
//
// WHY read from the store's artifacts: they're filled both live (artifact events) and
// on restore (GET /api/sessions/{id}), so this one component works for both.
// ─────────────────────────────────────────────────────────────────────────────

import { lazy, Suspense, useState } from "react";

import { exportSession, postWorkspaceFromSpec } from "../../lib/api";
import { useAppStore } from "../../store/appStore";
import JsonTree from "./JsonTree";

// Monaco is heavy, so we load it only when the user opens the Raw view (code-splitting).
const MonacoJson = lazy(() => import("./MonacoJson"));

// The loose shape of an IdeaDoc's content (enough to render the evolution nicely).
interface IdeaDocContent {
  chosen_idea?: string | null;
  decision_rationale?: string | null;
  ideas?: { name: string; pitch: string; feasibility_notes?: string; critic_notes?: string }[];
}

/** A labelled version dropdown shared by both views. */
function VersionPicker({
  versions,
  selected,
  onSelect,
}: {
  versions: number[];
  selected: number;
  onSelect: (version: number) => void;
}) {
  return (
    <select
      value={selected}
      onChange={(e) => onSelect(Number(e.target.value))}
      className="rounded border border-line bg-panel px-1.5 py-0.5 text-fg"
    >
      {versions.map((version) => (
        <option key={version} value={version}>
          v{version}
        </option>
      ))}
    </select>
  );
}

/** Render an IdeaDoc's content as a readable list (the evolution view). */
function IdeasView({ content }: { content: IdeaDocContent }) {
  return (
    <div className="flex flex-col gap-3 text-fg">
      {content.chosen_idea && (
        <div>
          <span className="text-muted">Chosen: </span>
          <span className="text-role-pm">{content.chosen_idea}</span>
        </div>
      )}
      {content.decision_rationale && <p className="text-muted">{content.decision_rationale}</p>}
      {(content.ideas ?? []).map((idea) => (
        <div key={idea.name} className="rounded border border-line p-2">
          <div className="font-semibold text-role-generator">{idea.name}</div>
          <p className="mt-1">{idea.pitch}</p>
          {idea.feasibility_notes && (
            <p className="mt-1 text-role-researcher">🔬 {idea.feasibility_notes}</p>
          )}
          {idea.critic_notes && <p className="mt-1 text-role-critic">⚔️ {idea.critic_notes}</p>}
        </div>
      ))}
    </div>
  );
}

/** The Spec tab body. */
export default function SpecTab() {
  const artifacts = useAppStore((s) => s.artifacts);
  const sessionId = useAppStore((s) => s.sessionId);

  const [view, setView] = useState<"spec" | "ideas">("spec");
  const [rawMode, setRawMode] = useState(false);
  const [pickedSpec, setPickedSpec] = useState<number | null>(null);
  const [pickedIdea, setPickedIdea] = useState<number | null>(null);

  const specs = artifacts.filter((a) => a.kind === "spec");
  const ideaDocs = artifacts.filter((a) => a.kind === "ideadoc");
  // The most recent Spec is the one we'd build a workspace from.
  const buildableSpec = specs.length > 0 ? specs[specs.length - 1] : null;

  if (specs.length === 0 && ideaDocs.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="max-w-xs text-center text-muted">
          The Spec will appear here once the crew produces one.
        </p>
      </div>
    );
  }

  // Show the picked version, or the latest until the user chooses one.
  const specVersions = specs.map((s) => s.version);
  const ideaVersions = ideaDocs.map((d) => d.version);
  const shownSpecVersion = pickedSpec ?? Math.max(...specVersions, 0);
  const shownIdeaVersion = pickedIdea ?? Math.max(...ideaVersions, 0);
  const shownSpec = specs.find((s) => s.version === shownSpecVersion);
  const shownIdea = ideaDocs.find((d) => d.version === shownIdeaVersion);

  return (
    <div className="flex h-full flex-col">
      {/* Sub-tabs + Export. */}
      <div className="flex items-center gap-2 border-b border-line px-2 py-1.5">
        <button
          type="button"
          onClick={() => setView("spec")}
          className={`rounded px-2 py-0.5 ${view === "spec" ? "bg-line text-fg" : "text-muted"}`}
        >
          Spec
        </button>
        <button
          type="button"
          onClick={() => setView("ideas")}
          className={`rounded px-2 py-0.5 ${view === "ideas" ? "bg-line text-fg" : "text-muted"}`}
        >
          Ideas
        </button>
        <div className="ml-auto flex items-center gap-2">
          {buildableSpec && (
            // Build a real workspace from this Spec → enters the build phase (M5).
            <button
              type="button"
              onClick={() => postWorkspaceFromSpec(buildableSpec.id)}
              className="rounded bg-accent px-2 py-0.5 text-white hover:bg-accent-hover"
            >
              Create workspace
            </button>
          )}
          {sessionId && (
            <button
              type="button"
              onClick={() => exportSession(sessionId)}
              className="rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
            >
              ⭳ Export
            </button>
          )}
        </div>
      </div>

      {view === "spec" && shownSpec ? (
        <>
          <div className="flex items-center gap-2 border-b border-line px-2 py-1.5">
            <VersionPicker
              versions={specVersions}
              selected={shownSpecVersion}
              onSelect={setPickedSpec}
            />
            <button
              type="button"
              onClick={() => setRawMode((r) => !r)}
              className="rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
            >
              {rawMode ? "Tree" : "Raw"}
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-3">
            {rawMode ? (
              <Suspense fallback={<p className="text-muted">Loading editor…</p>}>
                <MonacoJson value={shownSpec.content} />
              </Suspense>
            ) : (
              <JsonTree value={shownSpec.content} />
            )}
          </div>
        </>
      ) : view === "ideas" && shownIdea ? (
        <>
          <div className="flex items-center gap-2 border-b border-line px-2 py-1.5">
            <VersionPicker
              versions={ideaVersions}
              selected={shownIdeaVersion}
              onSelect={setPickedIdea}
            />
            <span className="text-[11px] text-muted">idea evolution</span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-3">
            <IdeasView content={shownIdea.content as IdeaDocContent} />
          </div>
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center p-8 text-muted">
          Nothing to show for this view yet.
        </div>
      )}
    </div>
  );
}
