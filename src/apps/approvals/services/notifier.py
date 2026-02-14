from typing import Any

from apps.accounts.models import UserProfile
from apps.approvals.models import ApprovalChannel, ApprovalRequest
from apps.approvals.services.telegram_client import TelegramClient


class ApprovalNotifier:
    def __init__(self, telegram_client: TelegramClient | None = None) -> None:
        self.telegram_client = telegram_client or TelegramClient()

    def notify(self, approval_request: ApprovalRequest) -> dict[str, Any]:
        channels = self._approval_channels(approval_request)
        if ApprovalChannel.TELEGRAM not in channels:
            return {
                "status": "skipped",
                "reason": "Telegram channel not configured for this agent.",
            }

        profile = (
            UserProfile.objects.select_related("user")
            .filter(user=approval_request.agent.owner)
            .order_by("-updated_at")
            .first()
        )
        if profile is None or profile.telegram_chat_id == "":
            return {"status": "skipped", "reason": "Owner has no telegram_chat_id configured."}

        response = self.telegram_client.send_approval_request(
            chat_id=profile.telegram_chat_id,
            approval_request=approval_request,
        )
        if response.get("ok"):
            return {"status": "sent"}
        return {"status": "failed", "reason": str(response.get("error", "Unknown Telegram error."))}

    @staticmethod
    def _approval_channels(approval_request: ApprovalRequest) -> set[str]:
        configured = approval_request.agent.config.get("approval_channels", [])
        if isinstance(configured, list):
            return {str(item).lower() for item in configured}
        return {approval_request.channel}
