# Sources, access and provenance

Nothing here logs in, sends cookies, solves challenges, or retries around a refusal. Every automated request identifies
itself (`MTGRetailSaleTracker/0.3 (+https://github.com/dlockar1mtg/mtgretailsaletracker)`), obeys robots.txt, and
waits between requests to the same host.

## Stores

**Wizards Play Network (official), weekly.** The public Store & Event Locator search page:
`https://locator.wizards.com/search?searchType=stores&query=Wichita%2C+KS&distance=310&page=N`.

- Basis: the locator's own sitemap (`/sitemap/en.xml`) lists `/search?searchType=stores...` pages for crawling. Its
  robots.txt allows everything except `/api/` and `/auth/`, and we use neither.
- One page carries every store's map pin (WPN id, name, coordinates, address). Full listings (website, phone) are
  paged ten at a time, so a run is about 32 requests, two seconds apart.
- The page embeds its data as a React Router turbo-stream, which `discovery.py` decodes. If Wizards changes the page,
  discovery reports a problem, keeps last week's list, and the alerts keep running.
- Checked on 2026-11-23: 314 stores within 310 miles of Wichita, 292 within 300.
- WPN is not a census of every Magic seller.

**OpenStreetMap, weekly.** Shops tagged `shop=games`, `shop=hobby`, `shop=collector`, `shop=comics`, or comic
bookshops, via the Overpass API. Data © OpenStreetMap contributors, ODbL. These are *candidates*: OSM does not say
whether a shop sells Magic.

**The owner's reports and stores.csv.** Hand-entered stores always win over an automatic match: same place, same
website, or a shared name word within 25 miles of a city-level location.

## Sales

**Each store's own website, daily** (`watch.py`). The tracker reads each listed website plus any extra pages in
`registry/sources.csv`, extracts the visible text, and looks for sale wording:
- percentages of at least 15 ("25% off", "save 30%"), or
- named sales (Black Friday, Cyber Monday, anniversary, holiday, clearance, storewide ...).

Lines about other games only are dropped. Storewide wording counts for WPN and hand-entered stores. For OSM-only
shops, the text must name Magic.

**Not read automatically:**
- Facebook, Instagram, X, TikTok, Discord, Linktree: login walls, and automated reading isn't permitted.
- GameStop and other chain-wide sites: no local sales.
- Pages whose robots.txt says no, or that refuse the request.

Those stores still reach the tracker through the "Report an MTG sale" form.

**What an automatic find is:** a quoted snippet with its URL and dates seen. It's sent as "🔎 POSSIBLE MTG SALE (found
automatically, unverified)", never as a verified deal. Percentages, dates and Magic eligibility in a snippet are
quoted, not checked. A sale becomes verified only when it's entered in `registry/events.csv` and `terms.csv`, with
`verified=yes` and `mtg_eligible=yes`.

## Coverage

Every Sunday roundup reports:
- the store counts by source and when discovery last ran;
- how many pages were read, not readable, refused, or unreachable.

An empty list means nothing was found. It is never proof that no sale exists.
