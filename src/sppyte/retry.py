"""
sppyte.retry
~~~~~~~~~~~~

Opt-in retry of transient failures for read requests.

Enable with ``Site(..., retry=True)`` or ``Site(..., retry=RetryOptions(...))``.
Reads (``GET`` requests and CAML `List.query`) are retried; writes never are.
Delays use exponential backoff with full jitter —
``random(0, min(max_delay, base_delay * 2**attempt))`` — unless the server
sent ``Retry-After``, in which case that wait is used as-is; if it exceeds
`RetryOptions.max_delay` retrying stops and the error propagates.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from requests import ConnectionError as RequestsConnectionError
from requests import Timeout

from sppyte.errors import SharePointError

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")

RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
"""HTTP statuses treated as transient by `is_transient`."""

_random = random.SystemRandom()


def is_transient(exc: BaseException) -> bool:
    """
    Default `RetryOptions.retry_on`: connection failures, timeouts, and
    `SharePointError` with status 429, 502, 503 or 504.
    """
    if isinstance(exc, SharePointError):
        return exc.status in RETRYABLE_STATUSES
    return isinstance(exc, RequestsConnectionError | Timeout)


@dataclass(frozen=True)
class RetryOptions:
    """Settings for `Site(retry=...)`."""

    retries: int = 2
    """Extra attempts after the first failure."""
    base_delay: float = 0.2
    """Base delay in seconds; doubles each attempt."""
    max_delay: float = 5.0
    """Upper bound on one delay, including a server-requested ``Retry-After``."""
    retry_on: Callable[[BaseException, int], bool] | None = None
    """
    Decide whether a failed attempt should be retried; receives the exception
    and the 1-based attempt number. Defaults to `is_transient`.
    """


def with_retry(options: RetryOptions | None, attempt: Callable[[], T]) -> T:
    """
    Run `attempt`; on a retryable exception, wait and run it again, up to
    `options.retries` more times. Re-raises the last exception.
    """
    if options is None:
        return attempt()
    should_retry = options.retry_on or (lambda exc, _n: is_transient(exc))
    retries = max(0, options.retries)
    for n in range(1, retries + 1):
        try:
            return attempt()
        except Exception as exc:
            if not should_retry(exc, n):
                raise
            retry_after = exc.retry_after if isinstance(exc, SharePointError) else None
            if retry_after is not None:
                if retry_after > options.max_delay:
                    raise
                wait = retry_after
            else:
                cap = min(options.max_delay, options.base_delay * 2 ** (n - 1))
                wait = _random.uniform(0, cap)
            time.sleep(wait)
    return attempt()
