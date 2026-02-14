from collections import Counter
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.approvals.models import ApprovalRequest, ApprovalStatus
from apps.approvals.services.decision_engine import ApprovalDecisionService
from apps.approvals.services.notifier import ApprovalNotifier
from apps.audit.models import AuditEvent, AuditLevel


@shared_task(bind=True, max_retries=3)
def notify_approval_request_task(self: Any, approval_request_id: int) -> dict[str, str]:
    approval_request = ApprovalRequest.objects.select_related("agent", "agent__owner").get(
        id=approval_request_id
    )
    notifier = ApprovalNotifier()
    return notifier.notify(approval_request)


@shared_task(bind=True, max_retries=3)
def process_expired_approval_requests_task(
    self: Any,
    batch_size: int = 200,
) -> dict[str, int]:
    now = timezone.now()
    queryset = (
        ApprovalRequest.objects.select_related("agent", "agent__owner")
        .filter(
            status=ApprovalStatus.PENDING,
            expires_at__isnull=False,
            expires_at__lte=now,
        )
        .order_by("expires_at")[:batch_size]
    )

    decision_service = ApprovalDecisionService()
    action_counter: Counter[str] = Counter()

    for approval_request in queryset:
        outcome = decision_service.apply_timeout_policy(
            approval_request=approval_request,
            current_time=now,
        )
        action_counter[outcome.action] += 1

        if outcome.action != "skipped_non_pending":
            AuditEvent.objects.create(
                actor=None,
                event_type="approval_timeout_policy_applied",
                level=AuditLevel.WARNING if outcome.action.startswith("auto_") else AuditLevel.INFO,
                entity_type="approval_request",
                entity_id=str(approval_request.id),
                payload={
                    "action": outcome.action,
                    "status": approval_request.status,
                    "timeout_policy": approval_request.timeout_policy,
                },
                message="Timeout policy processing executed for approval request.",
            )

    response = {key: int(value) for key, value in action_counter.items()}
    response["processed"] = int(sum(action_counter.values()))
    return response
