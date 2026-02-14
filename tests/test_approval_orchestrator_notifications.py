from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.services.orchestrator import ApprovalOrchestrator
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
def test_orchestrator_dispatches_telegram_notification_task() -> None:
    user = User.objects.create_user(
        username="grace",
        email="grace@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=user,
        name="Notify Agent",
        slug="notify-agent",
        instruction="Need telegram approval ping.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        config={"approval_channels": ["telegram"]},
        is_auto_enabled=True,
    )
    intent = TradeIntent.objects.create(
        agent=agent,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.DRAFT,
        request_payload={"source": "unit_test"},
    )

    orchestrator = ApprovalOrchestrator()
    with patch("apps.approvals.tasks.notify_approval_request_task.delay") as mocked_delay:
        approval_request = orchestrator.create_request(intent=intent, risk_score=88)

    mocked_delay.assert_called_once_with(approval_request.id)
