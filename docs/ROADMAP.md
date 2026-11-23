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

## Phase 1: store discovery
- [ ] Confirm a permitted way to read the official WPN locator (locator.wizards.com); tile the full 300-mile circle with completeness records
- [ ] Geocoding (US Census geocoder) so locations move from city-level to address-level
- [ ] Non-WPN supplementation with provenance; city bootstrap (Wichita, El Dorado, Tulsa, OKC/Edmond, Topeka, Kansas City), then small towns

## Phase 2: automatic sale leads
- [ ] Per-store source list (website, event calendar, public social pages) with access status
- [ ] Website/calendar adapters (rate-limited, robots-respecting) proposing registry rows as pull requests for review
- [ ] Image calendars: OCR proposals from screenshots attached to sale reports, always human-reviewed

## Phase 3: UIP integration
- [ ] Publish checksummed releases; UIP consumer with contract tests and freshness checks
- [ ] Join sealed deals to the UIP's MTG market prices (net of tax, travel) before calling anything an opportunity
