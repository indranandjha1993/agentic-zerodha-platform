from typing import Any, cast

from rest_framework import serializers

from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
    AnalysisNotificationEventType,
)
from apps.agents.services.analysis_notifications import AnalysisWebhookEndpointService
from apps.credentials.services.crypto import CredentialCryptoError


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = [
            "id",
            "owner",
            "risk_policy",
            "name",
            "slug",
            "instruction",
            "status",
            "execution_mode",
            "approval_mode",
            "approvers",
            "required_approvals",
            "schedule_cron",
            "config",
            "is_predictive",
            "is_auto_enabled",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("owner", "last_run_at", "created_at", "updated_at")
        extra_kwargs = {
            "required_approvals": {"min_value": 1},
        }

    def create(self, validated_data: dict[str, Any]) -> Agent:
        request = self.context["request"]
        approvers = validated_data.pop("approvers", [])
        agent = Agent.objects.create(owner=request.user, **validated_data)
        agent.approvers.set(approvers)
        return cast(Agent, agent)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        required_approvals = int(
            attrs.get(
                "required_approvals",
                self.instance.required_approvals if self.instance is not None else 1,
            )
        )
        approvers = attrs.get("approvers")
        if approvers is None:
            approver_count = self.instance.approvers.count() if self.instance is not None else 0
        else:
            approver_count = len(approvers)

        max_available_approvals = approver_count + 1
        if required_approvals > max_available_approvals:
            raise serializers.ValidationError(
                {
                    "required_approvals": (
                        "required_approvals cannot exceed owner + approvers "
                        f"({max_available_approvals})."
                    )
                }
            )
        return attrs

    def update(self, instance: Agent, validated_data: dict[str, Any]) -> Agent:
        approvers = validated_data.pop("approvers", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if approvers is not None:
            instance.approvers.set(approvers)
        return cast(Agent, instance)


class AgentAnalysisRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=4000)
    model = serializers.CharField(max_length=128, required=False, allow_blank=True)
    max_steps = serializers.IntegerField(required=False, min_value=1, max_value=10)
    async_mode = serializers.BooleanField(required=False)


class AgentAnalysisEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentAnalysisEvent
        fields = [
            "id",
            "run",
            "sequence",
            "event_type",
            "payload",
            "created_at",
        ]


class AgentAnalysisRunSerializer(serializers.ModelSerializer):
    event_count = serializers.SerializerMethodField()

    class Meta:
        model = AgentAnalysisRun
        fields = [
            "id",
            "agent",
            "requested_by",
            "status",
            "query",
            "model",
            "max_steps",
            "steps_executed",
            "usage",
            "result_text",
            "error_message",
            "metadata",
            "started_at",
            "completed_at",
            "event_count",
            "created_at",
            "updated_at",
        ]

    def get_event_count(self, obj: AgentAnalysisRun) -> int:
        return cast(int, obj.events.count())


class AgentAnalysisRunDetailSerializer(AgentAnalysisRunSerializer):
    events = AgentAnalysisEventSerializer(many=True, read_only=True)

    class Meta(AgentAnalysisRunSerializer.Meta):
        fields = AgentAnalysisRunSerializer.Meta.fields + ["events"]


class AgentAnalysisRunStatusSerializer(serializers.Serializer):
    run_id = serializers.IntegerField()
    status = serializers.CharField()
    is_final = serializers.BooleanField()
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    steps_executed = serializers.IntegerField()
    max_steps = serializers.IntegerField()
    latest_sequence = serializers.IntegerField(allow_null=True)
    latest_event_type = serializers.CharField(allow_blank=True)
    latest_event_at = serializers.DateTimeField(allow_null=True)
    error_message = serializers.CharField(allow_blank=True)


class AgentAnalysisWebhookEndpointSerializer(serializers.ModelSerializer):
    signing_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_signing_secret = serializers.SerializerMethodField()

    class Meta:
        model = AgentAnalysisWebhookEndpoint
        fields = [
            "id",
            "owner",
            "name",
            "callback_url",
            "signing_secret",
            "has_signing_secret",
            "is_active",
            "event_types",
            "headers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("owner", "has_signing_secret", "created_at", "updated_at")

    def get_has_signing_secret(self, obj: AgentAnalysisWebhookEndpoint) -> bool:
        return bool(obj.signing_secret_encrypted)

    def validate_event_types(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise serializers.ValidationError("event_types must be a list of event names.")
        allowed = set(AnalysisNotificationEventType.values)
        normalized = [str(item) for item in value]
        invalid = [item for item in normalized if item not in allowed]
        if invalid:
            raise serializers.ValidationError(
                f"Unsupported event_types: {', '.join(sorted(set(invalid)))}."
            )
        return normalized

    def validate_headers(self, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("headers must be an object of string pairs.")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if key == "":
                raise serializers.ValidationError("Header keys cannot be blank.")
            normalized[key] = str(raw_value)
        return normalized

    def create(self, validated_data: dict[str, Any]) -> AgentAnalysisWebhookEndpoint:
        request = self.context["request"]
        service = AnalysisWebhookEndpointService()
        try:
            endpoint = service.create_for_user(user=request.user, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(AgentAnalysisWebhookEndpoint, endpoint)

    def update(
        self,
        instance: AgentAnalysisWebhookEndpoint,
        validated_data: dict[str, Any],
    ) -> AgentAnalysisWebhookEndpoint:
        service = AnalysisWebhookEndpointService()
        try:
            endpoint = service.update(instance, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(AgentAnalysisWebhookEndpoint, endpoint)
