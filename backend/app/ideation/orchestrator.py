# ─────────────────────────────────────────────────────────────────────────────
# orchestrator.py — the ideation state machine and the human approval gate.
# READING ORDER: backend #26  (the heart of Phase 0)
#
# WHAT THIS FILE DOES:
#   Runs ONE ideation session as a sequence of steps, per round:
#       GENERATOR → RESEARCHER → CRITIC → PM → (wait for the human) → approve/change/reject
#   Each step streams a model turn over the event bus, parses its JSON into our schema
#   (retrying once on bad JSON), saves a new artifact version, and moves on. At the gate
#   it blocks on an asyncio.Event until the founder decides. A token budget and a cancel
#   flag can stop it early — gracefully, never by crashing.
#
# WHY a hand-written state machine (no framework): the flow is ~4 steps with one human
#   gate. A plain class makes every transition visible and teachable — which is the
#   whole point of this codebase. (PROMPT.md §3 explains the reasoning.)
#
# NOTE (simplification, flagged per Agreement 7): on "request changes" we re-run the
#   WHOLE round with the feedback. PROMPT.md §9 says "PM decides re-entry point"; doing
#   that would need the PM to emit a re-entry directive. We keep the simpler, readable
#   loop for now and can revisit if it ever matters.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.config import get_config
from app.cost import record_and_summarize
from app.events import event_bus
from app.ideation import repo
from app.ideation.parsing import parse_ideas, parse_pm
from app.ideation.roles import ROLE_PROMPTS
from app.ideation.schema import IdeaDoc, Spec
from app.providers.base import ChatMessage, StreamDone, TextDelta, Usage
from app.providers.factory import get_provider
from app.settings import get_settings

logger = logging.getLogger("aicompany.orchestrator")

# The ordered roles that build up the IdeaDoc before the PM writes the Spec.
_IDEA_ROLES = ("generator", "researcher", "critic")

# Appended to the user message when a role's JSON failed validation, to nudge a fix.
_FIX_TEMPLATE = (
    "\n\nYour previous response was not valid JSON for the required schema. "
    "Error:\n{error}\nReturn ONLY the corrected JSON inside one ```json fence."
)


class BudgetExceeded(Exception):
    """Raised when a session has used its token budget; stops the run gracefully."""


class RoleOutputError(Exception):
    """Raised when a role's JSON can't be parsed even after one retry."""

    def __init__(self, role: str, message: str) -> None:
        super().__init__(message)
        self.role = role
        self.message = message


@dataclass
class SessionControl:
    """The shared handle the REST endpoints use to talk to a running orchestrator.

    Exists because approve/cancel arrive as separate HTTP requests while the
    orchestrator is blocked at its gate — this is how they wake it and pass a decision.
    The registry that maps session_id → SessionControl lives in control.py.
    """

    approval: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str | None = None
    feedback: str | None = None
    cancelled: bool = False


class IdeationOrchestrator:
    """Runs one ideation session from seed to an approved (or rejected) Spec."""

    def __init__(self, session_id: str, seed: str, control: SessionControl) -> None:
        self.session_id = session_id
        self.seed = seed
        self.control = control

        settings = get_settings()
        config = get_config()
        self.provider = get_provider(settings)
        self.models = config.roles  # role name -> model string
        self._max_tokens = config.budget.max_session_tokens
        self._max_rounds = config.budget.max_rounds

        self.ideadoc = IdeaDoc(seed=seed)
        self.spec: Spec | None = None
        self.round = 0
        self._feedback: str | None = None
        self._tokens_used = 0
        self._ideadoc_version = 0
        self._spec_version = 0
        self._spec_artifact_id = 0

    # --- the public entry point ----------------------------------------------

    async def run(self) -> None:
        """Drive the whole session, translating every outcome into events + status.

        Exists as the top-level loop. It never lets an exception escape: budget,
        parse failures, and unexpected errors all become clean events + a final phase
        reset, so the server stays healthy no matter what a model returns.
        """
        self._emit("phase_changed", {"phase": "ideation"})
        await asyncio.to_thread(repo.create_session, self.session_id, self.seed[:60], self.seed)
        await self._save_ideadoc()  # version 1: just the seed

        try:
            while not self.control.cancelled:
                self.round += 1
                await asyncio.to_thread(repo.set_status, self.session_id, "running", self.round)
                await self._run_crew_round()
                if await self._await_gate() == "stop":
                    break
        except BudgetExceeded:
            self._emit("budget_exceeded", {"limit": self._max_tokens, "used": self._tokens_used})
            await asyncio.to_thread(repo.set_status, self.session_id, "budget_stopped")
        except RoleOutputError as error:
            # Don't crash on a model that won't produce valid JSON — report and stop.
            self._emit_error(f"orchestrator:{error.role}", error.message, recoverable=False)
        except Exception as error:  # noqa: BLE001 — last-resort guard; the server must survive
            logger.exception("orchestrator %s crashed", self.session_id)
            self._emit_error("orchestrator", str(error), recoverable=False)
        finally:
            self._emit("phase_changed", {"phase": "idle"})

    # --- one round of the crew -----------------------------------------------

    async def _run_crew_round(self) -> None:
        """Run Generator → Researcher → Critic → PM, saving artifacts as it goes."""
        for role in _IDEA_ROLES:
            self.ideadoc.ideas = await self._stream_role(role, parse_ideas)
            await self._save_ideadoc()

        pm_output = await self._stream_role("pm", parse_pm)
        self.ideadoc.decision_rationale = pm_output.decision_rationale
        self.ideadoc.chosen_idea = pm_output.chosen_idea
        await self._save_ideadoc()

        self.spec = pm_output.spec
        await self._save_spec()

        # Feedback (if any) applied to this round is now spent; clear it.
        self._feedback = None

    async def _stream_role(self, role: str, parser: Callable[[str], Any]) -> Any:
        """Stream one role's turn and parse it, retrying once on invalid JSON."""
        self._check_budget()

        user = self._build_user_message()
        text = await self._emit_turn(role, user)
        try:
            return parser(text)
        except (ValidationError, ValueError) as first_error:
            logger.warning("%s produced invalid JSON; retrying once", role)
            retry_user = user + _FIX_TEMPLATE.format(error=first_error)
            text = await self._emit_turn(role, retry_user)
            try:
                return parser(text)
            except (ValidationError, ValueError) as second_error:
                raise RoleOutputError(role, str(second_error)) from second_error

    async def _emit_turn(self, role: str, user_content: str) -> str:
        """Stream one model turn: emit turn/token/completed events, bill it, persist it.

        Returns the full text so the caller can parse it. This is the single place a
        model is actually called during ideation.
        """
        self._emit("agent_turn_started", {"role": role, "round": self.round})
        messages = [
            ChatMessage(role="system", content=ROLE_PROMPTS[role]),
            ChatMessage(role="user", content=user_content),
        ]

        parts: list[str] = []
        usage = Usage()
        async for event in self.provider.stream_chat(self.models[role], messages):
            if isinstance(event, TextDelta):
                parts.append(event.text)
                self._emit("token_stream", {"role": role, "text": event.text})
            elif isinstance(event, StreamDone):
                usage = event.usage

        text = "".join(parts)
        self._emit(
            "agent_turn_completed",
            {
                "role": role,
                "round": self.round,
                "usage": {"in": usage.tokens_in, "out": usage.tokens_out},
            },
        )
        await asyncio.to_thread(
            repo.add_message, self.session_id, role, text, usage.tokens_in, usage.tokens_out
        )
        model = self.models[role]
        cost_payload = await asyncio.to_thread(record_and_summarize, self.session_id, model, usage)
        self._emit("cost_update", cost_payload)
        self._tokens_used += usage.tokens_in + usage.tokens_out
        return text

    # --- the human gate ------------------------------------------------------

    async def _await_gate(self) -> str:
        """Block until the founder decides. Return "stop" (done) or "continue" (redo).

        Handles approve/reject/cancel, and "request changes": another round if rounds
        remain, otherwise a note asking to approve or reject (we don't loop forever).
        """
        question = "Approve this Spec, request changes, or reject?"
        while True:
            await asyncio.to_thread(
                repo.set_status, self.session_id, "awaiting_approval", self.round
            )
            self._emit(
                "awaiting_approval",
                {"artifact_id": self._spec_artifact_id, "question": question},
            )

            await self.control.approval.wait()
            self.control.approval.clear()  # reset for a possible next gate

            if self.control.cancelled:
                return await self._finish("cancelled", "cancelled")

            decision = self.control.decision or ""
            feedback = self.control.feedback
            self._emit(
                "approval_resolved",
                {"artifact_id": self._spec_artifact_id, "decision": decision, "feedback": feedback},
            )

            if decision == "approve":
                return await self._finish("approve", "approved")
            if decision == "reject":
                return await self._finish("reject", "rejected")

            # decision == "changes"
            if self.round >= self._max_rounds:
                note = f"Reached the maximum of {self._max_rounds} rounds — approve or reject."
                self._emit_error("orchestrator", note, recoverable=True)
                continue  # stay at the gate; only approve/reject will end it now
            self._feedback = feedback
            return "continue"

    async def _finish(self, decision: str, status: str) -> str:
        """Record the terminal status for a decision and signal the loop to stop."""
        logger.info("session %s ended: %s", self.session_id, status)
        await asyncio.to_thread(repo.set_status, self.session_id, status)
        return "stop"

    # --- helpers -------------------------------------------------------------

    def _check_budget(self) -> None:
        """Raise BudgetExceeded if the session has spent its token allowance."""
        if self._tokens_used >= self._max_tokens:
            raise BudgetExceeded

    def _build_user_message(self) -> str:
        """Build the user message: the current IdeaDoc JSON plus any founder feedback."""
        parts = ["Current Idea Document (JSON):", self.ideadoc.model_dump_json(indent=2)]
        if self._feedback:
            parts.append("\nFounder feedback to address:\n" + self._feedback)
        return "\n".join(parts)

    async def _save_ideadoc(self) -> None:
        """Persist a new IdeaDoc version and emit an artifact event."""
        self._ideadoc_version += 1
        content_json = self.ideadoc.model_dump_json()
        artifact_id = await asyncio.to_thread(
            repo.add_artifact, self.session_id, "ideadoc", self._ideadoc_version, content_json
        )
        content = self.ideadoc.model_dump()
        self._emit_artifact(artifact_id, "ideadoc", self._ideadoc_version, content)

    async def _save_spec(self) -> None:
        """Persist a new Spec version, remember its id for the gate, and emit it."""
        assert self.spec is not None
        self._spec_version += 1
        content_json = self.spec.model_dump_json()
        self._spec_artifact_id = await asyncio.to_thread(
            repo.add_artifact, self.session_id, "spec", self._spec_version, content_json
        )
        content = self.spec.model_dump()
        self._emit_artifact(self._spec_artifact_id, "spec", self._spec_version, content)

    def _emit_artifact(self, artifact_id: int, kind: str, version: int, content: dict) -> None:
        """Emit artifact_created for the first version of a kind, else artifact_updated."""
        name = "artifact_created" if version == 1 else "artifact_updated"
        payload = {"artifact_id": artifact_id, "kind": kind, "version": version, "content": content}
        self._emit(name, payload)

    def _emit_error(self, where: str, message: str, *, recoverable: bool) -> None:
        """Publish an `error` event — a graceful failure the UI can show as a note."""
        self._emit("error", {"where": where, "message": message, "recoverable": recoverable})

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """Publish an event tagged with this session's id."""
        event_bus.publish(event, payload, self.session_id)
