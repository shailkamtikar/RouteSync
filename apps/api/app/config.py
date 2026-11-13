"""Typed application settings loaded from the environment."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    ors_api_key: str = ""
    # Half-width of a route option's corridor: stops and reroutes must stay within it.
    corridor_width_m: int = 5000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    # Secret mixed into stored token hashes (device tokens, public tracking links).
    public_token_pepper: str = ""

    # GPS ingestion: fastest plausible bus speed, allowed device clock skew, requests per minute.
    gps_max_speed_kmh: float = Field(default=160.0, gt=0)
    gps_future_tolerance_s: float = Field(default=60.0, ge=0)
    ingest_rate_per_min: int = Field(default=120, gt=0)

    # ETA: a position older than this is shown as not live; farther than this from the route is off route.
    gps_stale_after_s: float = Field(default=120.0, gt=0)
    off_route_m: float = Field(default=1000.0, gt=0)

    # Arrival promise: delay thresholds in minutes, alert hysteresis and planning buffer.
    delay_minor_after_min: float = Field(default=5.0, ge=0)
    delay_significant_after_min: float = Field(default=15.0, gt=0)
    delay_critical_after_min: float = Field(default=60.0, gt=0)
    delay_alert_clear_margin_min: float = Field(default=5.0, ge=0)
    arrival_buffer_min: float = Field(default=0.0, ge=0)

    # RouteSync Companion (assistant). The key is server-side only.
    companion_enabled: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    companion_rate_per_min_link: int = Field(default=10, gt=0)
    companion_rate_per_day_link: int = Field(default=200, gt=0)

    # Public tracking links and public endpoint limits.
    tracking_link_hours_after_arrival: float = Field(default=24.0, ge=0)
    public_rate_per_min_ip: int = Field(default=120, gt=0)
    public_rate_per_min_token: int = Field(default=60, gt=0)

    # Rerouting guardrails. These are tuning values, not product rules.
    reroute_autoapply: bool = True
    reroute_min_saving_minutes: float = Field(default=10.0, ge=0)
    reroute_min_saving_pct: float = Field(default=5.0, ge=0)
    reroute_cooldown_minutes: float = Field(default=20.0, ge=0)
    reroute_max_per_journey: int = Field(default=3, ge=0)
    reroute_confirmations: int = Field(default=2, ge=1)
    reroute_eval_interval_s: float = Field(default=30.0, ge=0)

    # Route scoring weights and cost estimates (see app.optimizer). All must be >= 0.
    score_weight_lateness_per_min: float = Field(default=10.0, ge=0)
    score_weight_travel_per_min: float = Field(default=1.0, ge=0)
    score_weight_cost_per_unit: float = Field(default=0.05, ge=0)
    score_weight_distance_per_km: float = Field(default=0.05, ge=0)
    score_weight_risk_per_min: float = Field(default=2.0, ge=0)
    fuel_litres_per_km: float = Field(default=0.35, ge=0)
    fuel_price_per_litre: float = Field(default=95.0, ge=0)
    # Unset means "no toll data": tolls are reported as unknown instead of being invented.
    toll_per_km: float | None = Field(default=None, ge=0)

    def score_weights(self):
        from app.optimizer.scoring import Weights

        return Weights(
            lateness_per_min=self.score_weight_lateness_per_min,
            travel_per_min=self.score_weight_travel_per_min,
            cost_per_unit=self.score_weight_cost_per_unit,
            distance_per_km=self.score_weight_distance_per_km,
            risk_per_min=self.score_weight_risk_per_min,
        )

    def reroute_config(self):
        from app.optimizer.decision import DecisionConfig

        return DecisionConfig(
            min_saving_minutes=self.reroute_min_saving_minutes,
            min_saving_pct=self.reroute_min_saving_pct,
            cooldown_minutes=self.reroute_cooldown_minutes,
            max_reroutes_per_journey=self.reroute_max_per_journey,
            confirmations_required=self.reroute_confirmations,
            autoapply=self.reroute_autoapply,
        )

    def commitment_config(self):
        from app.eta.commitment import CommitmentConfig

        return CommitmentConfig(
            minor_after_min=self.delay_minor_after_min,
            significant_after_min=self.delay_significant_after_min,
            critical_after_min=self.delay_critical_after_min,
            clear_margin_min=self.delay_alert_clear_margin_min,
            buffer_min=self.arrival_buffer_min,
        )

    def cost_config(self):
        from app.optimizer.costs import CostConfig

        return CostConfig(
            fuel_litres_per_km=self.fuel_litres_per_km,
            fuel_price_per_litre=self.fuel_price_per_litre,
            toll_per_km=self.toll_per_km,
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
