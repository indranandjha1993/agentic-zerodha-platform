import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisRun,
    AgentStatus,
    AnalysisRunStatus,
    ApprovalMode,
    ExecutionMode,
)

User = get_user_model()


@pytest.mark.django_db
def test_analysis_run_history_and_detail_endpoints() -> None:
    owner = User.objects.create_user(
        username="history-owner",
        email="history-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="History Agent",
        slug="history-agent",
        instruction="Track analysis runs.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze HDFC Bank earnings.",
        model="openai/gpt-4o-mini",
        max_steps=4,
        steps_executed=2,
        result_text="Sample result",
    )
    AgentAnalysisEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_started",
        payload={"note": "started"},
    )
    AgentAnalysisEvent.objects.create(
        run=run,
        sequence=2,
        event_type="run_completed",
        payload={"note": "done"},
    )

    client = APIClient()
    client.force_authenticate(owner)

    list_response = client.get(f"/api/v1/agents/{agent.id}/analysis-runs/")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["id"] == run.id
    assert list_payload[0]["event_count"] == 2

    detail_response = client.get(f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == run.id
    assert len(detail_payload["events"]) == 2


@pytest.mark.django_db
def test_analysis_event_list_and_stream_endpoints() -> None:
    owner = User.objects.create_user(
        username="stream-owner",
        email="stream-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Stream Agent",
        slug="stream-agent",
        instruction="Stream events.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze Reliance.",
        model="openai/gpt-4o-mini",
        max_steps=4,
        steps_executed=1,
        result_text="Done",
    )
    AgentAnalysisEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_started",
        payload={"step": 1},
    )
    AgentAnalysisEvent.objects.create(
        run=run,
        sequence=2,
        event_type="run_completed",
        payload={"step": 2},
    )

    client = APIClient()
    client.force_authenticate(owner)

    events_response = client.get(
        f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/events/?since_sequence=1"
    )
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert len(events_payload) == 1
    assert events_payload[0]["sequence"] == 2

    stream_response = client.get(
        f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/events/stream/?timeout_seconds=5"
    )
    assert stream_response.status_code == 200
    assert stream_response["Content-Type"].startswith("text/event-stream")

    chunks = []
    for index, chunk in enumerate(stream_response.streaming_content):
        chunks.append(chunk.decode("utf-8"))
        if index >= 3:
            break
    body = "".join(chunks)
    assert "stream_end" in body
