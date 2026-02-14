from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.models import ApprovalRequest, ApprovalStatus, DecisionType
from apps.approvals.tasks import process_expired_approval_requests_task
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
def test_approval_queue_endpoint_returns_sla_summary() -> None:
    owner = User.objects.create_user(
        username="queue-owner",
        email="queue-owner@example.com",
        password="test-pass",
    )
    client = APIClient()
    client.force_authenticate(owner)

    agent = Agent.objects.create(
        owner=owner,
        name="Queue Agent",
        slug="queue-agent",
        instruction="Queue summary checks",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )

    now = timezone.now()
    ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        status=ApprovalStatus.PENDING,
        expires_at=now - timedelta(minutes=5),
    )
    ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        status=ApprovalStatus.PENDING,
        expires_at=now + timedelta(seconds=120),
    )
    ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        status=ApprovalStatus.PENDING,
        expires_at=now + timedelta(hours=1),
    )
    ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        status=ApprovalStatus.APPROVED,
        expires_at=now + timedelta(hours=1),
    )

    response = client.get("/api/v1/approval-requests/queue/?due_soon_seconds=300")
    assert response.status_code == 200

    payload = response.json()
    assert payload["summary"]["pending_count"] == 3
    assert payload["summary"]["overdue_count"] == 1
    assert payload["summary"]["due_soon_count"] == 1
    assert payload["summary"]["mine_pending_count"] == 3
    assert len(payload["results"]) == 3


@pytest.mark.django_db
def test_timeout_policy_auto_reject_marks_request_and_intent_rejected() -> None:
    owner = User.objects.create_user(
        username="auto-reject-owner",
        email="auto-reject-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Auto Reject Agent",
        slug="auto-reject-agent",
        instruction="Auto reject on timeout",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        timeout_policy="auto_reject",
        status=ApprovalStatus.PENDING,
        expires_at=timezone.now() - timedelta(minutes=1),
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

    result = process_expired_approval_requests_task.run(batch_size=100)
    approval_request.refresh_from_db()
    intent.refresh_from_db()

    assert result["processed"] >= 1
    assert approval_request.status == ApprovalStatus.REJECTED
    assert intent.status == IntentStatus.REJECTED
    assert approval_request.decisions.filter(decision=DecisionType.REJECT).exists()


@pytest.mark.django_db
def test_timeout_policy_auto_pause_pauses_agent_and_expires_request() -> None:
    owner = User.objects.create_user(
        username="auto-pause-owner",
        email="auto-pause-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Auto Pause Agent",
        slug="auto-pause-agent",
        instruction="Auto pause on timeout",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        timeout_policy="auto_pause",
        status=ApprovalStatus.PENDING,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="TCS",
        side=Side.SELL,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    process_expired_approval_requests_task.run(batch_size=100)
    approval_request.refresh_from_db()
    agent.refresh_from_db()
    intent.refresh_from_db()

    assert approval_request.status == ApprovalStatus.EXPIRED
    assert agent.status == AgentStatus.PAUSED
    assert agent.is_auto_enabled is False
    assert intent.status == IntentStatus.REJECTED


@pytest.mark.django_db
def test_timeout_policy_escalate_then_reject_on_second_expiry() -> None:
    owner = User.objects.create_user(
        username="escalate-owner",
        email="escalate-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Escalation Agent",
        slug="escalation-agent",
        instruction="Escalate on first timeout.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
        config={"escalation_grace_minutes": 5},
    )
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        timeout_policy="escalate",
        status=ApprovalStatus.PENDING,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    process_expired_approval_requests_task.run(batch_size=100)
    approval_request.refresh_from_db()
    assert approval_request.status == ApprovalStatus.PENDING
    assert approval_request.is_escalated is True
    assert approval_request.expires_at is not None
    assert approval_request.expires_at > timezone.now()

    approval_request.expires_at = timezone.now() - timedelta(minutes=1)
    approval_request.save(update_fields=["expires_at", "updated_at"])
    process_expired_approval_requests_task.run(batch_size=100)

    approval_request.refresh_from_db()
    intent.refresh_from_db()
    assert approval_request.status == ApprovalStatus.REJECTED
    assert intent.status == IntentStatus.REJECTED
