from typing import Any

from celery import shared_task

from apps.approvals.models import ApprovalRequest
from apps.approvals.services.notifier import ApprovalNotifier


@shared_task(bind=True, max_retries=3)
def notify_approval_request_task(self: Any, approval_request_id: int) -> dict[str, str]:
    approval_request = ApprovalRequest.objects.select_related("agent", "agent__owner").get(
        id=approval_request_id
    )
    notifier = ApprovalNotifier()
    return notifier.notify(approval_request)
