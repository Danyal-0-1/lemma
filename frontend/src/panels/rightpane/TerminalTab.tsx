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
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef } from "react";

import { createTerminal, ptyUrl } from "../../lib/api";

// VS Code Dark+ terminal colors, matching the rest of the app.
const TERMINAL_THEME = {
  background: "#1e1e1e",
  foreground: "#cccccc",
  cursor: "#cccccc",
  selectionBackground: "#264f78",
};

/** The Terminal tab. `active` tells us when it's the visible tab (so we can refit). */
export default function TerminalTab({
  workspaceId,
  active,
}: {
  workspaceId: string;
  active: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Build the terminal + socket once per workspace. Cleans up fully on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const term = new Terminal({
      fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
      fontSize: 13,
      theme: TERMINAL_THEME,
      cursorBlink: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    let disposed = false;
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
        socket.onopen = () => sendResize(socket);
        socket.onmessage = (event) => term.write(new Uint8Array(event.data as ArrayBuffer));
        // Keystrokes → BINARY frames (raw bytes into the shell).
        term.onData((data) => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(encoder.encode(data));
          }
        });
      })
      .catch((error) => term.write(`\r\n[could not open terminal: ${error}]\r\n`));

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
  }, [workspaceId]);

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

  return <div ref={containerRef} className="h-full w-full overflow-hidden" />;
}
