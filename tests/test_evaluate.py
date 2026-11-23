from datetime import date

import pytest

from conftest import event, evidence, store, term
from mtg_retail.core import config
from mtg_retail.evaluate import assess_all
from mtg_retail.registry import RegistryError, load

TODAY = date(2026, 11, 23)


def states(path):
    return {a.event.event_id: (a.state, a.alert_kind) for a in assess_all(load(path), config(), TODAY)}


def test_gathering_point_fixture_is_a_lead_not_a_deal(make_registry):
    """Calendar image says 'Black Friday Sale!' with no terms: a lead, never a qualifying alert."""
    path = make_registry(events=[event(status="ANNOUNCED_TERMS_UNKNOWN")],
                         evidence_rows=[evidence(source_type="user_screenshot", url="", access_status="not_applicable")])
    assert states(path)["test-sale"] == ("ANNOUNCED_TERMS_UNKNOWN", "lead")


def test_generic_discount_without_verified_mtg_eligibility_does_not_qualify(make_registry):
    path = make_registry(events=[event(status="VERIFIED")],
                         terms=[term(pct="50", mtg="unknown"), term(category="sealed", pct="25", mtg="unknown")])
    assert states(path)["test-sale"] == ("VERIFIED_NOT_APPLICABLE", None)


@pytest.mark.parametrize("category,pct,expected", [
    ("singles", "29", "VERIFIED_BELOW_THRESHOLD"), ("singles", "30", "VERIFIED_QUALIFYING"),
    ("sealed", "19", "VERIFIED_BELOW_THRESHOLD"), ("sealed", "20", "VERIFIED_QUALIFYING"),
])
def test_thresholds_are_inclusive(make_registry, category, pct, expected):
    path = make_registry(events=[event(status="VERIFIED")], terms=[term(category=category, pct=pct)])
    assert states(path)["test-sale"][0] == expected


def test_unverified_terms_never_qualify(make_registry):
    path = make_registry(events=[event(status="VERIFIED")], terms=[term(pct="50", verified="no")])
    assert states(path)["test-sale"] == ("VERIFIED_NOT_APPLICABLE", None)


def test_store_outside_the_radius_never_alerts(make_registry):
    far = store(lat=40.7128, lon=-74.0060)   # New York: ~1,200 miles
    path = make_registry(stores=[far], events=[event(status="VERIFIED")], terms=[term(pct="50")])
    (a,) = assess_all(load(path), config(), TODAY)
    assert a.state == "VERIFIED_QUALIFYING" and not a.in_radius and a.alert_kind is None


def test_expired_and_cancelled(make_registry):
    path = make_registry(events=[event(event_id="old-sale", start="2026-11-20", end="2026-11-22", status="VERIFIED"),
                                 event(event_id="gone-sale", status="CANCELLED")],
                         terms=[term(event_id="old-sale", pct="50")])
    got = states(path)
    assert got["old-sale"] == ("EXPIRED", None) and got["gone-sale"] == ("CANCELLED", None)


def test_a_sale_that_runs_today_is_still_live(make_registry):
    path = make_registry(events=[event(start="2026-11-21", end="2026-11-23", status="VERIFIED")], terms=[term(pct="40")])
    assert states(path)["test-sale"] == ("VERIFIED_QUALIFYING", "verified")


def test_closed_store_never_alerts(make_registry):
    path = make_registry(stores=[store(verification_status="closed")], events=[event()])
    assert states(path)["test-sale"][1] is None


@pytest.mark.parametrize("bad,match", [
    (dict(events=[event(store_id="nope")]), "unknown store_id"),
    (dict(events=[event(status="MAYBE")]), "review_status"),
    (dict(events=[event()], evidence_rows=[]), "no evidence"),
    (dict(events=[event()], evidence_rows=[evidence(url="")]), "needs its direct URL"),
    (dict(events=[event(start="2026-11-28", end="2026-11-27")]), "before start_date"),
    (dict(events=[event()], terms=[term(), term()]), "one row per event and category"),
    (dict(events=[event()], terms=[term(pct="120")]), "0-100"),
    (dict(stores=[store(store_id="Bad Id")]), "ids are"),
])
def test_registry_rejects_bad_rows(make_registry, bad, match):
    with pytest.raises(RegistryError, match=match):
        load(make_registry(**bad))


def test_the_real_registry_loads():
    reg = load()
    assert reg.stores and all(e.evidence for e in reg.events.values())
