# ─────────────────────────────────────────────────────────────────────────────
# test_events.py — prove the event pipe's three guarantees.
# READING ORDER: backend #10  (teaches: testing async code + fakes)
#
# We test three things, because they are the three promises the pipe makes:
#   1. an Event serializes to the exact envelope shape the client parses,
#   2. the EventBus delivers every published event to every subscriber (fan-out),
#   3. the Sequencer numbers outgoing frames 1, 2, 3… (monotonic, no gaps).
#
# Note the FakeSocket: we don't need a real WebSocket to test sequencing — we just
# need something with an async send_text that records what it was given. This is the
# "test against a small fake, not the whole world" habit worth learning.
# ─────────────────────────────────────────────────────────────────────────────

import json

from app.events import Event, EventBus, Sequencer


def test_event_serializes_to_expected_envelope() -> None:
    """An Event dumps to JSON containing exactly the documented envelope fields."""
    event = Event(seq=7, session_id="ideation_abc", event="token_stream", payload={"text": "hi"})

    parsed = json.loads(event.model_dump_json())

    assert parsed["v"] == 1
    assert parsed["seq"] == 7
    assert parsed["session_id"] == "ideation_abc"
    assert parsed["event"] == "token_stream"
    assert parsed["payload"] == {"text": "hi"}
    # ts is auto-filled and formatted as UTC with a 'Z' suffix.
    assert parsed["ts"].endswith("Z")


def test_bus_fans_out_to_every_subscriber() -> None:
    """publish() delivers the same event to all current subscribers.

    This is the property the whole architecture leans on: one publish, N clients.
    """
    bus = EventBus()
    first = bus.subscribe()
    second = bus.subscribe()

    bus.publish("phase_changed", {"phase": "ideation"}, session_id="s1")

    a = first.get_nowait()
    b = second.get_nowait()
    assert a.event == "phase_changed"
    assert b.event == "phase_changed"
    assert a.payload == {"phase": "ideation"}


def test_unsubscribe_stops_delivery() -> None:
    """After unsubscribe(), a queue receives no further events (no leak, no ghost)."""
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)

    bus.publish("heartbeat", {})

    assert queue.empty()


class FakeSocket:
    """A stand-in for a WebSocket that just records every frame sent to it.

    Exists so we can test the Sequencer's numbering without opening a real socket.
    """

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


async def test_sequencer_assigns_monotonic_seq() -> None:
    """The Sequencer stamps 1, 2, 3… across both emit() and emit_event() sends."""
    socket = FakeSocket()
    sequencer = Sequencer(socket.send_text)

    await sequencer.emit("hello", {"server_version": "test"})
    await sequencer.emit_event(Event(event="token_stream", payload={"text": "a"}))
    await sequencer.emit("heartbeat", {})

    seqs = [json.loads(frame)["seq"] for frame in socket.sent]
    assert seqs == [1, 2, 3]
