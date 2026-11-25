"""The sales board: one place to see every current sale, rebuilt by the daily workflow.

board/README.md       GitHub shows it when you open the board/ folder: tables of verified deals, announced
                      sales and automatic finds, with distances, dates, the store's wording and links.
board/sales.geojson   the same sales on a map (GitHub draws .geojson files as an interactive map; click a pin)
board/stores.geojson  every store the tracker knows, for reference
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from .evaluate import Assessment

COLORS = {"verified": "#1a7f37", "lead": "#d4a72c", "spotted": "#0969da"}
SECTIONS = [("verified", "\U0001F0CF Verified MTG sales (meet the 30% singles / 20% sealed thresholds)"),
            ("lead", "\U0001F4C5 Announced, details unknown"),
            ("spotted", "\U0001F50E Found automatically on store pages (unverified)")]


def _when(a: Assessment) -> str:
    e = a.event
    if a.alert_kind == "spotted":
        return f"on the page since {e.first_seen_on:%b %-d} (last seen {e.last_checked_on:%b %-d})"
    if e.start_date == e.end_date:
        return f"{e.start_date:%a %b %-d}" + (f", {e.local_hours}" if e.local_hours else "")
    return f"{e.start_date:%b %-d} – {e.end_date:%b %-d}"


def _what(a: Assessment) -> str:
    e = a.event
    if a.alert_kind == "verified":
        return "; ".join(f"{t.discount_percent:g}% off {t.category}" for t in a.qualifying_terms)
    if a.alert_kind == "spotted":
        return e.title
    return "terms not announced"


def _quote(a: Assessment) -> str:
    text = a.event.evidence[0].summary if a.event.evidence else ""
    text = text.replace("|", "/").replace("\n", " ")
    return text[:220] + ("…" if len(text) > 220 else "")


def _link(a: Assessment) -> str:
    urls = [ev.url for ev in a.event.evidence if ev.url]
    return f"[page]({urls[0]})" if urls else "owner report"


def build(assessments: list[Assessment], issues: dict[str, int], counts: dict, repo: str, today: date,
          out: Path, stores) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    live = [a for a in assessments if a.alert_kind]
    live.sort(key=lambda a: (a.event.start_date, a.distance_miles))
    lines = [
        "# MTG sales near Wichita",
        "",
        f"Updated **{today:%A, %B %-d, %Y}** by the daily run. Every current sale within {counts['radius']} miles. "
        f"**[Open the map](sales.geojson)** (click a pin), or the [map of all {counts['in_radius']} stores](stores.geojson).",
        "",
    ]
    for kind, heading in SECTIONS:
        rows = [a for a in live if a.alert_kind == kind]
        lines += [f"## {heading} ({len(rows)})", ""]
        if not rows:
            lines += ["_None right now._", ""]
            continue
        lines += ["| Store | Where | Miles | When | What | Source | Alert |", "|---|---|--:|---|---|---|---|"]
        for a in rows:
            n = issues.get(a.event.event_id)
            alert = f"[#{n}](https://github.com/{repo}/issues/{n})" if n else ""
            lines.append(f"| **{a.store.store_name}** | {a.store.city}, {a.store.state} | {a.distance_miles:.0f} | "
                         f"{_when(a)} | {_what(a)} | {_link(a)} | {alert} |")
        if kind == "spotted":
            lines += ["", "<details><summary>What each store's page says</summary>", ""]
            lines += [f"- **{a.store.store_name}**, {a.store.city}: “{_quote(a)}”" for a in rows]
            lines += ["", "</details>"]
        lines.append("")
    lines += [
        "## Coverage",
        "",
        f"- Stores within {counts['radius']} miles: **{counts['in_radius']}** ({counts['collectors']})",
        *([f"- Store pages checked today: {counts['checks']}"] if counts.get("checks") else []),
        "- Facebook/Instagram-only stores can't be read automatically. If you see a sale there, use "
        f"[Report an MTG sale](https://github.com/{repo}/issues/new/choose).",
        "- Automatic finds quote the store's own words. Percentages and whether Magic is included are not checked. "
        "An empty table means nothing was found, not that nothing exists.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")

    features = []
    for a in live:
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [a.store.longitude, a.store.latitude]},
                         "properties": {
                             "title": f"{a.store.store_name}: {_what(a)}",
                             "kind": {"verified": "Verified sale", "lead": "Announced, details unknown",
                                      "spotted": "Found automatically (unverified)"}[a.alert_kind],
                             "where": f"{a.store.address}, {a.store.city}, {a.store.state}".strip(", "),
                             "miles": round(a.distance_miles),
                             "when": _when(a),
                             "says": _quote(a),
                             "page": next((ev.url for ev in a.event.evidence if ev.url), ""),
                             "alert": f"https://github.com/{repo}/issues/{issues[a.event.event_id]}"
                                      if a.event.event_id in issues else "",
                             "marker-color": COLORS[a.alert_kind], "marker-size": "large",
                             "marker-symbol": {"verified": "star", "lead": "triangle", "spotted": "circle"}[a.alert_kind]}})
    (out / "sales.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=1,
                                                  ensure_ascii=False) + "\n", encoding="utf-8")
    store_features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
                       "properties": {"name": s.store_name, "where": f"{s.address}, {s.city}, {s.state}".strip(", "),
                                      "source": {"wpn": "Wizards Play Network", "osm": "OpenStreetMap (Magic not confirmed)",
                                                 "manual": "entered by hand"}.get(s.origin, s.origin),
                                      "website": s.website,
                                      "marker-color": "#6e7781" if s.origin == "osm" else "#8250df",
                                      "marker-size": "small"}}
                      for s in stores]
    (out / "stores.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": store_features},
                                                   ensure_ascii=False) + "\n", encoding="utf-8")
    return {"sales": len(live), "stores": len(store_features)}
