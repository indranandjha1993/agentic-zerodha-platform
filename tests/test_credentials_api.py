import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.credentials.models import BrokerCredential, LlmCredential
from apps.credentials.services.manager import BrokerCredentialService, LlmCredentialService

User = get_user_model()


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_create_broker_credential_encrypts_secret_values() -> None:
    user = User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="test-pass",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    payload = {
        "broker": "kite",
        "alias": "default",
        "api_key": "kite-api-key",
        "api_secret": "kite-api-secret",
        "access_token": "kite-access-token",
    }
    response = client.post("/api/v1/broker-credentials/", payload, format="json")
    assert response.status_code == 201

    response_payload = response.json()
    assert "api_secret" not in response_payload
    assert "access_token" not in response_payload
    assert response_payload["has_access_token"] is True

    stored = BrokerCredential.objects.get(user=user, alias="default")
    assert stored.api_secret_encrypted != payload["api_secret"]
    assert stored.access_token_encrypted != payload["access_token"]

    service = BrokerCredentialService()
    assert service.decrypt_api_secret(stored) == payload["api_secret"]
    assert service.decrypt_access_token(stored) == payload["access_token"]


@pytest.mark.django_db
@override_settings(ENCRYPTION_KEY="unit-test-encryption-key")
def test_create_llm_credential_encrypts_api_key() -> None:
    user = User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="test-pass",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    payload = {
        "provider": "openrouter",
        "api_key": "openrouter-key",
        "default_model": "openai/gpt-4o-mini",
    }
    response = client.post("/api/v1/llm-credentials/", payload, format="json")
    assert response.status_code == 201

    response_payload = response.json()
    assert "api_key" not in response_payload
    assert response_payload["has_api_key"] is True

    stored = LlmCredential.objects.get(user=user, provider="openrouter")
    assert stored.api_key_encrypted != payload["api_key"]

    service = LlmCredentialService()
    assert service.decrypt_api_key(stored) == payload["api_key"]
