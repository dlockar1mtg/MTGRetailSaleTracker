-- MTGRetailSaleTracker working database, schema v0.2.
-- Rebuilt on every run from the reviewed CSV registry (registry/*.csv); the CSVs are the source of truth.
-- v0.1 tables (stores, store_sources, sales, monitoring_runs) are kept so the v1 export contract does not break.

CREATE TABLE IF NOT EXISTS stores (
 store_id VARCHAR PRIMARY KEY, store_name VARCHAR NOT NULL, address VARCHAR,
 city VARCHAR, state VARCHAR, country VARCHAR DEFAULT 'USA',
 latitude DOUBLE, longitude DOUBLE, distance_miles DOUBLE,
 wpn_id VARCHAR, wpn_status VARCHAR DEFAULT 'wpn_unknown',
 sells_singles BOOLEAN, sells_sealed BOOLEAN, is_example BOOLEAN DEFAULT FALSE,
 verification_status VARCHAR DEFAULT 'candidate', last_verified_at TIMESTAMP,
 location_precision VARCHAR, website VARCHAR, notes VARCHAR,
 created_at TIMESTAMP DEFAULT current_timestamp, updated_at TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS store_sources (
 source_id VARCHAR PRIMARY KEY, store_id VARCHAR NOT NULL,
 source_type VARCHAR NOT NULL, source_url VARCHAR NOT NULL,
 access_status VARCHAR DEFAULT 'unverified', last_checked_at TIMESTAMP,
 FOREIGN KEY(store_id) REFERENCES stores(store_id)
);
-- v1 contract table: one row per verified, qualifying category of a sale (derived from promotion_terms).
CREATE TABLE IF NOT EXISTS sales (
 sale_id VARCHAR PRIMARY KEY, store_id VARCHAR NOT NULL,
 product_category VARCHAR NOT NULL CHECK (product_category IN ('singles','sealed')),
 discount_percent DOUBLE NOT NULL CHECK (discount_percent BETWEEN 0 AND 100),
 title VARCHAR NOT NULL, source_url VARCHAR NOT NULL,
 starts_at TIMESTAMP, ends_at TIMESTAMP,
 verification_status VARCHAR DEFAULT 'candidate',
 evidence_note VARCHAR, first_seen_at TIMESTAMP DEFAULT current_timestamp,
 last_seen_at TIMESTAMP DEFAULT current_timestamp,
 FOREIGN KEY(store_id) REFERENCES stores(store_id)
);
CREATE TABLE IF NOT EXISTS monitoring_runs (
 run_id VARCHAR PRIMARY KEY, collector VARCHAR NOT NULL,
 started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP,
 status VARCHAR NOT NULL, records_seen INTEGER DEFAULT 0,
 error_message VARCHAR
);
-- v0.2: sale events with unknown terms, category terms and evidence (handoff sections 7-8).
CREATE TABLE IF NOT EXISTS promotion_events (
 event_id VARCHAR PRIMARY KEY, store_id VARCHAR NOT NULL, title VARCHAR NOT NULL,
 start_date DATE NOT NULL, end_date DATE NOT NULL, local_hours VARCHAR, timezone VARCHAR NOT NULL,
 review_status VARCHAR NOT NULL, derived_state VARCHAR NOT NULL, alert_kind VARCHAR,
 distance_miles DOUBLE, in_radius BOOLEAN, near_boundary BOOLEAN,
 terms_version INTEGER NOT NULL, first_seen_on DATE NOT NULL, last_checked_on DATE NOT NULL, notes VARCHAR,
 FOREIGN KEY(store_id) REFERENCES stores(store_id)
);
CREATE TABLE IF NOT EXISTS promotion_terms (
 event_id VARCHAR NOT NULL, category VARCHAR NOT NULL CHECK (category IN ('singles','sealed')),
 discount_percent DOUBLE, mtg_eligible VARCHAR NOT NULL, conditions VARCHAR, exclusions VARCHAR,
 sale_where VARCHAR NOT NULL, verified VARCHAR NOT NULL, terms_version INTEGER NOT NULL, qualifies BOOLEAN NOT NULL,
 PRIMARY KEY (event_id, category),
 FOREIGN KEY(event_id) REFERENCES promotion_events(event_id)
);
CREATE TABLE IF NOT EXISTS promotion_evidence (
 evidence_id VARCHAR PRIMARY KEY, event_id VARCHAR NOT NULL, source_type VARCHAR NOT NULL, url VARCHAR,
 retrieved_on DATE NOT NULL, access_status VARCHAR NOT NULL, method VARCHAR, confidence VARCHAR NOT NULL, summary VARCHAR,
 FOREIGN KEY(event_id) REFERENCES promotion_events(event_id)
);
