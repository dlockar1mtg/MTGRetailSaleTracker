# MTGRetailSaleTracker

Independent, governed registry of Magic: The Gathering retailers and sale announcements within **300 straight-line miles of downtown Wichita, Kansas**. Designed to publish validated, versioned exports for eventual Unified Investment Platform (UIP) ingestion.

## Status
**Foundation scaffold, not a live monitoring service.** No official WPN bulk export, Facebook access, geocoder, or price feed is configured. Never interpret zero results as zero stores or sales. The existing ChatGPT alerts are separate from this repository.

## Quick start
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e '.[dev]'
python -m mtg_retail.cli init-db
python -m mtg_retail.cli import-stores examples/stores.example.csv
python -m mtg_retail.cli validate
python -m mtg_retail.cli export
pytest
```
Example records are fictional and excluded from production exports. See docs/SETUP.md, docs/SOURCES.md and docs/UIP_CONTRACT.md.

## Governance
- Fixed geographic center, configurable radius; geodesic (haversine) eligibility.
- Provenance, timestamps, source URLs and review states for every sale.
- No scraping of restricted or login-gated social media.
- Exports contain only reviewed, current, non-example records.
- Daily workflow runs validation and export, **not** a pretend live collector.
