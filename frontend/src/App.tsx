// App.tsx — global title/status chrome plus the R&D Studio workspace.

import { useEffect, useState } from "react";

import Studio from "./lab/Studio";
import { Icon } from "./lab/components/Icons";
import ShellOverlays from "./lab/components/ShellOverlays";
import { useLabStore } from "./lab/store";
import type { LabView } from "./lab/types";
import { getHealth, WS_URL } from "./lib/api";
import { EventSocket } from "./lib/ws";
import StatusBar from "./panels/StatusBar";
import Toasts from "./panels/Toasts";
import { useAppStore } from "./store/appStore";
import { useApplyTheme } from "./store/preferencesStore";

const COMMANDS: { view: LabView; label: string; detail: string }[] = [
  { view: "explorer", label: "Explorer: Open Project Files", detail: "Browse and read the selected workspace" },
  { view: "search", label: "Search: Find in Files", detail: "Search safely across project text" },
  { view: "source_control", label: "Source Control: Git", detail: "Review, stage, commit, and push" },
  { view: "hq", label: "R&D: Open Headquarters", detail: "Agents, departments, and research activity" },
  { view: "terminal", label: "Terminal: Open Trusted Shell", detail: "Local operator terminal, opt-in only" },
  { view: "organization", label: "R&D: Open Organization", detail: "Departments, teams, and duty cards" },
  { view: "research", label: "R&D: Open Research Board", detail: "Projects, tasks, and findings" },
  { view: "meetings", label: "R&D: Open Meeting Rooms", detail: "Bounded agent collaboration" },
  { view: "security", label: "R&D: Open Security Center", detail: "Capabilities and trust boundary" },
  { view: "workbench", label: "Open Ideation Workbench", detail: "Specs, mentor, diffs, and checks" },
];

function CommandPalette({ onClose }: { onClose: () => void }) {
  const setView = useLabStore((state) => state.setView);
  return (
    <div className="lab-command-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="lab-command-palette" role="dialog" aria-label="Command palette">
        <header><Icon name="research" size={16} /><span>Navigate Lemma</span><kbd>esc</kbd></header>
        <div>{COMMANDS.map((command, index) => <button key={command.view} onClick={() => { setView(command.view); onClose(); }}><span><strong>{command.label}</strong><small>{command.detail}</small></span>{index < 9 && <kbd>⌘{index + 1}</kbd>}</button>)}</div>
      </div>
    </div>
  );
}

export default function App() {
  useApplyTheme();
  const view = useLabStore((state) => state.view);
  const setView = useLabStore((state) => state.setView);
  const [palette, setPalette] = useState(false);

  useEffect(() => {
    const socket = new EventSocket(WS_URL, {
      onStatus: (status) => useAppStore.getState().setStatus(status),
      onEvent: (event) => {
        useAppStore.getState().applyEvent(event);
        useLabStore.getState().applyEvent(event);
      },
    });
    socket.connect();
    return () => socket.close();
  }, []);

  useEffect(() => { void useLabStore.getState().load(); }, []);

  useEffect(() => {
    getHealth().then((health) => {
      useAppStore.getState().setMock(health.mock_llm);
      useAppStore.getState().setHostExecutionEnabled(health.enable_host_execution);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!event.metaKey && !event.ctrlKey) {
        if (event.key === "Escape") setPalette(false);
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "k") { event.preventDefault(); setPalette(true); return; }
      const index = Number(event.key) - 1;
      if (index >= 0 && index < COMMANDS.length) { event.preventDefault(); setView(COMMANDS[index].view); return; }
      if (view !== "workbench") return;
      const store = useAppStore.getState();
      if (key === "n" && !event.shiftKey) { event.preventDefault(); store.newSession(); }
      else if (event.shiftKey && key === "d") { event.preventDefault(); store.setBuildTab("diff"); }
      else if (event.shiftKey && key === "t") { event.preventDefault(); store.setBuildTab("terminal"); }
      else if (event.shiftKey && key === "c") { event.preventDefault(); store.setBuildTab("checks"); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setView, view]);

  return (
    <div className="lab-app-shell">
      <Toasts />
      <header className="lab-titlebar">
        <div className="lab-title-brand"><strong>LEMMA</strong><span>/</span><span>{["explorer", "search", "source_control", "terminal"].includes(view) ? "Code" : view === "workbench" ? "Ideation" : "R&D Studio"}</span><span>/</span><b>{view.replaceAll("_", " ")}</b></div>
        <button className="lab-command-trigger" onClick={() => setPalette(true)}><Icon name="research" size={14} /><span>Navigate workspace…</span><kbd>⌘K</kbd></button>
        <div className="lab-local-chip"><span /> local only</div>
      </header>
      <Studio />
      <StatusBar />
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
      <ShellOverlays />
    </div>
  );
}
