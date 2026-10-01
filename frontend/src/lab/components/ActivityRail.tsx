// VS Code-style primary activity rail. Research remains a first-class workbench.

import { useShellStore } from "../../store/shellStore";
import { useLabStore } from "../store";
import type { LabView, ResearchView } from "../types";
import { Icon, type IconName } from "./Icons";

const RESEARCH_VIEWS: ResearchView[] = [
  "hq",
  "organization",
  "research",
  "knowledge",
  "evaluations",
  "meetings",
  "operations",
  "security",
];
const ITEMS: { id: LabView; label: string; icon: IconName }[] = [
  { id: "explorer", label: "Explorer", icon: "explorer" },
  { id: "search", label: "Search", icon: "search" },
  { id: "source_control", label: "Source Control", icon: "sourceControl" },
  { id: "hq", label: "R&D Research Studio", icon: "research" },
  { id: "terminal", label: "Terminal", icon: "terminal" },
  { id: "workbench", label: "Ideation Workbench", icon: "workbench" },
];

function isSelected(view: LabView, id: LabView): boolean {
  if (id === "hq") return RESEARCH_VIEWS.includes(view as ResearchView);
  return view === id;
}

export default function ActivityRail() {
  const view = useLabStore((state) => state.view);
  const setView = useLabStore((state) => state.setView);
  const running = useLabStore(
    (state) => Object.values(state.liveRuns).filter((run) => run.status === "running").length,
  );
  const overlay = useShellStore((state) => state.overlay);
  const setOverlay = useShellStore((state) => state.setOverlay);

  return (
    <nav className="lab-activity-rail" aria-label="Workbench activities">
      <div className="lab-mark" title="Lemma R&D Studio" aria-hidden="true"><span>λ</span></div>
      <div className="lab-rail-group">
        {ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`lab-rail-button ${isSelected(view, item.id) ? "is-active" : ""}`}
            onClick={() => setView(item.id)}
            aria-label={item.label}
            aria-current={isSelected(view, item.id) ? "page" : undefined}
            title={item.label}
          >
            <Icon name={item.icon} size={23} />
            {item.id === "hq" && running > 0 && (
              <span className="lab-rail-count" aria-label={`${running} active runs`}>{running}</span>
            )}
          </button>
        ))}
      </div>
      <div className="lab-rail-bottom">
        <button
          type="button"
          className={`lab-rail-button ${overlay === "account" ? "is-active" : ""}`}
          onClick={() => setOverlay(overlay === "account" ? null : "account")}
          aria-label="Accounts"
          title="Accounts"
        ><Icon name="account" size={22} /></button>
        <button
          type="button"
          className={`lab-rail-button ${overlay === "settings" ? "is-active" : ""}`}
          onClick={() => setOverlay(overlay === "settings" ? null : "settings")}
          aria-label="Manage settings"
          title="Manage settings"
        ><Icon name="settings" size={22} /></button>
      </div>
    </nav>
  );
}
