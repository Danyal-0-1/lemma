// App.tsx — global title/status chrome plus the R&D Studio workspace.

import { useEffect, useState } from "react";

import Studio from "./lab/Studio";
import { COMMANDS, CommandPalette } from "./lab/components/CommandPalette";
import { Icon } from "./lab/components/Icons";
import ShellOverlays from "./lab/components/ShellOverlays";
import { currentView, writeViewToUrl } from "./lab/navigation";
import { useLabStore } from "./lab/store";
import { getHealth, WS_URL } from "./lib/api";
import { EventSocket } from "./lib/ws";
import StatusBar from "./panels/StatusBar";
import Toasts from "./panels/Toasts";
import { useAppStore } from "./store/appStore";
import { useApplyTheme } from "./store/preferencesStore";

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
    const restore = () => useLabStore.getState().restoreView(currentView());
    writeViewToUrl(useLabStore.getState().view, { replace: true });
    window.addEventListener("hashchange", restore);
    window.addEventListener("popstate", restore);
    return () => {
      window.removeEventListener("hashchange", restore);
      window.removeEventListener("popstate", restore);
    };
  }, []);

  useEffect(() => {
    getHealth().then((health) => {
      useAppStore.getState().setMock(health.mock_llm);
      useAppStore.getState().setHostExecutionEnabled(health.enable_host_execution);
      useAppStore.getState().setHeadlessCodingEnabled(Boolean(health.enable_headless_coding));
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
