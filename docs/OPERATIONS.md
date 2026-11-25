# Operations

## The registry is the source of truth

GitHub Actions runners keep nothing between runs, so everything durable is plain CSV in `registry/`, reviewed and versioned in git. Each run rebuilds its DuckDB database from these files.

| File | One row per | Key columns |
|---|---|---|
| `stores.csv` | retailer | `store_id` (stable, never reused), address, `latitude`/`longitude` + `location_precision` (`address` or `city`), `wpn_status`, `sells_singles`/`sells_sealed` (yes/no/unknown), `verification_status` (candidate/verified/closed) |
| `events.csv` | sale event (one campaign at one store over a date window) | `event_id`, `store_id`, `start_date`/`end_date` (local), `local_hours`, `review_status`, `first_seen_on`, `last_checked_on` |
| `terms.csv` | category of an event (`singles` or `sealed`) | `discount_percent` (blank if unknown), `mtg_eligible` (yes/no/unknown), conditions, exclusions, `where`, `verified` (yes/no), `terms_version` |
| `evidence.csv` | observation | `source_type`, `url` (required except owner screenshots/reports), `retrieved_on`, `access_status`, `confidence`, summary |

## The sales board

`board/README.md` lists every current sale (verified, announced, found automatically) with distance, dates, the store's wording and links to the page and the alert issue. `board/sales.geojson` is the same on a map; GitHub draws it when you open the file. `board/stores.geojson` maps every known store. The daily run rebuilds all three; don't edit them by hand.

## Automatic files (registry/auto/, written by the daily workflow)

| File | What | Refreshed |
|---|---|---|
| `wpn_stores.csv` | every WPN store within 310 miles (official locator) | weekly |
| `osm_stores.csv` | game / hobby / comic shops from OpenStreetMap (candidates) | weekly |
| `checks.csv` | each page checked, its status (ok / skipped / robots / blocked / error) and last good read | daily |
| `detections.csv` | possible sales found on those pages (quoted text, first/last seen, still showing?) | daily |
| `discovery_manifest.json` | last discovery: counts, completeness, problems | weekly |

Don't edit these by hand. To correct a store, add it to `stores.csv` (it then replaces the automatic entry). To watch an
extra page, such as a store's events or sales page, add a row to `registry/sources.csv` (`store_id,url,notes`).

## Event states

You set `review_status` in `events.csv`; the tracker derives the rest.

| review_status | Meaning | Alert |
|---|---|---|
| `ANNOUNCED_TERMS_UNKNOWN` | a sale exists; discount or MTG eligibility unknown | 📅 lead |
| `PENDING_VERIFICATION` | terms seen, not confirmed | 📅 lead |
| `VERIFIED` | terms confirmed from the evidence | becomes **VERIFIED_QUALIFYING** (🃏 deal) if a verified, MTG-eligible term meets its threshold; else **VERIFIED_BELOW_THRESHOLD** or **VERIFIED_NOT_APPLICABLE** (no alert; an open lead is closed) |
| `SOURCE_INACCESSIBLE` | the source can't be checked | none |
| `CANCELLED` | the store cancelled | open issues get one "Cancelled" comment and close |
| `AUTO_DETECTED` | set by the daily checks only | 🔎 possible sale; closes a week after it leaves the page |

Any event whose `end_date` has passed is **EXPIRED**; its open issues close quietly. Stores outside 300 miles and `closed` stores never alert.

## Adding a sale you spotted

1. Open an issue with the **Report an MTG sale** form (store, city, dates, exact wording, link, screenshot).
2. The report is turned into registry rows: a store row if the store is new, an event row (`ANNOUNCED_TERMS_UNKNOWN` unless terms are clear), terms rows only for what is actually stated, and an evidence row (`user_screenshot` with no URL is fine).
3. Committing to `main` runs the alert workflow at once, so the 📅 or 🃏 email goes out within minutes.
4. When terms are confirmed, change `review_status` to `VERIFIED`, fill `terms.csv`, add the new evidence row, and raise `terms_version`. The lead issue closes and a 🃏 issue opens if it qualifies.

## Running it by hand

Actions → **MTG sale alerts** → *Run workflow*. Tick **rediscover** to refresh the store lists now instead of weekly. Use **dry_run** to see the would-be issues in the log without opening any, and **roundup = force** to send a roundup now.

## When something fails

- **Registry problem:** the run stops with `Registry problem: <file> row <n>: …` before anything is sent. Fix that row.
- **GitHub API error:** nothing partial is lost. Issues already opened stay in the ledger, and the next run sends only what's still due.
- **Repeat alerts:** shouldn't happen (each issue carries a hidden `mtg-retail-alert` marker, and runs never overlap). If one appears, check that nobody edited the marker out of an issue body.
