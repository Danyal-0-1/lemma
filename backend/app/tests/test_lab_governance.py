"""Focused tests for project data-egress policy."""

import pytest

from app.lab import repo
from app.lab.governance import enforce_model_egress
from app.models import ProjectPolicy
from app.settings import Settings


def _settings(*, mock: bool, local_models: str = "") -> Settings:
    return Settings(
        _env_file=None,
        mock_llm=mock,
        LEMMA_LOCAL_MODEL_IDS=local_models,
    )


def test_mock_provider_never_counts_as_model_egress() -> None:
    policy = ProjectPolicy(project_id="project-1", data_classification="local_only")
    enforce_model_egress(
        policy,
        ["deepseek/deepseek-chat"],
        settings=_settings(mock=True),
    )


def test_local_only_requires_explicit_local_model_attestation() -> None:
    policy = ProjectPolicy(project_id="project-1", data_classification="local_only")
    settings = _settings(mock=False, local_models="ollama/research")

    enforce_model_egress(policy, ["ollama/research"], settings=settings)
    with pytest.raises(repo.LabValidationError, match="local-only policy"):
        enforce_model_egress(policy, ["deepseek/deepseek-chat"], settings=settings)


def test_confidential_project_requires_explicit_model_allowlist() -> None:
    policy = ProjectPolicy(project_id="project-1", data_classification="confidential")
    with pytest.raises(repo.LabValidationError, match="explicit model allowlist"):
        enforce_model_egress(
            policy,
            ["deepseek/deepseek-chat"],
            settings=_settings(mock=False),
        )

    policy.allowed_models = ["deepseek/deepseek-chat"]
    enforce_model_egress(
        policy,
        ["deepseek/deepseek-chat"],
        settings=_settings(mock=False),
    )


def test_unknown_classification_fails_closed() -> None:
    policy = ProjectPolicy(project_id="project-1", data_classification="legacy-unknown")
    with pytest.raises(repo.LabValidationError, match="unsupported project data classification"):
        enforce_model_egress(
            policy,
            ["deepseek/deepseek-chat"],
            settings=_settings(mock=False),
        )
