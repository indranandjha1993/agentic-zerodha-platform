from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
    AgentStatus,
    AnalysisNotificationEventType,
    AnalysisRunStatus,
    ApprovalMode,
    ExecutionMode,
)
from apps.approvals.models import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    DecisionType,
    TelegramCallbackEvent,
    TimeoutPolicy,
)
from apps.audit.models import AuditEvent, AuditLevel
from apps.broker_kite.models import KiteSession
from apps.execution.models import IntentStatus, OrderType, ProductType, Side, TradeIntent
from apps.market_data.models import Instrument, TickSnapshot
from apps.risk.models import RiskPolicy

SEED_OWNER_RE = re.compile(r"^seed_owner_(\d+)$")
DEFAULT_PASSWORD = "SeedPass!234"
MODEL_COUNTS_ORDER = (
    "users",
    "profiles",
    "risk_policies",
    "agents",
    "analysis_runs",
    "analysis_events",
    "webhook_endpoints",
    "webhook_deliveries",
    "approval_requests",
    "approval_decisions",
    "telegram_callback_events",
    "trade_intents",
    "kite_sessions",
    "instruments",
    "tick_snapshots",
    "audit_events",
)

INSTRUMENT_CATALOG: tuple[tuple[str, str, Decimal], ...] = (
    ("RELIANCE", "Reliance Industries Ltd", Decimal("2870.50")),
    ("TCS", "Tata Consultancy Services Ltd", Decimal("4185.40")),
    ("INFY", "Infosys Ltd", Decimal("1889.25")),
    ("HDFCBANK", "HDFC Bank Ltd", Decimal("1698.80")),
    ("ICICIBANK", "ICICI Bank Ltd", Decimal("1238.55")),
    ("SBIN", "State Bank of India", Decimal("801.65")),
    ("LT", "Larsen & Toubro Ltd", Decimal("3689.35")),
    ("ITC", "ITC Ltd", Decimal("463.20")),
    ("AXISBANK", "Axis Bank Ltd", Decimal("1160.90")),
    ("MARUTI", "Maruti Suzuki India Ltd", Decimal("12105.80")),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", Decimal("1690.15")),
    ("BAJFINANCE", "Bajaj Finance Ltd", Decimal("7091.45")),
    ("HCLTECH", "HCL Technologies Ltd", Decimal("1672.40")),
    ("ULTRACEMCO", "UltraTech Cement Ltd", Decimal("10870.20")),
    ("TITAN", "Titan Company Ltd", Decimal("3594.15")),
    ("NESTLEIND", "Nestle India Ltd", Decimal("2529.30")),
    ("POWERGRID", "Power Grid Corporation of India Ltd", Decimal("346.50")),
    ("BHARTIARTL", "Bharti Airtel Ltd", Decimal("1724.95")),
    ("WIPRO", "Wipro Ltd", Decimal("585.30")),
    ("TECHM", "Tech Mahindra Ltd", Decimal("1690.45")),
    ("INDUSINDBK", "IndusInd Bank Ltd", Decimal("1588.30")),
    ("HINDUNILVR", "Hindustan Unilever Ltd", Decimal("2486.80")),
    ("ASIANPAINT", "Asian Paints Ltd", Decimal("3188.60")),
    ("NTPC", "NTPC Ltd", Decimal("398.10")),
    ("ADANIENT", "Adani Enterprises Ltd", Decimal("3095.40")),
    ("M&M", "Mahindra & Mahindra Ltd", Decimal("2939.80")),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd", Decimal("1919.70")),
    ("BAJAJFINSV", "Bajaj Finserv Ltd", Decimal("1876.20")),
    ("DRREDDY", "Dr. Reddy's Laboratories Ltd", Decimal("6898.35")),
    ("COALINDIA", "Coal India Ltd", Decimal("491.05")),
)


@dataclass(slots=True)
class SeedContext:
    run_number: int
    now: datetime
    owner: Any
    approver: Any
    primary_agent: Agent
    hedge_agent: Agent
    pending_run: AgentAnalysisRun
    running_run: AgentAnalysisRun
    completed_run: AgentAnalysisRun
    failed_run: AgentAnalysisRun
    canceled_run: AgentAnalysisRun
    endpoint: AgentAnalysisWebhookEndpoint
    pending_request: ApprovalRequest
    approved_request: ApprovalRequest
    rejected_request: ApprovalRequest
    expired_request: ApprovalRequest
    selected_instruments: list[Instrument]


def _increment(counter: Counter[str], key: str, amount: int = 1) -> None:
    counter[key] += amount


class Command(BaseCommand):
    help = (
        "Incrementally seed realistic demo data across all domain models. "
        "Every cycle appends a new linked dataset for users, agents, approvals, "
        "execution, market data, and audit."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--cycles",
            type=int,
            default=1,
            help="Number of incremental seed cycles to add in this execution.",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=DEFAULT_PASSWORD,
            help="Password used for generated seed users.",
        )

    def handle(self, *args: object, **options: object) -> None:
        cycles_raw = options.get("cycles")
        password_raw = options.get("password")
        if not isinstance(cycles_raw, int) or not isinstance(password_raw, str):
            raise CommandError("Invalid command options for seed_demo_data.")
        cycles = cycles_raw
        password = password_raw

        if cycles <= 0:
            raise CommandError("--cycles must be a positive integer.")

        base_run = self._next_seed_run_number()
        created = Counter[str]()
        completed_runs: list[int] = []

        for offset in range(cycles):
            run_number = base_run + offset
            with transaction.atomic():
                context = self._seed_cycle(
                    run_number=run_number, password=password, created=created
                )
            completed_runs.append(context.run_number)

        run_label = (
            f"run #{completed_runs[0]}"
            if len(completed_runs) == 1
            else f"runs #{completed_runs[0]} to #{completed_runs[-1]}"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo data for {run_label}. "
                f"(cycles={cycles}, generated_users={created['users']})"
            )
        )
        for model_key in MODEL_COUNTS_ORDER:
            if created[model_key] > 0:
                self.stdout.write(f"- {model_key}: +{created[model_key]}")

    def _next_seed_run_number(self) -> int:
        user_model = get_user_model()
        max_run_number = 0
        usernames = user_model.objects.filter(username__startswith="seed_owner_").values_list(
            "username",
            flat=True,
        )
        for username in usernames:
            match = SEED_OWNER_RE.match(str(username))
            if match is None:
                continue
            max_run_number = max(max_run_number, int(match.group(1)))
        return max_run_number + 1

    def _seed_cycle(self, run_number: int, password: str, created: Counter[str]) -> SeedContext:
        now = timezone.now()
        owner = self._create_seed_user(
            username=f"seed_owner_{run_number:04d}",
            email=f"seed.owner.{run_number:04d}@example.com",
            password=password,
            first_name="Seed",
            last_name=f"Owner {run_number}",
        )
        approver = self._create_seed_user(
            username=f"seed_approver_{run_number:04d}",
            email=f"seed.approver.{run_number:04d}@example.com",
            password=password,
            first_name="Seed",
            last_name=f"Approver {run_number}",
        )
        _increment(created, "users", amount=2)

        UserProfile.objects.create(
            user=owner,
            telegram_chat_id=str(9_000_000_000 + run_number),
            timezone="Asia/Kolkata",
        )
        UserProfile.objects.create(
            user=approver,
            telegram_chat_id=str(9_100_000_000 + run_number),
            timezone="Asia/Kolkata",
        )
        _increment(created, "profiles", amount=2)

        default_policy = RiskPolicy.objects.create(
            owner=owner,
            name=f"Core Intraday Policy {run_number:04d}",
            max_order_notional=Decimal("150000"),
            max_position_notional=Decimal("350000"),
            max_daily_loss=Decimal("12500"),
            max_orders_per_day=32,
            allowed_symbols=["RELIANCE", "TCS", "INFY", "HDFCBANK"],
            require_market_hours=True,
            allow_shorting=False,
            is_default=True,
        )
        RiskPolicy.objects.create(
            owner=owner,
            name=f"Aggressive Policy {run_number:04d}",
            max_order_notional=Decimal("250000"),
            max_position_notional=Decimal("750000"),
            max_daily_loss=Decimal("40000"),
            max_orders_per_day=64,
            allowed_symbols=["NIFTY", "BANKNIFTY", "FINNIFTY"],
            require_market_hours=True,
            allow_shorting=True,
            is_default=False,
        )
        _increment(created, "risk_policies", amount=2)

        selected_instruments = self._create_instruments_for_cycle(
            run_number=run_number, created=created
        )

        primary_agent = Agent.objects.create(
            owner=owner,
            risk_policy=default_policy,
            name=f"Momentum Pulse {run_number:04d}",
            slug=f"momentum-pulse-{run_number:04d}",
            instruction=(
                "Track trend, relative volume, and institutional flow. "
                "Generate directional trade ideas only when risk limits allow."
            ),
            status=AgentStatus.ACTIVE,
            execution_mode=ExecutionMode.LIVE if run_number % 2 == 0 else ExecutionMode.PAPER,
            approval_mode=ApprovalMode.RISK_BASED,
            required_approvals=2 if run_number % 2 == 0 else 1,
            schedule_cron="*/15 9-15 * * 1-5",
            config={
                "watchlist": [instrument.tradingsymbol for instrument in selected_instruments],
                "max_position_concentration": 0.35,
                "analysis_style": "macro+technical",
                "seed_run": run_number,
            },
            is_predictive=True,
            is_auto_enabled=True,
            last_run_at=now - timedelta(minutes=4),
        )
        hedge_agent = Agent.objects.create(
            owner=owner,
            risk_policy=default_policy,
            name=f"Hedge Sentinel {run_number:04d}",
            slug=f"hedge-sentinel-{run_number:04d}",
            instruction=(
                "Monitor drawdown and volatility spikes. "
                "Escalate to human approvals before any hedging action."
            ),
            status=AgentStatus.PAUSED,
            execution_mode=ExecutionMode.PAPER,
            approval_mode=ApprovalMode.ALWAYS,
            required_approvals=1,
            schedule_cron="*/30 9-15 * * 1-5",
            config={
                "hedge_instruments": ["NIFTY", "BANKNIFTY"],
                "alert_drawdown_pct": 1.5,
                "seed_run": run_number,
            },
            is_predictive=False,
            is_auto_enabled=False,
            last_run_at=now - timedelta(hours=1, minutes=15),
        )
        primary_agent.approvers.add(approver, owner)
        hedge_agent.approvers.add(approver)
        _increment(created, "agents", amount=2)

        pending_run = AgentAnalysisRun.objects.create(
            agent=primary_agent,
            requested_by=owner,
            status=AnalysisRunStatus.PENDING,
            query=f"Pre-open setup for {selected_instruments[0].tradingsymbol}",
            model=settings.OPENROUTER_DEFAULT_MODEL,
            max_steps=6,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            metadata={"source": "seed_demo_data", "seed_run": run_number},
        )
        running_run = AgentAnalysisRun.objects.create(
            agent=primary_agent,
            requested_by=owner,
            status=AnalysisRunStatus.RUNNING,
            query=f"Intraday momentum check for {selected_instruments[1].tradingsymbol}",
            model=settings.OPENROUTER_DEFAULT_MODEL,
            max_steps=6,
            steps_executed=3,
            usage={"prompt_tokens": 920, "completion_tokens": 180},
            started_at=now - timedelta(minutes=7),
            metadata={"phase": "research", "seed_run": run_number},
        )
        completed_run = AgentAnalysisRun.objects.create(
            agent=primary_agent,
            requested_by=owner,
            status=AnalysisRunStatus.COMPLETED,
            query=f"Synthesize news and order-flow for {selected_instruments[2].tradingsymbol}",
            model=settings.OPENROUTER_DEFAULT_MODEL,
            max_steps=7,
            steps_executed=7,
            usage={"prompt_tokens": 1820, "completion_tokens": 560},
            result_text=(
                "Signal quality is positive with confirming breadth; "
                "recommend scaled entry with protective stop under VWAP."
            ),
            started_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=21),
            metadata={"confidence": 0.74, "seed_run": run_number},
        )
        failed_run = AgentAnalysisRun.objects.create(
            agent=hedge_agent,
            requested_by=owner,
            status=AnalysisRunStatus.FAILED,
            query="Evaluate hedge trigger after volatility expansion",
            model=settings.OPENROUTER_DEFAULT_MODEL,
            max_steps=5,
            steps_executed=2,
            usage={"prompt_tokens": 640, "completion_tokens": 70},
            error_message="Web research timeout while fetching macro event feed.",
            started_at=now - timedelta(minutes=18),
            completed_at=now - timedelta(minutes=16),
            metadata={"retryable": True, "seed_run": run_number},
        )
        canceled_run = AgentAnalysisRun.objects.create(
            agent=hedge_agent,
            requested_by=owner,
            status=AnalysisRunStatus.CANCELED,
            query="Risk-on/risk-off classifier before noon session",
            model=settings.OPENROUTER_DEFAULT_MODEL,
            max_steps=5,
            steps_executed=1,
            usage={"prompt_tokens": 200, "completion_tokens": 20},
            started_at=now - timedelta(minutes=11),
            completed_at=now - timedelta(minutes=10),
            metadata={"cancel_reason": "operator_cancel", "seed_run": run_number},
        )
        _increment(created, "analysis_runs", amount=5)

        analysis_events_count = 0
        analysis_events_count += self._create_analysis_events(
            run=running_run,
            events=(
                ("analysis.started", {"state": "running"}),
                ("tool.google_search", {"query": running_run.query}),
                ("analysis.partial", {"confidence": 0.51}),
            ),
        )
        analysis_events_count += self._create_analysis_events(
            run=completed_run,
            events=(
                ("analysis.started", {"state": "running"}),
                ("analysis.signal", {"direction": "long", "confidence": 0.74}),
                ("analysis.completed", {"verdict": "buy_on_pullback"}),
            ),
        )
        analysis_events_count += self._create_analysis_events(
            run=failed_run,
            events=(
                ("analysis.started", {"state": "running"}),
                ("analysis.error", {"reason": "web_fetch_timeout"}),
            ),
        )
        analysis_events_count += self._create_analysis_events(
            run=canceled_run,
            events=(
                ("analysis.started", {"state": "running"}),
                ("analysis.canceled", {"reason": "manual_stop"}),
            ),
        )
        _increment(created, "analysis_events", amount=analysis_events_count)

        endpoint = AgentAnalysisWebhookEndpoint.objects.create(
            owner=owner,
            name=f"seed-webhook-{run_number:04d}",
            callback_url=f"https://seed-{run_number:04d}.example.com/analysis/webhook",
            signing_secret_encrypted=f"seed-signing-secret-{run_number:04d}",
            is_active=True,
            event_types=[
                AnalysisNotificationEventType.RUN_COMPLETED,
                AnalysisNotificationEventType.RUN_FAILED,
                AnalysisNotificationEventType.RUN_CANCELED,
            ],
            headers={"X-Seed-Run": str(run_number), "X-Environment": "demo"},
        )
        _increment(created, "webhook_endpoints")

        AgentAnalysisNotificationDelivery.objects.create(
            endpoint=endpoint,
            run=completed_run,
            event_type=AnalysisNotificationEventType.RUN_COMPLETED,
            success=True,
            status_code=200,
            attempt_count=1,
            max_attempts=3,
            last_attempt_at=now - timedelta(minutes=20),
            delivered_at=now - timedelta(minutes=20),
            request_payload={"run_id": completed_run.id, "status": completed_run.status},
            response_body='{"ok":true}',
        )
        AgentAnalysisNotificationDelivery.objects.create(
            endpoint=endpoint,
            run=failed_run,
            event_type=AnalysisNotificationEventType.RUN_FAILED,
            success=False,
            status_code=502,
            attempt_count=2,
            max_attempts=4,
            last_attempt_at=now - timedelta(minutes=14),
            next_retry_at=now + timedelta(minutes=3),
            request_payload={"run_id": failed_run.id, "status": failed_run.status},
            response_body="upstream temporarily unavailable",
            error_message="HTTP 502 from subscriber endpoint",
        )
        AgentAnalysisNotificationDelivery.objects.create(
            endpoint=endpoint,
            run=canceled_run,
            event_type=AnalysisNotificationEventType.RUN_CANCELED,
            success=False,
            status_code=410,
            attempt_count=3,
            max_attempts=3,
            last_attempt_at=now - timedelta(minutes=9),
            request_payload={"run_id": canceled_run.id, "status": canceled_run.status},
            response_body="resource gone",
            error_message="Subscriber rejected canceled state callback",
        )
        _increment(created, "webhook_deliveries", amount=3)

        pending_request = ApprovalRequest.objects.create(
            agent=primary_agent,
            requested_by=owner,
            channel=ApprovalChannel.DASHBOARD,
            status=ApprovalStatus.PENDING,
            required_approvals=primary_agent.required_approvals,
            timeout_policy=TimeoutPolicy.ESCALATE,
            is_escalated=False,
            intent_payload={
                "symbol": selected_instruments[0].tradingsymbol,
                "side": Side.BUY,
                "quantity": 5,
            },
            risk_snapshot={"risk_score": 42, "max_notional_used_pct": 37.8},
            notes="Awaiting desk sign-off after strong opening trend.",
            expires_at=now + timedelta(minutes=35),
        )
        approved_request = ApprovalRequest.objects.create(
            agent=primary_agent,
            requested_by=owner,
            channel=ApprovalChannel.TELEGRAM,
            status=ApprovalStatus.APPROVED,
            required_approvals=1,
            timeout_policy=TimeoutPolicy.AUTO_REJECT,
            is_escalated=False,
            intent_payload={
                "symbol": selected_instruments[1].tradingsymbol,
                "side": Side.BUY,
                "quantity": 3,
            },
            risk_snapshot={"risk_score": 28, "max_notional_used_pct": 24.2},
            notes="Telegram desk approved after quick liquidity check.",
            expires_at=now + timedelta(minutes=20),
            decided_at=now - timedelta(minutes=16),
            decided_by=approver,
            decision_reason="Depth was healthy and spread stayed below threshold.",
        )
        rejected_request = ApprovalRequest.objects.create(
            agent=hedge_agent,
            requested_by=owner,
            channel=ApprovalChannel.ADMIN,
            status=ApprovalStatus.REJECTED,
            required_approvals=1,
            timeout_policy=TimeoutPolicy.AUTO_REJECT,
            is_escalated=False,
            intent_payload={
                "symbol": selected_instruments[2].tradingsymbol,
                "side": Side.SELL,
                "quantity": 4,
            },
            risk_snapshot={"risk_score": 81, "max_notional_used_pct": 92.1},
            notes="Rejected due to concentration breach on sector exposure.",
            expires_at=now - timedelta(minutes=2),
            decided_at=now - timedelta(minutes=12),
            decided_by=owner,
            decision_reason="Order breached max position notional.",
        )
        expired_request = ApprovalRequest.objects.create(
            agent=hedge_agent,
            requested_by=owner,
            channel=ApprovalChannel.DASHBOARD,
            status=ApprovalStatus.EXPIRED,
            required_approvals=1,
            timeout_policy=TimeoutPolicy.AUTO_PAUSE,
            is_escalated=True,
            escalated_at=now - timedelta(minutes=44),
            intent_payload={
                "symbol": selected_instruments[0].tradingsymbol,
                "side": Side.BUY,
                "quantity": 2,
            },
            risk_snapshot={"risk_score": 65, "max_notional_used_pct": 61.3},
            notes="Escalated request timed out without desk response.",
            expires_at=now - timedelta(minutes=40),
            decided_at=now - timedelta(minutes=39),
            decision_reason="Timeout policy expired after escalation window.",
        )
        _increment(created, "approval_requests", amount=4)

        ApprovalDecision.objects.create(
            approval_request=approved_request,
            actor=approver,
            channel=ApprovalChannel.TELEGRAM,
            decision=DecisionType.APPROVE,
            reason="Approved on Telegram with confidence 0.74 setup.",
            metadata={"seed_run": run_number, "source": "telegram"},
        )
        ApprovalDecision.objects.create(
            approval_request=rejected_request,
            actor=owner,
            channel=ApprovalChannel.ADMIN,
            decision=DecisionType.REJECT,
            reason="Rejected in admin after risk dashboard alert.",
            metadata={"seed_run": run_number, "source": "admin"},
        )
        ApprovalDecision.objects.create(
            approval_request=expired_request,
            actor=None,
            channel=ApprovalChannel.DASHBOARD,
            decision=DecisionType.REJECT,
            reason="Auto-rejected after SLA timeout.",
            metadata={"seed_run": run_number, "source": "timeout"},
        )
        _increment(created, "approval_decisions", amount=3)

        TelegramCallbackEvent.objects.create(
            callback_query_id=f"seed-callback-{run_number:04d}-approve",
            approval_request=approved_request,
            telegram_user_id=str(9_100_000_000 + run_number),
            decision=DecisionType.APPROVE,
            raw_payload={"action": "approve", "seed_run": run_number},
        )
        TelegramCallbackEvent.objects.create(
            callback_query_id=f"seed-callback-{run_number:04d}-reject",
            approval_request=rejected_request,
            telegram_user_id=str(9_100_000_000 + run_number),
            decision=DecisionType.REJECT,
            raw_payload={"action": "reject", "seed_run": run_number},
        )
        _increment(created, "telegram_callback_events", amount=2)

        TradeIntent.objects.create(
            agent=primary_agent,
            approval_request=pending_request,
            symbol=selected_instruments[0].tradingsymbol,
            exchange=selected_instruments[0].exchange,
            side=Side.BUY,
            quantity=5,
            order_type=OrderType.LIMIT,
            product=ProductType.CNC,
            price=Decimal("1000.00"),
            status=IntentStatus.PENDING_APPROVAL,
            request_payload={"seed_run": run_number, "strategy": "momentum_pullback"},
        )
        TradeIntent.objects.create(
            agent=primary_agent,
            approval_request=approved_request,
            symbol=selected_instruments[1].tradingsymbol,
            exchange=selected_instruments[1].exchange,
            side=Side.BUY,
            quantity=3,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=Decimal("1200.00"),
            status=IntentStatus.PLACED,
            broker_order_id=f"KITE-{run_number:04d}-01",
            request_payload={"seed_run": run_number, "strategy": "trend_follow"},
            broker_response={"status": "success", "broker_message": "order placed"},
            placed_at=now - timedelta(minutes=15),
        )
        TradeIntent.objects.create(
            agent=hedge_agent,
            approval_request=rejected_request,
            symbol=selected_instruments[2].tradingsymbol,
            exchange=selected_instruments[2].exchange,
            side=Side.SELL,
            quantity=4,
            order_type=OrderType.LIMIT,
            product=ProductType.NRML,
            price=Decimal("950.00"),
            status=IntentStatus.FAILED,
            request_payload={"seed_run": run_number, "strategy": "hedge_breakout"},
            failure_reason="Blocked by risk gate: max position notional exceeded.",
        )
        TradeIntent.objects.create(
            agent=hedge_agent,
            approval_request=expired_request,
            symbol=selected_instruments[0].tradingsymbol,
            exchange=selected_instruments[0].exchange,
            side=Side.BUY,
            quantity=2,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=Decimal("1015.00"),
            status=IntentStatus.CANCELED,
            request_payload={"seed_run": run_number, "strategy": "volatility_hedge"},
            failure_reason="Canceled because approval request expired.",
        )
        _increment(created, "trade_intents", amount=4)

        self._create_kite_session(
            user_id=int(owner.id),
            kite_user_id=f"KITESEED{run_number:04d}",
            public_token=f"public-token-{run_number:04d}",
            access_token_last4=f"{run_number % 10_000:04d}",
            session_expires_at=now + timedelta(hours=8),
            is_active=True,
            metadata={"seed_run": run_number, "profile": "owner"},
        )
        self._create_kite_session(
            user_id=int(approver.id),
            kite_user_id=f"KITEAPPROVER{run_number:04d}",
            public_token=f"public-token-approver-{run_number:04d}",
            access_token_last4=f"{(run_number + 77) % 10_000:04d}",
            session_expires_at=now - timedelta(hours=2),
            is_active=False,
            metadata={"seed_run": run_number, "profile": "approver"},
        )
        _increment(created, "kite_sessions", amount=2)

        AuditEvent.objects.create(
            actor=owner,
            event_type="seed.cycle.started",
            level=AuditLevel.INFO,
            entity_type="seed_run",
            entity_id=str(run_number),
            request_id=f"seed-{run_number:04d}-01",
            payload={"seed_run": run_number, "phase": "start"},
            message="Seed cycle initialized for demo environment.",
        )
        AuditEvent.objects.create(
            actor=owner,
            event_type="analysis.run.completed",
            level=AuditLevel.INFO,
            entity_type="agent_analysis_run",
            entity_id=str(completed_run.id),
            request_id=f"seed-{run_number:04d}-02",
            payload={"seed_run": run_number, "run_id": completed_run.id},
            message="Completed analysis run delivered strong long-bias signal.",
        )
        AuditEvent.objects.create(
            actor=approver,
            event_type="approval.request.overdue",
            level=AuditLevel.WARNING,
            entity_type="approval_request",
            entity_id=str(expired_request.id),
            request_id=f"seed-{run_number:04d}-03",
            payload={"seed_run": run_number, "request_id": expired_request.id},
            message="Escalated approval request expired without final decision.",
        )
        AuditEvent.objects.create(
            actor=owner,
            event_type="execution.intent.failed",
            level=AuditLevel.ERROR,
            entity_type="trade_intent",
            entity_id=str(rejected_request.trade_intent.id),
            request_id=f"seed-{run_number:04d}-04",
            payload={"seed_run": run_number, "intent_status": IntentStatus.FAILED},
            message="Trade intent rejected due to risk concentration limits.",
        )
        AuditEvent.objects.create(
            actor=owner,
            event_type="seed.cycle.completed",
            level=AuditLevel.INFO,
            entity_type="seed_run",
            entity_id=str(run_number),
            request_id=f"seed-{run_number:04d}-05",
            payload={"seed_run": run_number, "phase": "complete"},
            message="Seed cycle completed successfully.",
        )
        _increment(created, "audit_events", amount=5)

        return SeedContext(
            run_number=run_number,
            now=now,
            owner=owner,
            approver=approver,
            primary_agent=primary_agent,
            hedge_agent=hedge_agent,
            pending_run=pending_run,
            running_run=running_run,
            completed_run=completed_run,
            failed_run=failed_run,
            canceled_run=canceled_run,
            endpoint=endpoint,
            pending_request=pending_request,
            approved_request=approved_request,
            rejected_request=rejected_request,
            expired_request=expired_request,
            selected_instruments=selected_instruments,
        )

    def _create_seed_user(
        self,
        username: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> Any:
        user_model = get_user_model()
        return user_model.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_staff=True,
        )

    def _create_instruments_for_cycle(
        self, run_number: int, created: Counter[str]
    ) -> list[Instrument]:
        created_instruments: list[Instrument] = []
        catalog_size = len(INSTRUMENT_CATALOG)
        start = (run_number - 1) * 3
        token_base = 10_000_000 + (run_number * 100)

        for offset in range(3):
            symbol, company_name, base_price = INSTRUMENT_CATALOG[(start + offset) % catalog_size]
            exchange = "NSE" if offset < 2 else "BSE"
            segment = exchange
            tradingsymbol = symbol
            exists = Instrument.objects.filter(
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                segment=segment,
            ).exists()
            if exists:
                tradingsymbol = f"{symbol}{run_number:04d}{offset}"

            instrument = Instrument.objects.create(
                instrument_token=token_base + offset,
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                name=company_name,
                segment=segment,
                instrument_type="EQ",
                lot_size=1,
                tick_size=Decimal("0.05"),
                is_active=True,
            )
            created_instruments.append(instrument)
            _increment(created, "instruments")

            for tick_offset in range(2):
                price = (
                    base_price
                    + Decimal(run_number % 7)
                    + Decimal(offset) * Decimal("0.35")
                    + Decimal(tick_offset) * Decimal("0.25")
                ).quantize(Decimal("0.01"))
                TickSnapshot.objects.create(
                    instrument=instrument,
                    last_price=price,
                    volume=150_000
                    + (run_number * 5_000)
                    + (offset * 10_000)
                    + (tick_offset * 4_000),
                    oi=95_000 + (run_number * 400) + (offset * 750),
                    source="kite_ticker" if tick_offset == 0 else "seed_replay",
                )
                _increment(created, "tick_snapshots")

        return created_instruments

    def _create_analysis_events(
        self,
        run: AgentAnalysisRun,
        events: tuple[tuple[str, dict[str, Any]], ...],
    ) -> int:
        count = 0
        for idx, (event_type, payload) in enumerate(events, start=1):
            AgentAnalysisEvent.objects.create(
                run=run,
                sequence=idx,
                event_type=event_type,
                payload=payload,
            )
            count += 1
        return count

    def _create_kite_session(
        self,
        *,
        user_id: int,
        kite_user_id: str,
        public_token: str,
        access_token_last4: str,
        session_expires_at: datetime | None,
        is_active: bool,
        metadata: dict[str, Any],
    ) -> None:
        KiteSession.objects.create(
            user_id=user_id,
            kite_user_id=kite_user_id,
            public_token=public_token,
            access_token_last4=access_token_last4,
            session_expires_at=session_expires_at,
            is_active=is_active,
            metadata=metadata,
        )
