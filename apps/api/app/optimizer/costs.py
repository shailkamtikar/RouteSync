"""Operating cost estimates. Fuel and tolls are configurable estimates, never live prices."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostConfig:
    fuel_litres_per_km: float = 0.35
    fuel_price_per_litre: float = 95.0
    # Toll charge per km on the route. None means "no toll data": tolls are then reported as
    # unknown (counted as 0) instead of inventing a price.
    toll_per_km: float | None = None
    currency: str = "INR"

    def __post_init__(self) -> None:
        for name in ("fuel_litres_per_km", "fuel_price_per_litre"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.toll_per_km is not None and self.toll_per_km < 0:
            raise ValueError("toll_per_km must not be negative")


@dataclass(frozen=True)
class CostEstimate:
    fuel: float
    toll: float
    total: float
    currency: str
    # Always True: no figure here comes from a live price source.
    is_estimate: bool = True
    toll_unknown: bool = False


def estimate_cost(distance_m: float, config: CostConfig | None = None) -> CostEstimate:
    cfg = config or CostConfig()
    kilometres = max(distance_m, 0.0) / 1000.0
    fuel = kilometres * cfg.fuel_litres_per_km * cfg.fuel_price_per_litre
    unknown = cfg.toll_per_km is None
    toll = 0.0 if unknown else kilometres * (cfg.toll_per_km or 0.0)
    return CostEstimate(
        fuel=fuel, toll=toll, total=fuel + toll, currency=cfg.currency, toll_unknown=unknown
    )
