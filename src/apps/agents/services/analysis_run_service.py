from typing import Any, cast

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.agents.models import Agent, AgentAnalysisEvent, AgentAnalysisRun, AnalysisRunStatus
from apps.agents.services.openrouter_market_analyst import (
    MissingLlmCredentialError,
    OpenRouterAgentError,
    OpenRouterMarketAnalyst,
)


class AgentAnalysisRunService:
    def __init__(self, analyst: OpenRouterMarketAnalyst | None = None) -> None:
        self.analyst = analyst or OpenRouterMarketAnalyst()

    def create_run(
        self,
        *,
        agent: Agent,
        requested_by: Any,
        query: str,
        model: str,
        max_steps: int,
    ) -> AgentAnalysisRun:
        run = AgentAnalysisRun.objects.create(
            agent=agent,
            requested_by=requested_by,
            status=AnalysisRunStatus.PENDING,
            query=query,
            model=model,
            max_steps=max_steps,
        )
        return cast(AgentAnalysisRun, run)

    def execute(self, run: AgentAnalysisRun) -> dict[str, Any]:
        run.status = AnalysisRunStatus.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
        self.append_event(
            run=run,
            event_type="run_started",
            payload={
                "query": run.query,
                "model": run.model,
                "max_steps": run.max_steps,
            },
        )

        def on_event(event_type: str, payload: dict[str, Any]) -> None:
            self.append_event(run=run, event_type=event_type, payload=payload)

        try:
            result = self.analyst.analyze(
                agent=run.agent,
                user_query=run.query,
                model=run.model or None,
                max_steps=run.max_steps,
                on_event=on_event,
            )
        except (MissingLlmCredentialError, OpenRouterAgentError) as exc:
            run.status = AnalysisRunStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                    "updated_at",
                ]
            )
            self.append_event(
                run=run,
                event_type="run_failed",
                payload={"error": str(exc)},
            )
            raise
        except Exception as exc:
            run.status = AnalysisRunStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                    "updated_at",
                ]
            )
            self.append_event(
                run=run,
                event_type="run_failed",
                payload={"error": str(exc)},
            )
            raise OpenRouterAgentError(str(exc)) from exc

        run.status = AnalysisRunStatus.COMPLETED
        run.result_text = str(result.get("analysis", ""))
        run.usage = cast(dict[str, Any], result.get("usage", {}))
        run.steps_executed = int(result.get("steps_executed", 0))
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "result_text",
                "usage",
                "steps_executed",
                "completed_at",
                "updated_at",
            ]
        )
        self.append_event(
            run=run,
            event_type="run_completed",
            payload={
                "steps_executed": run.steps_executed,
                "usage": run.usage,
            },
        )
        return result

    def append_event(
        self,
        *,
        run: AgentAnalysisRun,
        event_type: str,
        payload: dict[str, Any],
    ) -> AgentAnalysisEvent:
        with transaction.atomic():
            max_sequence = (
                AgentAnalysisEvent.objects.select_for_update()
                .filter(run=run)
                .aggregate(max_sequence=Max("sequence"))
                .get("max_sequence")
                or 0
            )
            event = AgentAnalysisEvent.objects.create(
                run=run,
                sequence=int(max_sequence) + 1,
                event_type=event_type,
                payload=payload,
            )
        return cast(AgentAnalysisEvent, event)

    @staticmethod
    def status_payload(run: AgentAnalysisRun) -> dict[str, Any]:
        latest_event = run.events.order_by("-sequence").first()
        is_final = run.status in {
            AnalysisRunStatus.COMPLETED,
            AnalysisRunStatus.FAILED,
            AnalysisRunStatus.CANCELED,
        }
        return {
            "run_id": run.id,
            "status": run.status,
            "is_final": is_final,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "steps_executed": run.steps_executed,
            "max_steps": run.max_steps,
            "latest_sequence": latest_event.sequence if latest_event is not None else None,
            "latest_event_type": latest_event.event_type if latest_event is not None else "",
            "latest_event_at": latest_event.created_at if latest_event is not None else None,
            "error_message": run.error_message,
        }
