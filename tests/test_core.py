from datetime import date
import csv
import hashlib
import json

from conftest import event, store, term
from mtg_retail.core import build_db, export, import_stores, validate
from mtg_retail.geo import miles_between


def test_v01_import_bug_is_fixed(tmp_path):
    """v0.1 crashed: 'Table stores does not have a column named current_timestamp' on the first import."""
    src = tmp_path / "c.csv"
    src.write_text("store_name,address,city,state,latitude,longitude,is_example,verification_status\n"
                   "Demo,1 St,Wichita,KS,37.6872,-97.3301,true,candidate\n")
    db = tmp_path / "x.duckdb"
    assert import_stores(src, db) == 1
    assert import_stores(src, db) == 1          # the upsert path runs too


def test_boundary_is_inclusive_at_300_miles():
    # 300 miles due north of the Wichita center along the meridian is about 4.342 degrees of latitude
    assert miles_between(37.6872, -97.3301, 37.6872 + 4.3420, -97.3301) < 300.05


def test_build_and_export_contract(tmp_path, make_registry):
    reg_dir = make_registry(stores=[store(), store(store_id="far-store", lat=40.71, lon=-74.0)],
                            events=[event(status="VERIFIED"), event(event_id="far-sale", store_id="far-store", status="VERIFIED")],
                            terms=[term(pct="35"), term(category="sealed", pct="10"), term(event_id="far-sale", pct="50")])
    db = tmp_path / "w.duckdb"
    build_db(db, registry_dir=reg_dir, today=date(2026, 11, 23))
    counts = validate(db)
    assert counts["stores_total"] == 2 and counts["stores_in_radius"] == 1
    out = tmp_path / "out"
    export(out, db)
    sales = list(csv.DictReader((out / "sales_v1.csv").open()))
    assert [(r["sale_id"], float(r["discount_percent"])) for r in sales] == [("test-sale:singles", 35.0)]
    events = [r["event_id"] for r in csv.DictReader((out / "events_v1.csv").open())]
    assert events == ["test-sale"]                       # out-of-radius events are not exported
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["contract_version"] == "1.1.0"
    for name, meta in manifest["files"].items():
        assert meta["sha256"] == hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert manifest["status"] == "registry_export_manual_sources"
