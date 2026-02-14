from typing import Any

import requests
from django.conf import settings

from apps.approvals.models import ApprovalRequest


class TelegramClient:
    def __init__(
        self,
        bot_token: str | None = None,
        api_base_url: str | None = None,
    ) -> None:
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.api_base_url = (api_base_url or settings.TELEGRAM_API_BASE_URL).rstrip("/")

    @property
    def is_configured(self) -> bool:
        return self.bot_token != ""

    def send_approval_request(
        self,
        *,
        chat_id: str,
        approval_request: ApprovalRequest,
    ) -> dict[str, Any]:
        if not self.is_configured:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured."}

        intent_payload = approval_request.intent_payload
        text = "\n".join(
            [
                "Approval required",
                f"Agent: {approval_request.agent.name}",
                f"Symbol: {intent_payload.get('symbol', '-')}",
                f"Side: {intent_payload.get('side', '-')}",
                f"Quantity: {intent_payload.get('quantity', '-')}",
                f"Risk score: {approval_request.risk_snapshot.get('risk_score', '-')}",
                f"Request ID: {approval_request.id}",
            ]
        )
        callback_prefix = f"approval:{approval_request.id}:"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "Approve", "callback_data": f"{callback_prefix}approve"},
                        {"text": "Reject", "callback_data": f"{callback_prefix}reject"},
                    ]
                ]
            },
        }
        return self._post("sendMessage", payload)

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured."}

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> dict[str, Any]:
        if not self.is_configured:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured."}

        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }
        return self._post("answerCallbackQuery", payload)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.bot_token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured."}

        url = f"{self.api_base_url}/bot{self.bot_token}/{method}"
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            parsed = response.json()
            if isinstance(parsed, dict):
                return parsed
            return {"ok": False, "error": "Unexpected Telegram response format."}
        except requests.RequestException as exc:
            return {"ok": False, "error": str(exc)}
