from typing import Any, cast

from rest_framework import serializers

from apps.credentials.models import BrokerCredential, LlmCredential
from apps.credentials.services.crypto import CredentialCryptoError
from apps.credentials.services.manager import BrokerCredentialService, LlmCredentialService


class BrokerCredentialSerializer(serializers.ModelSerializer):
    api_secret = serializers.CharField(write_only=True, required=False, allow_blank=False)
    access_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    refresh_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_access_token = serializers.SerializerMethodField()

    class Meta:
        model = BrokerCredential
        fields = [
            "id",
            "user",
            "broker",
            "alias",
            "api_key",
            "api_secret",
            "access_token",
            "refresh_token",
            "access_token_expires_at",
            "is_active",
            "extra_config",
            "has_access_token",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("user", "created_at", "updated_at", "has_access_token")
        extra_kwargs = {
            "api_key": {"required": True},
        }

    def get_has_access_token(self, obj: BrokerCredential) -> bool:
        return bool(obj.access_token_encrypted)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None and "api_secret" not in attrs:
            raise serializers.ValidationError({"api_secret": "This field is required."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> BrokerCredential:
        request = self.context["request"]
        service = BrokerCredentialService()
        try:
            credential = service.create_for_user(user=request.user, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(BrokerCredential, credential)

    def update(
        self,
        instance: BrokerCredential,
        validated_data: dict[str, Any],
    ) -> BrokerCredential:
        service = BrokerCredentialService()
        try:
            credential = service.update(instance, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(BrokerCredential, credential)


class LlmCredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False)
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = LlmCredential
        fields = [
            "id",
            "user",
            "provider",
            "api_key",
            "default_model",
            "is_active",
            "has_api_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("user", "created_at", "updated_at", "has_api_key")

    def get_has_api_key(self, obj: LlmCredential) -> bool:
        return bool(obj.api_key_encrypted)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None and "api_key" not in attrs:
            raise serializers.ValidationError({"api_key": "This field is required."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> LlmCredential:
        request = self.context["request"]
        service = LlmCredentialService()
        try:
            credential = service.create_for_user(user=request.user, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(LlmCredential, credential)

    def update(self, instance: LlmCredential, validated_data: dict[str, Any]) -> LlmCredential:
        service = LlmCredentialService()
        try:
            credential = service.update(instance, payload=validated_data)
        except CredentialCryptoError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return cast(LlmCredential, credential)
