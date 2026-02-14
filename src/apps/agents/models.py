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
