"""Exception types."""
from __future__ import annotations


class TruthTraceError(Exception):
    """Base class for errors raised on purpose by this package."""


class ConfigError(TruthTraceError):
    """Missing or invalid configuration."""


class MissingDependency(TruthTraceError):
    def __init__(self, package: str, extra: str):
        super().__init__(f"'{package}' is not installed. Install it with: pip install \"truthtrace[{extra}]\"")
        self.package, self.extra = package, extra


class TransientError(TruthTraceError):
    """A failure worth retrying (rate limit, timeout, server error)."""


class FetchBlocked(TruthTraceError):
    """robots.txt (or our own policy) does not allow fetching this URL."""


class ParseError(TruthTraceError):
    """A page or record could not be turned into an Article."""
