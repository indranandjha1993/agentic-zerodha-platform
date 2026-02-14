import hashlib
import hmac
import json
from typing import Any, cast

import requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from apps.agents.models import (
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
    AnalysisRunStatus,
    default_analysis_notification_event_types,
)
from apps.credentials.services.crypto import CredentialCrypto


class AnalysisWebhookEndpointService:
    def __init__(self, crypto: CredentialCrypto | None = None) -> None:
        self._crypto = crypto

    @property
    def crypto(self) -> CredentialCrypto:
        if self._crypto is None:
            self._crypto = CredentialCrypto()
        return self._crypto

    def create_for_user(
        self,
        *,
        user: Any,
        payload: dict[str, Any],
    ) -> AgentAnalysisWebhookEndpoint:
        event_types = payload.get("event_types", default_analysis_notification_event_types())
        headers = payload.get("headers", {})
        signing_secret = str(payload.get("signing_secret", ""))
        endpoint = AgentAnalysisWebhookEndpoint(
            owner=user,
            name=payload["name"],
            callback_url=payload["callback_url"],
            is_active=bool(payload.get("is_active", True)),
            event_types=[str(item) for item in event_types],
            headers=cast(dict[str, Any], headers),
            signing_secret_encrypted=(
                self.crypto.encrypt(signing_secret) if signing_secret != "" else ""
            ),
        )
        endpoint.save()
        return endpoint

    def update(
        self,
        endpoint: AgentAnalysisWebhookEndpoint,
        payload: dict[str, Any],
    ) -> AgentAnalysisWebhookEndpoint:
        for field in ("name", "callback_url", "is_active", "event_types", "headers"):
            if field in payload:
                setattr(endpoint, field, payload[field])

        if "signing_secret" in payload:
            secret = str(payload["signing_secret"])
            endpoint.signing_secret_encrypted = self.crypto.encrypt(secret) if secret != "" else ""

        endpoint.save()
        return endpoint

    def decrypt_signing_secret(self, endpoint: AgentAnalysisWebhookEndpoint) -> str:
        if endpoint.signing_secret_encrypted == "":
            return ""
        return self.crypto.decrypt(endpoint.signing_secret_encrypted)


class AnalysisRunNotificationDispatchService:
    def __init__(
        self,
        endpoint_service: AnalysisWebhookEndpointService | None = None,
    ) -> None:
        self.endpoint_service = endpoint_service or AnalysisWebhookEndpointService()
        self.timeout_seconds = int(
            max(1, getattr(settings, "ANALYSIS_WEBHOOK_REQUEST_TIMEOUT_SECONDS", 10))
        )
        self.max_response_chars = int(
            max(200, getattr(settings, "ANALYSIS_WEBHOOK_RESPONSE_MAX_CHARS", 1500))
        )

    def dispatch_for_run(self, run: AgentAnalysisRun) -> dict[str, Any]:
        event_type = self.event_type_for_status(run.status)
        if event_type is None:
            return {
                "status": "skipped",
                "reason": f"run status '{run.status}' is not final",
                "event_type": "",
                "attempted": 0,
                "delivered": 0,
                "failed": 0,
                "skipped": 0,
            }

        payload = self._build_payload(run=run, event_type=event_type)
        endpoints = self._active_endpoints_for_owner(run)

        attempted = 0
        delivered = 0
        failed = 0
        skipped = 0

        for endpoint in endpoints:
            if not endpoint.supports_event_type(event_type):
                skipped += 1
                continue

            attempted += 1
            delivery, _ = AgentAnalysisNotificationDelivery.objects.get_or_create(
                endpoint=endpoint,
                run=run,
                event_type=event_type,
                defaults={"request_payload": payload},
            )

            if delivery.success:
                skipped += 1
                continue

            delivery.request_payload = payload
            if self._deliver(
                endpoint=endpoint,
                payload=payload,
                event_type=event_type,
                delivery=delivery,
            ):
                delivered += 1
            else:
                failed += 1

        return {
            "status": "ok",
            "event_type": event_type,
            "attempted": attempted,
            "delivered": delivered,
            "failed": failed,
            "skipped": skipped,
        }

    @staticmethod
    def event_type_for_status(status_value: str) -> str | None:
        if status_value == AnalysisRunStatus.COMPLETED:
            return "analysis_run.completed"
        if status_value == AnalysisRunStatus.FAILED:
            return "analysis_run.failed"
        if status_value == AnalysisRunStatus.CANCELED:
            return "analysis_run.canceled"
        return None

    def _active_endpoints_for_owner(
        self,
        run: AgentAnalysisRun,
    ) -> QuerySet[AgentAnalysisWebhookEndpoint]:
        return AgentAnalysisWebhookEndpoint.objects.filter(
            owner=run.agent.owner,
            is_active=True,
        ).order_by(
            "id",
        )

    def _deliver(
        self,
        *,
        endpoint: AgentAnalysisWebhookEndpoint,
        payload: dict[str, Any],
        event_type: str,
        delivery: AgentAnalysisNotificationDelivery,
    ) -> bool:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        headers = {
            "Content-Type": "application/json",
            "X-Agentic-Event": event_type,
            "X-Agentic-Delivery-Id": str(delivery.id),
            "X-Agentic-Run-Id": str(delivery.run_id),
        }
        headers.update(self._normalized_headers(endpoint.headers))

        try:
            signing_secret = self.endpoint_service.decrypt_signing_secret(endpoint)
        except Exception as exc:
            delivery.success = False
            delivery.status_code = None
            delivery.response_body = ""
            delivery.error_message = str(exc)
            delivery.save(
                update_fields=[
                    "request_payload",
                    "success",
                    "status_code",
                    "response_body",
                    "error_message",
                    "updated_at",
                ]
            )
            return False

        if signing_secret != "":
            signature = hmac.new(
                signing_secret.encode("utf-8"),
                body.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            headers["X-Agentic-Signature"] = f"sha256={signature}"

        try:
            response = requests.post(
                endpoint.callback_url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response_text = response.text[: self.max_response_chars]
            success = 200 <= response.status_code < 300
            delivery.success = success
            delivery.status_code = response.status_code
            delivery.response_body = response_text
            delivery.error_message = ""
            if not success:
                delivery.error_message = f"Webhook returned HTTP {response.status_code}."
            delivery.save(
                update_fields=[
                    "request_payload",
                    "success",
                    "status_code",
                    "response_body",
                    "error_message",
                    "updated_at",
                ]
            )
            return success
        except requests.RequestException as exc:
            delivery.success = False
            delivery.status_code = None
            delivery.response_body = ""
            delivery.error_message = str(exc)
            delivery.save(
                update_fields=[
                    "request_payload",
                    "success",
                    "status_code",
                    "response_body",
                    "error_message",
                    "updated_at",
                ]
            )
            return False

    @staticmethod
    def _normalized_headers(raw_headers: Any) -> dict[str, str]:
        if not isinstance(raw_headers, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in raw_headers.items():
            normalized[str(key)] = str(value)
        return normalized

    @staticmethod
    def _build_payload(
        *,
        run: AgentAnalysisRun,
        event_type: str,
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "occurred_at": timezone.now().isoformat(),
            "agent": {
                "id": run.agent_id,
                "name": run.agent.name,
                "slug": run.agent.slug,
            },
            "run": {
                "id": run.id,
                "status": run.status,
                "query": run.query,
                "model": run.model,
                "max_steps": run.max_steps,
                "steps_executed": run.steps_executed,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
                "requested_by": run.requested_by_id,
            },
        }
