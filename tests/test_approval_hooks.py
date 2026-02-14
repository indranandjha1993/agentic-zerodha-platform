from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.models import ApprovalRequest, ApprovalStatus
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
def test_approval_decision_approve_marks_intent_and_dispatches_execution() -> None:
    user = User.objects.create_user(
        username="carol",
        email="carol@example.com",
        password="test-pass",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    agent = Agent.objects.create(
        owner=user,
        name="Momentum Agent",
        slug="momentum-agent",
        instruction="Trade on breakout momentum.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(agent=agent, requested_by=user)
    intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    with patch("apps.approvals.services.decision_engine.execute_intent_task.delay") as mocked_delay:
        response = client.post(
            f"/api/v1/approval-requests/{approval_request.id}/decide/",
            {"decision": "approve", "channel": "dashboard", "reason": "Looks good."},
            format="json",
        )

    assert response.status_code == 200
    approval_request.refresh_from_db()
    intent.refresh_from_db()

    assert approval_request.status == ApprovalStatus.APPROVED
    assert intent.status == IntentStatus.APPROVED
    mocked_delay.assert_called_once_with(intent.id, True)


@pytest.mark.django_db
def test_approval_decision_reject_marks_intent_rejected() -> None:
    user = User.objects.create_user(
        username="dave",
        email="dave@example.com",
        password="test-pass",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    agent = Agent.objects.create(
        owner=user,
        name="Reversion Agent",
        slug="reversion-agent",
        instruction="Trade mean reversion.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(agent=agent, requested_by=user)
    intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="TCS",
        side=Side.SELL,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    with patch("apps.approvals.services.decision_engine.execute_intent_task.delay") as mocked_delay:
        response = client.post(
            f"/api/v1/approval-requests/{approval_request.id}/decide/",
            {"decision": "reject", "channel": "dashboard", "reason": "Risk too high."},
            format="json",
        )

    assert response.status_code == 200
    approval_request.refresh_from_db()
    intent.refresh_from_db()

    assert approval_request.status == ApprovalStatus.REJECTED
    assert intent.status == IntentStatus.REJECTED
    assert intent.failure_reason == "Risk too high."
    mocked_delay.assert_not_called()
