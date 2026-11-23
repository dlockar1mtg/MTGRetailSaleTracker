# Roadmap

## Phase 0: foundation (v0.1 starter, audited Nov 23, 2026)
- [x] Repository structure, schema, geographic filter, tests, export contract
- [x] Audit: its 4 tests passed, but `import-stores` crashed (`current_timestamp` in DuckDB's ON CONFLICT SET) and `export` crashed (`COPY ... TO ?` filename parameter). Both fixed in v0.2.

## v0.2: registry, rules and alerts (Nov 23, 2026)
- [x] Reviewed CSV registry (stores, events, terms, evidence) as the durable source of truth; DuckDB rebuilt each run
- [x] Event states incl. announced-terms-unknown; inclusive 30% singles / 20% sealed thresholds; MTG eligibility required
- [x] GitHub-issue alerts sent exactly once (issues are the ledger), update comments, cancel/expire handling, Sunday roundup
- [x] Report-a-sale issue form; daily workflow + run on registry change; pinned versions; Dependabot
- [x] Seeds: Wizards Asylum Tulsa and The Gathering Point Black Friday 2026 leads

## v0.3: all stores and automatic checks (Nov 23, 2026)
- [x] Every WPN store within 300 miles from the official locator (weekly), OSM shops as candidates
- [x] Daily checks of every store's own website; sale wording becomes a "possible sale" alert (digest when many)
- [x] Automatic files in registry/auto/ committed by the workflow; hand-entered stores win over automatic matches

## Phase 1: store discovery (remaining)
- [ ] Geocoding (US Census geocoder) so locations move from city-level to address-level
- [ ] Non-WPN supplementation with provenance; city bootstrap (Wichita, El Dorado, Tulsa, OKC/Edmond, Topeka, Kansas City), then small towns

## Phase 2: automatic sale leads (remaining)
- [ ] Find stores' sale/event pages beyond the homepage (add them to registry/sources.csv)
- [ ] Image calendars: OCR proposals from screenshots attached to sale reports, always human-reviewed

## Phase 3: UIP integration
- [ ] Publish checksummed releases; UIP consumer with contract tests and freshness checks
- [ ] Join sealed deals to the UIP's MTG market prices (net of tax, travel) before calling anything an opportunity
