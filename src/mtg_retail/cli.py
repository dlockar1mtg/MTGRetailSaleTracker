import argparse
import json
import sys
from datetime import date
import urllib.parse
import urllib.request

from .alerts import LABELS, digest, parse_ledger, plan, roundup
from .core import build_db, config, export, import_stores, init_db, local_today, validate
from .registry import REGISTRY, RegistryError, load

AUTO = REGISTRY / "auto"
DIGEST_AT = 6          # more new automatic finds than this in one run -> one digest issue instead of one each


def _counts(reg, assessments, cfg):
    in_radius = {a.store.store_id for a in assessments if a.in_radius}
    in_radius |= {s.store_id for s in reg.stores.values()
                  if s.store_id not in {a.store.store_id for a in assessments}}  # stores with no events yet
    return {"stores": len(reg.stores), "verified_stores": sum(s.verification_status == "verified" for s in reg.stores.values()),
            "in_radius": len(in_radius), "radius": cfg["radius_miles"],
            "collectors": _collectors(reg), "checks": _check_summary()}


def _collectors(reg) -> str:
    wpn = sum(s.origin == "wpn" for s in reg.stores.values())
    osm = sum(s.origin == "osm" for s in reg.stores.values())
    manifest = _manifest()
    when = manifest.get("generated_on", "never")
    return (f"store discovery (Wizards store locator: {wpn} WPN stores; OpenStreetMap: {osm} other shops; last run {when}) "
            f"and daily checks of stores' own websites")


def _check_summary() -> str:
    from .discovery import read_rows
    rows = read_rows(AUTO / "checks.csv")
    if not rows:
        return ""
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    labels = {"ok": "read", "skipped": "not readable automatically (Facebook/Instagram, chain sites, or none listed)",
              "robots": "closed to robots", "blocked": "refused", "error": "unreachable"}
    return ", ".join(f"{n} {labels.get(k, k)}" for k, n in sorted(by.items(), key=lambda kv: -kv[1]))


def _manifest() -> dict:
    path = AUTO / "discovery_manifest.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def discover(force: bool, today: date | None = None) -> int:
    """Refresh registry/auto/wpn_stores.csv and osm_stores.csv (weekly unless forced)."""
    from .discovery import AUTO_FIELDS, DiscoveryError, merge_previous, osm_stores, wpn_stores, write_rows
    from .fetch import Fetcher, USER_AGENT
    cfg = config()
    today = today or local_today(cfg)
    manifest = _manifest()
    every = cfg.get("discovery_every_days", 7)
    prior = manifest.get("sources", {})

    def due(name: str) -> bool:
        last = prior.get(name, {}).get("generated_on")
        return force or not last or (today - date.fromisoformat(last)).days >= every
    fetcher = Fetcher(min_interval=2.0)
    out = {"attempted_on": today.isoformat(), "sources": dict(prior)}
    problems = []
    if due("wpn"):
        try:
            stores, info = wpn_stores(fetcher, cfg, today)
            write_rows(AUTO / "wpn_stores.csv", AUTO_FIELDS, [s.row() for s in merge_previous(stores, AUTO / "wpn_stores.csv")])
            out["sources"]["wpn"] = {**info, "generated_on": today.isoformat()}
            if not info["complete"]:
                problems.append(f"WPN locator incomplete: {info['failed_pages'] or 'pin count differs from total'}")
                out["sources"]["wpn"]["generated_on"] = prior.get("wpn", {}).get("generated_on")   # retry tomorrow
        except DiscoveryError as exc:
            problems.append(f"WPN locator: {exc}")
            out["sources"]["wpn"] = {**prior.get("wpn", {}), "error": str(exc)}
    else:
        print(f"WPN store list is from {prior['wpn']['generated_on']}; refreshed every {every} days.")

    def overpass(url: str, query: str) -> dict:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=260) as resp:
            return json.loads(resp.read())
    if due("osm"):
        try:
            stores, info = osm_stores(overpass, cfg, today)
            write_rows(AUTO / "osm_stores.csv", AUTO_FIELDS, [s.row() for s in merge_previous(stores, AUTO / "osm_stores.csv")])
            out["sources"]["osm"] = {**info, "generated_on": today.isoformat()}
        except DiscoveryError as exc:
            problems.append(f"OpenStreetMap: {exc}")
            out["sources"]["osm"] = {**prior.get("osm", {}), "error": str(exc)}
    else:
        print(f"OpenStreetMap shop list is from {prior['osm']['generated_on']}; refreshed every {every} days.")
    out["problems"] = problems
    # Each source keeps its own date; a failed source keeps its old one, so it is retried tomorrow.
    out["generated_on"] = max((v.get("generated_on") or "" for v in out["sources"].values()), default="") or None
    (AUTO / "discovery_manifest.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    for problem in problems:
        print(f"::warning title=Store discovery::{problem}")
    # Discovery problems never stop the alerts: the previous store lists stay in place.
    return 0


def watch(today: date | None = None) -> int:
    """Read every store's page and record possible sales in registry/auto/detections.csv."""
    from .discovery import read_rows, write_rows
    from .fetch import Fetcher
    from .watch import CHECK_FIELDS, DETECTION_FIELDS, check_sources, merge_checks, merge_detections
    cfg = config()
    today = today or local_today(cfg)
    reg = load()
    from .geo import miles_between
    limit = cfg["radius_miles"]
    sources = [(sid, url, reg.stores[sid].wpn_status == "wpn_verified" or reg.stores[sid].origin == "manual")
               for sid, url in reg.sources
               if miles_between(cfg["center_lat"], cfg["center_lon"], reg.stores[sid].latitude, reg.stores[sid].longitude) <= limit]
    results = check_sources(Fetcher(min_interval=3.0), sources)
    detections = merge_detections(read_rows(AUTO / "detections.csv"), results, today)
    write_rows(AUTO / "detections.csv", DETECTION_FIELDS, detections)
    write_rows(AUTO / "checks.csv", CHECK_FIELDS, merge_checks(read_rows(AUTO / "checks.csv"), results, today))
    summary = {}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    active = [d for d in detections if d["active"] == "yes"]
    print(json.dumps({"pages": len(results), "by_status": summary, "active_detections": len(active),
                      "new_today": sum(d["first_seen_on"] == today.isoformat() for d in active)}, indent=2))
    for d in active:
        print(f"  {d['store_id']:24} {d['headline']:28} {d['snippet'][:110]}")
    return 0


def notify(dry_run: bool, roundup_mode: str, today: date | None = None) -> int:
    cfg = config()
    today = today or local_today(cfg)
    reg, assessments = build_db(today=today)
    user = cfg.get("github_notify_user", "")
    if dry_run:
        ledger = {}
        print("DRY RUN: no issues are read or written; every due alert is shown as new.")
    else:
        from .github_api import GitHub
        gh = GitHub()
        for name, color, description in LABELS.values():
            gh.ensure_label(name, color, description)
        issues = gh.tracker_issues([label[0] for label in LABELS.values()])
        ledger = parse_ledger(issues, {i["number"]: gh.comments(i["number"]) for i in issues})
    actions = plan(assessments, ledger, user, today)
    new_spotted = [a for a in actions if a.kind == "create" and a.issue_kind == "spotted"]
    if len(new_spotted) > DIGEST_AT:
        by_event = {a.event.event_id: a for a in assessments}
        actions = [a for a in actions if a not in new_spotted] + [digest(new_spotted, by_event, user, today)]
    sent = {"created": 0, "commented": 0, "closed": 0}
    for act in actions:
        print(f"{act.kind.upper():8} {act.issue_kind:8} {act.event_id}  {act.title or ''}")
        if dry_run:
            if act.kind == "create":
                print(act.body)
            continue
        if act.kind == "create":
            gh.create_issue(act.title, act.body, [LABELS[act.issue_kind][0]])
            sent["created"] += 1
        elif act.kind == "comment":
            gh.comment(act.issue_number, act.body)
            sent["commented"] += 1
        elif act.kind == "close":
            gh.comment(act.issue_number, act.body)
            gh.close(act.issue_number)
            sent["closed"] += 1
    is_sunday = today.weekday() == 6
    if roundup_mode == "force" or (roundup_mode == "auto" and is_sunday):
        week = today.isoformat()
        title, body = roundup(assessments, _counts(reg, assessments, cfg), week, user, today)
        print(f"ROUNDUP  {title}")
        if dry_run:
            print(body)
        else:
            existing = {k for k in ledger if k[1] == "roundup"}
            if (f"roundup-{week}", "roundup") not in existing:
                gh.create_issue(title, body, [LABELS["roundup"][0]])
    print(json.dumps({"actions": len(actions), **({} if dry_run else sent),
                      "states": {a.event.event_id: a.state for a in assessments}}, indent=2))
    return 0


def main():
    p = argparse.ArgumentParser(description="MTG retailer and sale tracker")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    imp = sub.add_parser("import-stores", help="v0.1: load an ad-hoc candidate CSV (not the governed registry)")
    imp.add_argument("csv")
    sub.add_parser("check-registry", help="validate registry/*.csv and rebuild the working database")
    sub.add_parser("validate")
    exp = sub.add_parser("export")
    exp.add_argument("--out", default="output")
    note = sub.add_parser("notify", help="send due alerts as GitHub issues (exactly once)")
    note.add_argument("--dry-run", action="store_true")
    note.add_argument("--roundup", choices=("auto", "force", "skip"), default="auto")
    disc = sub.add_parser("discover", help="refresh the store lists from the Wizards locator and OpenStreetMap")
    disc.add_argument("--force", action="store_true", help="run even if the last discovery is recent")
    sub.add_parser("watch", help="check stores' own pages for sales")
    args = p.parse_args()
    try:
        if args.command == "init-db":
            init_db()
            print("Database initialized")
        elif args.command == "import-stores":
            print(f"Imported {import_stores(args.csv)} in-radius candidate rows")
        elif args.command == "check-registry":
            reg, assessments = build_db()
            print(json.dumps({"stores": len(reg.stores), "events": len(reg.events),
                              "states": {a.event.event_id: a.state for a in assessments}}, indent=2))
        elif args.command == "validate":
            print(json.dumps(validate(), indent=2, default=str))
        elif args.command == "export":
            build_db()
            export(args.out)
            print("Governed exports written")
        elif args.command == "notify":
            sys.exit(notify(args.dry_run, args.roundup))
        elif args.command == "discover":
            sys.exit(discover(args.force))
        elif args.command == "watch":
            sys.exit(watch())
    except RegistryError as exc:
        print(f"Registry problem: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
