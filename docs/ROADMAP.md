# Roadmap

## Phase 0 — foundation (this package)
- [x] Repository structure, schema, geographic filter, example import, tests, export contract
- [x] Scheduled quality workflow (does not scrape)

## Phase 1 — authoritative store discovery
- [ ] Validate official WPN access pathway and permissible extraction
- [ ] Tile and paginate full Wichita 300-mile radius
- [ ] Resolve address geocoding and ambiguous locations
- [ ] Merge non-WPN store candidates with provenance
- [ ] Human-review deduplication and registry completeness

## Phase 2 — promotion intelligence
- [ ] Map official store websites, calendars and public social URLs
- [ ] Implement per-source adapters with rate limits and error tracking
- [ ] Extract discounts, eligible SKUs, dates and exclusions
- [ ] Human review and duplicate-event fingerprinting
- [ ] Daily notifications and weekly digest with durable history

## Phase 3 — UIP integration
- [ ] Versioned, checksummed exports and data-quality gates
- [ ] Authenticated cross-repository release publishing
- [ ] UIP ingestion contract tests
- [ ] Price normalization, shipping/travel costs and valuation comparison
