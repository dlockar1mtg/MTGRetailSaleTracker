"""Store discovery on synthetic locator pages (same embedded-data format as locator.wizards.com)."""
from datetime import date
import json

import pytest

from mtg_retail.discovery import (DiscoveryError, decode_stream, locator_data, merge_previous, osm_stores,
                                  parse_address, read_rows, same_place, wpn_stores, write_rows, AUTO_FIELDS)
from mtg_retail.fetch import Page

CFG = {"center_lat": 37.6872, "center_lon": -97.3301, "radius_miles": 300, "near_boundary_review_miles": 10}
TODAY = date(2026, 11, 23)


def flatten(obj) -> list:
    """Encode like React Router's turbo-stream: a flat array of values and index references."""
    arr: list = []

    def put(v):
        i = len(arr)
        arr.append(None)
        if isinstance(v, dict):
            arr[i] = {f"_{put(k)}": (-5 if val is None else put(val)) for k, val in v.items()}
        elif isinstance(v, tuple):          # typed value, e.g. ("U", "https://...") for a URL
            arr[i] = list(v)
        elif isinstance(v, list):
            arr[i] = [put(x) for x in v]
        else:
            arr[i] = v
        return i
    put(obj)
    return arr


def html_for(data: dict) -> str:
    stream = json.dumps(flatten({"loaderData": {"root": {"x": 1}, "routes/($lang).search": data}, "actionData": None}))
    return ('<html><script>window.__reactRouterContext = {};</script><script>'
            f'window.__reactRouterContext.streamController.enqueue({json.dumps(stream + chr(10))});</script></html>')


def store(i, lat, lon, address, website="https://shop{}.example.test/"):
    return {"id": str(i), "name": f"Test Games {i}", "latitude": lat, "longitude": lon, "postalAddress": address,
            "website": website.format(i), "phoneNumber": f"555-01{i:02d}", "isPremium": i == 2, "isLegendary": False,
            "distance": 1000.0 * i, "emailAddress": "x@example.test"}


STORES = [store(1, 37.70, -97.30, "1 Main St, Testville, KS, 67000, United States"),
          store(2, 36.15, -95.99, "2 Elm St\nSuite 3\nTestburg, OK 74000-1234\nUnited States"),
          store(3, 38.83, -97.62, "3 Oak Ave, Testtown, Kansas, 67401, United States"),
          store(4, 41.88, -87.63, "4 Far Rd, Faraway, IL, 60601, United States")]      # ~620 miles: outside


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        n = int(url.rsplit("page=", 1)[1])
        if n not in self.pages:
            return Page(url, 500, "", url, "HTTP 500")
        return Page(url, 200, self.pages[n], url)


def pages(per_page=2, drop=()):
    pins = [{k: s[k] for k in ("id", "name", "latitude", "longitude", "postalAddress")} for s in STORES]
    out = {}
    for n in range(1, (len(STORES) + per_page - 1) // per_page + 1):
        if n in drop:
            continue
        chunk = STORES[(n - 1) * per_page:n * per_page]
        out[n] = html_for({"coords": {"lat": 37.687, "lng": -97.335}, "storePins": pins, "url": ("U", "https://x"),
                           "stores": {"storesByLocation": {"stores": chunk, "pageInfo": {
                               "page": n - 1, "pageSize": per_page, "totalResults": len(STORES)}}}})
    return out


def test_decoder_handles_typed_values_and_nulls():
    data = locator_data(pages()[1])
    assert data["url"] == "https://x" and data["coords"]["lat"] == 37.687
    assert decode_stream(flatten({"a": [1, {"b": "c"}]})) == {"a": [1, {"b": "c"}]}


def test_wpn_stores_pages_through_every_listing_and_keeps_the_radius():
    fetcher = FakeFetcher(pages())
    stores, info = wpn_stores(fetcher, CFG, TODAY)
    assert [s.store_id for s in stores] == ["wpn-1", "wpn-2", "wpn-3"]
    assert info["complete"] and info["pages"] == 2 and info["total_results"] == 4
    assert "distance=310" in fetcher.urls[0] and "query=Wichita%2C+KS" in fetcher.urls[0]
    two = stores[1]
    assert (two.address, two.city, two.state, two.postal_code) == ("2 Elm St, Suite 3", "Testburg", "OK", "74000-1234")
    assert two.kind == "premium" and two.website == "https://shop2.example.test/" and two.phone == "555-0102"
    assert stores[2].state == "KS"


def test_a_failed_listing_page_is_reported_and_keeps_pins():
    stores, info = wpn_stores(FakeFetcher(pages(drop={2})), CFG, TODAY)
    assert len(stores) == 3 and not info["complete"] and info["failed_pages"]
    assert next(s for s in stores if s.store_id == "wpn-3").website == ""   # its listing page failed


def test_unrecognised_page_raises():
    with pytest.raises(DiscoveryError):
        wpn_stores(FakeFetcher({1: "<html>maintenance</html>"}), CFG, TODAY)


@pytest.mark.parametrize("text,expected", [
    ("1 A St, Town, KS, 67000, United States", ("1 A St", "Town", "KS", "67000")),
    ("1 A St\nTown, OK 74000\nUnited States", ("1 A St", "Town", "OK", "74000")),
    ("1 A St\r\nSte 4, Big Town, MO, 64106, United States", ("1 A St, Ste 4", "Big Town", "MO", "64106")),
    ("1 A St, Town, Oklahoma, 73505, United States", ("1 A St", "Town", "OK", "73505")),
    ("8 Plaza, Town,  OK, 73401, USA", ("8 Plaza", "Town", "OK", "73401")),
    ("12 Rock Ave, Oklahoma City, OK, 73142-2704, U", ("12 Rock Ave", "Oklahoma City", "OK", "73142-2704")),
])
def test_address_shapes(text, expected):
    a = parse_address(text)
    assert (a["address"], a["city"], a["state"], a["postal_code"]) == expected


def test_merge_keeps_history_and_temporarily_missing_stores(tmp_path):
    path = tmp_path / "wpn.csv"
    old, _ = wpn_stores(FakeFetcher(pages()), CFG, date(2026, 11, 1))
    write_rows(path, AUTO_FIELDS, [s.row() for s in old])
    new, _ = wpn_stores(FakeFetcher(pages()), CFG, TODAY)
    merged = merge_previous([s for s in new if s.store_id != "wpn-3"], path)
    by = {s.store_id: s for s in merged}
    assert by["wpn-1"].first_seen_on == "2026-11-01" and by["wpn-1"].last_seen_on == "2026-11-23"
    assert by["wpn-3"].last_seen_on == "2026-11-01"          # missing today, kept (within 60 days)
    write_rows(path, AUTO_FIELDS, [s.row() for s in merged])
    assert len(read_rows(path)) == 3


def test_osm_shops_and_dedupe():
    data = {"elements": [
        {"type": "node", "id": 7, "lat": 37.75, "lon": -97.20, "tags": {"name": "Dragon Hobby", "shop": "hobby",
                                                                         "addr:city": "Testville", "addr:state": "KS",
                                                                         "website": "dragon.example.test"}},
        {"type": "way", "id": 8, "center": {"lat": 37.0, "lon": -97.0}, "tags": {"shop": "games"}},      # no name
        {"type": "node", "id": 9, "lat": 45.0, "lon": -93.0, "tags": {"name": "Too Far", "shop": "games"}},
    ]}
    calls = []

    def fake(url, query):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("busy")
        assert 'shop"="games"' in query and "(33.1944,-103.0074,42.1800,-91.6528)" in query
        return data
    stores, info = osm_stores(fake, CFG, TODAY)
    assert [s.store_id for s in stores] == ["osm-n7"] and len(calls) == 2
    assert stores[0].website == "http://dragon.example.test" and stores[0].state == "KS"
    assert same_place("Dragon Hobby", 37.75, -97.20, "The Dragon's Lair Hobby", 37.751, -97.201) is False
    assert same_place("Dragon Hobby", 37.75, -97.20, "Dragon Games", 37.755, -97.205) is True
    assert same_place("Alpha", 37.75, -97.20, "Beta", 37.7501, -97.2001) is True
