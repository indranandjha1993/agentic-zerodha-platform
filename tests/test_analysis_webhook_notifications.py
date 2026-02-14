import hashlib
import hmac
import json
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
