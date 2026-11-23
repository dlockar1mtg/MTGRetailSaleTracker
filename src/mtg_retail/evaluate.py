"""Turn the registry into decisions: each event's state, and which alerts are due.

States (handoff section 7.2). The reviewer records ANNOUNCED_TERMS_UNKNOWN, PENDING_VERIFICATION, VERIFIED,
SOURCE_INACCESSIBLE or CANCELLED; this module derives the rest:

  VERIFIED_QUALIFYING       verified, and at least one MTG category meets its threshold (singles >= 30, sealed >= 20)
  VERIFIED_BELOW_THRESHOLD  verified MTG terms, all below threshold
  VERIFIED_NOT_APPLICABLE   verified, but MTG is excluded or not shown to be included
  EXPIRED                   the sale's last day has passed (local date)

A term counts only when it is itself verified, MTG eligibility is "yes", and it has a percentage. "20% off
everything" with MTG eligibility "unknown" never qualifies. Stores outside the radius never alert.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .geo import miles_between
from .registry import Event, Registry, Store, Term

LEAD_STATES = {"ANNOUNCED_TERMS_UNKNOWN", "PENDING_VERIFICATION"}


@dataclass(frozen=True)
class Assessment:
    event: Event
    store: Store
    distance_miles: float
    in_radius: bool
    near_boundary: bool
    state: str
    qualifying_terms: tuple[Term, ...]
    alert_kind: str | None  # "verified", "lead", "spotted" (found automatically, unverified) or None


def qualifies(term: Term, cfg: dict) -> bool:
    if term.verified != "yes" or term.mtg_eligible != "yes" or term.discount_percent is None:
        return False
    need = cfg["threshold_singles_percent"] if term.category == "singles" else cfg["threshold_sealed_percent"]
    return term.discount_percent >= need


def assess(event: Event, store: Store, cfg: dict, today: date) -> Assessment:
    distance = miles_between(cfg["center_lat"], cfg["center_lon"], store.latitude, store.longitude)
    radius = cfg["radius_miles"]
    in_radius = distance <= radius
    near = abs(distance - radius) <= cfg.get("near_boundary_review_miles", 10)
    winners = tuple(t for t in event.terms if qualifies(t, cfg))
    if event.review_status == "CANCELLED":
        state = "CANCELLED"
    elif event.end_date < today:
        state = "EXPIRED"
    elif event.review_status == "VERIFIED":
        if winners:
            state = "VERIFIED_QUALIFYING"
        elif any(t.verified == "yes" and t.mtg_eligible == "yes" and t.discount_percent is not None for t in event.terms):
            state = "VERIFIED_BELOW_THRESHOLD"
        else:
            state = "VERIFIED_NOT_APPLICABLE"
    else:
        state = event.review_status
    kind = None
    if in_radius and store.verification_status != "closed":
        if state == "VERIFIED_QUALIFYING":
            kind = "verified"
        elif state in LEAD_STATES:
            kind = "lead"
        elif state == "AUTO_DETECTED":
            kind = "spotted"
    return Assessment(event, store, distance, in_radius, near, state, winners, kind)


def assess_all(registry: Registry, cfg: dict, today: date) -> list[Assessment]:
    out = [assess(e, registry.stores[e.store_id], cfg, today) for e in registry.events.values()]
    return sorted(out, key=lambda a: (a.event.start_date, a.event.event_id))
