from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentStatus, ApprovalMode, ExecutionMode
from apps.approvals.models import ApprovalRequest, ApprovalStatus
from apps.execution.models import IntentStatus, Side, TradeIntent

User = get_user_model()


@pytest.mark.django_db
def test_two_approvals_required_before_execution_dispatch() -> None:
    owner = User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="test-pass",
    )
    approver = User.objects.create_user(
        username="approver",
        email="approver@example.com",
        password="test-pass",
    )

    agent = Agent.objects.create(
        owner=owner,
        name="Two-Person Agent",
        slug="two-person-agent",
        instruction="Two approvals required before execution.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        required_approvals=2,
        is_auto_enabled=True,
    )
    agent.approvers.set([approver])

    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        required_approvals=2,
    )
    trade_intent = TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.PENDING_APPROVAL,
        request_payload={"source": "unit_test"},
    )

    owner_client = APIClient()
    owner_client.force_authenticate(owner)
    approver_client = APIClient()
    approver_client.force_authenticate(approver)

    with patch("apps.approvals.services.decision_engine.execute_intent_task.delay") as mocked_delay:
        response_owner = owner_client.post(
            f"/api/v1/approval-requests/{approval_request.id}/decide/",
            {"decision": "approve", "channel": "dashboard", "reason": "Owner approves."},
            format="json",
        )
        assert response_owner.status_code == 200
        assert response_owner.json()["status"] == ApprovalStatus.PENDING
        assert response_owner.json()["decision_outcome"]["is_final"] is False
        mocked_delay.assert_not_called()

        response_approver = approver_client.post(
            f"/api/v1/approval-requests/{approval_request.id}/decide/",
            {"decision": "approve", "channel": "dashboard", "reason": "Second approver approves."},
            format="json",
        )
        assert response_approver.status_code == 200
        assert response_approver.json()["status"] == ApprovalStatus.APPROVED
        assert response_approver.json()["decision_outcome"]["is_final"] is True
        mocked_delay.assert_called_once_with(trade_intent.id, True)

    approval_request.refresh_from_db()
    trade_intent.refresh_from_db()
    assert approval_request.status == ApprovalStatus.APPROVED
    assert trade_intent.status == IntentStatus.APPROVED


@pytest.mark.django_db
def test_duplicate_vote_by_same_actor_is_rejected() -> None:
    owner = User.objects.create_user(
        username="dup-owner",
        email="dup-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Duplicate Vote Agent",
        slug="duplicate-vote-agent",
        instruction="Prevent duplicate approvals.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        required_approvals=2,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        required_approvals=2,
    )

    client = APIClient()
    client.force_authenticate(owner)
    first = client.post(
        f"/api/v1/approval-requests/{approval_request.id}/decide/",
        {"decision": "approve", "channel": "dashboard"},
        format="json",
    )
    second = client.post(
        f"/api/v1/approval-requests/{approval_request.id}/decide/",
        {"decision": "approve", "channel": "dashboard"},
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "You have already decided this request."


@pytest.mark.django_db
def test_unassigned_user_cannot_access_approval_request() -> None:
    owner = User.objects.create_user(
        username="policy-owner",
        email="policy-owner@example.com",
        password="test-pass",
    )
    outsider = User.objects.create_user(
        username="outsider",
        email="outsider@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Policy Agent",
        slug="policy-agent",
        instruction="Only owner or approver can access request.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        required_approvals=1,
        is_auto_enabled=True,
    )
    approval_request = ApprovalRequest.objects.create(agent=agent, requested_by=owner)

    outsider_client = APIClient()
    outsider_client.force_authenticate(outsider)
    response = outsider_client.post(
        f"/api/v1/approval-requests/{approval_request.id}/decide/",
        {"decision": "approve", "channel": "dashboard"},
        format="json",
    )

    assert response.status_code == 404
