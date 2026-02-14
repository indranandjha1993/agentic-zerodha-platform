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
