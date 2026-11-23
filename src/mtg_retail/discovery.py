"""Store discovery: every Wizards Play Network store within the radius, plus game shops mapped in OpenStreetMap.

WPN (official): the public Store & Event Locator search page,
    https://locator.wizards.com/search?searchType=stores&query=Wichita%2C+KS&distance=310&page=N
These /search pages are what the locator's own sitemap lists for crawling; robots.txt allows them (only /api/
and /auth/ are disallowed, and we use neither). One page carries every store's map pin (id, name, coordinates,
address) and ten full listings (website, phone); the remaining listings are paged. The page embeds its data as a
React Router "turbo-stream", decoded below. About 32 requests a week, two seconds apart.

OpenStreetMap (open data, ODbL): shops tagged games / hobby / collector / comic books, via the Overpass API.
These are candidates: OSM does not say whether a shop sells Magic, so their sale pages only raise an alert when
the page itself mentions Magic.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field, fields
from datetime import date
import json
import math
import re
from pathlib import Path
from urllib.parse import quote_plus, urlencode

from .fetch import Fetcher
from .geo import miles_between

LOCATOR = "https://locator.wizards.com/search"
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
STATE_NAMES = {
    "alabama": "AL", "arkansas": "AR", "colorado": "CO", "iowa": "IA", "illinois": "IL", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "missouri": "MO", "nebraska": "NE", "new mexico": "NM", "oklahoma": "OK",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "wyoming": "WY", "mississippi": "MS",
}
COUNTRY = re.compile(r"^(united states( of america)?|us|usa|u\.?s\.?a?\.?|u)$", re.I)
ZIP = re.compile(r"^\d{5}(-\d{4})?$")
STATE_ZIP = re.compile(r"^(.+?)\s+(\d{5}(?:-\d{4})?)$")


class DiscoveryError(RuntimeError):
    pass


# ---------- turbo-stream (React Router single-fetch) ----------

def stream_from_html(html: str) -> list:
    """The flat turbo-stream array a React Router page enqueues for hydration."""
    chunks = re.findall(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\);', html)
    if not chunks:
        raise DiscoveryError("no embedded page data found (the locator page layout may have changed)")
    text = "".join(json.loads(c) for c in chunks)
    first = next((line for line in text.split("\n") if line.strip()), "")
    return json.loads(first)


def decode_stream(arr: list):
    """Decode turbo-stream's flattened form: objects are {"_<key index>": <value index>}, arrays are lists of
    indices, negative indices are null/undefined markers, and ["X", payload] entries are typed values."""
    memo: dict[int, object] = {}

    def value(i):
        if isinstance(i, int) and i < 0:
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str):
                out = v[1] if len(v) > 1 else None
                memo[i] = out
                return out
            out_list: list = []
            memo[i] = out_list
            out_list.extend(value(x) for x in v)
            return out_list
        if isinstance(v, dict):
            out_obj: dict = {}
            memo[i] = out_obj
            for k, vi in v.items():
                out_obj[arr[int(k[1:])]] = value(vi)
            return out_obj
        memo[i] = v
        return v

    return value(0)


def locator_data(html: str) -> dict:
    root = decode_stream(stream_from_html(html))
    for key, data in (root.get("loaderData") or {}).items():
        if key.endswith(".search") and isinstance(data, dict):
            return data
    raise DiscoveryError("the locator page has no search results block")


# ---------- addresses ----------

def parse_address(text: str) -> dict:
    """'12 Main St, Suite 4, Salina, KS, 67401, United States' and the locator's other shapes
    ('12 Main St\\nSalina, KS 67401\\nUnited States', full state names) -> street, city, state, postal_code."""
    parts = [p.strip() for p in re.split(r"[\r\n]+|,", text or "") if p.strip()]
    if parts and COUNTRY.match(parts[-1]):
        parts.pop()
    postal = state = ""
    if parts and ZIP.match(parts[-1]):
        postal = parts.pop()
    elif parts and STATE_ZIP.match(parts[-1]):
        state, postal = STATE_ZIP.match(parts.pop()).groups()
    if not state and parts:
        state = parts.pop()
    state = STATE_NAMES.get(state.strip().lower(), state.strip().upper()) if state else ""
    city = parts.pop() if parts else ""
    return {"address": ", ".join(parts), "city": city, "state": state if len(state) == 2 else "", "postal_code": postal}


# ---------- stores ----------

AUTO_FIELDS = ["store_id", "source", "source_id", "store_name", "address", "city", "state", "postal_code", "latitude",
               "longitude", "distance_miles", "website", "phone", "kind", "first_seen_on", "last_seen_on"]


@dataclass
class AutoStore:
    store_id: str
    source: str              # wpn | osm
    source_id: str
    store_name: str
    address: str
    city: str
    state: str
    postal_code: str
    latitude: float
    longitude: float
    distance_miles: float
    website: str = ""
    phone: str = ""
    kind: str = ""           # wpn: premium/legendary/standard; osm: the shop tag
    first_seen_on: str = ""
    last_seen_on: str = ""
    extra: dict = field(default_factory=dict, repr=False)

    def row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "extra"}


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I) and "." in url and " " not in url:
        url = "http://" + url
    return url if re.match(r"^https?://[^\s]+\.[^\s]+", url, re.I) else ""


def wpn_stores(fetcher: Fetcher, cfg: dict, today: date) -> tuple[list[AutoStore], dict]:
    query = cfg.get("wpn_query", "Wichita, KS")
    distance = cfg.get("wpn_query_distance_miles", cfg["radius_miles"] + cfg.get("near_boundary_review_miles", 10))
    limit = cfg["radius_miles"] + cfg.get("near_boundary_review_miles", 10)

    def page(n: int) -> dict:
        url = f"{LOCATOR}?{urlencode({'searchType': 'stores', 'query': query, 'distance': distance, 'page': n}, quote_via=quote_plus)}"
        got = fetcher.get(url)
        if not got.ok:
            raise DiscoveryError(f"locator page {n}: {got.error or got.status}")
        return locator_data(got.text)

    first = page(1)
    info = ((first.get("stores") or {}).get("storesByLocation") or {}).get("pageInfo") or {}
    total, size = int(info.get("totalResults") or 0), int(info.get("pageSize") or 10)
    pins = {str(p["id"]): p for p in first.get("storePins") or [] if p.get("id") is not None}
    if not total or not pins:
        raise DiscoveryError("the locator returned no stores (query not understood or layout changed)")
    details: dict[str, dict] = {}
    pages = max(1, math.ceil(total / size))
    failed_pages = []
    for n in range(1, pages + 1):
        try:
            data = first if n == 1 else page(n)
        except DiscoveryError as exc:
            failed_pages.append(f"{n}: {exc}")
            continue
        for s in ((data.get("stores") or {}).get("storesByLocation") or {}).get("stores") or []:
            details[str(s["id"])] = s
    out = []
    for sid, pin in pins.items():
        d = details.get(sid, {})
        lat, lon = float(pin["latitude"]), float(pin["longitude"])
        miles = miles_between(cfg["center_lat"], cfg["center_lon"], lat, lon)
        if miles > limit:
            continue
        addr = parse_address(d.get("postalAddress") or pin.get("postalAddress") or "")
        out.append(AutoStore(
            store_id=f"wpn-{sid}", source="wpn", source_id=sid, store_name=(d.get("name") or pin.get("name") or "").strip(),
            latitude=round(lat, 6), longitude=round(lon, 6), distance_miles=round(miles, 1),
            website=_clean_url(d.get("website") or ""), phone=(d.get("phoneNumber") or "").strip(),
            kind="legendary" if d.get("isLegendary") else "premium" if d.get("isPremium") else "standard",
            first_seen_on=today.isoformat(), last_seen_on=today.isoformat(),
            extra={"has_detail": bool(d)}, **addr))
    manifest = {"source": "wpn_locator", "query": query, "query_distance_miles": distance, "total_results": total,
                "pins": len(pins), "pages": pages, "failed_pages": failed_pages,
                "listings_with_detail": sum(s.extra["has_detail"] for s in out), "kept_within_miles": limit,
                "kept": len(out), "complete": len(pins) == total and not failed_pages}
    return out, manifest


def overpass_query(cfg: dict) -> str:
    """A bounding box around the circle (much lighter for Overpass than a 500 km "around"); distance is
    filtered here afterwards."""
    miles = cfg["radius_miles"] + cfg.get("near_boundary_review_miles", 10)
    dlat = miles / 69.0
    dlon = miles / (69.0 * math.cos(math.radians(cfg["center_lat"])))
    box = (f"({cfg['center_lat'] - dlat:.4f},{cfg['center_lon'] - dlon:.4f},"
           f"{cfg['center_lat'] + dlat:.4f},{cfg['center_lon'] + dlon:.4f})")
    return (f'[out:json][timeout:240];(nwr["shop"="games"]{box};nwr["shop"="hobby"]{box};'
            f'nwr["shop"="collector"]{box};nwr["shop"="books"]["books"~"comic"]{box};'
            f'nwr["shop"="comics"]{box};);out center tags;')


def osm_stores(fetch_json, cfg: dict, today: date) -> tuple[list[AutoStore], dict]:
    """`fetch_json(url, query) -> dict` posts the Overpass query (tests pass a fake)."""
    query = overpass_query(cfg)
    errors = []
    data = None
    for endpoint in OVERPASS:
        try:
            data = fetch_json(endpoint, query)
            break
        except Exception as exc:  # noqa: BLE001 - try the next public endpoint
            errors.append(f"{endpoint}: {type(exc).__name__}: {str(exc)[:120]}")
    if data is None:
        raise DiscoveryError("OpenStreetMap (Overpass) unavailable: " + "; ".join(errors))
    limit = cfg["radius_miles"] + cfg.get("near_boundary_review_miles", 10)
    out = []
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if not name or lat is None or lon is None:
            continue
        miles = miles_between(cfg["center_lat"], cfg["center_lon"], float(lat), float(lon))
        if miles > limit:
            continue
        street = " ".join(x for x in (tags.get("addr:housenumber", ""), tags.get("addr:street", "")) if x)
        osm_id = f"{el.get('type', 'x')[0]}{el.get('id')}"
        out.append(AutoStore(
            store_id=f"osm-{osm_id}", source="osm", source_id=osm_id, store_name=name, address=street,
            city=tags.get("addr:city", ""), state=STATE_NAMES.get(tags.get("addr:state", "").lower(), tags.get("addr:state", "").upper()[:2]),
            postal_code=tags.get("addr:postcode", ""), latitude=round(float(lat), 6), longitude=round(float(lon), 6),
            distance_miles=round(miles, 1), website=_clean_url(tags.get("website") or tags.get("contact:website") or ""),
            phone=tags.get("phone") or tags.get("contact:phone") or "", kind=f"shop={tags.get('shop', '')}",
            first_seen_on=today.isoformat(), last_seen_on=today.isoformat()))
    return out, {"source": "openstreetmap_overpass", "elements": len(data.get("elements") or []), "kept": len(out),
                 "kept_within_miles": limit, "complete": True}


# ---------- merging and files ----------

STOP = {"the", "and", "of", "games", "game", "gaming", "shop", "store", "llc", "inc", "co", "hobby", "hobbies",
        "comics", "comic", "cards", "card", "collectibles", "&", "-", "tcg"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", name.lower()) if len(t) >= 3 and t not in STOP}


def same_place(a_name: str, a_lat: float, a_lon: float, b_name: str, b_lat: float, b_lon: float) -> bool:
    miles = miles_between(a_lat, a_lon, b_lat, b_lon)
    return miles <= 0.08 or (miles <= 1.0 and bool(_tokens(a_name) & _tokens(b_name)))


def merge_previous(current: list[AutoStore], path: Path) -> list[AutoStore]:
    """Keep first_seen_on; stores missing from today's listing stay with their old last_seen_on (they may be
    a temporary gap) and drop after 60 days."""
    previous = {r["store_id"]: r for r in read_rows(path)}
    out = []
    seen = set()
    for s in current:
        old = previous.get(s.store_id)
        if old:
            s.first_seen_on = old["first_seen_on"] or s.first_seen_on
            if not s.website and old.get("website"):
                s.website = old["website"]          # a page of listings failed this run; keep the last known site
            if not s.phone and old.get("phone"):
                s.phone = old["phone"]
        seen.add(s.store_id)
        out.append(s)
    today = date.fromisoformat(current[0].last_seen_on) if current else date.today()
    for sid, r in previous.items():
        if sid in seen or not r.get("last_seen_on"):
            continue
        if (today - date.fromisoformat(r["last_seen_on"])).days <= 60:
            out.append(AutoStore(**{k: (float(r[k]) if k in ("latitude", "longitude", "distance_miles") else r[k])
                                    for k in AUTO_FIELDS}))
    return sorted(out, key=lambda s: (s.distance_miles, s.store_id))


def read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
