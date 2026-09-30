// ─────────────────────────────────────────────────────────────────────────────
// ws.ts — the WebSocket client: stay connected, detect gaps, survive Strict Mode.
// READING ORDER: frontend #11
//
// WHAT THIS FILE DOES: opens the /ws event stream and keeps it open. If the
// connection drops it reconnects with exponential backoff (1s → 2s → 4s … capped
// at 15s). It also watches `seq` for gaps and warns in the console — a small habit
// that teaches you to think about protocol reliability.
//
// WHY a class (not a hook): the reconnect logic is plain state that outlives any one
// render. The React seam is a single useEffect in App.tsx that constructs one of
// these and calls close() on cleanup. That cleanup is what makes it survive React 18
// Strict Mode, which deliberately mounts → unmounts → mounts components in dev: each
// cycle fully closes its socket, so we never leak a second "ghost" connection.
// ─────────────────────────────────────────────────────────────────────────────

import type { Event } from "./events";

/** Connection states the UI cares about (drives the status-bar dot). */
export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

/** Callbacks the socket reports back to (wired to the store in App.tsx). */
interface Handlers {
  onStatus: (status: ConnectionStatus) => void;
  onEvent: (event: Event) => void;
}

// Backoff schedule: start at 1s, double each attempt, never wait more than 15s.
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 15000;
const MAX_EVENT_CHARS = 5_000_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate untrusted socket JSON before any store reads fields from it. */
function parseEvent(data: unknown): Event | null {
  if (typeof data !== "string" || data.length > MAX_EVENT_CHARS) return null;
  try {
    const value: unknown = JSON.parse(data);
    if (!isRecord(value) || !isRecord(value.payload)) return null;
    if (value.v !== 1 || !Number.isSafeInteger(value.seq) || Number(value.seq) < 1) return null;
    if (typeof value.ts !== "string" || typeof value.event !== "string") return null;
    if (value.event.length === 0 || value.event.length > 120) return null;
    if (value.session_id !== null && typeof value.session_id !== "string") return null;
    return value as unknown as Event;
  } catch {
    return null;
  }
}

export class EventSocket {
  private ws: WebSocket | null = null;
  // True once close() is called, so pending reconnects and onclose handlers stop.
  private stopped = false;
  // How many reconnects we've attempted in a row (resets to 0 on a successful open).
  private attempt = 0;
  // The last seq we saw on THIS connection; resets to 0 each time we (re)connect,
  // because seq is per-connection on the server.
  private lastSeq = 0;
  private reconnectTimer: number | undefined;

  constructor(
    private readonly url: string,
    private readonly handlers: Handlers,
  ) {}

  /** Open the connection and begin auto-managing it. Call once, after construction. */
  connect(): void {
    this.stopped = false;
    this.open();
  }

  /** Open a single WebSocket and attach its lifecycle handlers. */
  private open(): void {
    this.handlers.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      // Fresh connection: reset the backoff and the per-connection seq counter.
      this.attempt = 0;
      this.lastSeq = 0;
      this.handlers.onStatus("open");
    };

    ws.onmessage = (message: MessageEvent<unknown>) => {
      const event = parseEvent(message.data);
      if (event === null) {
        console.warn("[ws] ignored malformed event frame");
        return;
      }
      // Gap detection: after the first message, each seq should be exactly +1.
      // A gap means we dropped a frame — worth a warning while learning the protocol.
      if (this.lastSeq !== 0 && event.seq !== this.lastSeq + 1) {
        console.warn(`[ws] seq gap: expected ${this.lastSeq + 1}, got ${event.seq}`);
      }
      this.lastSeq = event.seq;
      this.handlers.onEvent(event);
    };

    // onerror is followed by onclose; closing here funnels both into one reconnect path.
    ws.onerror = () => ws.close();

    ws.onclose = () => {
      // If close() was called intentionally, do nothing — this is a clean shutdown.
      if (!this.stopped) {
        this.scheduleReconnect();
      }
    };
  }

  /** Wait (with growing backoff) then try to open again. */
  private scheduleReconnect(): void {
    this.handlers.onStatus("reconnecting");
    const delay = Math.min(BASE_DELAY_MS * 2 ** this.attempt, MAX_DELAY_MS);
    this.attempt += 1;
    this.reconnectTimer = window.setTimeout(() => this.open(), delay);
  }

  /** Close for good and cancel any pending reconnect. Safe to call anytime. */
  close(): void {
    this.stopped = true;
    if (this.reconnectTimer !== undefined) {
      clearTimeout(this.reconnectTimer);
    }
    this.handlers.onStatus("closed");
    if (this.ws) {
      // Detach onclose FIRST so this deliberate close doesn't trigger a reconnect.
      this.ws.onclose = null;
      this.ws.close();
    }
  }
}
