from datetime import date
import io
import json
import urllib.error

import pytest

from conftest import event, term
from mtg_retail.alerts import parse_ledger, plan, roundup
from mtg_retail.core import config
from mtg_retail.evaluate import assess_all
from mtg_retail.github_api import GitHub, GitHubError
from mtg_retail.registry import load

TODAY = date(2026, 11, 23)


def assessments(path, today=TODAY):
    return assess_all(load(path), config(), today)


def issue(number, body, state="open"):
    return {"number": number, "body": body, "state": state}


def test_a_new_lead_is_announced_once(make_registry):
    a = assessments(make_registry())
    first = plan(a, {}, "owner", TODAY)
    assert [(x.kind, x.issue_kind) for x in first] == [("create", "lead")]
    assert first[0].title.startswith("\U0001F4C5 MTG SALE ANNOUNCED (details unknown): Test Games, Testville")
    assert "@owner" in first[0].body and "kind=lead version=0" in first[0].body
    ledger = parse_ledger([issue(1, first[0].body)], {})
    assert plan(a, ledger, "owner", TODAY) == []          # the next daily run sends nothing


def test_verified_deal_title_names_the_discount(make_registry):
    a = assessments(make_registry(events=[event(status="VERIFIED")],
                                  terms=[term(pct="50"), term(category="sealed", pct="20")]))
    (act,) = plan(a, {}, "owner", TODAY)
    assert act.title.startswith("\U0001F0CF MTG SALE: 50% off singles + 20% off sealed – Test Games")
    assert "[VERIFIED MTG SALE]" in act.body and "https://example.test/sale" in act.body


def test_changed_terms_comment_once_on_the_same_issue(make_registry):
    v1 = assessments(make_registry(events=[event(status="VERIFIED")], terms=[term(pct="30", version="1")]))
    body = plan(v1, {}, "owner", TODAY)[0].body
    v2 = assessments(make_registry(events=[event(status="VERIFIED")], terms=[term(pct="40", version="2")]))
    (act,) = plan(v2, parse_ledger([issue(7, body)], {}), "owner", TODAY)
    assert act.kind == "comment" and act.issue_number == 7 and "version=2" in act.body
    ledger = parse_ledger([issue(7, body)], {7: [act.body]})
    assert plan(v2, ledger, "owner", TODAY) == []


def test_lead_that_becomes_verified_opens_a_deal_and_closes_the_lead(make_registry):
    lead = plan(assessments(make_registry()), {}, "owner", TODAY)[0]
    verified = assessments(make_registry(events=[event(status="VERIFIED")], terms=[term(pct="35", version="1")]))
    acts = plan(verified, parse_ledger([issue(3, lead.body)], {}), "owner", TODAY)
    assert [(x.kind, x.issue_kind) for x in acts] == [("create", "verified"), ("close", "lead")]


def test_lead_resolved_below_threshold_is_closed_without_a_deal(make_registry):
    lead = plan(assessments(make_registry()), {}, "owner", TODAY)[0]
    low = assessments(make_registry(events=[event(status="VERIFIED")], terms=[term(pct="15")]))
    (act,) = plan(low, parse_ledger([issue(3, lead.body)], {}), "owner", TODAY)
    assert act.kind == "close" and "below threshold" in act.body


def test_cancelled_sale_gets_one_closing_comment(make_registry):
    deal = plan(assessments(make_registry(events=[event(status="VERIFIED")], terms=[term(pct="40")])), {}, "o", TODAY)[0]
    gone = assessments(make_registry(events=[event(status="CANCELLED")], terms=[term(pct="40")]))
    (act,) = plan(gone, parse_ledger([issue(5, deal.body)], {}), "o", TODAY)
    assert act.kind == "close" and act.body.startswith("**Cancelled:**")
    assert plan(gone, parse_ledger([issue(5, deal.body, state="closed")], {}), "o", TODAY) == []


def test_expired_sale_is_closed_quietly(make_registry):
    path = make_registry(events=[event(status="VERIFIED")], terms=[term(pct="40")])
    deal = plan(assessments(path), {}, "o", TODAY)[0]
    (act,) = plan(assessments(path, today=date(2026, 11, 30)), parse_ledger([issue(5, deal.body)], {}), "o", date(2026, 11, 30))
    assert act.kind == "close" and act.body == "This sale has ended."


def test_roundup_says_coverage_out_loud(make_registry):
    title, body = roundup(assessments(make_registry()), {"stores": 1, "verified_stores": 1, "in_radius": 1, "radius": 300,
                                                         "collectors": "none yet"}, "2026-11-22", "owner", TODAY)
    assert title == "\U0001F4CB MTG weekly roundup – week of 2026-11-22"
    assert "- none verified yet" in body and "not that nothing exists" in body and "kind=roundup" in body


class FakeAPI:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, request, timeout=30):
        self.calls.append((request.get_method(), request.full_url, request.data))
        key = (request.get_method(), request.full_url.split("api.test")[1])
        status, payload = self.routes.get(key, (200, []))
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, None)

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(json.dumps(payload).encode())


def test_github_client_pages_issues_and_skips_pull_requests():
    api = FakeAPI({("GET", "/repos/o/r/issues?state=all&labels=x&per_page=100&page=1"):
                   (200, [{"number": 1, "body": "a"}, {"number": 2, "body": "b", "pull_request": {}}])})
    gh = GitHub("o/r", "t", api="https://api.test", opener=api)
    assert [i["number"] for i in gh.tracker_issues(["x"])] == [1]


def test_github_label_already_existing_is_fine_but_other_errors_raise():
    gh = GitHub("o/r", "t", api="https://api.test", opener=FakeAPI({("POST", "/repos/o/r/labels"): (422, {})}))
    gh.ensure_label("x", "ffffff", "d")
    gh = GitHub("o/r", "t", api="https://api.test", opener=FakeAPI({("POST", "/repos/o/r/labels"): (403, {})}))
    with pytest.raises(GitHubError, match="HTTP 403"):
        gh.ensure_label("x", "ffffff", "d")


def test_github_client_needs_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubError):
        GitHub("o/r", "")
