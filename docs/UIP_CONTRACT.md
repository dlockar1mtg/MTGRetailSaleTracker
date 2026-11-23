# UIP export contract v1.1.0

The tracker is a standalone upstream producer. The UIP is a downstream consumer and must not directly mutate tracker tables.

Artifacts:
- `stores_v1.csv`: verified in-radius, non-example stores with stable IDs and geographic fields.
- `sales_v1.csv`: verified, qualifying, non-expired promotions linked to store IDs.
- `events_v1.csv` (added in 1.1.0): every non-expired in-radius event with its derived state (leads included), alert kind, distance and terms version.
- `manifest.json`: contract version, regional policy, generation time (UTC), per-file SHA-256 and row counts, coverage counts, and `status` (`registry_export_manual_sources` while there are no automated collectors: an empty `sales_v1.csv` is not evidence of no sales).

Versioning: additive fields may be introduced in v1; breaking field changes require v2. Stable IDs are opaque strings. Timestamps are UTC by policy for production collectors; source-local event times must be normalized and recorded with original timezone in future schema migrations.

**Not yet production-ready:** no automatic live collectors, no durable hosted DB, no publish-to-UIP job, and no deal-level price validation. The current exports are contract previews only.

Planned UIP ingestion: fetch signed or checksummed release artifact, validate schema and manifest, verify freshness and provenance, stage in UIP DuckDB, then join with card/box market price data without treating advertised percent-off as realized arbitrage.
