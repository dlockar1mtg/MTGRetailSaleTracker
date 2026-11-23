"""Minimal GitHub REST client (standard library only) for the alert issues.

Uses the workflow's GITHUB_TOKEN (permissions: issues: write). No other repository is touched.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, repo: str | None = None, token: str | None = None, api: str = "https://api.github.com", opener=None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.api = api.rstrip("/")
        self.opener = opener or urllib.request.urlopen
        if not self.repo or not self.token:
            raise GitHubError("GITHUB_REPOSITORY and GITHUB_TOKEN are required to send alerts")

    def _call(self, method: str, path: str, payload: dict | None = None):
        url = path if path.startswith("http") else f"{self.api}/repos/{self.repo}{path}"
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "MTGRetailSaleTracker",
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with self.opener(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            raise GitHubError(f"{method} {path}: HTTP {exc.code}") from exc

    def _pages(self, path: str):
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            batch = self._call("GET", f"{path}{sep}per_page=100&page={page}") or []
            yield from batch
            if len(batch) < 100:
                return
            page += 1

    def ensure_label(self, name: str, color: str, description: str) -> None:
        try:
            self._call("POST", "/labels", {"name": name, "color": color, "description": description})
        except GitHubError as exc:
            if "HTTP 422" not in str(exc):  # 422: the label already exists
                raise

    def tracker_issues(self, labels: list[str]) -> list[dict]:
        seen: dict[int, dict] = {}
        for label in labels:
            for issue in self._pages(f"/issues?state=all&labels={label}"):
                if "pull_request" not in issue:
                    seen[issue["number"]] = issue
        return list(seen.values())

    def comments(self, number: int) -> list[str]:
        return [c.get("body") or "" for c in self._pages(f"/issues/{number}/comments")]

    def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        return self._call("POST", "/issues", {"title": title, "body": body, "labels": labels})["number"]

    def comment(self, number: int, body: str) -> None:
        self._call("POST", f"/issues/{number}/comments", {"body": body})

    def close(self, number: int) -> None:
        self._call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})
