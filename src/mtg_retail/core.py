"""Working database and exports. The reviewed CSV registry (registry/*.csv) is the source of truth;
`build_db` rebuilds the DuckDB file from it on every run, so ephemeral CI runners lose nothing."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from .evaluate import assess_all, qualifies
from .geo import miles_between
from .registry import REGISTRY, load

BASE = Path(__file__).resolve().parents[2]
CONTRACT_VERSION = "1.1.0"   # 1.0.0 + additive fields (events_v1.csv, manifest checksums/coverage)


def config():
    return json.loads((BASE / "config/region.json").read_text())


def local_today(cfg: dict | None = None) -> date:
    return datetime.now(ZoneInfo((cfg or config())["timezone"])).date()


def db_path():
    return Path(os.environ.get("MTG_DB_PATH", str(BASE / "data/mtg_retail.duckdb")))


def connect(path: Path | None = None):
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))


def init_db(path: Path | None = None):
    with connect(path) as con:
        con.execute((BASE / "sql/schema.sql").read_text())


def stable_id(*parts):
    return hashlib.sha256("|".join(str(p).strip().casefold() for p in parts).encode()).hexdigest()[:20]


def import_stores(path, db: Path | None = None):
    """v0.1 command, kept for ad-hoc candidate lists (it does not touch the governed registry)."""
    cfg = config()
    n = 0
    with connect(db) as con, open(path, newline="", encoding="utf-8") as f:
        con.execute((BASE / "sql/schema.sql").read_text())
        for row in csv.DictReader(f):
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Invalid coordinates")
            dist = miles_between(cfg["center_lat"], cfg["center_lon"], lat, lon)
            if dist > cfg["radius_miles"]:
                continue
            sid = stable_id(row["store_name"], row["address"], row["city"], row["state"])
            # DuckDB reads a bare `current_timestamp` in ON CONFLICT ... SET as a column name (the v0.1 bug):
            # use now() there.
            con.execute("""INSERT INTO stores (store_id,store_name,address,city,state,latitude,longitude,distance_miles,is_example,verification_status)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET
            latitude=excluded.latitude,longitude=excluded.longitude,distance_miles=excluded.distance_miles,
            updated_at=now()""", [sid, row["store_name"], row["address"], row["city"], row["state"], lat, lon, dist,
                                  row.get("is_example", "").lower() == "true", row.get("verification_status", "candidate")])
            n += 1
    return n


def _yes(value: str):
    return True if value == "yes" else False if value == "no" else None


def build_db(path: Path | None = None, registry_dir: Path = REGISTRY, today: date | None = None):
    """Rebuild the working database from the registry. Returns (registry, assessments)."""
    cfg = config()
    today = today or local_today(cfg)
    reg = load(registry_dir)
    assessments = assess_all(reg, cfg, today)
    target = Path(path) if path else db_path()
    if target.exists():
        target.unlink()
    with connect(target) as con:
        con.execute((BASE / "sql/schema.sql").read_text())
        for s in reg.stores.values():
            con.execute("""INSERT INTO stores (store_id,store_name,address,city,state,latitude,longitude,distance_miles,
                wpn_status,sells_singles,sells_sealed,is_example,verification_status,last_verified_at,location_precision,website,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,FALSE,?,?,?,?,?)""",
                        [s.store_id, s.store_name, s.address, s.city, s.state, s.latitude, s.longitude,
                         miles_between(cfg["center_lat"], cfg["center_lon"], s.latitude, s.longitude), s.wpn_status,
                         _yes(s.sells_singles), _yes(s.sells_sealed), s.verification_status, s.last_verified_on,
                         s.location_precision, s.website, s.notes])
        for a in assessments:
            e = a.event
            con.execute("""INSERT INTO promotion_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [e.event_id, e.store_id, e.title, e.start_date, e.end_date, e.local_hours, e.timezone,
                         e.review_status, a.state, a.alert_kind, a.distance_miles, a.in_radius, a.near_boundary,
                         e.terms_version, e.first_seen_on, e.last_checked_on, e.notes])
            for t in e.terms:
                con.execute("INSERT INTO promotion_terms VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [t.event_id, t.category, t.discount_percent, t.mtg_eligible, t.conditions, t.exclusions,
                             t.where, t.verified, t.terms_version, qualifies(t, cfg)])
            for ev in e.evidence:
                con.execute("INSERT INTO promotion_evidence VALUES (?,?,?,?,?,?,?,?,?)",
                            [ev.evidence_id, ev.event_id, ev.source_type, ev.url, ev.retrieved_on, ev.access_status,
                             ev.method, ev.confidence, ev.summary])
            if a.state == "VERIFIED_QUALIFYING" and a.in_radius:
                url = next((ev.url for ev in e.evidence if ev.url), "")
                for t in a.qualifying_terms:
                    con.execute("""INSERT INTO sales (sale_id,store_id,product_category,discount_percent,title,source_url,
                        starts_at,ends_at,verification_status,evidence_note) VALUES (?,?,?,?,?,?,?,?, 'verified', ?)""",
                                [f"{e.event_id}:{t.category}", e.store_id, t.category, t.discount_percent, e.title, url,
                                 datetime.combine(e.start_date, datetime.min.time()),
                                 datetime.combine(e.end_date, datetime.max.time().replace(microsecond=0)),
                                 "; ".join(x for x in (t.conditions, t.exclusions) if x)])
    return reg, assessments


def validate(path: Path | None = None):
    cfg = config()
    with connect(path) as con:
        bad = con.execute("""SELECT COUNT(*) FROM stores WHERE distance_miles IS NULL OR latitude NOT BETWEEN -90 AND 90
                             OR longitude NOT BETWEEN -180 AND 180""").fetchone()[0]
        return {
            "stores_total": con.execute("SELECT COUNT(*) FROM stores").fetchone()[0],
            "stores_in_radius": con.execute("SELECT COUNT(*) FROM stores WHERE distance_miles <= ?", [cfg["radius_miles"]]).fetchone()[0],
            "invalid_geography": bad,
            "verified_stores": con.execute("SELECT COUNT(*) FROM stores WHERE verification_status='verified' AND NOT is_example").fetchone()[0],
            "events_by_state": dict(con.execute("SELECT derived_state, COUNT(*) FROM promotion_events GROUP BY 1 ORDER BY 1").fetchall()),
            "near_boundary_stores": con.execute("SELECT COUNT(*) FROM promotion_events WHERE near_boundary").fetchone()[0],
        }


def _write_csv(con, sql: str, params: list, target: Path) -> None:
    cursor = con.execute(sql, params)
    header = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(["" if v is None else v for v in row] for row in rows)


def export(out="output", path: Path | None = None):
    """Contract v1.x preview. stores_v1/sales_v1 keep their v1.0.0 columns; events_v1 is additive."""
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    cfg = config()
    with connect(path) as con:
        # v0.1 used `COPY ... TO ?`, which DuckDB rejects (the filename cannot be a parameter); write the CSVs here.
        _write_csv(con, """SELECT store_id,store_name,address,city,state,country,latitude,longitude,distance_miles,wpn_id,wpn_status,sells_singles,sells_sealed,last_verified_at
          FROM stores WHERE verification_status='verified' AND NOT is_example AND distance_miles <= ? ORDER BY store_id""",
                   [cfg["radius_miles"]], dest / "stores_v1.csv")
        _write_csv(con, """SELECT s.sale_id,s.store_id,s.product_category,s.discount_percent,s.title,s.source_url,s.starts_at,s.ends_at,s.evidence_note,s.last_seen_at
          FROM sales s JOIN stores t ON s.store_id=t.store_id
          WHERE s.verification_status='verified' AND NOT t.is_example AND t.distance_miles<=?
          AND ((s.product_category='singles' AND s.discount_percent>=?) OR (s.product_category='sealed' AND s.discount_percent>=?))
          AND (s.ends_at IS NULL OR s.ends_at>=current_timestamp)
          ORDER BY s.sale_id""",
                   [cfg["radius_miles"], cfg["threshold_singles_percent"], cfg["threshold_sealed_percent"]], dest / "sales_v1.csv")
        _write_csv(con, """SELECT event_id,store_id,title,start_date,end_date,local_hours,timezone,derived_state,alert_kind,
          round(distance_miles,1) AS distance_miles,terms_version,last_checked_on FROM promotion_events
          WHERE in_radius AND derived_state NOT IN ('EXPIRED') ORDER BY start_date,event_id""", [], dest / "events_v1.csv")
        counts = validate(path)
    files = {}
    for name in ("stores_v1.csv", "sales_v1.csv", "events_v1.csv"):
        data = (dest / name).read_bytes()
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "rows": max(0, data.count(b"\n") - 1)}
    (dest / "manifest.json").write_text(json.dumps({
        "contract_version": CONTRACT_VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "region": cfg, "files": files, "coverage": counts,
        "status": "registry_export_manual_sources",  # no automated collectors yet: an empty sales file is not "no sales"
    }, indent=2, default=str))
