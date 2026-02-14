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
            "schedule_cron",
            "config",
            "is_predictive",
            "is_auto_enabled",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("owner", "last_run_at", "created_at", "updated_at")

    def create(self, validated_data: dict[str, Any]) -> Agent:
        request = self.context["request"]
        agent = Agent.objects.create(owner=request.user, **validated_data)
        return cast(Agent, agent)
