import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.accounts.models import UserProfile
from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
)
from apps.approvals.models import ApprovalDecision, ApprovalRequest, TelegramCallbackEvent
from apps.audit.models import AuditEvent
from apps.broker_kite.models import KiteSession
from apps.execution.models import TradeIntent
from apps.market_data.models import Instrument, TickSnapshot
from apps.risk.models import RiskPolicy

User = get_user_model()


@pytest.mark.django_db
def test_seed_demo_data_creates_records_across_all_models() -> None:
    call_command("seed_demo_data", cycles=1, verbosity=0)

    assert User.objects.filter(username__startswith="seed_owner_").count() == 1
    assert UserProfile.objects.count() >= 2
    assert RiskPolicy.objects.count() >= 2
    assert Agent.objects.count() >= 2
    assert AgentAnalysisRun.objects.count() >= 5
    assert AgentAnalysisEvent.objects.count() >= 10
    assert AgentAnalysisWebhookEndpoint.objects.count() >= 1
    assert AgentAnalysisNotificationDelivery.objects.count() >= 3
    assert ApprovalRequest.objects.count() >= 4
    assert ApprovalDecision.objects.count() >= 3
    assert TelegramCallbackEvent.objects.count() >= 2
    assert TradeIntent.objects.count() >= 4
    assert KiteSession.objects.count() >= 2
    assert Instrument.objects.count() >= 3
    assert TickSnapshot.objects.count() >= 6
    assert AuditEvent.objects.count() >= 5


@pytest.mark.django_db
def test_seed_demo_data_is_incremental_for_repeated_runs() -> None:
    call_command("seed_demo_data", cycles=1, verbosity=0)
    counts_after_first = {
        "owners": User.objects.filter(username__startswith="seed_owner_").count(),
        "profiles": UserProfile.objects.count(),
        "agents": Agent.objects.count(),
        "analysis_runs": AgentAnalysisRun.objects.count(),
        "approval_requests": ApprovalRequest.objects.count(),
        "trade_intents": TradeIntent.objects.count(),
        "audit_events": AuditEvent.objects.count(),
    }

    call_command("seed_demo_data", cycles=1, verbosity=0)
    counts_after_second = {
        "owners": User.objects.filter(username__startswith="seed_owner_").count(),
        "profiles": UserProfile.objects.count(),
        "agents": Agent.objects.count(),
        "analysis_runs": AgentAnalysisRun.objects.count(),
        "approval_requests": ApprovalRequest.objects.count(),
        "trade_intents": TradeIntent.objects.count(),
        "audit_events": AuditEvent.objects.count(),
    }

    assert counts_after_second["owners"] == counts_after_first["owners"] + 1
    assert counts_after_second["profiles"] > counts_after_first["profiles"]
    assert counts_after_second["agents"] > counts_after_first["agents"]
    assert counts_after_second["analysis_runs"] > counts_after_first["analysis_runs"]
    assert counts_after_second["approval_requests"] > counts_after_first["approval_requests"]
    assert counts_after_second["trade_intents"] > counts_after_first["trade_intents"]
    assert counts_after_second["audit_events"] > counts_after_first["audit_events"]
