import csv
import hashlib
import json
import os
from pathlib import Path
import duckdb
from .geo import miles_between

BASE = Path(__file__).resolve().parents[2]
def config():
    return json.loads((BASE / 'config/region.json').read_text())
def db_path():
    return Path(os.environ.get('MTG_DB_PATH', str(BASE / 'data/mtg_retail.duckdb')))
def connect():
    p = db_path(); p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))
def init_db():
    with connect() as con:
        con.execute((BASE / 'sql/schema.sql').read_text())
def stable_id(*parts):
    return hashlib.sha256('|'.join(str(p).strip().casefold() for p in parts).encode()).hexdigest()[:20]
def import_stores(path):
    cfg=config(); n=0
    with connect() as con, open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            lat=float(row['latitude']); lon=float(row['longitude'])
            if not (-90<=lat<=90 and -180<=lon<=180): raise ValueError('Invalid coordinates')
            dist=miles_between(cfg['center_lat'],cfg['center_lon'],lat,lon)
            if dist > cfg['radius_miles']: continue
            sid=stable_id(row['store_name'],row['address'],row['city'],row['state'])
            con.execute("""INSERT INTO stores (store_id,store_name,address,city,state,latitude,longitude,distance_miles,is_example,verification_status)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET
            latitude=excluded.latitude,longitude=excluded.longitude,distance_miles=excluded.distance_miles,
            updated_at=current_timestamp""", [sid,row['store_name'],row['address'],row['city'],row['state'],lat,lon,dist,
            row.get('is_example','').lower()=='true',row.get('verification_status','candidate')]); n+=1
    return n
def validate():
    with connect() as con:
        bad=con.execute("""SELECT COUNT(*) FROM stores WHERE distance_miles > ? OR distance_miles IS NULL OR latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180""",[config()['radius_miles']]).fetchone()[0]
        return {'stores_total':con.execute('SELECT COUNT(*) FROM stores').fetchone()[0], 'invalid_geography':bad,
        'verified_stores':con.execute("SELECT COUNT(*) FROM stores WHERE verification_status='verified' AND NOT is_example").fetchone()[0]}
def export(out='output'):
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    cfg=config()
    with connect() as con:
        con.execute("""COPY (SELECT store_id,store_name,address,city,state,country,latitude,longitude,distance_miles,wpn_id,wpn_status,sells_singles,sells_sealed,last_verified_at
          FROM stores WHERE verification_status='verified' AND NOT is_example AND distance_miles <= ? ORDER BY store_id)
          TO ? (HEADER, DELIMITER ',')""",[cfg['radius_miles'],str(dest/'stores_v1.csv')])
        con.execute("""COPY (SELECT s.sale_id,s.store_id,s.product_category,s.discount_percent,s.title,s.source_url,s.starts_at,s.ends_at,s.evidence_note,s.last_seen_at
          FROM sales s JOIN stores t ON s.store_id=t.store_id
          WHERE s.verification_status='verified' AND t.verification_status='verified' AND NOT t.is_example AND t.distance_miles<=?
          AND ((s.product_category='singles' AND s.discount_percent>=?) OR (s.product_category='sealed' AND s.discount_percent>=?))
          AND (s.ends_at IS NULL OR s.ends_at>=current_timestamp)
          ORDER BY s.sale_id) TO ? (HEADER, DELIMITER ',')""",
          [cfg['radius_miles'],cfg['threshold_singles_percent'],cfg['threshold_sealed_percent'],str(dest/'sales_v1.csv')])
    (dest/'manifest.json').write_text(json.dumps({'contract_version':'1.0.0','region':cfg,'status':'registry_export_not_live_collector'},indent=2))
