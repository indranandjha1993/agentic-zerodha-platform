import pytest
from django.test import Client
from django.test.utils import override_settings


@pytest.mark.django_db
@override_settings(
    REQUIRED_RUNTIME_SECRET_KEYS=("OPENROUTER_API_KEY", "KITE_API_KEY"),
    OPENROUTER_API_KEY="set-value",
    KITE_API_KEY="",
)
def test_health_check_returns_ok() -> None:
    client = Client()
    response = client.get("/health/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime_secrets"]["required"] == ["OPENROUTER_API_KEY", "KITE_API_KEY"]
    assert payload["runtime_secrets"]["configured"]["OPENROUTER_API_KEY"] is True
    assert payload["runtime_secrets"]["configured"]["KITE_API_KEY"] is False
    assert payload["runtime_secrets"]["all_configured"] is False
