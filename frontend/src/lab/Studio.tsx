// Top-level VS Code-style R&D shell. The original Workbench remains one activity.

import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import Conversation from "../panels/Conversation";
import RightPane from "../panels/rightpane/RightPane";
import Sidebar from "../panels/Sidebar";
import ActivityRail from "./components/ActivityRail";
import ContextSidebar from "./components/ContextSidebar";
import { ErrorState, LoadingState } from "./components/UI";
import IdeWorkspace from "./ide/IdeWorkspace";
import { useLabStore } from "./store";
import type { IdeView, ResearchView as ResearchViewId } from "./types";
import HqView from "./views/HqView";
import MeetingsView from "./views/MeetingsView";
import OrganizationView from "./views/OrganizationView";
import ResearchView from "./views/ResearchView";
import SecurityView from "./views/SecurityView";

function Handle() {
  return <PanelResizeHandle className="lab-resize-handle" />;
}

function LegacyWorkbench() {
  return (
    <div className="lab-studio-body">
      <ActivityRail />
      <PanelGroup direction="horizontal" className="min-h-0 flex-1">
        <Panel defaultSize={20} minSize={13} className="border-r border-line"><Sidebar /></Panel>
        <Handle />
        <Panel minSize={30}><Conversation /></Panel>
        <Handle />
        <Panel defaultSize={34} minSize={21} className="border-l border-line"><RightPane /></Panel>
      </PanelGroup>
    </div>
  );
}

const IDE_VIEWS: IdeView[] = ["explorer", "search", "source_control", "terminal"];

export default function Studio() {
  const view = useLabStore((state) => state.view);
  const loading = useLabStore((state) => state.loading);
  const error = useLabStore((state) => state.error);
  const load = useLabStore((state) => state.load);

  if (view === "workbench") return <LegacyWorkbench />;
  if (IDE_VIEWS.includes(view as IdeView)) {
    return (
      <div className="lab-studio-body">
        <ActivityRail />
        <IdeWorkspace view={view as IdeView} />
      </div>
    );
  }

  const researchView = view as ResearchViewId;

  return (
    <div className="lab-studio-body">
      <ActivityRail />
      <ContextSidebar view={researchView} />
      <section className="lab-editor-area">
        {loading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : (
          <>
            {researchView === "hq" && <HqView />}
            {researchView === "organization" && <OrganizationView />}
            {researchView === "research" && <ResearchView />}
            {researchView === "meetings" && <MeetingsView />}
            {researchView === "security" && <SecurityView />}
          </>
        )}
      </section>
    </div>
  );
}
