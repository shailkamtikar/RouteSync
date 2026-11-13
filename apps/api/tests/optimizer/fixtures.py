"""A northern Pune-Nanded corridor, built from the deterministic fake routing provider."""

from app.optimizer.models import ActiveStop, Candidate, CorridorVariant, JourneyState
from app.providers.routing.fake import FakeRoutingProvider

PUNE = (73.8567, 18.5204)
AHMEDNAGAR = (74.7496, 19.0948)
BEED = (75.7601, 18.9891)
PARBHANI = (76.7748, 19.2608)
NANDED = (77.321, 19.1383)
LATUR = (76.5604, 18.4088)

STOP_BEED = ActiveStop("beed", "Beed", *BEED)
STOP_PARBHANI = ActiveStop("parbhani", "Parbhani", *PARBHANI)


def planned_route(provider: FakeRoutingProvider | None = None):
    """The route assigned at the start: Pune through the active stops to Nanded."""
    provider = provider or FakeRoutingProvider()
    return provider.route([PUNE, AHMEDNAGAR, BEED, PARBHANI, NANDED])[0]


def make_state(
    *,
    position=AHMEDNAGAR,
    stops=(STOP_BEED, STOP_PARBHANI),
    variants: tuple[CorridorVariant, ...] = (),
    destination=NANDED,
) -> JourneyState:
    route = planned_route()
    return JourneyState(
        position=position,
        remaining_stops=tuple(stops),
        destination=destination,
        destination_name="Nanded",
        corridor_centreline=tuple(route.coordinates),
        current_route=tuple(route.coordinates),
        current_route_distance_m=route.distance_m,
        current_route_duration_s=route.duration_s,
        variants=variants,
    )


def candidate_through(waypoints, name="test", **kwargs) -> Candidate:
    result = FakeRoutingProvider().route(waypoints)[0]
    return Candidate(
        name=name,
        source=kwargs.pop("source", "variant"),
        coordinates=tuple(result.coordinates),
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        **kwargs,
    )
