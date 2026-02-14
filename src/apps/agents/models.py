from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AgentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ARCHIVED = "archived", "Archived"


class ExecutionMode(models.TextChoices):
    PAPER = "paper", "Paper"
    LIVE = "live", "Live"


class ApprovalMode(models.TextChoices):
    NONE = "none", "None"
    ALWAYS = "always", "Always"
    RISK_BASED = "risk_based", "Risk Based"


class Agent(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agents",
    )
    risk_policy = models.ForeignKey(
        "risk.RiskPolicy",
        on_delete=models.SET_NULL,
        related_name="agents",
        null=True,
        blank=True,
    )
    approvers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="agent_approvals",
        blank=True,
    )

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    instruction = models.TextField()

    status = models.CharField(max_length=16, choices=AgentStatus.choices, default=AgentStatus.DRAFT)
    execution_mode = models.CharField(
        max_length=16,
        choices=ExecutionMode.choices,
        default=ExecutionMode.PAPER,
    )
    approval_mode = models.CharField(
        max_length=16,
        choices=ApprovalMode.choices,
        default=ApprovalMode.RISK_BASED,
    )
    required_approvals = models.PositiveSmallIntegerField(default=1)

    schedule_cron = models.CharField(max_length=100, blank=True)
    config = models.JSONField(default=dict, blank=True)

    is_predictive = models.BooleanField(default=False)
    is_auto_enabled = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "slug"), name="unique_agent_slug_per_owner")
        ]

    def __str__(self) -> str:
        return f"{self.owner_id}:{self.slug}"


class AnalysisRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


class AnalysisNotificationEventType(models.TextChoices):
    RUN_COMPLETED = "analysis_run.completed", "Analysis Run Completed"
    RUN_FAILED = "analysis_run.failed", "Analysis Run Failed"
    RUN_CANCELED = "analysis_run.canceled", "Analysis Run Canceled"


def default_analysis_notification_event_types() -> list[str]:
    return [
        "analysis_run.completed",
        "analysis_run.failed",
        "analysis_run.canceled",
    ]


class AgentAnalysisRun(TimeStampedModel):
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name="analysis_runs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_analysis_runs",
    )

    status = models.CharField(
        max_length=16,
        choices=AnalysisRunStatus.choices,
        default=AnalysisRunStatus.PENDING,
    )
    query = models.TextField()
    model = models.CharField(max_length=128, blank=True)
    max_steps = models.PositiveSmallIntegerField(default=6)
    steps_executed = models.PositiveIntegerField(default=0)
    usage = models.JSONField(default=dict, blank=True)

    result_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("agent", "created_at")),
            models.Index(fields=("status", "created_at")),
        ]

    def __str__(self) -> str:
        return f"AnalysisRun<{self.id}:{self.status}>"


class AgentAnalysisEvent(TimeStampedModel):
    run = models.ForeignKey(
        AgentAnalysisRun,
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("run", "sequence"),
                name="unique_analysis_event_sequence_per_run",
            )
        ]
        indexes = [
            models.Index(fields=("run", "sequence")),
            models.Index(fields=("event_type", "created_at")),
        ]

    def __str__(self) -> str:
        return f"AnalysisEvent<{self.run_id}:{self.sequence}:{self.event_type}>"


class AgentAnalysisWebhookEndpoint(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analysis_webhook_endpoints",
    )
    name = models.CharField(max_length=128)
    callback_url = models.URLField(max_length=500)
    signing_secret_encrypted = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    event_types = models.JSONField(
        default=default_analysis_notification_event_types,
        blank=True,
    )
    headers = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"),
                name="unique_analysis_webhook_name_per_owner",
            )
        ]
        indexes = [models.Index(fields=("owner", "is_active"))]

    def __str__(self) -> str:
        return f"AnalysisWebhook<{self.owner_id}:{self.name}>"

    def supports_event_type(self, event_type: str) -> bool:
        configured = self.event_types if isinstance(self.event_types, list) else []
        return event_type in {str(item) for item in configured}


class AgentAnalysisNotificationDelivery(TimeStampedModel):
    endpoint = models.ForeignKey(
        AgentAnalysisWebhookEndpoint,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    run = models.ForeignKey(
        AgentAnalysisRun,
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    event_type = models.CharField(max_length=64, choices=AnalysisNotificationEventType.choices)
    success = models.BooleanField(default=False)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_body = models.TextField(blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "run", "event_type"),
                name="unique_analysis_delivery_per_endpoint_run_event",
            )
        ]
        indexes = [
            models.Index(fields=("run", "created_at")),
            models.Index(fields=("endpoint", "created_at")),
            models.Index(fields=("event_type", "created_at")),
        ]

    def __str__(self) -> str:
        return f"AnalysisDelivery<{self.run_id}:{self.event_type}:{self.success}>"
