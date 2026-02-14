from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.agents.models import (
    Agent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
    AgentStatus,
    AnalysisNotificationEventType,
    AnalysisRunStatus,
)
from apps.approvals.models import ApprovalRequest, ApprovalStatus
from apps.audit.models import AuditEvent, AuditLevel
from apps.broker_kite.models import KiteSession
from apps.execution.models import IntentStatus, Side, TradeIntent
from apps.market_data.models import Instrument, TickSnapshot
from apps.risk.models import RiskPolicy

User = get_user_model()


@pytest.mark.django_db
def test_control_tower_metrics_requires_admin_login() -> None:
    client = Client()

    response = client.get("/admin/control-tower/metrics/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_control_tower_metrics_returns_cross_module_snapshot() -> None:
    owner = User.objects.create_user(
        username="ops-owner",
        email="ops-owner@example.com",
        password="test-pass",
        is_staff=True,
        is_superuser=True,
    )
    UserProfile.objects.create(user=owner, telegram_chat_id="123456")
    risk_policy = RiskPolicy.objects.create(owner=owner, name="Default Ops", is_default=True)
    agent = Agent.objects.create(
        owner=owner,
        risk_policy=risk_policy,
        name="Ops Agent",
        slug="ops-agent",
        instruction="Track execution quality",
        status=AgentStatus.ACTIVE,
        is_auto_enabled=True,
        is_predictive=True,
    )

    now = timezone.now()
    approval_request = ApprovalRequest.objects.create(
        agent=agent,
        requested_by=owner,
        status=ApprovalStatus.PENDING,
        expires_at=now - timedelta(minutes=5),
        is_escalated=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.FAILED,
        query="Why did spread widen?",
        error_message="Volatility threshold exceeded.",
    )
    endpoint = AgentAnalysisWebhookEndpoint.objects.create(
        owner=owner,
        name="Ops Webhook",
        callback_url="https://example.com/hook",
    )
    AgentAnalysisNotificationDelivery.objects.create(
        endpoint=endpoint,
        run=run,
        event_type=AnalysisNotificationEventType.RUN_FAILED,
        success=False,
        attempt_count=1,
        max_attempts=3,
        next_retry_at=now + timedelta(minutes=1),
    )
    TradeIntent.objects.create(
        agent=agent,
        approval_request=approval_request,
        symbol="INFY",
        side=Side.BUY,
        quantity=1,
        status=IntentStatus.FAILED,
        failure_reason="Risk guard rejected notional",
    )
    KiteSession.objects.create(
        user=owner,
        kite_user_id="KITE123",
        is_active=True,
        session_expires_at=now + timedelta(hours=2),
    )
    instrument = Instrument.objects.create(
        instrument_token=101,
        tradingsymbol="INFY",
        exchange="NSE",
        segment="NSE",
        is_active=True,
    )
    TickSnapshot.objects.create(
        instrument=instrument,
        last_price=1800,
        volume=100,
        source="kite_ticker",
    )
    AuditEvent.objects.create(
        actor=owner,
        event_type="execution.failed",
        level=AuditLevel.ERROR,
        message="Order placement failed",
    )

    client = Client()
    client.force_login(owner)

    response = client.get("/admin/control-tower/metrics/")
    assert response.status_code == 200
    payload = response.json()

    assert payload["metric_values"]["agents_active"] == 1
    assert payload["metric_values"]["approvals_pending"] == 1
    assert payload["metric_values"]["approvals_overdue"] == 1
    assert payload["metric_values"]["analysis_failed_24h"] == 1
    assert payload["metric_values"]["deliveries_retrying"] == 1
    assert payload["metric_values"]["intents_failed_24h"] == 1
    assert payload["metric_values"]["market_ticks_5m"] == 1
    assert payload["metric_values"]["audit_error_24h"] == 1
    assert payload["alerts"]
    assert payload["module_panels"]
