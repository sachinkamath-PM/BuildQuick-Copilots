from __future__ import annotations

import os
from dataclasses import dataclass

from app.domain.models import Product


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    auth_mode: str
    assistant_provider: str
    database_url: str
    identity_introspection_url: str
    openai_api_key: str
    app_secret: str
    request_limit_per_minute: int
    allowed_hosts: tuple[str, ...]
    feature_tyche: bool
    feature_plutus: bool
    feature_nous: bool
    migrate_on_startup: bool
    guest_retention_hours: int
    guest_cleanup_interval_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.getenv("APP_ENV", "development").lower(),
            auth_mode=os.getenv("AUTH_MODE", "local").lower(),
            assistant_provider=os.getenv("ASSISTANT_PROVIDER", "mock").lower(),
            database_url=os.getenv("DATABASE_URL", "sqlite:///work/copilots.db"),
            identity_introspection_url=os.getenv("IDENTITY_INTROSPECTION_URL", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            app_secret=os.getenv("APP_SECRET", "local-development-secret-change-me"),
            request_limit_per_minute=int(os.getenv("REQUEST_LIMIT_PER_MINUTE", "180")),
            allowed_hosts=tuple(
                host.strip()
                for host in os.getenv("ALLOWED_HOSTS", "*").split(",")
                if host.strip()
            ),
            feature_tyche=_bool("FEATURE_TYCHE", True),
            feature_plutus=_bool("FEATURE_PLUTUS", True),
            feature_nous=_bool("FEATURE_NOUS", True),
            migrate_on_startup=_bool("MIGRATE_ON_STARTUP", True),
            guest_retention_hours=int(os.getenv("GUEST_RETENTION_HOURS", "24")),
            guest_cleanup_interval_seconds=int(os.getenv("GUEST_CLEANUP_INTERVAL_SECONDS", "3600")),
        )

    def validate(self) -> None:
        if self.request_limit_per_minute < 1:
            raise RuntimeError("REQUEST_LIMIT_PER_MINUTE must be positive")
        if not self.allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must contain at least one host")
        if self.guest_retention_hours < 1:
            raise RuntimeError("GUEST_RETENTION_HOURS must be positive")
        if self.guest_cleanup_interval_seconds < 60:
            raise RuntimeError("GUEST_CLEANUP_INTERVAL_SECONDS must be at least 60")
        if self.app_env == "demo":
            errors: list[str] = []
            if self.auth_mode != "guest":
                errors.append("demo AUTH_MODE must be guest")
            if self.app_secret == "local-development-secret-change-me" or len(self.app_secret.encode()) < 32:
                errors.append("demo APP_SECRET must contain at least 32 bytes")
            if self.allowed_hosts == ("*",):
                errors.append("demo ALLOWED_HOSTS must be explicit")
            if errors:
                raise RuntimeError("Invalid demo configuration: " + "; ".join(errors))
            return
        if self.app_env != "production":
            return
        errors: list[str] = []
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            errors.append("production DATABASE_URL must use PostgreSQL")
        if self.auth_mode != "introspection":
            errors.append("production AUTH_MODE must be introspection")
        if not self.identity_introspection_url.startswith("https://"):
            errors.append("production identity introspection must use HTTPS")
        if self.assistant_provider == "openai" and not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required for the OpenAI provider")
        if self.app_secret == "local-development-secret-change-me" or len(self.app_secret.encode()) < 32:
            errors.append("production APP_SECRET must contain at least 32 bytes")
        if errors:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errors))

    def feature_enabled(self, product: Product) -> bool:
        return {
            Product.TYCHE: self.feature_tyche,
            Product.PLUTUS: self.feature_plutus,
            Product.NOUS: self.feature_nous,
        }[product]

    def public_features(self) -> dict[str, bool]:
        return {
            "tyche": self.feature_tyche,
            "plutus": self.feature_plutus,
            "nous": self.feature_nous,
        }

    def browser_auth_mode(self) -> str:
        if self.app_env == "development" and self.auth_mode == "local":
            return "development"
        if self.app_env == "demo" and self.auth_mode == "guest":
            return "guest"
        return "external"


settings = Settings.from_env()
settings.validate()
