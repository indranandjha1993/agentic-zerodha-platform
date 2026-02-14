from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.agents.models import (
    Agent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentStatus,
    AnalysisRunStatus,
)
from apps.approvals.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    DecisionType,
)
from apps.audit.models import AuditEvent, AuditLevel
from apps.broker_kite.models import KiteSession
from apps.execution.models import IntentStatus, TradeIntent
from apps.market_data.models import Instrument, TickSnapshot
from apps.risk.models import RiskPolicy


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    return int(value)


def _admin_url(name: str, query: dict[str, Any] | None = None) -> str:
    url = str(reverse(name))
    if not query:
        return url
    return f"{url}?{urlencode(query, doseq=True)}"


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return str(timezone.localtime(value).strftime("%d %b %Y %H:%M"))


def _tone_for_ratio(numerator: int, denominator: int, warning: float, critical: float) -> str:
    if denominator <= 0:
        return "ok"
    ratio = numerator / denominator
    if ratio >= critical:
        return "critical"
    if ratio >= warning:
        return "warn"
    return "ok"


def build_admin_dashboard_snapshot() -> dict[str, Any]:
    now = timezone.now()
    past_5m = now - timedelta(minutes=5)
    past_24h = now - timedelta(hours=24)
    next_24h = now + timedelta(hours=24)

    agent_stats = Agent.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=AgentStatus.ACTIVE)),
        paused=Count("id", filter=Q(status=AgentStatus.PAUSED)),
        draft=Count("id", filter=Q(status=AgentStatus.DRAFT)),
        archived=Count("id", filter=Q(status=AgentStatus.ARCHIVED)),
        auto_enabled=Count("id", filter=Q(is_auto_enabled=True)),
        predictive=Count("id", filter=Q(is_predictive=True)),
    )
    analysis_stats = AgentAnalysisRun.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=AnalysisRunStatus.PENDING)),
        running=Count("id", filter=Q(status=AnalysisRunStatus.RUNNING)),
        completed=Count("id", filter=Q(status=AnalysisRunStatus.COMPLETED)),
        failed=Count("id", filter=Q(status=AnalysisRunStatus.FAILED)),
        completed_24h=Count(
            "id",
            filter=Q(status=AnalysisRunStatus.COMPLETED, created_at__gte=past_24h),
        ),
        failed_24h=Count(
            "id",
            filter=Q(status=AnalysisRunStatus.FAILED, created_at__gte=past_24h),
        ),
    )
    analysis_duration_stats = AgentAnalysisRun.objects.filter(
        status=AnalysisRunStatus.COMPLETED,
        started_at__isnull=False,
        completed_at__isnull=False,
        completed_at__gte=past_24h,
    ).aggregate(
        average_duration=Avg(
            ExpressionWrapper(
                F("completed_at") - F("started_at"),
                output_field=DurationField(),
            )
        )
    )

    delivery_stats = AgentAnalysisNotificationDelivery.objects.aggregate(
        total=Count("id"),
        successful=Count("id", filter=Q(success=True)),
        retrying=Count(
            "id",
            filter=Q(
                success=False, next_retry_at__isnull=False, attempt_count__lt=F("max_attempts")
            ),
        ),
        failed=Count(
            "id",
            filter=Q(success=False)
            & (Q(next_retry_at__isnull=True) | Q(attempt_count__gte=F("max_attempts"))),
        ),
        failed_24h=Count("id", filter=Q(success=False, created_at__gte=past_24h)),
    )

    approval_stats = ApprovalRequest.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=ApprovalStatus.PENDING)),
        approved=Count("id", filter=Q(status=ApprovalStatus.APPROVED)),
        rejected=Count("id", filter=Q(status=ApprovalStatus.REJECTED)),
        expired=Count("id", filter=Q(status=ApprovalStatus.EXPIRED)),
        escalated=Count("id", filter=Q(is_escalated=True, status=ApprovalStatus.PENDING)),
        overdue=Count(
            "id",
            filter=Q(
                status=ApprovalStatus.PENDING,
                expires_at__isnull=False,
                expires_at__lt=now,
            ),
        ),
        due_soon=Count(
            "id",
            filter=Q(
                status=ApprovalStatus.PENDING,
                expires_at__isnull=False,
                expires_at__gte=now,
                expires_at__lte=now + timedelta(minutes=15),
            ),
        ),
        approved_24h=Count(
            "id",
            filter=Q(
                status=ApprovalStatus.APPROVED, decided_at__isnull=False, decided_at__gte=past_24h
            ),
        ),
        rejected_24h=Count(
            "id",
            filter=Q(
                status__in=(
                    ApprovalStatus.REJECTED,
                    ApprovalStatus.EXPIRED,
                    ApprovalStatus.CANCELED,
                ),
                decided_at__isnull=False,
                decided_at__gte=past_24h,
            ),
        ),
    )
    decision_stats = ApprovalDecision.objects.filter(created_at__gte=past_24h).aggregate(
        total=Count("id"),
        approve=Count("id", filter=Q(decision=DecisionType.APPROVE)),
        reject=Count("id", filter=Q(decision=DecisionType.REJECT)),
        dashboard=Count("id", filter=Q(channel="dashboard")),
        admin=Count("id", filter=Q(channel="admin")),
        telegram=Count("id", filter=Q(channel="telegram")),
    )

    intent_stats = TradeIntent.objects.aggregate(
        total=Count("id"),
        pending_approval=Count("id", filter=Q(status=IntentStatus.PENDING_APPROVAL)),
        approved=Count("id", filter=Q(status=IntentStatus.APPROVED)),
        queued=Count("id", filter=Q(status=IntentStatus.QUEUED)),
        placed=Count("id", filter=Q(status=IntentStatus.PLACED)),
        failed=Count("id", filter=Q(status=IntentStatus.FAILED)),
        placed_24h=Count("id", filter=Q(status=IntentStatus.PLACED, created_at__gte=past_24h)),
        failed_24h=Count("id", filter=Q(status=IntentStatus.FAILED, created_at__gte=past_24h)),
    )

    instrument_stats = Instrument.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
    )
    tick_stats = TickSnapshot.objects.aggregate(
        ticks_5m=Count("id", filter=Q(created_at__gte=past_5m)),
        ticks_24h=Count("id", filter=Q(created_at__gte=past_24h)),
    )

    kite_stats = KiteSession.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        expiring_24h=Count(
            "id",
            filter=Q(
                is_active=True,
                session_expires_at__isnull=False,
                session_expires_at__gte=now,
                session_expires_at__lte=next_24h,
            ),
        ),
        expired=Count(
            "id",
            filter=Q(
                is_active=True,
                session_expires_at__isnull=False,
                session_expires_at__lt=now,
            ),
        ),
    )

    risk_stats = RiskPolicy.objects.aggregate(
        total=Count("id"),
        defaults=Count("id", filter=Q(is_default=True)),
        market_hours_required=Count("id", filter=Q(require_market_hours=True)),
        shorting_enabled=Count("id", filter=Q(allow_shorting=True)),
    )
    profile_stats = UserProfile.objects.aggregate(
        total=Count("id"),
        telegram_connected=Count(
            "id", filter=Q(telegram_chat_id__isnull=False) & ~Q(telegram_chat_id="")
        ),
    )
    user_model = get_user_model()
    user_stats = user_model.objects.aggregate(
        total=Count("id"), staff=Count("id", filter=Q(is_staff=True))
    )

    audit_stats = AuditEvent.objects.filter(created_at__gte=past_24h).aggregate(
        total=Count("id"),
        info=Count("id", filter=Q(level=AuditLevel.INFO)),
        warning=Count("id", filter=Q(level=AuditLevel.WARNING)),
        error=Count("id", filter=Q(level=AuditLevel.ERROR)),
    )

    avg_duration = analysis_duration_stats.get("average_duration")
    average_runtime_seconds = 0
    if avg_duration is not None:
        average_runtime_seconds = int(avg_duration.total_seconds())

    metric_values = {
        "agents_total": _as_int(agent_stats["total"]),
        "agents_active": _as_int(agent_stats["active"]),
        "agents_paused": _as_int(agent_stats["paused"]),
        "agents_auto_enabled": _as_int(agent_stats["auto_enabled"]),
        "agents_predictive": _as_int(agent_stats["predictive"]),
        "analysis_running": _as_int(analysis_stats["running"]),
        "analysis_failed_24h": _as_int(analysis_stats["failed_24h"]),
        "analysis_completed_24h": _as_int(analysis_stats["completed_24h"]),
        "analysis_avg_runtime_seconds": average_runtime_seconds,
        "approvals_pending": _as_int(approval_stats["pending"]),
        "approvals_overdue": _as_int(approval_stats["overdue"]),
        "approvals_due_soon": _as_int(approval_stats["due_soon"]),
        "approvals_escalated": _as_int(approval_stats["escalated"]),
        "decisions_telegram_24h": _as_int(decision_stats["telegram"]),
        "intents_pending_approval": _as_int(intent_stats["pending_approval"]),
        "intents_queued": _as_int(intent_stats["queued"]),
        "intents_failed_24h": _as_int(intent_stats["failed_24h"]),
        "intents_placed_24h": _as_int(intent_stats["placed_24h"]),
        "deliveries_retrying": _as_int(delivery_stats["retrying"]),
        "deliveries_failed": _as_int(delivery_stats["failed"]),
        "kite_active_sessions": _as_int(kite_stats["active"]),
        "kite_expiring_24h": _as_int(kite_stats["expiring_24h"]),
        "kite_expired": _as_int(kite_stats["expired"]),
        "market_active_instruments": _as_int(instrument_stats["active"]),
        "market_ticks_5m": _as_int(tick_stats["ticks_5m"]),
        "market_ticks_24h": _as_int(tick_stats["ticks_24h"]),
        "risk_policies_total": _as_int(risk_stats["total"]),
        "risk_default_policies": _as_int(risk_stats["defaults"]),
        "profiles_total": _as_int(profile_stats["total"]),
        "profiles_telegram_connected": _as_int(profile_stats["telegram_connected"]),
        "users_total": _as_int(user_stats["total"]),
        "audit_warning_24h": _as_int(audit_stats["warning"]),
        "audit_error_24h": _as_int(audit_stats["error"]),
    }

    headline_cards = [
        {
            "title": "Active Agents",
            "metric_key": "agents_active",
            "description": "Agents currently allowed to execute.",
            "href": _admin_url(
                "admin:agents_agent_changelist", {"status__exact": AgentStatus.ACTIVE}
            ),
            "tone": "ok",
        },
        {
            "title": "Pending Approvals",
            "metric_key": "approvals_pending",
            "description": "Human approvals waiting for action.",
            "href": _admin_url(
                "admin:approvals_approvalrequest_changelist",
                {"status__exact": ApprovalStatus.PENDING},
            ),
            "tone": "warn",
        },
        {
            "title": "Running Analysis",
            "metric_key": "analysis_running",
            "description": "Open research jobs in progress.",
            "href": _admin_url(
                "admin:agents_agentanalysisrun_changelist",
                {"status__exact": AnalysisRunStatus.RUNNING},
            ),
            "tone": "ok",
        },
        {
            "title": "Queued Trade Intents",
            "metric_key": "intents_queued",
            "description": "Orders ready to be routed.",
            "href": _admin_url(
                "admin:execution_tradeintent_changelist",
                {"status__exact": IntentStatus.QUEUED},
            ),
            "tone": "warn",
        },
        {
            "title": "Retrying Webhooks",
            "metric_key": "deliveries_retrying",
            "description": "Delivery retries currently in flight.",
            "href": _admin_url(
                "admin:agents_agentanalysisnotificationdelivery_changelist",
                {"success__exact": "0", "next_retry_at__isnull": "False"},
            ),
            "tone": "warn",
        },
        {
            "title": "Audit Errors (24h)",
            "metric_key": "audit_error_24h",
            "description": "Critical platform errors raised in logs.",
            "href": _admin_url(
                "admin:audit_auditevent_changelist",
                {"level__exact": AuditLevel.ERROR},
            ),
            "tone": "critical",
        },
    ]

    queue_cards = [
        {
            "title": "Overdue approvals",
            "metric_key": "approvals_overdue",
            "detail": "Pending requests past expiry.",
            "href": _admin_url(
                "admin:approvals_approvalrequest_changelist",
                {"status__exact": ApprovalStatus.PENDING, "expires_at__isnull": "False"},
            ),
            "tone": "critical" if metric_values["approvals_overdue"] > 0 else "ok",
        },
        {
            "title": "Due in 15 minutes",
            "metric_key": "approvals_due_soon",
            "detail": "Requests close to timeout threshold.",
            "href": _admin_url(
                "admin:approvals_approvalrequest_changelist",
                {"status__exact": ApprovalStatus.PENDING},
            ),
            "tone": "warn" if metric_values["approvals_due_soon"] > 0 else "ok",
        },
        {
            "title": "Failed intents (24h)",
            "metric_key": "intents_failed_24h",
            "detail": "Execution failures in the last day.",
            "href": _admin_url(
                "admin:execution_tradeintent_changelist",
                {"status__exact": IntentStatus.FAILED},
            ),
            "tone": _tone_for_ratio(
                metric_values["intents_failed_24h"],
                max(metric_values["intents_placed_24h"], 1),
                warning=0.05,
                critical=0.15,
            ),
        },
        {
            "title": "Expiring Kite sessions",
            "metric_key": "kite_expiring_24h",
            "detail": "Active broker sessions ending in 24h.",
            "href": _admin_url(
                "admin:broker_kite_kitesession_changelist", {"is_active__exact": "1"}
            ),
            "tone": "warn" if metric_values["kite_expiring_24h"] > 0 else "ok",
        },
    ]

    alerts: list[dict[str, str]] = []
    if metric_values["approvals_overdue"] > 0:
        alerts.append(
            {
                "title": "Approval SLA breach",
                "detail": f"{metric_values['approvals_overdue']} requests are overdue.",
                "tone": "critical",
                "href": _admin_url(
                    "admin:approvals_approvalrequest_changelist",
                    {"status__exact": ApprovalStatus.PENDING},
                ),
            }
        )
    if metric_values["deliveries_failed"] > 0:
        alerts.append(
            {
                "title": "Webhook delivery failures",
                "detail": (
                    f"{metric_values['deliveries_failed']} deliveries need manual inspection."
                ),
                "tone": "critical",
                "href": _admin_url(
                    "admin:agents_agentanalysisnotificationdelivery_changelist",
                    {"success__exact": "0"},
                ),
            }
        )
    if metric_values["kite_expired"] > 0:
        alerts.append(
            {
                "title": "Expired Kite sessions",
                "detail": f"{metric_values['kite_expired']} active sessions are already expired.",
                "tone": "critical",
                "href": _admin_url(
                    "admin:broker_kite_kitesession_changelist", {"is_active__exact": "1"}
                ),
            }
        )
    if metric_values["market_ticks_5m"] == 0:
        alerts.append(
            {
                "title": "Market feed is stale",
                "detail": "No ticks captured in the last 5 minutes.",
                "tone": "warn",
                "href": _admin_url("admin:market_data_ticksnapshot_changelist"),
            }
        )
    if not alerts:
        alerts.append(
            {
                "title": "System within thresholds",
                "detail": "No critical incidents are currently open.",
                "tone": "ok",
                "href": _admin_url("admin:index"),
            }
        )

    failed_runs = (
        AgentAnalysisRun.objects.filter(status=AnalysisRunStatus.FAILED)
        .select_related("agent")
        .order_by("-created_at")[:6]
    )
    expiring_approvals = (
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.PENDING,
            expires_at__isnull=False,
        )
        .select_related("agent", "requested_by")
        .order_by("expires_at", "-created_at")[:6]
    )
    failed_intents = (
        TradeIntent.objects.filter(status=IntentStatus.FAILED)
        .select_related("agent")
        .order_by("-created_at")[:6]
    )
    latest_audit = (
        AuditEvent.objects.filter(level__in=(AuditLevel.WARNING, AuditLevel.ERROR))
        .select_related("actor")
        .order_by("-created_at")[:6]
    )

    recent = {
        "failed_runs": [
            {
                "title": f"Run #{item.id} · {item.agent.name}",
                "subtitle": item.error_message[:90]
                if item.error_message
                else "No error message captured.",
                "timestamp": _format_timestamp(item.created_at),
                "href": reverse("admin:agents_agentanalysisrun_change", args=[item.id]),
                "tone": "critical",
            }
            for item in failed_runs
        ],
        "expiring_approvals": [
            {
                "title": f"Approval #{item.id} · {item.agent.name}",
                "subtitle": f"Channel: {item.channel} · Required: {item.required_approvals}",
                "timestamp": _format_timestamp(item.expires_at),
                "href": reverse("admin:approvals_approvalrequest_change", args=[item.id]),
                "tone": "warn",
            }
            for item in expiring_approvals
        ],
        "failed_intents": [
            {
                "title": f"Intent #{item.id} · {item.symbol} {item.side}",
                "subtitle": item.failure_reason[:90]
                if item.failure_reason
                else "No failure reason captured.",
                "timestamp": _format_timestamp(item.created_at),
                "href": reverse("admin:execution_tradeintent_change", args=[item.id]),
                "tone": "critical",
            }
            for item in failed_intents
        ],
        "audit_highlights": [
            {
                "title": f"{item.event_type} · {item.level}",
                "subtitle": item.message[:90] if item.message else "No message payload",
                "timestamp": _format_timestamp(item.created_at),
                "href": reverse("admin:audit_auditevent_change", args=[item.id]),
                "tone": "critical" if item.level == AuditLevel.ERROR else "warn",
            }
            for item in latest_audit
        ],
    }

    module_panels = [
        {
            "title": "Agents",
            "description": "Agent lifecycle, autonomy settings, and runtime posture.",
            "href": _admin_url("admin:agents_agent_changelist"),
            "metrics": [
                {"label": "Total", "metric_key": "agents_total"},
                {"label": "Active", "metric_key": "agents_active"},
                {"label": "Paused", "metric_key": "agents_paused"},
                {"label": "Auto-enabled", "metric_key": "agents_auto_enabled"},
                {"label": "Predictive", "metric_key": "agents_predictive"},
            ],
        },
        {
            "title": "Analysis",
            "description": "OpenRouter-powered research runs and completion health.",
            "href": _admin_url("admin:agents_agentanalysisrun_changelist"),
            "metrics": [
                {"label": "Running", "metric_key": "analysis_running"},
                {"label": "Completed 24h", "metric_key": "analysis_completed_24h"},
                {"label": "Failed 24h", "metric_key": "analysis_failed_24h"},
                {"label": "Avg runtime (s)", "metric_key": "analysis_avg_runtime_seconds"},
                {"label": "Retrying webhooks", "metric_key": "deliveries_retrying"},
            ],
        },
        {
            "title": "Approvals",
            "description": "Human-in-loop requests across admin, dashboard, and Telegram.",
            "href": _admin_url("admin:approvals_approvalrequest_changelist"),
            "metrics": [
                {"label": "Pending", "metric_key": "approvals_pending"},
                {"label": "Overdue", "metric_key": "approvals_overdue"},
                {"label": "Escalated", "metric_key": "approvals_escalated"},
                {"label": "Due soon", "metric_key": "approvals_due_soon"},
                {"label": "Telegram decisions 24h", "metric_key": "decisions_telegram_24h"},
            ],
        },
        {
            "title": "Execution",
            "description": "Trade intent pipeline from approval to broker placement.",
            "href": _admin_url("admin:execution_tradeintent_changelist"),
            "metrics": [
                {"label": "Pending approval", "metric_key": "intents_pending_approval"},
                {"label": "Queued", "metric_key": "intents_queued"},
                {"label": "Placed 24h", "metric_key": "intents_placed_24h"},
                {"label": "Failed 24h", "metric_key": "intents_failed_24h"},
            ],
        },
        {
            "title": "Broker Sessions",
            "description": "Zerodha Kite credential and session continuity.",
            "href": _admin_url("admin:broker_kite_kitesession_changelist"),
            "metrics": [
                {"label": "Active sessions", "metric_key": "kite_active_sessions"},
                {"label": "Expiring 24h", "metric_key": "kite_expiring_24h"},
                {"label": "Expired", "metric_key": "kite_expired"},
            ],
        },
        {
            "title": "Market Data",
            "description": "Instrument coverage and live feed ingestion cadence.",
            "href": _admin_url("admin:market_data_instrument_changelist"),
            "metrics": [
                {"label": "Active instruments", "metric_key": "market_active_instruments"},
                {"label": "Ticks 5m", "metric_key": "market_ticks_5m"},
                {"label": "Ticks 24h", "metric_key": "market_ticks_24h"},
            ],
        },
        {
            "title": "Risk & Access",
            "description": "Policy defaults and operator account readiness.",
            "href": _admin_url("admin:risk_riskpolicy_changelist"),
            "metrics": [
                {"label": "Risk policies", "metric_key": "risk_policies_total"},
                {"label": "Default policies", "metric_key": "risk_default_policies"},
                {"label": "Users", "metric_key": "users_total"},
                {"label": "Profiles", "metric_key": "profiles_total"},
                {"label": "Telegram linked", "metric_key": "profiles_telegram_connected"},
            ],
        },
        {
            "title": "Audit",
            "description": "Security and operations telemetry from platform events.",
            "href": _admin_url("admin:audit_auditevent_changelist"),
            "metrics": [
                {"label": "Warnings 24h", "metric_key": "audit_warning_24h"},
                {"label": "Errors 24h", "metric_key": "audit_error_24h"},
            ],
        },
    ]

    return {
        "generated_at": now.isoformat(),
        "generated_at_label": _format_timestamp(now),
        "refresh_interval_ms": 20_000,
        "metric_values": metric_values,
        "headline_cards": headline_cards,
        "queue_cards": queue_cards,
        "alerts": alerts,
        "recent": recent,
        "module_panels": module_panels,
    }
