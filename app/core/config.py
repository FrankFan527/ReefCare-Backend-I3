from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    # Application
    app_name: str = "ReefCare MY"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str

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