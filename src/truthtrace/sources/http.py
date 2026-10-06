"""A polite HTTP fetcher: honest User-Agent, robots.txt, per-host delay, retries with backoff.

The transport is injectable (``opener``), so all of this is unit-tested without the network.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from typing import Callable
from urllib.parse import urlsplit

from ..errors import FetchBlocked, TransientError

log = logging.getLogger(__name__)

# opener(url, headers) -> (status_code, body_bytes)
Opener = Callable[[str, dict[str, str]], tuple[int, bytes]]


def urllib_opener(url: str, headers: dict[str, str], timeout: float = 30.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (http/https only)
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise TransientError(f"network error: {exc}") from exc


class PoliteFetcher:
    def __init__(self, user_agent: str, *, min_delay: float = 5.0, max_retries: int = 3,
                 opener: Opener | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if "Mozilla" in user_agent:
            raise ValueError("use an honest User-Agent that identifies this tool, not a browser string")
        self.user_agent = user_agent
        self.min_delay, self.max_retries = min_delay, max_retries
        self._open = opener or urllib_opener
        self._sleep, self._clock = sleep, clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.requests_made = 0

    def _wait_for_host(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host)
            if last is not None:
                wait = self.min_delay - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)
            self._last[host] = self._clock()

    def _raw_get(self, url: str) -> tuple[int, bytes]:
        host = urlsplit(url).netloc
        self._wait_for_host(host)
        self.requests_made += 1
        return self._open(url, {"User-Agent": self.user_agent, "Accept": "text/html,application/xml;q=0.9"})

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                status, body = self._raw_get(base + "/robots.txt")
            except TransientError:
                status, body = 503, b""
            if status == 200:
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                self._robots[base] = parser
            elif 400 <= status < 500:
                self._robots[base] = None  # no robots.txt: everything allowed
            else:
                parser.disallow_all = True  # robots.txt unavailable: be conservative
                self._robots[base] = parser
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        robots = self._robots_for(url)
        return True if robots is None else robots.can_fetch(self.user_agent, url)

    def get(self, url: str) -> bytes:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"refusing non-http URL {url!r}")
        if not self.allowed(url):
            raise FetchBlocked(f"robots.txt disallows {url}")
        delay = self.min_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                status, body = self._raw_get(url)
            except TransientError:
                status, body = 503, b""
            if status == 200:
                return body
            if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                log.warning("HTTP %s for %s, retrying in %.0fs", status, url, delay)
                self._sleep(delay)
                delay *= 2
                continue
            if status in (429, 500, 502, 503, 504):
                raise TransientError(f"HTTP {status} for {url}")
            raise FetchBlocked(f"HTTP {status} for {url}")
        raise TransientError(f"gave up on {url}")  # pragma: no cover
