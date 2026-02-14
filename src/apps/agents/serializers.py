from typing import Any, cast

from rest_framework import serializers

from apps.agents.models import Agent


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
