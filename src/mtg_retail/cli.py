import argparse
import json
import sys
from datetime import date

from .alerts import LABELS, parse_ledger, plan, roundup
from .core import build_db, config, export, import_stores, init_db, local_today, validate
from .registry import RegistryError


def _counts(reg, assessments, cfg):
    in_radius = {a.store.store_id for a in assessments if a.in_radius}
    in_radius |= {s.store_id for s in reg.stores.values()
                  if s.store_id not in {a.store.store_id for a in assessments}}  # stores with no events yet
    return {"stores": len(reg.stores), "verified_stores": sum(s.verification_status == "verified" for s in reg.stores.values()),
            "in_radius": len(in_radius), "radius": cfg["radius_miles"],
            "collectors": "none yet - sales are entered from reviewed reports (see docs/OPERATIONS.md)"}


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
    except RegistryError as exc:
        print(f"Registry problem: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
