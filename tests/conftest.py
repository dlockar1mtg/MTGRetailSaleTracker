"""Synthetic registries for tests. Never the real registry/ data."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

STORE_FIELDS = ["store_id", "store_name", "address", "city", "state", "latitude", "longitude", "location_precision",
                "wpn_status", "sells_singles", "sells_sealed", "verification_status", "website", "notes", "last_verified_on"]
EVENT_FIELDS = ["event_id", "store_id", "title", "start_date", "end_date", "local_hours", "timezone", "review_status",
                "first_seen_on", "last_checked_on", "notes"]
TERM_FIELDS = ["event_id", "category", "discount_percent", "mtg_eligible", "conditions", "exclusions", "where", "verified",
               "terms_version"]
EVIDENCE_FIELDS = ["evidence_id", "event_id", "source_type", "url", "retrieved_on", "access_status", "method",
                   "confidence", "summary"]


def store(store_id="test-store", lat=37.80, lon=-96.90, **kw):
    row = dict(store_id=store_id, store_name="Test Games", address="1 Test St", city="Testville", state="KS",
               latitude=lat, longitude=lon, location_precision="city", wpn_status="wpn_unknown", sells_singles="yes",
               sells_sealed="yes", verification_status="verified", website="", notes="", last_verified_on="2026-11-01")
    row.update(kw)
    return row


def event(event_id="test-sale", store_id="test-store", start="2026-11-27", end="2026-11-27", status="ANNOUNCED_TERMS_UNKNOWN", **kw):
    row = dict(event_id=event_id, store_id=store_id, title="Test Sale", start_date=start, end_date=end, local_hours="",
               timezone="America/Chicago", review_status=status, first_seen_on="2026-11-20", last_checked_on="2026-11-20",
               notes="")
    row.update(kw)
    return row


def term(event_id="test-sale", category="singles", pct="30", mtg="yes", verified="yes", version="1", **kw):
    row = dict(event_id=event_id, category=category, discount_percent=pct, mtg_eligible=mtg, conditions="", exclusions="",
               where="in_store", verified=verified, terms_version=version)
    row.update(kw)
    return row


def evidence(event_id="test-sale", evidence_id=None, source_type="store_website", url="https://example.test/sale", **kw):
    row = dict(evidence_id=evidence_id or f"ev-{event_id}", event_id=event_id, source_type=source_type, url=url,
               retrieved_on="2026-11-20", access_status="ok", method="manual_review", confidence="high", summary="test")
    row.update(kw)
    return row


def write(directory: Path, stores=(), events=(), terms=(), evidence_rows=()):
    directory.mkdir(parents=True, exist_ok=True)
    for name, fields, rows in (("stores.csv", STORE_FIELDS, stores), ("events.csv", EVENT_FIELDS, events),
                               ("terms.csv", TERM_FIELDS, terms), ("evidence.csv", EVIDENCE_FIELDS, evidence_rows)):
        with (directory / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return directory


@pytest.fixture
def make_registry(tmp_path):
    def _make(stores=(store(),), events=(event(),), terms=(), evidence_rows=None):
        if evidence_rows is None:
            evidence_rows = [evidence(e["event_id"]) for e in events]
        return write(tmp_path / "registry", stores, events, terms, evidence_rows)
    return _make
