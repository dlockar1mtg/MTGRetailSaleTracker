"""Alerts as GitHub issues, sent once.

Every alert is an issue whose body carries a hidden marker:

    <!-- mtg-retail-alert event=<event_id> kind=<verified|lead> version=<terms_version> -->

The issues themselves are the delivery ledger, so nothing is lost when a runner is recycled. Before sending,
the notifier reads every issue (open and closed) with the tracker's labels and their comments' markers:

  - no issue for (event, kind)            -> open one (GitHub emails the owner; the body @mentions them)
  - issue exists, same terms_version      -> nothing (no repeat alerts across daily runs)
  - issue exists, newer terms_version     -> one "Update" comment carrying the new version's marker
  - the event was cancelled               -> one "Cancelled" comment, and the issue is closed
  - a lead later becomes a verified deal  -> a new "verified" issue; the lead issue is closed with a link
  - the event has expired                 -> its open issues are closed quietly (no email-worthy comment)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re

from .evaluate import Assessment

MARKER = re.compile(r"<!-- mtg-retail-alert event=([a-z0-9_-]+) kind=(verified|lead|roundup) version=([0-9A-Za-z_-]+) -->")
LABELS = {
    "verified": ("mtg-sale-verified", "1a7f37", "Verified MTG sale meeting the singles/sealed threshold"),
    "lead": ("mtg-sale-lead", "d4a72c", "Announced MTG sale, terms not yet verified"),
    "roundup": ("mtg-weekly-roundup", "5b5bd6", "Weekly MTG sales roundup"),
}
CATEGORY_LABEL = {"singles": "Singles", "sealed": "Sealed"}


@dataclass
class IssueState:
    number: int
    state: str
    kind: str
    event_id: str
    versions: set[str] = field(default_factory=set)


def parse_ledger(issues: list[dict], comments: dict[int, list[str]]) -> dict[tuple[str, str], IssueState]:
    """(event_id, kind) -> the issue for it, with every version already announced (body + comments)."""
    out: dict[tuple[str, str], IssueState] = {}
    for issue in issues:
        found = MARKER.search(issue.get("body") or "")
        if not found:
            continue
        event_id, kind, version = found.groups()
        state = out.setdefault((event_id, kind), IssueState(issue["number"], issue.get("state", "open"), kind, event_id))
        state.versions.add(version)
        for text in comments.get(issue["number"], []):
            for match in MARKER.finditer(text or ""):
                state.versions.add(match.group(3))
    return out


def _date_span(a: Assessment) -> str:
    e = a.event
    span = e.start_date.strftime("%a %b %-d, %Y") if e.start_date == e.end_date else \
        f"{e.start_date.strftime('%a %b %-d')} - {e.end_date.strftime('%a %b %-d, %Y')}"
    return f"{span}{(' · ' + e.local_hours) if e.local_hours else ''} ({e.timezone})"


def _where(a: Assessment) -> str:
    s = a.store
    place = ", ".join(p for p in (s.address, f"{s.city}, {s.state}".strip(", ")) if p)
    approx = " (approx., city-level location)" if s.location_precision == "city" else ""
    return f"{place} · {a.distance_miles:.0f} miles from Wichita (straight line){approx}"


def _evidence_lines(a: Assessment) -> list[str]:
    lines = []
    for ev in a.event.evidence:
        link = ev.url or "(no public link: user-supplied screenshot/report)"
        lines.append(f"- {ev.source_type.replace('_', ' ')} · {link} · seen {ev.retrieved_on.isoformat()} · "
                     f"{ev.confidence} confidence · {ev.summary}")
    return lines


def title_for(a: Assessment) -> str:
    s, e = a.store, a.event
    when = e.start_date.strftime("%b %-d") if e.start_date == e.end_date else \
        f"{e.start_date.strftime('%b %-d')}-{e.end_date.strftime('%b %-d')}"
    if a.alert_kind == "verified":
        best = sorted(a.qualifying_terms, key=lambda t: -(t.discount_percent or 0))
        deal = " + ".join(f"{t.discount_percent:g}% off {CATEGORY_LABEL[t.category].lower()}" for t in best)
        return f"\U0001F0CF MTG SALE: {deal} – {s.store_name}, {s.city} – {when}"
    return f"\U0001F4C5 MTG SALE ANNOUNCED (details unknown): {s.store_name}, {s.city} – {when}"


def body_for(a: Assessment, notify_user: str, today: date) -> str:
    e = a.event
    if a.alert_kind == "verified":
        head = "[VERIFIED MTG SALE]"
        term_lines = []
        for t in sorted(e.terms, key=lambda t: t.category):
            pct = "unknown" if t.discount_percent is None else f"{t.discount_percent:g}%"
            mark = "qualifies" if t in a.qualifying_terms else "does not meet the threshold / not verified"
            term_lines.append(f"- **{CATEGORY_LABEL[t.category]}:** {pct} off ({mark})"
                              f"{'; conditions: ' + t.conditions if t.conditions else ''}"
                              f"{'; exclusions: ' + t.exclusions if t.exclusions else ''}"
                              f"{'; where: ' + t.where.replace('_', ' ') if t.where != 'unknown' else ''}")
        status = "Verified against the evidence below."
    else:
        head = "[SALE ANNOUNCED — DETAILS UNKNOWN]"
        term_lines = [f"- {CATEGORY_LABEL[t.category]}: "
                      f"{'unknown' if t.discount_percent is None else f'{t.discount_percent:g}% (not verified for MTG)'}"
                      for t in e.terms] or ["- Discount and MTG eligibility are not known yet."]
        status = ("This is a lead, **not** a verified qualifying deal. Check the store's post or call before "
                  "making the trip; the tracker updates this issue if terms are confirmed.")
    parts = [
        f"**{head} {a.store.store_name} — {a.store.city}, {a.store.state}**",
        "",
        f"**Dates:** {_date_span(a)}",
        f"**Where:** {_where(a)}",
        "**Terms:**",
        *term_lines,
        f"**Status:** {status}",
        "",
        "**Evidence:**",
        *_evidence_lines(a),
        "",
        f"Event ID `{e.event_id}` · terms version {e.terms_version} · checked {e.last_checked_on.isoformat()} · "
        f"sent {today.isoformat()}" + (f" · notes: {e.notes}" if e.notes else ""),
        "",
        f"@{notify_user}" if notify_user else "",
        f"<!-- mtg-retail-alert event={e.event_id} kind={a.alert_kind} version={e.terms_version} -->",
    ]
    return "\n".join(parts).strip() + "\n"


@dataclass(frozen=True)
class Action:
    kind: str           # create | comment | close
    issue_kind: str     # verified | lead
    event_id: str
    title: str = ""
    body: str = ""
    issue_number: int | None = None


def plan(assessments: list[Assessment], ledger: dict[tuple[str, str], IssueState], notify_user: str,
         today: date) -> list[Action]:
    actions: list[Action] = []
    for a in assessments:
        eid = a.event.event_id
        version = str(a.event.terms_version)
        if a.alert_kind:
            existing = ledger.get((eid, a.alert_kind))
            if existing is None:
                actions.append(Action("create", a.alert_kind, eid, title_for(a), body_for(a, notify_user, today)))
            elif version not in existing.versions and existing.state == "open":
                body = (f"**Update:** the terms changed (version {version}).\n\n" + body_for(a, notify_user, today))
                actions.append(Action("comment", a.alert_kind, eid, body=body, issue_number=existing.number))
            if a.alert_kind == "verified":
                lead = ledger.get((eid, "lead"))
                if lead and lead.state == "open":
                    actions.append(Action("close", "lead", eid, body="Verified — see the new MTG SALE issue for this event.",
                                          issue_number=lead.number))
        for kind in ("verified", "lead"):
            issue = ledger.get((eid, kind))
            if not issue or issue.state != "open" or kind == a.alert_kind:
                continue
            if a.state == "CANCELLED":
                actions.append(Action("close", kind, eid, body=f"**Cancelled:** the store cancelled this sale. @{notify_user}",
                                      issue_number=issue.number))
            elif a.state == "EXPIRED":
                actions.append(Action("close", kind, eid, body="This sale has ended.", issue_number=issue.number))
            elif kind == "lead" and a.alert_kind is None:
                actions.append(Action("close", kind, eid, body=f"Resolved as {a.state.replace('_', ' ').lower()}: "
                                      "no qualifying MTG discount.", issue_number=issue.number))
    return actions


def roundup(assessments: list[Assessment], registry_counts: dict, week_label: str, notify_user: str,
            today: date) -> tuple[str, str]:
    upcoming = [a for a in assessments if a.state not in {"EXPIRED", "CANCELLED"} and a.in_radius]
    verified = [a for a in upcoming if a.alert_kind == "verified"]
    leads = [a for a in upcoming if a.alert_kind == "lead"]

    def line(a: Assessment) -> str:
        return (f"- **{a.store.store_name}**, {a.store.city} – {_date_span(a)} – "
                f"{a.distance_miles:.0f} mi – `{a.event.event_id}`")
    title = f"\U0001F4CB MTG weekly roundup – week of {week_label}"
    body = "\n".join([
        f"**Verified qualifying sales ({len(verified)})**", *([line(a) for a in verified] or ["- none verified yet"]), "",
        f"**Announced, terms unknown ({len(leads)})**", *([line(a) for a in leads] or ["- none"]), "",
        "**Coverage (read before trusting an empty list)**",
        f"- Stores in the registry: {registry_counts['stores']} ({registry_counts['verified_stores']} verified, "
        f"{registry_counts['in_radius']} within {registry_counts['radius']} miles)",
        f"- Automated collectors: {registry_counts['collectors']}",
        "- No list here means nothing was *found*, not that nothing exists. Report a sale you spot with the "
        "\"Report an MTG sale\" issue form.",
        "",
        f"@{notify_user}" if notify_user else "",
        f"<!-- mtg-retail-alert event=roundup-{week_label} kind=roundup version=1 -->",
    ])
    return title, body.strip() + "\n"
