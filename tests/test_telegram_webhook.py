from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.models import ApprovalRequest, ApprovalStatus, TelegramCallbackEvent
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
@override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="test-bot-token")
def test_telegram_webhook_approves_request_and_dispatches_execution() -> None:
    user = User.objects.create_user(
        username="eve",
        email="eve@example.com",
        password="test-pass",
    )
    UserProfile.objects.create(user=user, telegram_chat_id="123456")

    agent = Agent.objects.create(
        owner=user,
        name="Telegram Agent",
        slug="telegram-agent",
        instruction="Use telegram approvals.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
        config={"approval_channels": ["dashboard", "telegram"]},
    )
    approval_request = ApprovalRequest.objects.create(agent=agent, requested_by=user)
    trade_intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    client = APIClient()
    payload = {
        "callback_query": {
            "id": "callback-1",
            "from": {"id": 123456},
            "message": {"chat": {"id": 123456}},
            "data": f"approval:{approval_request.id}:approve",
        }
    }

    with patch(
        "apps.approvals.services.decision_engine.execute_intent_task.delay"
    ) as mocked_delay, patch(
        "apps.approvals.telegram_views.TelegramClient.answer_callback_query"
    ) as mocked_answer:
        response = client.post(
            "/api/v1/telegram/webhook/test-secret/",
            payload,
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    approval_request.refresh_from_db()
    trade_intent.refresh_from_db()
    assert approval_request.status == ApprovalStatus.APPROVED
    assert trade_intent.status == IntentStatus.APPROVED
    mocked_delay.assert_called_once_with(trade_intent.id, True)
    mocked_answer.assert_called_once()
    assert TelegramCallbackEvent.objects.filter(callback_query_id="callback-1").exists()


@pytest.mark.django_db
@override_settings(TELEGRAM_WEBHOOK_SECRET="test-secret", TELEGRAM_BOT_TOKEN="test-bot-token")
def test_telegram_webhook_duplicate_callback_is_ignored() -> None:
    user = User.objects.create_user(
        username="frank",
        email="frank@example.com",
        password="test-pass",
    )
    UserProfile.objects.create(user=user, telegram_chat_id="999000")

    agent = Agent.objects.create(
        owner=user,
        name="Duplicate Callback Agent",
        slug="duplicate-callback-agent",
        instruction="test duplicate callback handling",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(agent=agent, requested_by=user)
    TelegramCallbackEvent.objects.create(
        callback_query_id="callback-duplicate",
        approval_request=approval_request,
        telegram_user_id="999000",
    )

    payload = {
        "callback_query": {
            "id": "callback-duplicate",
            "from": {"id": 999000},
            "message": {"chat": {"id": 999000}},
            "data": f"approval:{approval_request.id}:approve",
        }
    }
    client = APIClient()
    response = client.post(
        "/api/v1/telegram/webhook/test-secret/",
        payload,
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
