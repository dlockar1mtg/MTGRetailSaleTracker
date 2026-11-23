"""Automatic sale checks: read each store's own website (and any extra pages in registry/sources.csv) and pick
out text that announces a sale.

A detection is a *possible* sale. It becomes an alert of its own kind ("POSSIBLE MTG SALE, auto-found,
unverified") and is never treated as a verified deal: the percentages, dates and MTG eligibility in a snippet are
quoted, not trusted. What counts as a sale snippet:

  - "NN% off" / "save NN%" / "NN% discount" with NN >= 15, or
  - a named sale: Black Friday, Cyber Monday, Small Business Saturday, Boxing Day, anniversary / holiday /
    Christmas / clearance / warehouse / storewide / sitewide sale.

A snippet that only names other games (Pokemon, Lorcana, Warhammer ...) is ignored. For WPN stores (which run
Magic events) a storewide snippet counts; for stores found only in OpenStreetMap the snippet must mention Magic.
Facebook, Instagram and chain-wide sites are not read (login walls / no local sales); those stores still get
alerts from the "Report an MTG sale" form.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .fetch import Fetcher

SKIP_HOSTS = ("facebook.com", "fb.com", "fb.me", "instagram.com", "twitter.com", "x.com", "tiktok.com", "discord.gg",
              "discord.com", "linktr.ee", "gamestop.com", "wpn.wizards.com", "wizards.com", "google.com", "goo.gl",
              "yelp.com", "walmart.com", "target.com", "barnesandnoble.com")
PERCENT = re.compile(r"(?:\b(\d{1,2})\s?%\s?(?:off|discount)\b|\bsave\s+(?:up\s+to\s+)?(\d{1,2})\s?%|\b(\d{1,2})\s?%\s+savings)", re.I)
NAMED = re.compile(r"\b(black\s+friday|cyber\s+monday|small\s+business\s+saturday|boxing\s+day|"
                   r"(?:anniversary|holiday|christmas|clearance|warehouse|store[\s-]?wide|site[\s-]?wide|"
                   r"inventory|moving|closing|end[\s-]of[\s-]year|new\s+year'?s?|summer|spring|labor\s+day|"
                   r"memorial\s+day|4th\s+of\s+july|independence\s+day)\s+sale)\b", re.I)
MTG = re.compile(r"\b(magic(?::|\s+the\s+gathering)?|mtg|singles|commander\s+(?:deck|precon)|booster|collector\s+booster|"
                 r"play\s+booster|secret\s+lair|sealed)\b", re.I)
MAGIC_NAMED = re.compile(r"\b(magic(?::|\s+the\s+gathering)?|mtg|secret\s+lair|commander)\b", re.I)
EXCLUDES_MAGIC = re.compile(r"\b(?:exclud\w*|except|not\s+including|does\s+not\s+apply\s+to)\b[^.!?]{0,80}?"
                            r"\b(magic|mtg|singles|sealed)\b", re.I)
STOREWIDE = re.compile(r"\b(everything|store[\s-]?wide|site[\s-]?wide|entire\s+store|all\s+(?:items|products|"
                       r"merchandise|in[\s-]stock)|whole\s+store)\b", re.I)
OTHER_GAMES = re.compile(r"\b(pok[eé]mon|yu-?gi-?oh|lorcana|warhammer|one\s+piece|flesh\s+and\s+blood|digimon|"
                         r"star\s+wars|d&d|dungeons|board\s+games?|lego|funko|video\s+games?|comics?|models?|trains?)\b", re.I)
MIN_PERCENT = 15


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer",
             "tr", "td", "th", "span", "a", "button", "nav", "aside", "main", "ul", "ol", "table", "strong", "em"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.meta: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and a.get("content"):
                self.meta.append(a["content"])
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def visible_text(html: str) -> list[str]:
    """Blocks of visible text (one per line), plus the meta description."""
    parser = _Text()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML: use what was parsed
        pass
    blocks = [re.sub(r"\s+", " ", b).strip() for b in "".join(parser.parts).split("\n")]
    return [b for b in parser.meta + blocks if b]


@dataclass(frozen=True)
class Snippet:
    text: str
    percents: tuple[int, ...]
    named: str
    mtg: str                 # yes | storewide | no

    @property
    def key(self) -> str:
        norm = re.sub(r"[^a-z0-9%]+", " ", self.text.lower()).strip()
        return hashlib.sha256(norm.encode()).hexdigest()[:10]

    @property
    def headline(self) -> str:
        bits = []
        if self.percents:
            bits.append(f"{max(self.percents)}% off" if len(set(self.percents)) == 1 else
                        f"{min(self.percents)}-{max(self.percents)}% off")
        if self.named:
            bits.append(self.named.title().replace("  ", " "))
        return " · ".join(bits) or "sale"


def _pieces(blocks: list[str]) -> list[str]:
    out = []
    for block in blocks:
        out.extend(re.split(r"(?<=[.!?])\s+", block) if len(block) > 600 else [block])
    return [p for p in out if p]


def _percents(piece: str) -> tuple[int, ...]:
    return tuple(p for m in PERCENT.finditer(piece) for p in (int(x) for x in m.groups() if x) if p >= MIN_PERCENT)


def _other_only(piece: str) -> bool:
    """Names another game and not Magic ("Pokemon booster boxes 30% off": 'booster' alone is not Magic)."""
    return bool(OTHER_GAMES.search(piece)) and not MAGIC_NAMED.search(piece) and not STOREWIDE.search(piece)


def find_sales(blocks: list[str], wpn_store: bool) -> list[Snippet]:
    """Consecutive sale lines form one snippet (a banner often splits "BLACK FRIDAY" from "25% off singles"),
    with a short line on either side as context. A line about other games only is never part of one."""
    pieces = _pieces(blocks)
    hit = [not _other_only(p) and bool(_percents(p) or NAMED.search(p)) for p in pieces]
    found: dict[str, Snippet] = {}
    k = 0
    while k < len(pieces):
        if not hit[k]:
            k += 1
            continue
        end = k
        while end + 1 < len(pieces) and hit[end + 1]:
            end += 1
        run = pieces[k:end + 1]
        context = list(run)
        if k and len(pieces[k - 1]) <= 120 and not _other_only(pieces[k - 1]):
            context.insert(0, pieces[k - 1])
        if end + 1 < len(pieces) and len(pieces[end + 1]) <= 120 and not _other_only(pieces[end + 1]):
            context.append(pieces[end + 1])
        k = end + 1
        text = " · ".join(context)
        percents = tuple(p for piece in run for p in _percents(piece))
        named = next((m.group(1) for piece in run for m in [NAMED.search(piece)] if m), "")
        if EXCLUDES_MAGIC.search(text):
            mtg = "excluded"                    # e.g. "Excludes sealed MtG": still worth a look, flagged
        elif MAGIC_NAMED.search(text) or (MTG.search(text) and not OTHER_GAMES.search(text)):
            mtg = "yes"
        elif STOREWIDE.search(text) or named:
            mtg = "storewide"
        else:
            mtg = "no"
        if mtg == "no" or (mtg == "storewide" and not wpn_store):
            continue
        text = text[:400] + ("…" if len(text) > 400 else "")
        snip = Snippet(text, percents, named, mtg)
        found.setdefault(snip.key, snip)
    return list(found.values())


def checkable(url: str) -> tuple[bool, str]:
    if not url:
        return False, "no website listed"
    host = urlsplit(url).netloc.lower()
    for skip in SKIP_HOSTS:
        if host == skip or host.endswith("." + skip):
            return False, f"not read automatically ({skip})"
    return True, ""


@dataclass
class CheckResult:
    store_id: str
    url: str
    status: str             # ok | skipped | robots | blocked | error
    detail: str
    snippets: list[Snippet]


def check_sources(fetcher: Fetcher, sources: list[tuple[str, str, bool]], workers: int = 8) -> list[CheckResult]:
    """sources: (store_id, url, is_wpn_store). Pages shared by several stores are fetched once."""
    by_url: dict[str, list[tuple[str, bool]]] = {}
    results: list[CheckResult] = []
    for store_id, url, wpn in sources:
        ok, why = checkable(url)
        if not ok:
            results.append(CheckResult(store_id, url, "skipped", why, []))
            continue
        by_url.setdefault(url, []).append((store_id, wpn))

    def one(url: str) -> list[CheckResult]:
        page = fetcher.get(url)
        owners = by_url[url]
        if page.status == -1:
            return [CheckResult(s, url, "robots", page.error, []) for s, _ in owners]
        if page.status in (401, 403, 429):
            return [CheckResult(s, url, "blocked", page.error or f"HTTP {page.status}", []) for s, _ in owners]
        if not page.ok:
            return [CheckResult(s, url, "error", page.error or f"HTTP {page.status}", []) for s, _ in owners]
        blocks = visible_text(page.text)
        return [CheckResult(s, url, "ok", f"{len(blocks)} text blocks", find_sales(blocks, wpn)) for s, wpn in owners]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch in pool.map(one, list(by_url)):
            results.extend(batch)
    return results


DETECTION_FIELDS = ["detection_id", "store_id", "url", "headline", "snippet", "percents", "named_sale", "mtg_context",
                    "version", "first_seen_on", "last_seen_on", "active"]
CHECK_FIELDS = ["store_id", "url", "status", "detail", "last_checked_on", "last_ok_on"]
CONTEXT_RANK = {"yes": 0, "storewide": 1, "excluded": 2}


def summarize(snippets: list[Snippet]) -> dict:
    """One detection per store page: the page's sale wording, best first."""
    ordered = sorted(snippets, key=lambda x: (CONTEXT_RANK.get(x.mtg, 2), -max(x.percents or (0,)), x.text))
    percents = sorted({p for x in snippets for p in x.percents})
    named = next((x.named for x in ordered if x.named), "")
    bits = []
    if percents:
        bits.append(f"{percents[-1]}% off" if len(percents) == 1 else f"{percents[0]}-{percents[-1]}% off")
    if named:
        bits.append(re.sub(r"\s+", " ", named).title())
    headline = " · ".join(bits) or "sale"
    signature = "|".join([headline.lower(), ordered[0].mtg])
    return {"headline": headline, "snippet": " … ".join(x.text for x in ordered[:3])[:900],
            "percents": " ".join(map(str, percents)), "named_sale": named, "mtg_context": ordered[0].mtg,
            "version": hashlib.sha256(signature.encode()).hexdigest()[:8]}


def merge_detections(previous: list[dict], results: list[CheckResult], today: date) -> list[dict]:
    """One detection per store page while that page shows sale wording. The id carries the month it was first
    seen, so next year's sale on the same page is a new alert. A page that could not be read this run leaves
    its detection as it was (a transient error is not the end of a sale)."""
    rows = {r["detection_id"]: dict(r) for r in previous}
    active_for = {(r["store_id"], r["url"]): r["detection_id"] for r in previous if r.get("active") == "yes"}
    read_ok = {(r.store_id, r.url) for r in results if r.status == "ok"}
    current = set()
    for r in results:
        if not r.snippets:
            continue
        did = active_for.get((r.store_id, r.url)) or \
            f"auto-{r.store_id}-{hashlib.sha256(r.url.encode()).hexdigest()[:6]}-{today:%Y%m}"[:64]
        current.add(did)
        row = rows.get(did) or {"detection_id": did, "store_id": r.store_id, "url": r.url, "first_seen_on": today.isoformat()}
        row.update(summarize(r.snippets), last_seen_on=today.isoformat(), active="yes")
        rows[did] = row
    for did, row in rows.items():
        if did not in current and (row["store_id"], row["url"]) in read_ok:
            row["active"] = "no"
    keep = [r for r in rows.values()
            if r["active"] == "yes" or (today - date.fromisoformat(r["last_seen_on"])).days <= 30]
    return sorted(keep, key=lambda r: (r["store_id"], r["detection_id"]))


def merge_checks(previous: list[dict], results: list[CheckResult], today: date) -> list[dict]:
    old = {(r["store_id"], r["url"]): r for r in previous}
    out = []
    for r in results:
        prev = old.get((r.store_id, r.url), {})
        out.append({"store_id": r.store_id, "url": r.url, "status": r.status, "detail": r.detail[:200],
                    "last_checked_on": today.isoformat(),
                    "last_ok_on": today.isoformat() if r.status == "ok" else prev.get("last_ok_on", "")})
    return sorted(out, key=lambda r: (r["store_id"], r["url"]))
