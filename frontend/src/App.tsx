// ─────────────────────────────────────────────────────────────────────────────
// App.tsx — the three-panel shell + the one place the WebSocket is wired up.
// READING ORDER: frontend #17
//
// WHAT IT DOES: lays out the fixed three panels (now resizable) and, in a single
// useEffect, opens the /ws event stream. Events flow into the zustand store; the
// panels read from the store and render.
//
// WHY the WebSocket lives in a useEffect with a cleanup return: React 18 Strict Mode
// (on in main.tsx) mounts → unmounts → mounts components in development to catch
// effects that don't clean up. Because we close the socket in the cleanup, each
// cycle fully tears down its connection — so we never end up with two "ghost"
// sockets double-firing events. This is the exact bug the addendum warned about.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { getHealth, WS_URL } from "./lib/api";
import { EventSocket } from "./lib/ws";
import Conversation from "./panels/Conversation";
import RightPane from "./panels/rightpane/RightPane";
import Sidebar from "./panels/Sidebar";
import StatusBar from "./panels/StatusBar";
import Toasts from "./panels/Toasts";
import { useAppStore } from "./store/appStore";

/** A thin draggable divider between two panels. */
function Handle() {
  return <PanelResizeHandle className="w-px bg-line transition-colors hover:bg-accent" />;
}

/** The application root. */
export default function App() {
  // Open the event stream once, on mount; close it on unmount (Strict-Mode-safe).
  useEffect(() => {
    // We read store actions via getState() inside the handlers so this effect never
    // needs to re-run — it depends on nothing and runs exactly once per mount.
    const socket = new EventSocket(WS_URL, {
      onStatus: (status) => useAppStore.getState().setStatus(status),
      onEvent: (event) => useAppStore.getState().applyEvent(event),
    });
    socket.connect();
    return () => socket.close();
  }, []);

  // Ask the backend once whether it's in mock mode, so the MOCK badge is accurate.
  useEffect(() => {
    getHealth()
      .then((health) => useAppStore.getState().setMock(health.mock_llm))
      .catch(() => {
        // If health fails the WebSocket's dot already shows the connection problem;
        // nothing else to do here.
      });
  }, []);

  // Keyboard shortcuts (PROMPT.md §12). Cmd (mac) or Ctrl (elsewhere) is the modifier.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!event.metaKey && !event.ctrlKey) return;
      const store = useAppStore.getState();
      const key = event.key.toLowerCase();
      if (key === "n" && !event.shiftKey) {
        event.preventDefault();
        store.newSession();
      } else if (event.shiftKey && key === "d") {
        event.preventDefault();
        store.setBuildTab("diff");
      } else if (event.shiftKey && key === "t") {
        event.preventDefault();
        store.setBuildTab("terminal");
      } else if (event.shiftKey && key === "c") {
        event.preventDefault();
        store.setBuildTab("checks");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <Toasts />
      {/* Slim title bar. */}
      <header className="flex h-9 flex-none items-center border-b border-line bg-sidebar px-3 font-semibold text-fg">
        Lemma
      </header>

      {/* Exactly three panels, now resizable. Sizes are percentages of the width. */}
      <PanelGroup direction="horizontal" className="min-h-0 flex-1">
        <Panel defaultSize={18} minSize={12} className="border-r border-line">
          <Sidebar />
        </Panel>
        <Handle />
        <Panel minSize={30}>
          <Conversation />
        </Panel>
        <Handle />
        <Panel defaultSize={34} minSize={20} className="border-l border-line">
          <RightPane />
        </Panel>
      </PanelGroup>

      <StatusBar />
    </div>
  );
}
