"""Automatic sale checks on synthetic store pages."""
from datetime import date
import io
import urllib.error

import pytest

from conftest import store as store_row, write as write_registry
from mtg_retail.alerts import parse_ledger, plan, title_for
from mtg_retail.core import config
from mtg_retail.discovery import AUTO_FIELDS, write_rows
from mtg_retail.evaluate import assess_all
from mtg_retail.fetch import Fetcher, Page
from mtg_retail.registry import load
from mtg_retail.watch import (CHECK_FIELDS, DETECTION_FIELDS, CheckResult, check_sources, checkable, find_sales,
                              merge_detections, visible_text)

TODAY = date(2026, 11, 23)

BANNER = """<html><head><title>Test Games</title><meta name="description" content="Your local game store">
<script>var sale = "99% off";</script><style>.x{}</style></head><body>
<div class="announcement-bar"><p>BLACK FRIDAY</p><p>25% off all Magic singles, Fri 11/27 only!</p></div>
<p>Pokemon booster boxes 30% off this week</p>
<p>Members save 10% every day</p>
<p>Pre-orders for the next Magic set are open.</p>
</body></html>"""


def test_visible_text_skips_scripts_and_keeps_blocks():
    blocks = visible_text(BANNER)
    assert "Your local game store" in blocks and "BLACK FRIDAY" in blocks
    assert not any("99%" in b for b in blocks)


def test_find_sales_keeps_magic_and_drops_other_games_and_small_discounts():
    (found,) = find_sales(visible_text(BANNER), wpn_store=True)
    assert "BLACK FRIDAY · 25% off all Magic singles" in found.text and "Pokemon" not in found.text
    assert found.mtg == "yes" and found.percents == (25,) and found.headline == "25% off · Black Friday"
    assert find_sales(["Pokemon booster boxes 30% off this week"], wpn_store=True) == []
    assert find_sales(["Members save 10% every day"], wpn_store=True) == []


def test_storewide_counts_for_wpn_stores_only():
    blocks = ["Holiday Sale: 20% off everything in the store Dec 1-7"]
    assert [s.mtg for s in find_sales(blocks, wpn_store=True)] == ["storewide"]
    assert find_sales(blocks, wpn_store=False) == []
    assert find_sales(["Our 10% off punch card"], wpn_store=True) == []


def test_headline_and_stable_key():
    (s,) = find_sales(["Save 30% on Magic sealed this weekend"], wpn_store=True)
    assert s.headline == "30% off" and s.percents == (30,)
    (again,) = find_sales(["Save 30%  on MAGIC sealed this weekend"], wpn_store=True)
    assert again.key == s.key


def test_skipped_hosts():
    assert checkable("https://www.facebook.com/somestore")[0] is False
    assert checkable("https://www.gamestop.com/")[0] is False
    assert checkable("")[0] is False
    assert checkable("https://store.example.test/")[0] is True


class FakeOpener:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, req, timeout=30):
        self.seen.append(req.full_url)
        status, body = self.routes.get(req.full_url, (404, ""))
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)

        class R(io.BytesIO):
            headers = {"Content-Type": "text/html; charset=utf-8"}
            url = req.full_url

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        r = R(body.encode())
        r.status = status
        return r


def test_check_sources_obeys_robots_and_fetches_shared_pages_once():
    opener = FakeOpener({
        "https://a.example.test/robots.txt": (200, "User-agent: *\nDisallow:"),
        "https://a.example.test/": (200, BANNER),
        "https://b.example.test/robots.txt": (200, "User-agent: *\nDisallow: /"),
        "https://c.example.test/robots.txt": (404, ""),
        "https://c.example.test/": (403, ""),
    })
    fetcher = Fetcher(opener=opener, min_interval=0)
    results = check_sources(fetcher, [("s1", "https://a.example.test/", True), ("s2", "https://a.example.test/", True),
                                      ("s3", "https://b.example.test/", True), ("s4", "https://c.example.test/", True),
                                      ("s5", "https://facebook.com/x", True)])
    by = {r.store_id: r for r in results}
    assert by["s1"].status == "ok" and by["s1"].snippets and by["s2"].snippets
    assert opener.seen.count("https://a.example.test/") == 1
    assert by["s3"].status == "robots" and "https://b.example.test/" not in opener.seen
    assert by["s4"].status == "blocked" and by["s5"].status == "skipped"


def _result(store_id, url, texts, status="ok"):
    return CheckResult(store_id, url, status, "", [s for t in texts for s in find_sales([t], True)])


def test_detections_stay_active_while_seen_and_survive_page_errors():
    r1 = merge_detections([], [_result("s1", "https://a/", ["Black Friday sale on Magic"])], TODAY)
    assert r1[0]["active"] == "yes" and r1[0]["first_seen_on"] == "2026-11-23"
    later = date(2026, 11, 25)
    r2 = merge_detections(r1, [_result("s1", "https://a/", [], status="error")], later)
    assert r2[0]["active"] == "yes" and r2[0]["last_seen_on"] == "2026-11-23"     # unreadable page: unchanged
    r3 = merge_detections(r2, [_result("s1", "https://a/", [])], later)
    assert r3[0]["active"] == "no"                                                # read, and gone


def _registry_with_detection(tmp_path, active="yes", last="2026-11-23", wpn=True):
    reg = write_registry(tmp_path / "registry", stores=[store_row(store_id="manual-store", lat=36.0, lon=-95.0)])
    auto = reg / "auto"
    write_rows(auto / "wpn_stores.csv", AUTO_FIELDS, [
        {"store_id": "wpn-1", "source": "wpn", "source_id": "1", "store_name": "Test Games", "address": "1 Main St",
         "city": "Testville", "state": "KS", "postal_code": "67000", "latitude": 37.70, "longitude": -97.30,
         "distance_miles": 2.0, "website": "https://a.example.test/", "phone": "", "kind": "standard",
         "first_seen_on": "2026-11-01", "last_seen_on": "2026-11-23"},
        {"store_id": "wpn-2", "source": "wpn", "source_id": "2", "store_name": "Test Games", "address": "x",
         "city": "Elsewhere", "state": "OK", "postal_code": "", "latitude": 36.0001, "longitude": -95.0001,
         "distance_miles": 150.0, "website": "", "phone": "", "kind": "standard",
         "first_seen_on": "2026-11-01", "last_seen_on": "2026-11-23"}])
    write_rows(auto / "detections.csv", DETECTION_FIELDS, [
        {"detection_id": "auto-wpn-1-abcdef0123", "store_id": "wpn-1", "url": "https://a.example.test/",
         "headline": "25% off · Black Friday", "snippet": "BLACK FRIDAY 25% off all Magic singles",
         "percents": "25", "named_sale": "BLACK FRIDAY", "mtg_context": "yes", "first_seen_on": "2026-11-20",
         "last_seen_on": last, "active": active}])
    return reg


def test_auto_stores_merge_and_detections_alert_once(tmp_path):
    reg = load(_registry_with_detection(tmp_path))
    assert "wpn-1" in reg.stores and "wpn-2" not in reg.stores            # wpn-2 duplicates the manual store
    assert reg.stores["wpn-1"].verification_status == "verified" and reg.stores["wpn-1"].origin == "wpn"
    assert ("wpn-1", "https://a.example.test/") in reg.sources
    a = [x for x in assess_all(reg, config(), TODAY) if x.event.event_id.startswith("auto-")]
    assert a[0].state == "AUTO_DETECTED" and a[0].alert_kind == "spotted"
    (act,) = [x for x in plan(a, {}, "owner", TODAY)]
    assert act.title.startswith("\U0001F50E POSSIBLE MTG SALE (found automatically, unverified): 25% off")
    assert "NOT VERIFIED" in act.body and "BLACK FRIDAY 25% off all Magic singles" in act.body
    ledger = parse_ledger([{"number": 4, "body": act.body, "state": "open"}], {})
    assert plan(a, ledger, "owner", TODAY) == []


def test_detection_gone_closes_its_issue_after_a_week(tmp_path):
    reg = load(_registry_with_detection(tmp_path, active="no", last="2026-11-20"))
    a = [x for x in assess_all(reg, config(), TODAY) if x.event.event_id.startswith("auto-")]
    assert a[0].state == "EXPIRED"
    body = "x <!-- mtg-retail-alert event=auto-wpn-1-abcdef0123 kind=spotted version=1 -->"
    (act,) = plan(a, parse_ledger([{"number": 9, "body": body, "state": "open"}], {}), "o", TODAY)
    assert act.kind == "close" and act.issue_number == 9
    digest_body = body + "\n<!-- mtg-retail-alert event=auto-other-1 kind=spotted version=1 -->"
    assert plan(a, parse_ledger([{"number": 9, "body": digest_body, "state": "open"}], {}), "o", TODAY) == []


def test_many_new_finds_share_one_digest_issue(tmp_path):
    from mtg_retail.alerts import digest
    reg = load(_registry_with_detection(tmp_path))
    a = [x for x in assess_all(reg, config(), TODAY) if x.event.event_id.startswith("auto-")]
    acts = plan(a, {}, "owner", TODAY)
    d = digest(acts, {x.event.event_id: x for x in a}, "owner", TODAY)
    assert d.title.startswith("\U0001F50E 1 POSSIBLE MTG SALES") and "@owner" in d.body
    ledger = parse_ledger([{"number": 5, "body": d.body + "\n<!-- mtg-retail-alert event=auto-x-1 kind=spotted version=1 -->",
                            "state": "open"}], {})
    assert ledger[("auto-wpn-1-abcdef0123", "spotted")].shared and plan(a, ledger, "owner", TODAY) == []


def test_auto_store_matching_a_hand_entered_store_by_website_or_city_name_is_not_duplicated(tmp_path):
    reg_dir = write_registry(tmp_path / "registry", stores=[
        store_row(store_id="hand-entered", lat=36.154, lon=-95.993, location_precision="city",
                  store_name="Wizards Asylum Comics & Games", website="https://www.asylum.example.test/")])
    rows = [{"store_id": f"wpn-{i}", "source": "wpn", "source_id": str(i), "store_name": name, "address": "", "city": "Tulsa",
             "state": "OK", "postal_code": "", "latitude": lat, "longitude": lon, "distance_miles": 130.0, "website": site,
             "phone": "", "kind": "standard", "first_seen_on": "2026-11-23", "last_seen_on": "2026-11-23"}
            for i, name, lat, lon, site in [
                (1, "Wizard's Asylum", 36.06, -95.85, ""),                                # city-level match by name
                (2, "Different Name LLC", 36.20, -95.90, "http://asylum.example.test/shop"),  # same website
                (3, "Another Shop", 36.10, -95.95, "https://another.example.test/")]]
    write_rows(reg_dir / "auto" / "wpn_stores.csv", AUTO_FIELDS, rows)
    reg = load(reg_dir)
    assert set(reg.stores) == {"hand-entered", "wpn-3"}


def test_one_detection_per_page_and_a_new_discount_is_an_update(tmp_path):
    lines = ["Black Friday Sale! · Log in", "Black Friday Sale! · Search", "25% off Magic singles Friday"]
    first = merge_detections([], [_result("s1", "https://a/", lines)], TODAY)
    assert len(first) == 1 and first[0]["headline"] == "25% off · Black Friday"
    assert first[0]["detection_id"].startswith("auto-s1-") and first[0]["detection_id"].endswith("-202611")
    same = merge_detections(first, [_result("s1", "https://a/", lines[::-1])], date(2026, 11, 24))
    assert [r["detection_id"] for r in same] == [first[0]["detection_id"]] and same[0]["version"] == first[0]["version"]
    bigger = merge_detections(same, [_result("s1", "https://a/", ["40% off Magic singles Friday"])], date(2026, 11, 25))
    assert bigger[0]["detection_id"] == first[0]["detection_id"] and bigger[0]["version"] != first[0]["version"]
    assert bigger[0]["first_seen_on"] == "2026-11-23"


def test_magic_exclusions_are_flagged():
    (s,) = find_sales(["BLACK FRIDAY SALE · Buy One Get One 50% Off Storewide · Excludes Sealed MtG, Games Workshop"], True)
    assert s.mtg == "excluded"
