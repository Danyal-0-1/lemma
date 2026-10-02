// ─────────────────────────────────────────────────────────────────────────────
// TerminalTab.tsx — the embedded terminal (xterm.js ↔ the workspace shell).
// READING ORDER: frontend #23
//
// WHAT IT DOES: renders an xterm.js terminal, asks the backend to spawn a shell in the
// active workspace, and connects a /pty WebSocket. Keystrokes go out as BINARY frames;
// resize goes out as a TEXT control frame; shell output comes back as bytes we write to
// xterm. This is where you run `claude` / `codex` to actually build the project.
//
// WHY the disposed/throwaway-socket dance: React 18 Strict Mode mounts→unmounts→mounts
// in dev. If we get unmounted after asking the backend for a terminal but before
// connecting, that shell would be orphaned. So on cleanup we mark `disposed`, and if the
// terminal id arrives late we briefly open+close a socket to let the backend reap it —
// no ghost shells left behind.
// ─────────────────────────────────────────────────────────────────────────────

import { FitAddon } from "@xterm/addon-fit";
import { Terminal, type ITheme } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";

import { createTerminal, ptyUrl } from "../../lib/api";
import { usePreferencesStore, type ResolvedTheme } from "../../store/preferencesStore";

// VS Code Dark+ terminal colors, matching the rest of the app.
const TERMINAL_THEMES: Record<ResolvedTheme, ITheme> = {
  dark: { background: "#1e1e1e", foreground: "#cccccc", cursor: "#cccccc", selectionBackground: "#264f78" },
  light: { background: "#ffffff", foreground: "#3b3b3b", cursor: "#3b3b3b", selectionBackground: "#add6ff" },
  gray: { background: "#262626", foreground: "#d4d4d4", cursor: "#d4d4d4", selectionBackground: "#555555" },
};

type ConnectionState = "connecting" | "open" | "closed" | "error";

interface ConnectionNotice {
  state: ConnectionState;
  message: string;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The backend could not create a terminal session.";
}

/** Turn a WebSocket close into a useful, non-technical status for the operator. */
export function terminalCloseNotice(
  close: Pick<CloseEvent, "code" | "reason">,
  connectionFailed = false,
): ConnectionNotice {
  const reason = close.reason.trim();
  if (close.code === 1000 && !connectionFailed) {
    return { state: "closed", message: reason || "Terminal session ended." };
  }
  if (reason) {
    return { state: "error", message: `Terminal connection closed: ${reason}` };
  }
  return {
    state: "error",
    message: connectionFailed
      ? "Could not connect to the terminal. Confirm the backend is running, then retry."
      : `Terminal connection closed unexpectedly (code ${close.code}).`,
  };
}

/** The Terminal tab. `active` tells us when it's the visible tab (so we can refit). */
export default function TerminalTab({
  workspaceId,
  active,
}: {
  workspaceId: string;
  active: boolean;
}) {
  const resolvedTheme = usePreferencesStore((state) => state.resolvedTheme);
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [connection, setConnection] = useState<ConnectionNotice>({
    state: "connecting",
    message: "Starting trusted terminal…",
  });

  // Build the terminal + socket once per workspace. Cleans up fully on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    setConnection({ state: "connecting", message: "Starting trusted terminal…" });

    const term = new Terminal({
      fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
      fontSize,
      theme: TERMINAL_THEMES[resolvedTheme],
      cursorBlink: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    let disposed = false;
    let socketFailed = false;
    const encoder = new TextEncoder();

    function sendResize(socket: WebSocket) {
      if (socket.readyState === WebSocket.OPEN) {
        // Resize is a TEXT frame; the backend tells them apart from keystrokes by type.
        socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    }

    createTerminal(workspaceId)
      .then(({ terminal_id }) => {
        if (disposed) {
          // Unmounted before we connected — open+close so the backend reaps the shell.
          const throwaway = new WebSocket(ptyUrl(terminal_id));
          throwaway.onopen = () => throwaway.close();
          return;
        }
        const socket = new WebSocket(ptyUrl(terminal_id));
        socket.binaryType = "arraybuffer";
        wsRef.current = socket;
        socket.onopen = () => {
          if (disposed) return;
          setConnection({ state: "open", message: "Terminal connected." });
          sendResize(socket);
        };
        socket.onmessage = (event) => term.write(new Uint8Array(event.data as ArrayBuffer));
        socket.onerror = () => {
          if (disposed) return;
          socketFailed = true;
          setConnection({
            state: "error",
            message: "Could not connect to the terminal. Confirm the backend is running, then retry.",
          });
        };
        socket.onclose = (event) => {
          if (disposed) return;
          if (wsRef.current === socket) wsRef.current = null;
          setConnection(terminalCloseNotice(event, socketFailed));
        };
        // Keystrokes → BINARY frames (raw bytes into the shell).
        term.onData((data) => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(encoder.encode(data));
          }
        });
      })
      .catch((error: unknown) => {
        if (disposed) return;
        const message = errorMessage(error);
        term.write(`\r\n[could not open terminal: ${message}]\r\n`);
        setConnection({ state: "error", message });
      });

    // Keep the PTY size in sync with the container.
    const onResize = () => {
      fit.fit();
      if (wsRef.current) sendResize(wsRef.current);
    };
    const observer = new ResizeObserver(onResize);
    observer.observe(container);

    return () => {
      disposed = true;
      observer.disconnect();
      wsRef.current?.close();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
    };
  }, [attempt, workspaceId]);

  useEffect(() => {
    if (termRef.current) termRef.current.options.theme = TERMINAL_THEMES[resolvedTheme];
  }, [resolvedTheme]);

  useEffect(() => {
    if (!termRef.current) return;
    termRef.current.options.fontSize = fontSize;
    fitRef.current?.fit();
  }, [fontSize]);

  // When this tab becomes visible again it had zero size while hidden, so refit.
  useEffect(() => {
    if (!active || !fitRef.current || !termRef.current) return;
    fitRef.current.fit();
    const socket = wsRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(
        JSON.stringify({ type: "resize", cols: termRef.current.cols, rows: termRef.current.rows }),
      );
    }
  }, [active]);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={containerRef} className="h-full w-full overflow-hidden" />
      {connection.state !== "open" && (
        <div
          className="absolute inset-x-3 top-3 z-10 flex items-center gap-3 rounded border border-line bg-sidebar px-3 py-2 text-xs text-fg shadow-lg"
          role={connection.state === "connecting" ? "status" : "alert"}
        >
          <span className="min-w-0 flex-1">{connection.message}</span>
          {connection.state !== "connecting" && (
            <button
              type="button"
              className="rounded border border-line px-2 py-1 text-fg hover:bg-line"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}
