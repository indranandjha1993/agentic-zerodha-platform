from typing import Any, cast

from rest_framework import serializers

from apps.agents.models import Agent, AgentAnalysisEvent, AgentAnalysisRun


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
