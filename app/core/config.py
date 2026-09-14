from pydantic import Field, field_validator, SecretStr
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    # Application
    app_name: str = "ReefCare MY"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # US5.6 stays independent of submission and case-review workflows.
    hotspot_enabled: bool = True
    hotspot_timeout_seconds: float = Field(default=10, gt=0, le=60)

    # Database
    database_url: str

    # evidence_storage_dir: str = (
    #     "./private_evidence"
    # )

    supabase_url: str
    supabase_secret_key: SecretStr
    supabase_storage_bucket: str = (
        "reefcare-evidence"
    )

    # JWT
    jwt_secret_key: str = Field(
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
    )

    # CORS
    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )

    # Rate limiting
    login_rate_limit_requests: int = Field(
        default=5,
        ge=1,
    )

    login_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
    )

    # Epic 4 Smart Report Structuring
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_base_url: str = (
        "https://generativelanguage.googleapis.com/"
        "v1beta"
    )
    smart_report_timeout_seconds: int = Field(
        default=20,
        ge=5,
        le=60,
    )
    smart_report_rate_limit_requests: int = Field(
        default=10,
        ge=1,
        le=100,
    )
    smart_report_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("app_env")
    @classmethod
    def validate_environment(
        cls,
        value: str,
    ) -> str:
        allowed = {
            "development",
            "test",
            "production",
        }

        normalised = value.lower()

        if normalised not in allowed:
            raise ValueError(
                "APP_ENV must be development, "
                "test or production"
            )

        return normalised

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


settings = Settings()
