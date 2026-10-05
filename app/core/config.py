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

    # US5.9: explainable, data-assisted suggestions. Bump the rule version
    # whenever a threshold changes so stored results retain their provenance.
    related_incident_rule_version: str = Field(default="rid-v2-image", min_length=1, max_length=50)
    related_incident_window_days: int = Field(default=7, ge=1, le=90)
    related_incident_pool_limit: int = Field(default=200, ge=1, le=500)
    related_incident_result_limit: int = Field(default=20, ge=1, le=100)
    related_incident_timeout_seconds: float = Field(default=30, gt=0, le=60)
    related_incident_nearby_metres: float = Field(default=500, gt=0, le=5000)
    related_incident_depth_tolerance_metres: float = Field(default=5, gt=0, le=30)
    related_incident_description_threshold: float = Field(default=0.35, gt=0, le=1)
    related_incident_min_score: float = Field(default=0.55, gt=0, le=1)
    related_incident_medium_score: float = Field(default=0.70, gt=0, le=1)
    related_incident_high_score: float = Field(default=0.85, gt=0, le=1)
    related_incident_images_enabled: bool = True
    # US5.9 image similarity.
    # ONNX inference runs after successful report submission.
    related_incident_image_model_path: str = (
        "models/resnet18-avgpool512.onnx"
    )
    related_incident_image_threshold: float = Field(default=0.80, gt=0, le=1)
    related_incident_image_top_k: int = Field(default=10, ge=1, le=100)
    related_incident_images_per_report: int = Field(default=8, ge=1, le=20)
    related_incident_image_timeout_seconds: float = Field(default=12, gt=0, le=60)
    related_incident_image_max_pixels: int = Field(default=20000000, ge=1000000, le=50000000)

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

    # -----------------------------------------------------------------
    # Epic 8 selected external context (US8.3).
    #
    # NOAA Coral Reef Watch CRW v3.1 via ERDDAP griddap. Public domain,
    # free to use, attribution required and carried in the
    # external_context_source table.
    # -----------------------------------------------------------------

    external_context_enabled: bool = True

    # Tried in order until one answers. Both serve the same CRW v3.1
    # product under the same variable names. PacIOOS (Hawaii) is the
    # upstream publisher and is reachable from Malaysia; the NOAA
    # CoastWatch West Coast mirror was not, in testing on 2026-10-05.
    noaa_crw_base_urls: str = (
        "https://pae-paha.pacioos.hawaii.edu/erddap/griddap/dhw_5km.csv,"
        "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW.csv"
    )

    # per mirror; with two mirrors the worst case is twice this
    noaa_crw_timeout_seconds: float = Field(
        default=6.0,
        gt=0,
        le=30,
    )

    # how old a stored value may be before a read tries to refresh it
    external_context_staleness_hours: int = Field(
        default=24,
        ge=1,
        le=168,
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

    @model_validator(mode="after")
    def validate_related_incident_thresholds(self):
        if not (
            self.related_incident_min_score
            < self.related_incident_medium_score
            < self.related_incident_high_score
        ):
            raise ValueError("Related-incident scores must satisfy minimum < medium < high")
        return self

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
