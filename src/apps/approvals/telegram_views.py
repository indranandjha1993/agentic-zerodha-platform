import re
from typing import Any

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserProfile
from apps.approvals.models import (
    ApprovalRequest,
    DecisionType,
    TelegramCallbackEvent,
)
from apps.approvals.services.decision_engine import (
    ApprovalDecisionConflictError,
    ApprovalDecisionService,
)
from apps.approvals.services.telegram_client import TelegramClient

CALLBACK_PATTERN = re.compile(r"^approval:(?P<approval_id>\d+):(?P<decision>approve|reject)$")


class TelegramWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: tuple[type, ...] = ()

    def post(
        self,
        request: Request,
        webhook_secret: str,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        if not self._is_valid_secret(request, webhook_secret):
            return Response({"detail": "Invalid Telegram webhook secret."}, status=403)

        callback_query = request.data.get("callback_query")
        if not isinstance(callback_query, dict):
            return Response({"status": "ignored"}, status=200)

        callback_id = str(callback_query.get("id", ""))
        if callback_id == "":
            return Response({"status": "ignored"}, status=200)

        if TelegramCallbackEvent.objects.filter(callback_query_id=callback_id).exists():
            return Response({"status": "duplicate"}, status=200)

        callback_data = str(callback_query.get("data", ""))
        pattern_match = CALLBACK_PATTERN.match(callback_data)
        telegram_user_id = self._extract_telegram_user_id(callback_query)
        default_event_kwargs: dict[str, Any] = {
            "callback_query_id": callback_id,
            "telegram_user_id": telegram_user_id,
            "raw_payload": request.data,
        }

        if pattern_match is None:
            TelegramCallbackEvent.objects.create(**default_event_kwargs)
            self._answer_callback(callback_id, "Unsupported approval action.", True)
            return Response({"status": "ignored"}, status=200)

        approval_id = int(pattern_match.group("approval_id"))
        decision = pattern_match.group("decision")
        if decision not in {DecisionType.APPROVE, DecisionType.REJECT}:
            TelegramCallbackEvent.objects.create(**default_event_kwargs)
            self._answer_callback(callback_id, "Invalid decision.", True)
            return Response({"status": "ignored"}, status=200)

        profile = (
            UserProfile.objects.select_related("user")
            .filter(telegram_chat_id=telegram_user_id)
            .order_by("-updated_at")
            .first()
        )
        if profile is None:
            TelegramCallbackEvent.objects.create(decision=decision, **default_event_kwargs)
            self._answer_callback(callback_id, "This Telegram account is not linked.", True)
            return Response({"status": "unauthorized"}, status=200)

        try:
            approval_request = ApprovalRequest.objects.select_related("agent", "agent__owner").get(
                id=approval_id,
                agent__owner=profile.user,
            )
        except ApprovalRequest.DoesNotExist:
            TelegramCallbackEvent.objects.create(decision=decision, **default_event_kwargs)
            self._answer_callback(callback_id, "Approval request not found.", True)
            return Response({"status": "not_found"}, status=200)

        callback_event = TelegramCallbackEvent.objects.create(
            approval_request=approval_request,
            decision=decision,
            **default_event_kwargs,
        )
        decision_service = ApprovalDecisionService()
        reason = ApprovalDecisionService.default_reason_for_channel(
            decision,
            "telegram",
        )

        try:
            decision_service.decide(
                approval_request=approval_request,
                actor=profile.user,
                decision=decision,
                channel="telegram",
                reason=reason,
                metadata={
                    "telegram_callback_query_id": callback_id,
                    "telegram_user_id": telegram_user_id,
                },
            )
        except ApprovalDecisionConflictError:
            self._answer_callback(callback_id, "Approval request already decided.")
            return Response({"status": "already_decided"}, status=200)

        callback_message = (
            "Approved. Execution has been queued."
            if decision == DecisionType.APPROVE
            else "Rejected."
        )
        self._answer_callback(callback_id, callback_message)

        return Response(
            {"status": "processed", "callback_event_id": callback_event.id},
            status=200,
        )

    @staticmethod
    def _extract_telegram_user_id(callback_query: dict[str, Any]) -> str:
        message_chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
        if message_chat_id is not None:
            return str(message_chat_id)

        from_id = callback_query.get("from", {}).get("id")
        return str(from_id) if from_id is not None else ""

    @staticmethod
    def _is_valid_secret(request: Request, webhook_secret: str) -> bool:
        configured_secret = str(settings.TELEGRAM_WEBHOOK_SECRET)
        if configured_secret == "":
            return False

        if webhook_secret != configured_secret:
            return False

        header_secret = str(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""))
        return header_secret == configured_secret

    @staticmethod
    def _answer_callback(callback_query_id: str, message: str, show_alert: bool = False) -> None:
        client = TelegramClient()
        if not client.is_configured:
            return

        client.answer_callback_query(
            callback_query_id=callback_query_id,
            text=message,
            show_alert=show_alert,
        )
