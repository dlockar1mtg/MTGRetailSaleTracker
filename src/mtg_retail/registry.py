"""The governed registry: reviewed CSV files in registry/, versioned in git.

GitHub Actions runners keep nothing between runs, so the source of truth is plain CSV in the repository: every
change is a reviewed commit with history, and each run rebuilds its working database from these files.

  stores.csv    one row per retailer (stable store_id that survives renames and moves)
  events.csv    one row per sale event (a campaign at one store over a date window)
  terms.csv     category-level terms of an event (singles / sealed), versioned
  evidence.csv  every observation backing an event (URL or user screenshot, when, how, confidence)
  sources.csv   optional: extra pages to check automatically for a store (event calendar, sales page)

Machine-maintained files in registry/auto/ (written by the daily workflow, never edited by hand):

  wpn_stores.csv   every Wizards Play Network store within the radius, from the official store locator
  osm_stores.csv   game / hobby / comic shops mapped in OpenStreetMap (candidates: Magic not confirmed)
  detections.csv   possible sales found on stores' own pages (become AUTO_DETECTED events)
  checks.csv       when each page was last read, and whether it could be

A store in stores.csv wins over the same shop found automatically (same place, or within a mile with a shared
name word), so hand-entered details are never overwritten.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
import re

REGISTRY = Path(__file__).resolve().parents[2] / "registry"

STORE_STATUSES = {"candidate", "verified", "closed"}
WPN_STATUSES = {"wpn_verified", "non_wpn_verified", "wpn_unknown"}
YES_NO_UNKNOWN = {"yes", "no", "unknown"}
PRECISIONS = {"address", "city"}
# The reviewer's record of where an event stands. EXPIRED and the verified sub-states are derived, not entered.
REVIEW_STATUSES = {"ANNOUNCED_TERMS_UNKNOWN", "PENDING_VERIFICATION", "VERIFIED", "SOURCE_INACCESSIBLE", "CANCELLED"}
AUTO_STATUS = "AUTO_DETECTED"          # set only by the automatic checks (registry/auto/detections.csv)
ACTIVE_DETECTION_DAYS = 7              # a detection still on the page counts as live for a week after each sighting
CATEGORIES = {"singles", "sealed"}
WHERE = {"in_store", "online", "both", "unknown"}
SOURCE_TYPES = {"store_website", "store_calendar", "facebook_post", "facebook_image", "instagram_post",
                "event_listing", "user_screenshot", "user_report", "other"}
ACCESS = {"ok", "blocked", "removed", "login_required", "not_indexed", "error", "not_applicable"}
CONFIDENCE = {"high", "medium", "low"}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Store:
    store_id: str
    store_name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    location_precision: str
    wpn_status: str
    sells_singles: str
    sells_sealed: str
    verification_status: str
    website: str
    notes: str
    last_verified_on: date | None
    origin: str = "manual"           # manual | wpn | osm
    source_id: str = ""


@dataclass(frozen=True)
class Term:
    event_id: str
    category: str
    discount_percent: float | None
    mtg_eligible: str
    conditions: str
    exclusions: str
    where: str
    verified: str
    terms_version: int


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    event_id: str
    source_type: str
    url: str
    retrieved_on: date
    access_status: str
    method: str
    confidence: str
    summary: str


@dataclass
class Event:
    event_id: str
    store_id: str
    title: str
    start_date: date
    end_date: date
    local_hours: str
    timezone: str
    review_status: str
    first_seen_on: date
    last_checked_on: date
    notes: str
    terms: list[Term] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    alert_version: str = ""          # automatic finds: changes when the page's discount or sale name changes

    @property
    def terms_version(self) -> int:
        return max((t.terms_version for t in self.terms), default=0)


@dataclass
class Registry:
    stores: dict[str, Store]
    events: dict[str, Event]
    sources: list[tuple[str, str]] = field(default_factory=list)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RegistryError(f"missing registry file {path.name}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _choice(value: str, allowed: set[str], what: str, where: str) -> str:
    if value not in allowed:
        raise RegistryError(f"{where}: {what} must be one of {sorted(allowed)}, got {value!r}")
    return value


def _date(value: str, what: str, where: str, required: bool = True) -> date | None:
    if not value and not required:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError(f"{where}: {what} must be YYYY-MM-DD, got {value!r}") from exc


def _id(value: str, where: str) -> str:
    if not ID_PATTERN.match(value):
        raise RegistryError(f"{where}: ids are 3-64 chars of a-z, 0-9, _ and -, got {value!r}")
    return value


def load(directory: Path = REGISTRY) -> Registry:
    stores: dict[str, Store] = {}
    for n, r in enumerate(_rows(directory / "stores.csv"), start=2):
        where = f"stores.csv row {n}"
        sid = _id(r["store_id"], where)
        if sid in stores:
            raise RegistryError(f"{where}: duplicate store_id {sid}")
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except ValueError as exc:
            raise RegistryError(f"{where}: latitude/longitude must be numbers") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise RegistryError(f"{where}: coordinates out of range")
        stores[sid] = Store(
            store_id=sid, store_name=r["store_name"] or _fail(f"{where}: store_name is required"),
            address=r["address"], city=r["city"], state=r["state"], latitude=lat, longitude=lon,
            location_precision=_choice(r["location_precision"], PRECISIONS, "location_precision", where),
            wpn_status=_choice(r["wpn_status"], WPN_STATUSES, "wpn_status", where),
            sells_singles=_choice(r["sells_singles"], YES_NO_UNKNOWN, "sells_singles", where),
            sells_sealed=_choice(r["sells_sealed"], YES_NO_UNKNOWN, "sells_sealed", where),
            verification_status=_choice(r["verification_status"], STORE_STATUSES, "verification_status", where),
            website=r["website"], notes=r["notes"], last_verified_on=_date(r["last_verified_on"], "last_verified_on", where, False),
        )
    events: dict[str, Event] = {}
    for n, r in enumerate(_rows(directory / "events.csv"), start=2):
        where = f"events.csv row {n}"
        eid = _id(r["event_id"], where)
        if eid in events:
            raise RegistryError(f"{where}: duplicate event_id {eid}")
        if r["store_id"] not in stores:
            raise RegistryError(f"{where}: unknown store_id {r['store_id']!r}")
        start, end = _date(r["start_date"], "start_date", where), _date(r["end_date"], "end_date", where)
        if end < start:
            raise RegistryError(f"{where}: end_date is before start_date")
        events[eid] = Event(
            event_id=eid, store_id=r["store_id"], title=r["title"] or _fail(f"{where}: title is required"),
            start_date=start, end_date=end, local_hours=r["local_hours"], timezone=r["timezone"] or "America/Chicago",
            review_status=_choice(r["review_status"], REVIEW_STATUSES, "review_status", where),
            first_seen_on=_date(r["first_seen_on"], "first_seen_on", where),
            last_checked_on=_date(r["last_checked_on"], "last_checked_on", where), notes=r["notes"],
        )
    seen_terms: set[tuple[str, str]] = set()
    for n, r in enumerate(_rows(directory / "terms.csv"), start=2):
        where = f"terms.csv row {n}"
        if r["event_id"] not in events:
            raise RegistryError(f"{where}: unknown event_id {r['event_id']!r}")
        key = (r["event_id"], r["category"])
        if key in seen_terms:
            raise RegistryError(f"{where}: one row per event and category ({key})")
        seen_terms.add(key)
        pct = None
        if r["discount_percent"]:
            pct = float(r["discount_percent"])
            if not 0 <= pct <= 100:
                raise RegistryError(f"{where}: discount_percent must be 0-100")
        try:
            version = int(r["terms_version"] or "1")
        except ValueError as exc:
            raise RegistryError(f"{where}: terms_version must be a whole number") from exc
        events[r["event_id"]].terms.append(Term(
            event_id=r["event_id"], category=_choice(r["category"], CATEGORIES, "category", where), discount_percent=pct,
            mtg_eligible=_choice(r["mtg_eligible"], YES_NO_UNKNOWN, "mtg_eligible", where), conditions=r["conditions"],
            exclusions=r["exclusions"], where=_choice(r["where"], WHERE, "where", where),
            verified=_choice(r["verified"], {"yes", "no"}, "verified", where), terms_version=version,
        ))
    evidence_ids: set[str] = set()
    for n, r in enumerate(_rows(directory / "evidence.csv"), start=2):
        where = f"evidence.csv row {n}"
        evid = _id(r["evidence_id"], where)
        if evid in evidence_ids:
            raise RegistryError(f"{where}: duplicate evidence_id {evid}")
        evidence_ids.add(evid)
        if r["event_id"] not in events:
            raise RegistryError(f"{where}: unknown event_id {r['event_id']!r}")
        source_type = _choice(r["source_type"], SOURCE_TYPES, "source_type", where)
        if source_type not in {"user_screenshot", "user_report"} and not r["url"].startswith(("https://", "http://")):
            raise RegistryError(f"{where}: a {source_type} needs its direct URL (only user screenshots/reports may have none)")
        events[r["event_id"]].evidence.append(Evidence(
            evidence_id=evid, event_id=r["event_id"], source_type=source_type, url=r["url"],
            retrieved_on=_date(r["retrieved_on"], "retrieved_on", where),
            access_status=_choice(r["access_status"], ACCESS, "access_status", where), method=r["method"],
            confidence=_choice(r["confidence"], CONFIDENCE, "confidence", where), summary=r["summary"],
        ))
    for event in events.values():
        if not event.evidence:
            raise RegistryError(f"event {event.event_id} has no evidence row; every event needs at least one")
    _add_auto(directory, stores, events)
    return Registry(stores=stores, events=events, sources=_sources(directory, stores))


def _sources(directory: Path, stores: dict[str, Store]) -> list[tuple[str, str]]:
    """Every page to check automatically: each store's website, plus registry/sources.csv."""
    out = [(s.store_id, s.website) for s in stores.values() if s.website and s.verification_status != "closed"]
    path = directory / "sources.csv"
    if path.is_file():
        for n, r in enumerate(_rows(path), start=2):
            if r["store_id"] not in stores:
                raise RegistryError(f"sources.csv row {n}: unknown store_id {r['store_id']!r}")
            if not r["url"].startswith(("https://", "http://")):
                raise RegistryError(f"sources.csv row {n}: url must start with http(s)://")
            out.append((r["store_id"], r["url"]))
    return list(dict.fromkeys(out))


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    host = urlsplit(url or "").netloc.lower().removeprefix("www.")
    generic = ("facebook.com", "instagram.com", "gamestop.com", "wizards.com", "linktr.ee", "tcgplayerpro.com")
    return "" if not host or any(host == g or host.endswith("." + g) for g in generic) else host


def _same_store(r: dict, lat: float, lon: float, s: Store, same_place) -> bool:
    """An automatically found shop that is already in the registry: same place, same website, or (for a store
    entered with only a city-level location) a shared name word within 25 miles."""
    from .discovery import _tokens
    from .geo import miles_between
    if same_place(r["store_name"], lat, lon, s.store_name, s.latitude, s.longitude):
        return True
    if _host(r.get("website", "")) and _host(r.get("website", "")) == _host(s.website):
        return True
    return (s.location_precision == "city" and miles_between(lat, lon, s.latitude, s.longitude) <= 25
            and bool(_tokens(r["store_name"]) & _tokens(s.store_name)))


def _add_auto(directory: Path, stores: dict[str, Store], events: dict[str, Event]) -> None:
    from .discovery import osm_relevant, read_rows, same_place
    auto = directory / "auto"
    found = [(r, "wpn") for r in read_rows(auto / "wpn_stores.csv")] + [(r, "osm") for r in read_rows(auto / "osm_stores.csv")]
    newest = max((r["last_seen_on"] for r, _ in found if r.get("last_seen_on")), default="")
    for r, origin in found:
        if origin == "osm" and not osm_relevant(r["store_name"], r.get("kind", "")):
            continue
        lat, lon = float(r["latitude"]), float(r["longitude"])
        # Official WPN ids are distinct stores even when close together (two shops in one mall); only compare
        # against hand-entered stores, and OpenStreetMap shops against everything already kept.
        against = [x for x in stores.values() if x.origin == "manual" or origin == "osm"]
        if r["store_id"] in stores or any(_same_store(r, lat, lon, x, same_place) for x in against):
            continue
        current = r.get("last_seen_on") == newest
        wpn = origin == "wpn"
        note = (f"Wizards store locator, WPN store {r['source_id']} ({r['kind']})" if wpn else
                f"OpenStreetMap {r['kind']} ({r['source_id']}); Magic not confirmed") + (
                f"; phone {r['phone']}" if r.get("phone") else "") + ("" if current else f"; not listed since {r['last_seen_on']}")
        stores[r["store_id"]] = Store(
            store_id=r["store_id"], store_name=r["store_name"], address=r["address"], city=r["city"], state=r["state"],
            latitude=lat, longitude=lon, location_precision="address", wpn_status="wpn_verified" if wpn else "wpn_unknown",
            sells_singles="unknown", sells_sealed="unknown",
            verification_status="verified" if wpn and current else "candidate", website=r.get("website", ""), notes=note,
            last_verified_on=date.fromisoformat(r["last_seen_on"]) if r.get("last_seen_on") else None, origin=origin,
            source_id=r["source_id"])
    for r in read_rows(auto / "detections.csv"):
        if r["store_id"] not in stores or r["detection_id"] in events:
            continue
        first, last = date.fromisoformat(r["first_seen_on"]), date.fromisoformat(r["last_seen_on"])
        end = last + timedelta(days=ACTIVE_DETECTION_DAYS) if r["active"] == "yes" else last
        events[r["detection_id"]] = Event(
            event_id=r["detection_id"], store_id=r["store_id"], title=r["headline"], start_date=first, end_date=end,
            local_hours="", timezone="America/Chicago", review_status=AUTO_STATUS, first_seen_on=first,
            last_checked_on=last, notes=f"mtg_context={r['mtg_context']}", alert_version=r.get("version") or "1",
            evidence=[Evidence(evidence_id=f"ev-{r['detection_id']}"[:64], event_id=r["detection_id"],
                               source_type="store_website", url=r["url"], retrieved_on=last, access_status="ok",
                               method="automatic_page_check", confidence="low", summary=r["snippet"])])


def _fail(message: str):
    raise RegistryError(message)
