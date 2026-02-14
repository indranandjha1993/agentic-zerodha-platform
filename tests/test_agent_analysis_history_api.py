import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
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
    assert list_payload["count"] == 1
    assert len(list_payload["results"]) == 1
    assert list_payload["results"][0]["id"] == run.id
    assert list_payload["results"][0]["event_count"] == 2

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


@pytest.mark.django_db
def test_analysis_run_status_endpoint_returns_compact_payload() -> None:
    owner = User.objects.create_user(
        username="status-owner",
        email="status-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Status Agent",
        slug="status-agent",
        instruction="Status endpoint test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.RUNNING,
        query="Analyze SBI.",
        model="openai/gpt-4o-mini",
        max_steps=6,
        steps_executed=2,
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
        event_type="tool_result",
        payload={"step": 2},
    )

    client = APIClient()
    client.force_authenticate(owner)

    response = client.get(f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/status/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run.id
    assert payload["status"] == AnalysisRunStatus.RUNNING
    assert payload["is_final"] is False
    assert payload["latest_sequence"] == 2
    assert payload["latest_event_type"] == "tool_result"


@pytest.mark.django_db
def test_analysis_run_list_supports_filters_and_pagination() -> None:
    owner = User.objects.create_user(
        username="filter-owner",
        email="filter-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Filter Agent",
        slug="filter-agent",
        instruction="Filter and pagination test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze HDFCBANK",
        model="openai/gpt-4o-mini",
        max_steps=4,
        result_text="HDFCBANK analysis",
    )
    AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.FAILED,
        query="Analyze ITC",
        model="openai/gpt-4o-mini",
        max_steps=4,
        error_message="Failure",
    )

    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(
        f"/api/v1/agents/{agent.id}/analysis-runs/?status=completed&q=HDFCBANK&page=1&page_size=1"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["status"] == AnalysisRunStatus.COMPLETED


@pytest.mark.django_db
def test_cancel_analysis_run_endpoint_marks_run_canceled() -> None:
    owner = User.objects.create_user(
        username="cancel-owner",
        email="cancel-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Cancel Agent",
        slug="cancel-agent",
        instruction="Cancel endpoint test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.PENDING,
        query="Analyze AXISBANK",
        model="openai/gpt-4o-mini",
        max_steps=4,
    )

    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/cancel/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == AnalysisRunStatus.CANCELED
    assert payload["is_final"] is True

    run.refresh_from_db()
    assert run.status == AnalysisRunStatus.CANCELED
    assert run.events.filter(event_type="cancel_requested").exists()


@pytest.mark.django_db
def test_user_analysis_event_stream_only_emits_visible_final_events() -> None:
    owner = User.objects.create_user(
        username="global-stream-owner",
        email="global-stream-owner@example.com",
        password="test-pass",
    )
    outsider = User.objects.create_user(
        username="global-stream-outsider",
        email="global-stream-outsider@example.com",
        password="test-pass",
    )
    visible_agent = Agent.objects.create(
        owner=owner,
        name="Visible Stream Agent",
        slug="stream-visible-agent",
        instruction="Visible stream.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    hidden_agent = Agent.objects.create(
        owner=outsider,
        name="Hidden Stream Agent",
        slug="stream-hidden-agent",
        instruction="Hidden stream.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    visible_run = AgentAnalysisRun.objects.create(
        agent=visible_agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze visible run.",
        model="openai/gpt-4o-mini",
        max_steps=3,
        result_text="Visible complete",
    )
    hidden_run = AgentAnalysisRun.objects.create(
        agent=hidden_agent,
        requested_by=outsider,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze hidden run.",
        model="openai/gpt-4o-mini",
        max_steps=3,
        result_text="Hidden complete",
    )
    AgentAnalysisEvent.objects.create(
        run=visible_run,
        sequence=1,
        event_type="run_completed",
        payload={"note": "visible"},
    )
    AgentAnalysisEvent.objects.create(
        run=hidden_run,
        sequence=1,
        event_type="run_completed",
        payload={"note": "hidden"},
    )

    client = APIClient()
    client.force_authenticate(owner)
    response = client.get("/api/v1/agents/analysis-events/stream/?timeout_seconds=5")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")

    chunks: list[str] = []
    for index, chunk in enumerate(response.streaming_content):
        chunks.append(chunk.decode("utf-8"))
        if "analysis_run_finalized" in chunks[-1] or index >= 3:
            break
    body = "".join(chunks)
    assert "analysis_run_finalized" in body
    assert f"\"id\": {visible_run.id}" in body
    assert "stream-hidden-agent" not in body


@pytest.mark.django_db
def test_analysis_notification_delivery_list_endpoints() -> None:
    owner = User.objects.create_user(
        username="delivery-owner",
        email="delivery-owner@example.com",
        password="test-pass",
    )
    agent = Agent.objects.create(
        owner=owner,
        name="Delivery Agent",
        slug="delivery-agent",
        instruction="Delivery list endpoint test.",
        status=AgentStatus.ACTIVE,
        execution_mode=ExecutionMode.PAPER,
        approval_mode=ApprovalMode.ALWAYS,
        is_auto_enabled=True,
    )
    run = AgentAnalysisRun.objects.create(
        agent=agent,
        requested_by=owner,
        status=AnalysisRunStatus.COMPLETED,
        query="Analyze BAJFINANCE",
        model="openai/gpt-4o-mini",
        max_steps=4,
        result_text="Done",
    )
    endpoint = AgentAnalysisWebhookEndpoint.objects.create(
        owner=owner,
        name="delivery-endpoint",
        callback_url="https://example.com/hook",
        event_types=["analysis_run.completed"],
        headers={},
        is_active=True,
    )
    delivery = AgentAnalysisNotificationDelivery.objects.create(
        endpoint=endpoint,
        run=run,
        event_type="analysis_run.completed",
        success=True,
        status_code=200,
        attempt_count=1,
        max_attempts=3,
        request_payload={"event_type": "analysis_run.completed"},
        response_body="ok",
    )

    client = APIClient()
    client.force_authenticate(owner)

    run_response = client.get(
        f"/api/v1/agents/{agent.id}/analysis-runs/{run.id}/notification-deliveries/"
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["count"] == 1
    assert run_payload["results"][0]["id"] == delivery.id

    endpoint_response = client.get(
        f"/api/v1/analysis-webhook-endpoints/{endpoint.id}/deliveries/?run_id={run.id}"
    )
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.json()
    assert endpoint_payload["count"] == 1
    assert endpoint_payload["results"][0]["run"] == run.id

    detail_response = client.get(
        f"/api/v1/analysis-webhook-endpoints/{endpoint.id}/deliveries/{delivery.id}/"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == delivery.id
