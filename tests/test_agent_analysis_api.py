from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.credentials.services.manager import LlmCredentialService

User = get_user_model()


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_agent_analyze_endpoint_returns_analysis_payload() -> None:
    owner = User.objects.create_user(
        username="analysis-owner",
        email="analysis-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Research Agent",
        slug="research-agent",
        instruction="Analyze market and company context.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    llm_service = LlmCredentialService()
    llm_service.create_for_user(
        user=owner,
        payload={
            "provider": "openrouter",
            "api_key": "test-openrouter-key",
            "default_model": "openai/gpt-4o-mini",
            "is_active": True,
        },
    )

    client = APIClient()
    client.force_authenticate(owner)
    with patch(
        "apps.agents.services.openrouter_market_analyst.OpenRouterMarketAnalyst.analyze"
    ) as mocked_analyze:
        mocked_analyze.return_value = {
            "status": "ok",
            "model": "openai/gpt-4o-mini",
            "analysis": "Mocked analysis",
            "tool_trace": [],
            "usage": {},
            "steps_executed": 0,
        }
        response = client.post(
            f"/api/v1/agents/{agent.id}/analyze/",
            {"query": "Analyze Infosys outlook for next quarter."},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["analysis"] == "Mocked analysis"
    mocked_analyze.assert_called_once()


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_agent_analyze_endpoint_requires_openrouter_credential() -> None:
    owner = User.objects.create_user(
        username="analysis-missing-cred",
        email="analysis-missing-cred@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="No Key Agent",
        slug="no-key-agent",
        instruction="Needs credential.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )

    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(
        f"/api/v1/agents/{agent.id}/analyze/",
        {"query": "Analyze TCS fundamentals."},
        format="json",
    )

    assert response.status_code == 400
    assert "No active OpenRouter credential" in response.json()["detail"]
