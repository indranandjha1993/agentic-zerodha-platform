from typing import Any, cast

from django.db.models import QuerySet

from apps.credentials.models import BrokerCredential, BrokerType, LlmCredential, LlmProvider
from apps.credentials.services.crypto import CredentialCrypto


class BrokerCredentialService:
    def __init__(self, crypto: CredentialCrypto | None = None) -> None:
        self._crypto = crypto

    @property
    def crypto(self) -> CredentialCrypto:
        if self._crypto is None:
            self._crypto = CredentialCrypto()
        return self._crypto

    def create_for_user(self, *, user: Any, payload: dict[str, Any]) -> BrokerCredential:
        credential = BrokerCredential(
            user=user,
            broker=payload.get("broker", BrokerType.KITE),
            alias=payload.get("alias", "default"),
            api_key=payload["api_key"],
            api_secret_encrypted=self.crypto.encrypt(payload["api_secret"]),
            access_token_encrypted=self.crypto.encrypt(payload.get("access_token", "")),
            refresh_token_encrypted=self.crypto.encrypt(payload.get("refresh_token", "")),
            access_token_expires_at=payload.get("access_token_expires_at"),
            is_active=payload.get("is_active", True),
            extra_config=payload.get("extra_config", {}),
        )
        credential.save()
        return credential

    def update(self, credential: BrokerCredential, payload: dict[str, Any]) -> BrokerCredential:
        for field in ("broker", "alias", "api_key", "is_active", "extra_config"):
            if field in payload:
                setattr(credential, field, payload[field])

        if "access_token_expires_at" in payload:
            credential.access_token_expires_at = payload["access_token_expires_at"]

        if "api_secret" in payload:
            credential.api_secret_encrypted = self.crypto.encrypt(payload["api_secret"])
        if "access_token" in payload:
            credential.access_token_encrypted = self.crypto.encrypt(payload.get("access_token", ""))
        if "refresh_token" in payload:
            credential.refresh_token_encrypted = self.crypto.encrypt(
                payload.get("refresh_token", "")
            )

        credential.save()
        return credential

    def decrypt_access_token(self, credential: BrokerCredential) -> str:
        return self.crypto.decrypt(credential.access_token_encrypted)

    def decrypt_api_secret(self, credential: BrokerCredential) -> str:
        return self.crypto.decrypt(credential.api_secret_encrypted)


class LlmCredentialService:
    def __init__(self, crypto: CredentialCrypto | None = None) -> None:
        self._crypto = crypto

    @property
    def crypto(self) -> CredentialCrypto:
        if self._crypto is None:
            self._crypto = CredentialCrypto()
        return self._crypto

    def create_for_user(self, *, user: Any, payload: dict[str, Any]) -> LlmCredential:
        credential = LlmCredential(
            user=user,
            provider=payload.get("provider", LlmProvider.OPENROUTER),
            api_key_encrypted=self.crypto.encrypt(payload["api_key"]),
            default_model=payload.get("default_model", "openai/gpt-4o-mini"),
            is_active=payload.get("is_active", True),
        )
        credential.save()
        return credential

    def update(self, credential: LlmCredential, payload: dict[str, Any]) -> LlmCredential:
        for field in ("provider", "default_model", "is_active"):
            if field in payload:
                setattr(credential, field, payload[field])

        if "api_key" in payload:
            credential.api_key_encrypted = self.crypto.encrypt(payload["api_key"])

        credential.save()
        return credential

    def decrypt_api_key(self, credential: LlmCredential) -> str:
        return self.crypto.decrypt(credential.api_key_encrypted)


def get_active_broker_credential(
    *,
    user: Any,
    broker: str = "kite",
    alias: str = "default",
) -> BrokerCredential | None:
    queryset: QuerySet[BrokerCredential] = BrokerCredential.objects.filter(
        user=user,
        broker=broker,
        alias=alias,
        is_active=True,
    )
    credential = queryset.order_by("-updated_at").first()
    return cast(BrokerCredential | None, credential)


def get_active_llm_credential(
    *,
    user: Any,
    provider: str = "openrouter",
) -> LlmCredential | None:
    queryset: QuerySet[LlmCredential] = LlmCredential.objects.filter(
        user=user,
        provider=provider,
        is_active=True,
    )
    credential = queryset.order_by("-updated_at").first()
    return cast(LlmCredential | None, credential)
