# MTGRetailSaleTracker

Tracks Magic: The Gathering retailers and their sales within **300 straight-line miles of Wichita, Kansas**, and sends an alert, once, when a sale is announced or verified:

- **Singles:** at least **30%** off eligible MTG singles
- **Sealed:** at least **20%** off eligible sealed MTG product

**📍 See every current sale: [the sales board](board/)**, a table plus a map, updated every morning.

It runs independently and publishes versioned exports for the Universal Investment Platform (UIP) to read later.

## Status (v0.3, Nov 2026)

| Works now | Not yet |
|---|---|
| **Every WPN store** within the radius from Wizards' official store locator, refreshed weekly (~290 stores) | Reading Facebook / Instagram (login walls): report what you see with the form |
| Game, hobby and comic shops from OpenStreetMap as candidates | Reading sale *images* (flyers, calendar pictures) |
| **Daily automatic checks** of every store's own website for sale wording, as "possible sale" alerts | Turning an automatic find into a verified deal without a person checking it |
| Reviewed registry of stores, sale events, terms and evidence (`registry/*.csv`) | UIP ingestion (the export is a contract preview) |
| Alerts as GitHub issues, each sent once, plus a Sunday roundup with coverage counts | |
| "Report an MTG sale" issue form; pinned versions; monthly Dependabot | |

**An empty alert list means nothing was found, not that nothing exists.** Every roundup states the coverage: how many stores and pages were checked, and how many couldn't be read.

## How alerts reach you

Each alert is a GitHub issue opened by the daily workflow. GitHub emails Devon's account (`dlockar1`): each alert issue is assigned to him and @mentions him. (`dlockar1mtg` is the organization that owns the repository; an organization can't be @mentioned, so alerts must name the personal account. That is `github_notify_user` in `config/region.json`.)

- `🃏 MTG SALE: 30% off singles – <store>, <city> – <date>`: a **verified** deal that meets a threshold
- `📅 MTG SALE ANNOUNCED (details unknown): <store>, <city> – <date>`: a **lead** (for example a calendar that just says "Black Friday Sale!")
- `🔎 POSSIBLE MTG SALE (found automatically, unverified): 25% off · Black Friday – <store>, <city>`: sale wording found on a store's own website, quoted with the link. When one run finds more than six at once, they arrive as one digest issue.
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
