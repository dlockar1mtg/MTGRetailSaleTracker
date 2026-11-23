CREATE TABLE IF NOT EXISTS stores (
 store_id VARCHAR PRIMARY KEY, store_name VARCHAR NOT NULL, address VARCHAR,
 city VARCHAR, state VARCHAR, country VARCHAR DEFAULT 'USA',
 latitude DOUBLE, longitude DOUBLE, distance_miles DOUBLE,
 wpn_id VARCHAR, wpn_status VARCHAR DEFAULT 'unverified',
 sells_singles BOOLEAN, sells_sealed BOOLEAN, is_example BOOLEAN DEFAULT FALSE,
 verification_status VARCHAR DEFAULT 'candidate', last_verified_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT current_timestamp, updated_at TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS store_sources (
 source_id VARCHAR PRIMARY KEY, store_id VARCHAR NOT NULL,
 source_type VARCHAR NOT NULL, source_url VARCHAR NOT NULL,
 access_status VARCHAR DEFAULT 'unverified', last_checked_at TIMESTAMP,
 FOREIGN KEY(store_id) REFERENCES stores(store_id)
);
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
