import json
import time
from collections.abc import Iterator
from typing import cast

from django.conf import settings
from django.db.models import Q, QuerySet
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.agents.models import Agent, AgentAnalysisEvent, AgentAnalysisRun, AnalysisRunStatus
from apps.agents.serializers import (
    AgentAnalysisEventSerializer,
    AgentAnalysisRequestSerializer,
    AgentAnalysisRunDetailSerializer,
    AgentAnalysisRunSerializer,
    AgentAnalysisRunStatusSerializer,
    AgentSerializer,
)
from apps.agents.services.analysis_run_service import AgentAnalysisRunService
from apps.agents.services.openrouter_market_analyst import (
    MissingLlmCredentialError,
    OpenRouterAgentError,
)
from apps.agents.tasks import execute_agent_analysis_run_task
from apps.audit.models import AuditEvent, AuditLevel


class AgentViewSet(ModelViewSet):
    serializer_class = AgentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Agent]:
        return (
            Agent.objects.filter(Q(owner=self.request.user) | Q(approvers=self.request.user))
            .select_related("risk_policy")
            .prefetch_related("approvers")
            .distinct()
            .order_by("-updated_at")
        )

    def perform_update(self, serializer: AgentSerializer) -> None:
        agent = self.get_object()
        if agent.owner_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("Only the owner can update this agent.")
        serializer.save()

    def perform_destroy(self, instance: Agent) -> None:
        if instance.owner_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("Only the owner can delete this agent.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="analyze")
    def analyze(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        serializer = AgentAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        selected_model = serializer.validated_data.get("model", "").strip() or str(
            agent.config.get("openrouter_model", "")
        )
        if selected_model == "":
            selected_model = settings.OPENROUTER_DEFAULT_MODEL
        max_steps = int(
            serializer.validated_data.get("max_steps", settings.OPENROUTER_ANALYST_MAX_STEPS)
        )
        async_mode = bool(
            serializer.validated_data.get("async_mode", settings.AGENT_ANALYSIS_ASYNC_DEFAULT)
        )

        run_service = AgentAnalysisRunService()
        run = run_service.create_run(
            agent=agent,
            requested_by=request.user,
            query=serializer.validated_data["query"],
            model=selected_model,
            max_steps=max_steps,
        )
        if async_mode:
            execute_agent_analysis_run_task.delay(run.id)
            payload = run_service.status_payload(run)
            payload["message"] = "Analysis run queued."
            serializer = AgentAnalysisRunStatusSerializer(payload)
            return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

        try:
            result = run_service.execute(run)
        except MissingLlmCredentialError as exc:
            AuditEvent.objects.create(
                actor=request.user,
                event_type="agent_market_analysis_failed",
                level=AuditLevel.WARNING,
                entity_type="agent_analysis_run",
                entity_id=str(run.id),
                payload={"error": str(exc)},
                message="OpenRouter credential missing for analysis run.",
            )
            return Response(
                {"detail": str(exc), "run_id": run.id},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OpenRouterAgentError as exc:
            AuditEvent.objects.create(
                actor=request.user,
                event_type="agent_market_analysis_failed",
                level=AuditLevel.ERROR,
                entity_type="agent_analysis_run",
                entity_id=str(run.id),
                payload={"error": str(exc)},
                message="OpenRouter market analysis failed.",
            )
            return Response(
                {"detail": str(exc), "run_id": run.id},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        AuditEvent.objects.create(
            actor=request.user,
            event_type="agent_market_analysis_completed",
            level=AuditLevel.INFO,
            entity_type="agent_analysis_run",
            entity_id=str(run.id),
            payload={
                "model": result.get("model"),
                "steps_executed": result.get("steps_executed"),
            },
            message="OpenRouter market analysis completed.",
        )

        response_payload = dict(result)
        response_payload["run_id"] = run.id
        response_payload["run_status"] = run.status
        return Response(response_payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="analysis-runs")
    def list_analysis_runs(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        runs_queryset = (
            AgentAnalysisRun.objects.filter(agent=agent)
            .select_related("requested_by")
        )
        status_filter = request.query_params.get("status", "").strip()
        search_query = request.query_params.get("q", "").strip()
        date_from_param = request.query_params.get("date_from", "").strip()
        date_to_param = request.query_params.get("date_to", "").strip()
        order_by = request.query_params.get("order_by", "-created_at").strip()

        if status_filter != "":
            runs_queryset = runs_queryset.filter(status=status_filter)
        if search_query != "":
            runs_queryset = runs_queryset.filter(
                Q(query__icontains=search_query)
                | Q(model__icontains=search_query)
                | Q(result_text__icontains=search_query)
            )

        date_from = parse_date(date_from_param) if date_from_param else None
        date_to = parse_date(date_to_param) if date_to_param else None
        if date_from is not None:
            runs_queryset = runs_queryset.filter(created_at__date__gte=date_from)
        if date_to is not None:
            runs_queryset = runs_queryset.filter(created_at__date__lte=date_to)

        allowed_order_fields = {
            "created_at",
            "-created_at",
            "started_at",
            "-started_at",
            "completed_at",
            "-completed_at",
        }
        if order_by not in allowed_order_fields:
            order_by = "-created_at"
        runs_queryset = runs_queryset.order_by(order_by)

        page_param = request.query_params.get("page", "1")
        page_size_param = request.query_params.get("page_size", "20")
        page = int(page_param) if page_param.isdigit() else 1
        page_size = int(page_size_param) if page_size_param.isdigit() else 20
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        total = runs_queryset.count()
        runs = list(runs_queryset[offset : offset + page_size])
        serializer = AgentAnalysisRunSerializer(runs, many=True)

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path=r"analysis-runs/(?P<run_id>[^/.]+)")
    def get_analysis_run(
        self,
        request: Request,
        run_id: str,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        run = self._get_run(agent=agent, run_id=run_id)
        if run is None:
            return Response({"detail": "Analysis run not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AgentAnalysisRunDetailSerializer(run)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path=r"analysis-runs/(?P<run_id>[^/.]+)/status")
    def get_analysis_run_status(
        self,
        request: Request,
        run_id: str,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        run = self._get_run(agent=agent, run_id=run_id)
        if run is None:
            return Response({"detail": "Analysis run not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = AgentAnalysisRunService.status_payload(run)
        serializer = AgentAnalysisRunStatusSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path=r"analysis-runs/(?P<run_id>[^/.]+)/cancel")
    def cancel_analysis_run(
        self,
        request: Request,
        run_id: str,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        run = self._get_run(agent=agent, run_id=run_id)
        if run is None:
            return Response({"detail": "Analysis run not found."}, status=status.HTTP_404_NOT_FOUND)

        if run.status in {
            AnalysisRunStatus.COMPLETED,
            AnalysisRunStatus.FAILED,
            AnalysisRunStatus.CANCELED,
        }:
            return Response(
                {"detail": f"Run cannot be canceled in status '{run.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metadata = dict(run.metadata)
        metadata["canceled_by"] = request.user.id
        metadata["canceled_at"] = timezone.now().isoformat()
        run.status = AnalysisRunStatus.CANCELED
        run.error_message = run.error_message or "Canceled by user."
        run.completed_at = run.completed_at or timezone.now()
        run.metadata = metadata
        run.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "metadata",
                "updated_at",
            ]
        )

        run_service = AgentAnalysisRunService()
        run_service.append_event(
            run=run,
            event_type="cancel_requested",
            payload={"actor_id": request.user.id},
        )
        payload = run_service.status_payload(run)
        serializer = AgentAnalysisRunStatusSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path=r"analysis-runs/(?P<run_id>[^/.]+)/events")
    def list_analysis_events(
        self,
        request: Request,
        run_id: str,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        run = self._get_run(agent=agent, run_id=run_id)
        if run is None:
            return Response({"detail": "Analysis run not found."}, status=status.HTTP_404_NOT_FOUND)

        since_sequence_param = request.query_params.get("since_sequence", "0")
        since_sequence = int(since_sequence_param) if since_sequence_param.isdigit() else 0
        events = run.events.filter(sequence__gt=since_sequence).order_by("sequence")

        serializer = AgentAnalysisEventSerializer(events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path=r"analysis-runs/(?P<run_id>[^/.]+)/events/stream",
    )
    def stream_analysis_events(
        self,
        request: Request,
        run_id: str,
        pk: str | None = None,
    ) -> Response | StreamingHttpResponse:
        agent = self.get_object()
        run = self._get_run(agent=agent, run_id=run_id)
        if run is None:
            return Response({"detail": "Analysis run not found."}, status=status.HTTP_404_NOT_FOUND)

        timeout_param = request.query_params.get("timeout_seconds", "30")
        timeout_seconds = int(timeout_param) if timeout_param.isdigit() else 30
        timeout_seconds = max(5, min(timeout_seconds, 120))

        poll_param = request.query_params.get("poll_interval", "1.0")
        try:
            poll_interval = float(poll_param)
        except ValueError:
            poll_interval = 1.0
        poll_interval = max(0.2, min(poll_interval, 5.0))

        since_sequence_param = request.query_params.get("since_sequence", "0")
        since_sequence = int(since_sequence_param) if since_sequence_param.isdigit() else 0

        def event_stream() -> Iterator[str]:
            last_sequence = since_sequence
            deadline = time.monotonic() + timeout_seconds
            final_statuses = {"completed", "failed", "canceled"}

            while time.monotonic() < deadline:
                pending_events = list(
                    AgentAnalysisEvent.objects.filter(run=run, sequence__gt=last_sequence)
                    .order_by("sequence")
                    .all()
                )
                if pending_events:
                    for event in pending_events:
                        payload = AgentAnalysisEventSerializer(event).data
                        message = json.dumps(payload, ensure_ascii=True)
                        chunk = (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {message}\n\n"
                        )
                        yield chunk
                        last_sequence = event.sequence
                else:
                    yield "event: heartbeat\ndata: {}\n\n"

                run_status = (
                    AgentAnalysisRun.objects.filter(id=run.id)
                    .values_list("status", flat=True)
                    .first()
                )
                status_value = str(run_status or "")
                has_more = AgentAnalysisEvent.objects.filter(
                    run=run,
                    sequence__gt=last_sequence,
                ).exists()
                if status_value in final_statuses and not has_more:
                    stream_end_payload = json.dumps(
                        {"run_id": run.id, "status": status_value},
                        ensure_ascii=True,
                    )
                    yield f"event: stream_end\ndata: {stream_end_payload}\n\n"
                    return
                time.sleep(poll_interval)

            yield "event: timeout\ndata: {}\n\n"

        response = StreamingHttpResponse(
            streaming_content=event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def _get_run(*, agent: Agent, run_id: str) -> AgentAnalysisRun | None:
        if not run_id.isdigit():
            return None
        run = (
            AgentAnalysisRun.objects.filter(agent=agent, id=int(run_id))
            .select_related("requested_by")
            .prefetch_related("events")
            .first()
        )
        return cast(AgentAnalysisRun | None, run)
