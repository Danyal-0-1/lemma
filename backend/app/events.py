# ─────────────────────────────────────────────────────────────────────────────
# events.py — the event pipe: one envelope shape + one in-process pub/sub bus.
# READING ORDER: backend #7  ← RETYPE THIS (M1)
#
# WHAT THIS FILE DOES:
#   Defines the single message shape (`Event`) that EVERYTHING the UI streams
#   travels in, and the `EventBus` that subsystems publish to. The /ws endpoint
#   (see ws.py) subscribes to the bus and fans messages out to the browser.
#
# HOW IT FITS (the whole point of the architecture):
#   Instead of every feature knowing about WebSockets, features just call
#   `event_bus.publish(...)`. The transport layer (ws.py) is the only code that
#   touches sockets. This decoupling is why the orchestrator, workspaces, and
#   checks can all stream to the UI without importing each other.
#
#   subsystem ──publish──▶ EventBus ──queue──▶ /ws connection ──send──▶ browser
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("aicompany.events")

# How big a per-connection queue may grow before we assume the client is too slow
# and start dropping (rather than ballooning memory forever).
MAX_QUEUE = 1000


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string ending in 'Z'.

    Exists so every event carries a consistent, millisecond-precision timestamp in
    the exact format the protocol documents (e.g. "2026-07-21T18:04:11.532Z").
    """
    # isoformat() gives "+00:00" for UTC; the protocol uses the shorter "Z" suffix.
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Event(BaseModel):
    """One message on the wire — the envelope every /ws frame uses.

    Exists so the client can parse ANY event with one shape: read `event` to know
    what happened and `payload` for the details. `seq` and `ts` are protocol
    plumbing (ordering + timing); see the field notes below.
    """

    # Protocol version — lets us evolve the envelope later without guessing.
    v: int = 1
    # Per-CONNECTION monotonic counter. Assigned by the Sequencer at send time, NOT
    # here, because two browsers connected at once each get their own 1,2,3… stream.
    seq: int = 0
    # When the event happened (set at publish, so it reflects the real moment).
    ts: str = Field(default_factory=now_iso)
    # Which ideation/build session this belongs to (None for connection-level events).
    session_id: str | None = None
    # The event name — e.g. "token_stream", "phase_changed". See PROMPT.md §7.
    event: str
    # Event-specific data. Kept as a free dict so new events need no envelope changes.
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBus:
    """In-process publish/subscribe hub. Every subsystem publishes; /ws subscribes.

    Exists to decouple "something happened" from "send it over a socket". It is a
    plain in-memory bus because this app is a single local process — no Redis, no
    network broker needed (that would be complexity with no payoff here).
    """

    def __init__(self) -> None:
        # One asyncio.Queue per connected client. A set gives O(1) add/remove.
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def subscribe(self) -> asyncio.Queue[Event]:
        """Register a new subscriber and return its queue.

        Exists so a /ws connection can start receiving events. The caller MUST call
        unsubscribe() when done (ws.py does this in a finally block) or the queue
        leaks and we keep trying to feed a dead client.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        """Remove a subscriber's queue. Safe to call even if already removed."""
        self._subscribers.discard(queue)

    def publish(self, event: str, payload: dict[str, Any], session_id: str | None = None) -> None:
        """Send one event to every current subscriber. Synchronous by design.

        Exists as the ONE method the rest of the backend calls to talk to the UI.
        It's sync (no await) so any code — even non-async — can fire an event without
        ceremony; delivery to sockets happens later, on each connection's own task.
        """
        envelope = Event(session_id=session_id, event=event, payload=payload)
        # Iterate over a snapshot (list(...)) so a subscriber unsubscribing mid-loop
        # can't corrupt the set we're walking.
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # A client too slow to drain 1000 queued events is treated as gone-ish;
                # we drop rather than block the publisher (which would stall the app).
                logger.warning("dropping event %r: a subscriber queue is full", event)


class Sequencer:
    """Wraps one WebSocket and stamps each outgoing frame with a monotonic seq.

    Exists because `seq` is per-connection: this object owns the counter for ONE
    socket and serializes sends behind a lock, so heartbeats and streamed events
    can never interleave into a garbled frame or reuse a number.
    """

    def __init__(self, send_text: Any) -> None:
        # `send_text` is any async callable taking a str (WebSocket.send_text in prod,
        # a fake in tests) — this keeps the Sequencer testable without a real socket.
        self._send_text = send_text
        self._seq = 0
        # One send at a time: guarantees seq increments and writes stay ordered even
        # when the pump task and the heartbeat task both try to send at once.
        self._lock = asyncio.Lock()

    async def emit_event(self, event: Event) -> None:
        """Assign the next seq to `event` and send it as JSON over the socket."""
        async with self._lock:
            self._seq += 1
            # model_copy makes a numbered copy without mutating the shared bus object
            # (the same Event instance may sit in several connections' queues).
            numbered = event.model_copy(update={"seq": self._seq})
            await self._send_text(numbered.model_dump_json())

    async def emit(self, name: str, payload: dict[str, Any], session_id: str | None = None) -> None:
        """Build a fresh Event and send it — used for connection-local events.

        Exists for events a single connection originates itself (hello, heartbeat),
        as opposed to events relayed from the bus via emit_event().
        """
        await self.emit_event(Event(event=name, payload=payload, session_id=session_id))


# The one shared bus for this process. A module-level singleton is the right call
# here: there is exactly one backend process, and every subsystem imports THIS bus
# so they all publish to the same place.
event_bus = EventBus()
