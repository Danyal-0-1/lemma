# ─────────────────────────────────────────────────────────────────────────────
# ws.py — the /ws transport: turn bus events into WebSocket frames for one client.
# READING ORDER: backend #8
#
# WHAT THIS FILE DOES:
#   Handles a single browser's /ws connection. It subscribes to the EventBus, sends
#   a `hello`, then runs three things at once:
#     1. a PUMP that forwards every bus event to this socket,
#     2. a HEARTBEAT every 20s so idle connections stay alive and detectable,
#     3. a READ loop whose only job is to notice when the client disconnects.
#
# HOW IT FITS: this is the ONLY place that touches WebSockets on the outbound path.
#   Everything else just calls event_bus.publish(); ws.py delivers.
#
# WHY three concurrent tasks: sending and "watching for disconnect" must happen
#   simultaneously. asyncio lets us run them as tasks and cancel the others the
#   instant one finishes (e.g. the client drops).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.events import EventBus, Sequencer

logger = logging.getLogger("aicompany.ws")

# The protocol's keepalive cadence (PROMPT.md §7: heartbeat every 20s).
HEARTBEAT_SECONDS = 20


async def _pump(sequencer: Sequencer, queue: asyncio.Queue) -> None:
    """Forward every event from the bus queue to this socket, forever.

    Exists as the outbound path: it blocks on the queue and, whenever a subsystem
    publishes, stamps the event with the next seq and sends it. Cancelled when the
    connection ends.
    """
    while True:
        event = await queue.get()
        await sequencer.emit_event(event)


async def _heartbeat(sequencer: Sequencer) -> None:
    """Emit a `heartbeat` event every HEARTBEAT_SECONDS, forever.

    Exists so a connection with no activity still produces traffic — this keeps
    proxies from timing the socket out and lets the client tell "quiet" from "dead".
    """
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await sequencer.emit("heartbeat", {})


async def connect_websocket(ws: WebSocket, bus: EventBus, server_version: str) -> None:
    """Serve one /ws connection from accept to disconnect.

    Exists as the lifecycle for a single client: accept, subscribe, greet with
    `hello`, run pump+heartbeat, and — crucially — always unsubscribe and cancel
    the helper tasks in `finally` so a dropped client leaks nothing.
    """
    await ws.accept()
    queue = bus.subscribe()
    sequencer = Sequencer(ws.send_text)

    # Greet the client so it knows which backend it reached (used by the UI's hello).
    await sequencer.emit("hello", {"server_version": server_version, "active_session": None})

    pump_task = asyncio.create_task(_pump(sequencer, queue))
    heartbeat_task = asyncio.create_task(_heartbeat(sequencer))

    try:
        # We don't expect the client to send anything, but we must keep reading so
        # the disconnect actually surfaces (as WebSocketDisconnect) instead of hanging.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("client disconnected from /ws")
    finally:
        # Order matters: stop feeding the (now dead) socket, then drop the subscription.
        pump_task.cancel()
        heartbeat_task.cancel()
        bus.unsubscribe(queue)
