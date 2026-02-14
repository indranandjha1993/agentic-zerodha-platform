import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class ApprovalChannel(models.TextChoices):
    DASHBOARD = "dashboard", "Dashboard"
    ADMIN = "admin", "Admin"
    TELEGRAM = "telegram", "Telegram"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELED = "canceled", "Canceled"


class DecisionType(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"


class TimeoutPolicy(models.TextChoices):
    AUTO_REJECT = "auto_reject", "Auto Reject"
    AUTO_PAUSE = "auto_pause", "Auto Pause Agent"
    ESCALATE = "escalate", "Escalate To Admin"


class ApprovalRequest(TimeStampedModel):
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_created",
    )

    channel = models.CharField(
        max_length=16,
        choices=ApprovalChannel.choices,
        default=ApprovalChannel.DASHBOARD,
    )
    status = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    required_approvals = models.PositiveSmallIntegerField(default=1)
    timeout_policy = models.CharField(
        max_length=16,
        choices=TimeoutPolicy.choices,
        default=TimeoutPolicy.AUTO_REJECT,
    )
    is_escalated = models.BooleanField(default=False)
    escalated_at = models.DateTimeField(null=True, blank=True)

    intent_payload = models.JSONField(default=dict, blank=True)
    risk_snapshot = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_decided",
    )
    decision_reason = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"ApprovalRequest<{self.id}>:{self.status}"


class ApprovalDecision(TimeStampedModel):
    approval_request = models.ForeignKey(
        ApprovalRequest,
        on_delete=models.CASCADE,
        related_name="decisions",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_decisions",
    )
    channel = models.CharField(max_length=16, choices=ApprovalChannel.choices)
    decision = models.CharField(max_length=16, choices=DecisionType.choices)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("approval_request", "actor"),
                condition=Q(actor__isnull=False),
                name="unique_decision_per_actor_per_request",
            )
        ]

    def __str__(self) -> str:
        return f"ApprovalDecision<{self.approval_request_id}>:{self.decision}"


class TelegramCallbackEvent(TimeStampedModel):
    callback_query_id = models.CharField(max_length=128, unique=True)
    approval_request = models.ForeignKey(
        ApprovalRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telegram_callback_events",
    )
    telegram_user_id = models.CharField(max_length=64, blank=True)
    decision = models.CharField(max_length=16, choices=DecisionType.choices, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=("approval_request", "created_at"))]

    def __str__(self) -> str:
        return f"TelegramCallbackEvent<{self.callback_query_id}>"
