import logging
from typing import Any, cast

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.agents.models import Agent, AgentAnalysisEvent, AgentAnalysisRun, AnalysisRunStatus
from apps.agents.services.openrouter_market_analyst import (
    MissingLlmCredentialError,
    OpenRouterAgentCanceledError,
    OpenRouterAgentError,
    OpenRouterMarketAnalyst,
)

logger = logging.getLogger(__name__)


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
        if run.status == AnalysisRunStatus.CANCELED:
            return {
                "status": "canceled",
                "model": run.model,
                "analysis": "",
                "tool_trace": [],
                "usage": run.usage,
                "steps_executed": run.steps_executed,
            }

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
            if not should_continue():
                raise OpenRouterAgentCanceledError("Analysis run canceled by user.")
            self.append_event(run=run, event_type=event_type, payload=payload)

        def should_continue() -> bool:
            run.refresh_from_db(fields=["status"])
            return bool(run.status != AnalysisRunStatus.CANCELED)

        try:
            result = self.analyst.analyze(
                agent=run.agent,
                user_query=run.query,
                model=run.model or None,
                max_steps=run.max_steps,
                on_event=on_event,
                should_continue=should_continue,
            )
        except OpenRouterAgentCanceledError:
            run.refresh_from_db(fields=["status", "completed_at"])
            run.status = AnalysisRunStatus.CANCELED
            if run.completed_at is None:
                run.completed_at = timezone.now()
            run.error_message = run.error_message or "Canceled by user."
            run.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
            self.append_event_once(
                run=run,
                event_type="run_canceled",
                payload={"reason": "Canceled by user."},
            )
            self.enqueue_final_notifications(run)
            return {
                "status": "canceled",
                "model": run.model,
                "analysis": "",
                "tool_trace": [],
                "usage": run.usage,
                "steps_executed": run.steps_executed,
            }
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
            self.enqueue_final_notifications(run)
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
            self.enqueue_final_notifications(run)
            raise OpenRouterAgentError(str(exc)) from exc

        run.refresh_from_db(fields=["status"])
        if run.status == AnalysisRunStatus.CANCELED:
            run.completed_at = run.completed_at or timezone.now()
            run.error_message = run.error_message or "Canceled by user."
            run.save(update_fields=["completed_at", "error_message", "updated_at"])
            self.append_event_once(
                run=run,
                event_type="run_canceled",
                payload={"reason": "Canceled by user."},
            )
            self.enqueue_final_notifications(run)
            return {
                "status": "canceled",
                "model": run.model,
                "analysis": "",
                "tool_trace": [],
                "usage": run.usage,
                "steps_executed": run.steps_executed,
            }

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
        self.enqueue_final_notifications(run)
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

    def append_event_once(
        self,
        *,
        run: AgentAnalysisRun,
        event_type: str,
        payload: dict[str, Any],
    ) -> AgentAnalysisEvent:
        existing = run.events.filter(event_type=event_type).order_by("-sequence").first()
        if existing is not None:
            return cast(AgentAnalysisEvent, existing)
        return self.append_event(run=run, event_type=event_type, payload=payload)

    @staticmethod
    def enqueue_final_notifications(run: AgentAnalysisRun) -> None:
        if run.status not in {
            AnalysisRunStatus.COMPLETED,
            AnalysisRunStatus.FAILED,
            AnalysisRunStatus.CANCELED,
        }:
            return

        from apps.agents.tasks import dispatch_analysis_run_notifications_task

        try:
            dispatch_analysis_run_notifications_task.delay(run.id)
        except Exception:
            logger.warning(
                "Unable to enqueue analysis run notifications.",
                extra={"run_id": run.id, "run_status": run.status},
                exc_info=True,
            )

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
