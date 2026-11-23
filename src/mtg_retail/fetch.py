"""Polite HTTP for the collectors: identifies itself, obeys robots.txt, one request at a time per host.

Nothing here logs in, sends cookies, solves challenges or retries around a refusal. A page that robots.txt
disallows, or that answers 401/403/429, is recorded as such and skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit

USER_AGENT = "MTGRetailSaleTracker/0.3 (+https://github.com/dlockar1mtg/mtgretailsaletracker)"
MAX_BYTES = 3_000_000


@dataclass
class Page:
    url: str
    status: int          # HTTP status; 0 for a network error; -1 when robots.txt disallows the fetch
    text: str
    final_url: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _decode(raw: bytes, content_type: str, encoding: str) -> str:
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    return raw.decode(charset, errors="replace")


class Fetcher:
    """`opener(request, timeout)` is urllib's by default; tests pass a fake."""

    def __init__(self, opener=None, min_interval: float = 2.0, timeout: int = 25, respect_robots: bool = True):
        self.opener = opener or urllib.request.urlopen
        self.min_interval = min_interval
        self.timeout = timeout
        self.respect_robots = respect_robots
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _host_lock(self, host: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def _raw(self, url: str) -> Page:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
                                                   "Accept-Encoding": "gzip", "Accept-Language": "en-US,en;q=0.8"})
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
                headers = getattr(resp, "headers", {}) or {}
                text = _decode(raw, headers.get("Content-Type", "") or "", headers.get("Content-Encoding", "") or "")
                return Page(url, getattr(resp, "status", 200), text, getattr(resp, "url", url) or url)
        except urllib.error.HTTPError as exc:
            return Page(url, exc.code, "", url, f"HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
            return Page(url, 0, "", url, f"{type(exc).__name__}: {str(exc)[:160]}")

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            page = self._raw(root + "/robots.txt")
            parser = urllib.robotparser.RobotFileParser()
            if page.status in (401, 403):
                parser.disallow_all = True
            elif page.ok:
                parser.parse(page.text.splitlines())
            else:
                parser.allow_all = True      # no robots.txt (404) or unreachable: the page fetch itself decides
            self._robots[root] = parser
        return self._robots[root].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> Page:
        host = urlsplit(url).netloc.lower()
        with self._host_lock(host):
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            try:
                if not self.allowed(url):
                    return Page(url, -1, "", url, "disallowed by robots.txt")
                return self._raw(url)
            finally:
                self._last[host] = time.monotonic()
