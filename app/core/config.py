from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    # Application
    app_name: str = "ReefCare MY"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # US5.6 stays independent of submission and
    # case-review workflows.
    hotspot_enabled: bool = True

    hotspot_timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=60,
    )

    # Database
    database_url: str

    # Evidence storage
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

    # -----------------------------------------------------------------------
    # Epic 4 Smart Report Structuring.
    # -----------------------------------------------------------------------

    gemini_api_key: SecretStr | None = None

    gemini_model: str = (
        "gemini-3.1-flash-lite"
    )

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

    # -----------------------------------------------------------------------
    # Epic 9 Reef-Aware Dive Planning.
    #
    # I3 public live forecast horizon:
    # Malaysia today through Malaysia today + 6 days.
    # -----------------------------------------------------------------------

    planning_forecast_enabled: bool = True

    planning_forecast_horizon_days: int = Field(
        default=7,
        ge=1,
        le=16,
    )

    planning_forecast_timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=60,
    )

    planning_timezone: str = (
        "Asia/Kuala_Lumpur"
    )

    open_meteo_marine_base_url: str = (
        "https://marine-api.open-meteo.com/"
        "v1/marine"
    )

    open_meteo_weather_base_url: str = (
        "https://api.open-meteo.com/"
        "v1/forecast"
    )

    # Draft deterministic rule.
    #
    # These are centralised rather than scattered through
    # service code. The team can replace them once the I3
    # rule set has been formally reviewed.
    planning_rule_version: str = (
        "i3-draft-1"
    )

    planning_wave_more_favourable_max_m: float = Field(
        default=0.8,
        ge=0,
    )

    planning_wave_less_favourable_above_m: float = Field(
        default=1.5,
        ge=0,
    )

    planning_wind_more_favourable_max_kmh: float = Field(
        default=12.0,
        ge=0,
    )

    planning_wind_less_favourable_above_kmh: float = Field(
        default=20.0,
        ge=0,
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

    @model_validator(mode="after")
    def validate_planning_thresholds(
        self,
    ):
        if (
            self.planning_wave_more_favourable_max_m
            >=
            self.planning_wave_less_favourable_above_m
        ):
            raise ValueError(
                "Planning wave thresholds must have "
                "more-favourable below less-favourable"
            )

        if (
            self.planning_wind_more_favourable_max_kmh
            >=
            self.planning_wind_less_favourable_above_kmh
        ):
            raise ValueError(
                "Planning wind thresholds must have "
                "more-favourable below less-favourable"
            )

        return self

    @property
    def cors_origin_list(
        self,
    ) -> list[str]:
        return [
            origin.strip()
            for origin
            in self.cors_origins.split(",")
            if origin.strip()
        ]


settings = Settings()