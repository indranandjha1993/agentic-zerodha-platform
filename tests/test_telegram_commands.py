from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.models import ApprovalRequest, ApprovalStatus
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
@override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="test-bot-token")
def test_telegram_pending_command_lists_requests() -> None:
    user = User.objects.create_user(
        username="tg-pending-user",
        email="tg-pending-user@example.com",
        password="test-pass",
    )
    UserProfile.objects.create(user=user, telegram_chat_id="333222")

    agent = Agent.objects.create(
        owner=user,
        name="Telegram Pending Agent",
        slug="telegram-pending-agent",
        instruction="Pending approvals command test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    ApprovalRequest.objects.create(agent=agent, requested_by=user, status=ApprovalStatus.PENDING)

    client = APIClient()
    payload = {"message": {"chat": {"id": 333222}, "text": "/pending"}}
    with patch("apps.approvals.telegram_views.TelegramClient.send_message") as mocked_send:
        response = client.post(
            "/api/v1/telegram/webhook/test-secret/",
            payload,
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "command_processed"
    mocked_send.assert_called_once()


@pytest.mark.django_db
@override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="test-bot-token")
def test_telegram_approve_command_updates_request_and_intent() -> None:
    user = User.objects.create_user(
        username="tg-approve-user",
        email="tg-approve-user@example.com",
        password="test-pass",
    )
    UserProfile.objects.create(user=user, telegram_chat_id="777111")

    agent = Agent.objects.create(
        owner=user,
        name="Telegram Approve Agent",
        slug="telegram-approve-agent",
        instruction="Approve command test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=user,
        status=ApprovalStatus.PENDING,
    )
    intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    client = APIClient()
    payload = {"message": {"chat": {"id": 777111}, "text": f"/approve {approval_request.id}"}}
    with patch(
        "apps.approvals.services.decision_engine.execute_intent_task.delay"
    ) as mocked_delay, patch("apps.approvals.telegram_views.TelegramClient.send_message"):
        response = client.post(
            "/api/v1/telegram/webhook/test-secret/",
            payload,
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "command_processed"

    approval_request.refresh_from_db()
    intent.refresh_from_db()
    assert approval_request.status == ApprovalStatus.APPROVED
    assert intent.status == IntentStatus.APPROVED
    mocked_delay.assert_called_once_with(intent.id, True)
