"""Enforce whether project content may be sent to configured model providers."""

from __future__ import annotations

from collections.abc import Iterable

from app.lab import repo
from app.models import ProjectPolicy
from app.settings import Settings, get_settings


def _model_set(models: Iterable[str]) -> set[str]:
    return {model.strip() for model in models if model.strip()}


def enforce_model_egress(
    policy: ProjectPolicy,
    models: Iterable[str],
    *,
    settings: Settings | None = None,
) -> None:
    """Fail closed when a project's classification does not permit model egress.

    Model identifiers alone cannot prove that an OpenAI-compatible endpoint is local,
    so local models must be explicitly declared by the operator. Mock mode is entirely
    in-process and therefore never sends project content over the network.
    """
    selected = _model_set(models)
    configured = settings or get_settings()
    if configured.mock_llm:
        return

    classification = str(policy.data_classification)
    if classification == "local_only":
        remote = sorted(selected - configured.local_models())
        if remote:
            raise repo.LabValidationError(
                "local-only policy blocks remote model egress: "
                f"{', '.join(remote)}; configure verified local IDs in "
                "LEMMA_LOCAL_MODEL_IDS or explicitly change the project classification"
            )
    elif classification == "confidential" and not policy.allowed_models:
        raise repo.LabValidationError(
            "confidential projects require an explicit model allowlist before content egress"
        )
    elif classification not in {"confidential", "public"}:
        raise repo.LabValidationError(
            f"unsupported project data classification blocks model egress: {classification}"
        )
