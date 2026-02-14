import re
from typing import Any, cast

from django.conf import settings
from django.db.models import Q
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserProfile
from apps.approvals.models import ApprovalRequest, DecisionType, TelegramCallbackEvent
from apps.approvals.services.decision_engine import (
    ApprovalDecisionConflictError,
    ApprovalDecisionDuplicateError,
    ApprovalDecisionPermissionError,
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
        if isinstance(callback_query, dict):
            return self._handle_callback_query(request=request, callback_query=callback_query)

        message = request.data.get("message")
        if isinstance(message, dict):
            return self._handle_message_command(message=message)

        return Response({"status": "ignored"}, status=200)

    def _handle_callback_query(
        self,
        *,
        request: Request,
        callback_query: dict[str, Any],
    ) -> Response:
        callback_id = str(callback_query.get("id", ""))
        if callback_id == "":
            return Response({"status": "ignored"}, status=200)

        if TelegramCallbackEvent.objects.filter(callback_query_id=callback_id).exists():
            return Response({"status": "duplicate"}, status=200)

        callback_data = str(callback_query.get("data", ""))
        pattern_match = CALLBACK_PATTERN.match(callback_data)
        telegram_user_id = self._extract_chat_id(callback_query)
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

        profile = self._get_profile_by_telegram_chat_id(telegram_user_id)
        if profile is None:
            TelegramCallbackEvent.objects.create(decision=decision, **default_event_kwargs)
            self._answer_callback(callback_id, "This Telegram account is not linked.", True)
            return Response({"status": "unauthorized"}, status=200)

        approval_request = self._get_accessible_approval_request(
            user=profile.user,
            approval_id=approval_id,
        )
        if approval_request is None:
            TelegramCallbackEvent.objects.create(decision=decision, **default_event_kwargs)
            self._answer_callback(callback_id, "Approval request not found.", True)
            return Response({"status": "not_found"}, status=200)

        callback_event = TelegramCallbackEvent.objects.create(
            approval_request=approval_request,
            decision=decision,
            **default_event_kwargs,
        )

        reason = ApprovalDecisionService.default_reason_for_channel(decision, "telegram")
        outcome = self._decide_with_service(
            approval_request=approval_request,
            actor=profile.user,
            decision=decision,
            channel="telegram",
            reason=reason,
            callback_id=callback_id,
            telegram_user_id=telegram_user_id,
        )
        if outcome is None:
            return Response({"status": "already_decided"}, status=200)

        if decision == DecisionType.REJECT:
            callback_message = "Rejected."
        elif outcome.is_final:
            callback_message = "Approved. Execution has been queued."
        else:
            remaining = outcome.required_approvals - outcome.approved_count
            callback_message = f"Approval recorded. Waiting for {remaining} more approval(s)."
        self._answer_callback(callback_id, callback_message)

        return Response(
            {"status": "processed", "callback_event_id": callback_event.id},
            status=200,
        )

    def _handle_message_command(self, *, message: dict[str, Any]) -> Response:
        text = str(message.get("text", "")).strip()
        if not text.startswith("/"):
            return Response({"status": "ignored"}, status=200)

        chat_id = self._extract_chat_id(message)
        profile = self._get_profile_by_telegram_chat_id(chat_id)
        if profile is None:
            self._send_text(
                chat_id=chat_id,
                text="This Telegram chat is not linked to any user profile.",
            )
            return Response({"status": "unauthorized"}, status=200)

        command, args = self._parse_command(text)
        if command == "/help":
            self._send_text(chat_id=chat_id, text=self._help_text())
            return Response({"status": "command_processed"}, status=200)
        if command == "/pending":
            return self._handle_pending_command(chat_id=chat_id, profile=profile, args=args)
        if command == "/status":
            return self._handle_status_command(chat_id=chat_id, profile=profile, args=args)
        if command in {"/approve", "/reject"}:
            return self._handle_decision_command(
                chat_id=chat_id,
                profile=profile,
                command=command,
                args=args,
            )

        self._send_text(chat_id=chat_id, text="Unsupported command. Use /help.")
        return Response({"status": "ignored"}, status=200)

    def _handle_pending_command(
        self,
        *,
        chat_id: str,
        profile: UserProfile,
        args: list[str],
    ) -> Response:
        limit = 5
        if args and args[0].isdigit():
            limit = max(1, min(int(args[0]), 10))

        queryset = (
            ApprovalRequest.objects.filter(
                Q(agent__owner=profile.user) | Q(agent__approvers=profile.user),
                status="pending",
            )
            .exclude(decisions__actor=profile.user)
            .select_related("agent")
            .distinct()
            .order_by("expires_at", "created_at")[:limit]
        )
        if not queryset:
            self._send_text(chat_id=chat_id, text="No pending approvals for you.")
            return Response({"status": "command_processed"}, status=200)

        lines = ["Pending approvals:"]
        for item in queryset:
            symbol = str(item.intent_payload.get("symbol", "-"))
            lines.append(
                f"- #{item.id} {item.agent.name} | {symbol} | "
                f"pending approvals: {item.required_approvals}"
            )
        lines.append("Use /status <id>, /approve <id> [reason], /reject <id> [reason].")
        self._send_text(chat_id=chat_id, text="\n".join(lines))
        return Response({"status": "command_processed"}, status=200)

    def _handle_status_command(
        self,
        *,
        chat_id: str,
        profile: UserProfile,
        args: list[str],
    ) -> Response:
        if not args or not args[0].isdigit():
            self._send_text(chat_id=chat_id, text="Usage: /status <approval_request_id>")
            return Response({"status": "command_processed"}, status=200)

        approval_request = self._get_accessible_approval_request(
            user=profile.user,
            approval_id=int(args[0]),
        )
        if approval_request is None:
            self._send_text(chat_id=chat_id, text="Approval request not found.")
            return Response({"status": "command_processed"}, status=200)

        approved_count = approval_request.decisions.filter(decision=DecisionType.APPROVE).count()
        lines = [
            f"Request #{approval_request.id}",
            f"Agent: {approval_request.agent.name}",
            f"Status: {approval_request.status}",
            f"Approved count: {approved_count}/{approval_request.required_approvals}",
            f"Timeout policy: {approval_request.timeout_policy}",
        ]
        if approval_request.expires_at is not None:
            lines.append(f"Expires at: {approval_request.expires_at.isoformat()}")
        self._send_text(chat_id=chat_id, text="\n".join(lines))
        return Response({"status": "command_processed"}, status=200)

    def _handle_decision_command(
        self,
        *,
        chat_id: str,
        profile: UserProfile,
        command: str,
        args: list[str],
    ) -> Response:
        if not args or not args[0].isdigit():
            self._send_text(
                chat_id=chat_id,
                text=f"Usage: {command} <approval_request_id> [reason]",
            )
            return Response({"status": "command_processed"}, status=200)

        approval_request = self._get_accessible_approval_request(
            user=profile.user,
            approval_id=int(args[0]),
        )
        if approval_request is None:
            self._send_text(chat_id=chat_id, text="Approval request not found.")
            return Response({"status": "command_processed"}, status=200)

        decision = "approve" if command == "/approve" else "reject"
        reason = " ".join(args[1:]).strip()
        if reason == "":
            reason = ApprovalDecisionService.default_reason_for_channel(decision, "telegram")

        outcome = self._decide_with_service(
            approval_request=approval_request,
            actor=profile.user,
            decision=decision,
            channel="telegram",
            reason=reason,
            callback_id="",
            telegram_user_id=chat_id,
        )
        if outcome is None:
            self._send_text(chat_id=chat_id, text="Approval request already decided.")
            return Response({"status": "command_processed"}, status=200)

        if decision == DecisionType.REJECT:
            text = "Rejected."
        elif outcome.is_final:
            text = "Approved. Execution has been queued."
        else:
            remaining = outcome.required_approvals - outcome.approved_count
            text = f"Approval recorded. Waiting for {remaining} more approval(s)."
        self._send_text(chat_id=chat_id, text=text)
        return Response({"status": "command_processed"}, status=200)

    def _decide_with_service(
        self,
        *,
        approval_request: ApprovalRequest,
        actor: Any,
        decision: str,
        channel: str,
        reason: str,
        callback_id: str,
        telegram_user_id: str,
    ) -> Any | None:
        decision_service = ApprovalDecisionService()
        try:
            return decision_service.decide(
                approval_request=approval_request,
                actor=actor,
                decision=decision,
                channel=channel,
                reason=reason,
                metadata={
                    "telegram_callback_query_id": callback_id,
                    "telegram_user_id": telegram_user_id,
                },
            )
        except ApprovalDecisionConflictError:
            return None
        except ApprovalDecisionPermissionError:
            return None
        except ApprovalDecisionDuplicateError:
            return None

    @staticmethod
    def _parse_command(text: str) -> tuple[str, list[str]]:
        chunks = text.split()
        command = chunks[0].split("@")[0].lower()
        args = chunks[1:]
        return command, args

    @staticmethod
    def _help_text() -> str:
        return (
            "Available commands:\n"
            "/pending [limit] - list pending approvals\n"
            "/status <id> - show approval status\n"
            "/approve <id> [reason] - approve a request\n"
            "/reject <id> [reason] - reject a request"
        )

    @staticmethod
    def _get_profile_by_telegram_chat_id(telegram_chat_id: str) -> UserProfile | None:
        profile = (
            UserProfile.objects.select_related("user")
            .filter(telegram_chat_id=telegram_chat_id)
            .order_by("-updated_at")
            .first()
        )
        return cast(UserProfile | None, profile)

    @staticmethod
    def _get_accessible_approval_request(*, user: Any, approval_id: int) -> ApprovalRequest | None:
        request_obj = (
            ApprovalRequest.objects.select_related("agent", "agent__owner")
            .filter(Q(agent__owner=user) | Q(agent__approvers=user), id=approval_id)
            .distinct()
            .first()
        )
        return cast(ApprovalRequest | None, request_obj)

    @staticmethod
    def _extract_chat_id(payload: dict[str, Any]) -> str:
        message_chat_id = payload.get("message", {}).get("chat", {}).get("id")
        if message_chat_id is None:
            message_chat_id = payload.get("chat", {}).get("id")
        if message_chat_id is not None:
            return str(message_chat_id)

        from_id = payload.get("from", {}).get("id")
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

    @staticmethod
    def _send_text(chat_id: str, text: str) -> None:
        client = TelegramClient()
        if not client.is_configured or chat_id == "":
            return
        client.send_message(chat_id=chat_id, text=text)
