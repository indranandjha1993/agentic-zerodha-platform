import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import (
    Agent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
    AgentStatus,
    AnalysisNotificationEventType,
    AnalysisRunStatus,
    ApprovalMode,
    ExecutionMode,
)
from apps.agents.services.analysis_notifications import (
    AnalysisRunNotificationDispatchService,
    AnalysisWebhookEndpointService,
)
from apps.agents.tasks import dispatch_analysis_run_notifications_task

User = get_user_model()


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_analysis_webhook_endpoint_api_create_update() -> None:
    owner = User.objects.create_user(
        username="webhook-owner",
        email="webhook-owner@example.com",
        password="test-pass",
    )

    client = APIClient()
    client.force_authenticate(owner)

    create_response = client.post(
        "/api/v1/analysis-webhook-endpoints/",
        {
            "name": "dashboard-listener",
            "callback_url": "https://example.com/hooks/analysis",
            "signing_secret": "top-secret",
            "event_types": [AnalysisNotificationEventType.RUN_COMPLETED],
            "headers": {"X-Custom": "abc123"},
        },
        format="json",
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["name"] == "dashboard-listener"
    assert payload["has_signing_secret"] is True
    assert "signing_secret" not in payload

    endpoint = AgentAnalysisWebhookEndpoint.objects.get(id=payload["id"])
    assert endpoint.signing_secret_encrypted != ""

    patch_response = client.patch(
        f"/api/v1/analysis-webhook-endpoints/{endpoint.id}/",
        {
            "event_types": [
                AnalysisNotificationEventType.RUN_COMPLETED,
                AnalysisNotificationEventType.RUN_FAILED,
            ],
            "signing_secret": "",
        },
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["has_signing_secret"] is False


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_analysis_notification_dispatch_is_signed_and_idempotent() -> None:
    owner = User.objects.create_user(
        username="dispatch-owner",
        email="dispatch-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Dispatch Agent",
        slug="dispatch-agent",
        instruction="Dispatch notifications.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze ICICIBANK",
        model="openai/gpt-4o-mini",
        max_steps=4,
        steps_executed=2,
        result_text="Done",
        completed_at=timezone.now(),
    )

    endpoint_service = AnalysisWebhookEndpointService()
    endpoint_service.create_for_user(
        user=owner,
        payload={
            "name": "ops-webhook",
            "callback_url": "https://example.com/ops/webhook",
            "signing_secret": "webhook-secret",
            "event_types": [AnalysisNotificationEventType.RUN_COMPLETED],
            "headers": {},
            "is_active": True,
        },
    )

    mocked_response = Mock()
    mocked_response.status_code = 202
    mocked_response.text = "accepted"

    service = AnalysisRunNotificationDispatchService(endpoint_service=endpoint_service)

    with patch(
        "apps.agents.services.analysis_notifications.requests.post",
        return_value=mocked_response,
    ) as mocked_post:
        first = service.dispatch_for_run(run)

    assert first["delivered"] == 1
    assert first["failed"] == 0
    assert first["event_type"] == AnalysisNotificationEventType.RUN_COMPLETED

    delivery = AgentAnalysisNotificationDelivery.objects.get(
        run=run,
        event_type=AnalysisNotificationEventType.RUN_COMPLETED,
    )
    assert delivery.success is True
    assert delivery.status_code == 202

    kwargs = mocked_post.call_args.kwargs
    raw_body = kwargs["data"]
    assert isinstance(raw_body, bytes)
    payload = json.loads(raw_body.decode("utf-8"))
    assert payload["run"]["id"] == run.id

    headers = kwargs["headers"]
    assert headers["X-Agentic-Event"] == AnalysisNotificationEventType.RUN_COMPLETED
    expected_signature = hmac.new(
        b"webhook-secret",
        raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    assert headers["X-Agentic-Signature"] == f"sha256={expected_signature}"

    with patch("apps.agents.services.analysis_notifications.requests.post") as mocked_post_again:
        second = service.dispatch_for_run(run)

    assert second["delivered"] == 0
    assert second["skipped"] == 1
    assert mocked_post_again.call_count == 0
    assert AgentAnalysisNotificationDelivery.objects.filter(run=run).count() == 1


@pytest.mark.django_db
@override_settings(
    ENCRYPTION_KEY="unit-test-encryption-key",
    ANALYSIS_WEBHOOK_MAX_ATTEMPTS=3,
    ANALYSIS_WEBHOOK_RETRY_BASE_SECONDS=60,
    ANALYSIS_WEBHOOK_RETRY_MAX_SECONDS=600,
)
def test_analysis_notification_dispatch_retries_with_backoff() -> None:
    owner = User.objects.create_user(
        username="retry-owner",
        email="retry-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Retry Agent",
        slug="retry-agent",
        instruction="Retry failed webhook deliveries.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze SBIN",
        model="openai/gpt-4o-mini",
        max_steps=4,
        completed_at=timezone.now(),
    )

    endpoint_service = AnalysisWebhookEndpointService()
    endpoint = endpoint_service.create_for_user(
        user=owner,
        payload={
            "name": "retry-webhook",
            "callback_url": "https://example.com/retry/webhook",
            "signing_secret": "",
            "event_types": [AnalysisNotificationEventType.RUN_COMPLETED],
            "headers": {},
            "is_active": True,
        },
    )
    service = AnalysisRunNotificationDispatchService(endpoint_service=endpoint_service)

    failed_response = Mock()
    failed_response.status_code = 503
    failed_response.text = "service unavailable"
    with patch(
        "apps.agents.services.analysis_notifications.requests.post",
        return_value=failed_response,
    ) as mocked_failed_post:
        first = service.dispatch_for_run(run)

    assert mocked_failed_post.call_count == 1
    assert first["failed"] == 1
    assert first["retry_scheduled_in_seconds"] == 60

    delivery = AgentAnalysisNotificationDelivery.objects.get(endpoint=endpoint, run=run)
    assert delivery.success is False
    assert delivery.attempt_count == 1
    assert delivery.next_retry_at is not None

    with patch("apps.agents.services.analysis_notifications.requests.post") as mocked_not_due:
        second = service.dispatch_for_run(run)

    assert mocked_not_due.call_count == 0
    assert second["attempted"] == 1
    assert second["failed"] == 0
    assert second["retry_scheduled_in_seconds"] is not None

    delivery.next_retry_at = timezone.now() - timedelta(seconds=1)
    delivery.save(update_fields=["next_retry_at", "updated_at"])

    success_response = Mock()
    success_response.status_code = 200
    success_response.text = "ok"
    with patch(
        "apps.agents.services.analysis_notifications.requests.post",
        return_value=success_response,
    ) as mocked_success_post:
        third = service.dispatch_for_run(run)

    assert mocked_success_post.call_count == 1
    assert third["delivered"] == 1
    assert third["failed"] == 0
    assert third["retry_scheduled_in_seconds"] is None

    delivery.refresh_from_db()
    assert delivery.success is True
    assert delivery.attempt_count == 2
    assert delivery.next_retry_at is None
    assert delivery.delivered_at is not None


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_dispatch_task_schedules_follow_up_retry() -> None:
    owner = User.objects.create_user(
        username="retry-task-owner",
        email="retry-task-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Retry Task Agent",
        slug="retry-task-agent",
        instruction="Retry task scheduling.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze ULTRACEMCO",
        model="openai/gpt-4o-mini",
        max_steps=4,
        completed_at=timezone.now(),
    )

    with patch(
        "apps.agents.tasks.AnalysisRunNotificationDispatchService.dispatch_for_run",
        return_value={
            "status": "ok",
            "event_type": "analysis_run.completed",
            "attempted": 1,
            "delivered": 0,
            "failed": 1,
            "skipped": 0,
            "retry_scheduled_in_seconds": 45,
        },
    ) as mocked_dispatch:
        with patch(
            "apps.agents.tasks.dispatch_analysis_run_notifications_task.apply_async"
        ) as mocked_apply_async:
            payload = dispatch_analysis_run_notifications_task(run.id)

    assert mocked_dispatch.call_count == 1
    assert payload["retry_scheduled_in_seconds"] == 45
    mocked_apply_async.assert_called_once_with(args=[run.id], countdown=45)
