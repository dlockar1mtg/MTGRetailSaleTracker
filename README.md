# MTGRetailSaleTracker

Tracks Magic: The Gathering retailers and their sales within **300 straight-line miles of Wichita, Kansas**, and sends an alert, once, when a sale is announced or verified:

- **Singles:** at least **30%** off eligible MTG singles
- **Sealed:** at least **20%** off eligible sealed MTG product

It runs independently and publishes versioned exports for the Universal Investment Platform (UIP) to read later.

## Status (v0.2, Nov 2026)

| Works now | Not yet |
|---|---|
| Reviewed registry of stores, sale events, terms and evidence (`registry/*.csv`) | Automatic store discovery (WPN locator, directories) |
| State rules: announced / pending / verified qualifying / below threshold / not applicable / expired / cancelled | Automatic checking of store websites and calendars |
| Alerts as GitHub issues, each sent exactly once, plus a Sunday roundup | Reading Facebook/Instagram automatically (mostly blocked; report what you see instead) |
| "Report an MTG sale" issue form for sales you spot | UIP ingestion (the export is a contract preview) |
| Daily run, plus a run whenever the registry changes; pinned versions; monthly Dependabot | Geocoding (store locations are city-level until then) |

**An empty alert list means nothing was found, not that nothing exists.** Every roundup states the coverage.

## How alerts reach you

Each alert is a GitHub issue opened by the daily workflow. GitHub emails the owner, and the body @mentions them so the email arrives even if repository notifications are quiet.

- `🃏 MTG SALE: 30% off singles – <store>, <city> – <date>`: a **verified** deal that meets a threshold
- `📅 MTG SALE ANNOUNCED (details unknown): <store>, <city> – <date>`: a **lead** (for example a calendar that just says "Black Friday Sale!")
- `📋 MTG weekly roundup – week of <date>`: Sundays

The issues are also the "already sent" ledger. A sale is announced once, a real change (higher discount, new dates) adds one update comment, and a cancellation or the sale ending closes the issue.

**Gmail filter** so these never get buried: *Matches* `subject:("[dlockar1mtg/MTGRetailSaleTracker]")` → *Apply label* "MTG Sales", *Star it*, *Always mark it as important*, *Never send it to Spam*.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
pytest -q
python -m mtg_retail.cli check-registry               # validate registry/*.csv, rebuild the working database
python -m mtg_retail.cli notify --dry-run --roundup force   # what would be sent, without sending
python -m mtg_retail.cli export --out output           # UIP contract preview + manifest with checksums
```

See [docs/OPERATIONS.md](docs/OPERATIONS.md) to add a store or sale, [docs/SOURCES.md](docs/SOURCES.md) for the source policy, [docs/UIP_CONTRACT.md](docs/UIP_CONTRACT.md) for the export, and [docs/ROADMAP.md](docs/ROADMAP.md).

## Governance

- Fixed center and radius in `config/region.json`; straight-line (haversine) distance; stores within 10 miles of the edge are flagged for review.
- Every event needs evidence: a direct URL, or an owner screenshot/report clearly marked as such. No invented URLs or percentages.
- "20% off everything" never qualifies until MTG eligibility is confirmed; announced sales without terms are leads, never deals.
- No scraping behind logins and no bypassing robots rules or rate limits.
- The repository is public (by the owner's decision, Nov 2026) and holds only public business information.
