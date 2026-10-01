"""Bounded multi-model evaluation runner with durable candidates and provenance."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.cost import estimate_usd, record_and_summarize
from app.events import event_bus
from app.lab import repo, workflows
from app.models import EvaluationCandidate, EvaluationExperiment, ProjectPolicy
from app.providers.base import ChatMessage, ModelProvider, StreamDone, TextDelta, Usage
from app.providers.factory import get_provider
from app.settings import get_settings

logger = logging.getLogger("aicompany.lab.evaluation")
MAX_EVALUATION_OUTPUT_CHARS = 200_000


class EvaluationRunner:
    """Execute comparison candidates in the background and make cancellation durable."""

    def __init__(self, provider: ModelProvider | None = None) -> None:
        self._provided_provider = provider
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._guard = asyncio.Lock()

    def _provider(self) -> ModelProvider:
        return self._provided_provider or get_provider(get_settings())

    async def start(self, experiment_id: str) -> EvaluationExperiment:
        async with self._guard:
            existing = self._tasks.get(experiment_id)
            if existing is not None and not existing.done():
                raise repo.LabConflictError("evaluation is already running")
            experiment, _, _ = await asyncio.to_thread(workflows.get_evaluation, experiment_id)
            policy = await asyncio.to_thread(
                workflows.assert_run_allowed,
                experiment.project_id,
                experiment.models,
            )
            experiment, candidates = await asyncio.to_thread(
                workflows.mark_evaluation_running, experiment_id
            )
            task = asyncio.create_task(self._execute(experiment, candidates, policy))
            self._tasks[experiment.id] = task
            task.add_done_callback(lambda _task: self._tasks.pop(experiment.id, None))
            return experiment

    async def cancel(self, experiment_id: str) -> EvaluationExperiment:
        task = self._tasks.get(experiment_id)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return await asyncio.to_thread(workflows.cancel_evaluation, experiment_id)

    async def shutdown(self) -> None:
        ids = list(self._tasks)
        await asyncio.gather(*(self.cancel(item) for item in ids), return_exceptions=True)

    @staticmethod
    def _emit(experiment: EvaluationExperiment, name: str, payload: dict[str, Any]) -> None:
        event_bus.publish(
            name,
            {"experiment_id": experiment.id, "project_id": experiment.project_id, **payload},
            experiment.project_id,
        )

    async def _candidate(
        self,
        experiment: EvaluationExperiment,
        candidate: EvaluationCandidate,
        policy: ProjectPolicy,
    ) -> None:
        await asyncio.to_thread(workflows.mark_evaluation_candidate_running, candidate.id)
        system_prompt = (
            "You are one candidate in a controlled model evaluation. Answer the supplied "
            "prompt directly. Do not claim tools, browsing, files, or evidence that were "
            "not supplied. Make uncertainties explicit."
        )
        user_prompt = experiment.prompt
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ]
        approximate_input = sum(max(1, len(message.content) // 4) for message in messages)
        remaining = policy.max_run_tokens - approximate_input
        if remaining < 128:
            raise repo.LabValidationError("evaluation prompt exceeds the token budget")
        call = await asyncio.to_thread(
            workflows.begin_model_call,
            project_id=experiment.project_id,
            run_id=None,
            agent_id=None,
            stage="evaluation_candidate",
            model=candidate.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            policy=policy,
        )
        started = time.monotonic()
        parts: list[str] = []
        chars = 0
        usage = Usage()
        try:
            async for event in self._provider().stream_chat(
                candidate.model,
                messages,
                max_output_tokens=min(8_192, remaining),
            ):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    chars += len(event.text)
                    if chars > MAX_EVALUATION_OUTPUT_CHARS:
                        raise RuntimeError("evaluation response exceeded the output limit")
                    self._emit(
                        experiment,
                        "lab_evaluation_token",
                        {
                            "candidate_id": candidate.id,
                            "model": candidate.model,
                            "text": event.text,
                        },
                    )
                elif isinstance(event, StreamDone):
                    usage = event.usage
        except asyncio.CancelledError:
            await asyncio.to_thread(
                workflows.finish_model_call,
                call.id,
                status="cancelled",
                latency_ms=int((time.monotonic() - started) * 1_000),
            )
            raise
        except Exception as error:
            await asyncio.to_thread(
                workflows.finish_model_call,
                call.id,
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1_000),
                error=type(error).__name__,
            )
            raise
        response = "".join(parts)
        if not response.strip():
            usd = estimate_usd(candidate.model, usage)
            await asyncio.to_thread(
                workflows.finish_model_call,
                call.id,
                status="failed",
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                usd=usd,
                latency_ms=int((time.monotonic() - started) * 1_000),
                error="empty response",
            )
            raise RuntimeError("model returned an empty evaluation response")
        usd = estimate_usd(candidate.model, usage)
        elapsed_ms = int((time.monotonic() - started) * 1_000)
        await asyncio.to_thread(
            workflows.finish_model_call,
            call.id,
            status="completed",
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            usd=usd,
            latency_ms=elapsed_ms,
        )
        if usage.tokens_in + usage.tokens_out > policy.max_run_tokens or usd > policy.max_run_usd:
            raise repo.LabValidationError("evaluation candidate exceeded the project budget")
        _, project_usd = await asyncio.to_thread(
            workflows.model_call_totals, project_id=experiment.project_id
        )
        if project_usd > policy.max_project_usd:
            raise repo.LabValidationError("project exceeded its configured spend limit")
        await asyncio.to_thread(
            workflows.complete_evaluation_candidate,
            candidate.id,
            response,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            usd=usd,
            latency_ms=elapsed_ms,
        )
        await asyncio.to_thread(
            record_and_summarize,
            f"evaluation:{experiment.id}",
            candidate.model,
            usage,
        )
        self._emit(
            experiment,
            "lab_evaluation_candidate_completed",
            {"candidate_id": candidate.id, "model": candidate.model},
        )

    async def _execute(
        self,
        experiment: EvaluationExperiment,
        candidates: list[EvaluationCandidate],
        policy: ProjectPolicy,
    ) -> None:
        self._emit(experiment, "lab_evaluation_started", {"models": experiment.models})
        try:
            # Sequential execution is deliberate: it makes cancellation immediate and
            # avoids multiplying provider spend when a project uses several remote models.
            for candidate in candidates:
                try:
                    await self._candidate(experiment, candidate, policy)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - each candidate is isolated
                    logger.exception(
                        "evaluation %s candidate %s failed", experiment.id, candidate.id
                    )
                    await asyncio.to_thread(
                        workflows.fail_evaluation_candidate,
                        candidate.id,
                        "model evaluation failed; review local server logs",
                    )
                    self._emit(
                        experiment,
                        "lab_evaluation_candidate_failed",
                        {"candidate_id": candidate.id, "model": candidate.model},
                    )
            final = await asyncio.to_thread(workflows.finish_evaluation, experiment.id)
            self._emit(experiment, f"lab_evaluation_{final.status}", {})
        except asyncio.CancelledError:
            await asyncio.to_thread(workflows.cancel_evaluation, experiment.id)
            self._emit(experiment, "lab_evaluation_cancelled", {})
            raise


evaluation_runner = EvaluationRunner()
