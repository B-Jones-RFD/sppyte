"""OData `$batch` support: send several REST requests in one round trip.

SharePoint 2016+ and Subscription Edition support `/_api/$batch`; SharePoint
2013 does not. Each sub-request gets its own `BatchResponse`; a failing
sub-request does not fail the batch, so check `BatchResponse.ok`. Consecutive
writes are grouped into one changeset (atomic on the server); reads are sent
as individual parts. Order is preserved.

Example:
    ```python
    batch = site.batch()
    batch.get(f"{pets.path}/items", params={"$top": 5})
    batch.post(
        f"{pets.path}/items", {"__metadata": {"type": pets.item_type}, "Title": "A"}
    )
    batch.merge(
        f"{pets.path}/items(7)",
        {"__metadata": {"type": pets.item_type}, "Title": "B"},
    )
    for res in batch.send():
        if not res.ok:
            print(res.status, res.error)
    ```
"""

from __future__ import annotations

import contextlib
import json as jsonlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit

from sppyte.errors import ConfigurationError, ResponseFormatError, SharePointErrorDetails, parse_sharepoint_error
from sppyte.odata import JSON_NOMETADATA, JSON_VERBOSE

if TYPE_CHECKING:
    from sppyte.odata import Params
    from sppyte.site import Site

CRLF = "\r\n"
WRITE_METHODS = frozenset({"POST", "PATCH", "MERGE", "DELETE"})
"""Methods that are grouped into changesets."""
HTTP_OK_MIN = 200
HTTP_OK_MAX = 299

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_STATUS_RE = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})")


@dataclass
class BatchRequest:
    """One sub-request of a `$batch` call, with its URL already resolved.

    Attributes:
        method: Upper-cased HTTP method.
        url: Absolute URL of the sub-request.
        headers: Extra headers; defaults are added when the part is encoded.
        body: Serialised body, or `None`.
    """

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None


@dataclass
class BatchResponse:
    """Response to one `BatchRequest`, in request order.

    Attributes:
        status: HTTP status of the part.
        headers: Response headers with lower-cased names.
        body: Raw body text.
        json: Parsed body when the part is JSON and parses; otherwise `None`.
    """

    status: int
    headers: dict[str, str]
    body: str
    json: Any = None

    @property
    def ok(self) -> bool:
        """Whether the part has a 2xx status."""
        return HTTP_OK_MIN <= self.status <= HTTP_OK_MAX

    @property
    def error(self) -> SharePointErrorDetails | None:
        """SharePoint's error object for a failed part, if the body carried one."""
        return None if self.ok else parse_sharepoint_error(self.body)


class Batch:
    """Collects sub-requests and sends them as one `/_api/$batch` call.

    Obtain one from `Site.batch()`. Paths are site-relative (`_api/...`) or
    absolute URLs on the site's host; query options go in `params`. Builder
    methods return the batch so calls can be chained.

    Args:
        site: The site to send the batch to.
    """

    def __init__(self, site: Site):
        self.site = site
        self.requests: list[BatchRequest] = []

    def __len__(self) -> int:
        return len(self.requests)

    def __repr__(self) -> str:
        return f"Batch({len(self.requests)} requests, {self.site!r})"

    # ------------------------------------------------------------ builders ----
    def add(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json: Any = None,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Batch:
        """Queue a sub-request.

        Default headers are `Accept: application/json;odata=nometadata`,
        `Content-Type: application/json;odata=verbose` when there is a body, and
        `If-Match: *` for `PATCH` / `MERGE` / `DELETE`; `headers` override them.

        Args:
            method: HTTP method (`GET`, `POST`, `MERGE`, `PATCH` or `DELETE`).
            path: Site-relative REST path (`_api/...`) or an absolute URL on the site's host.
            params: OData query options appended to the URL.
            json: JSON body, serialised for you.
            body: Pre-serialised body, sent as-is. Pass either `json` or `body`.
            headers: Extra headers for this sub-request.

        Returns:
            This batch, so calls can be chained.

        Raises:
            ValueError: if both `json` and `body` are given.
            ConfigurationError: if an absolute `path` is not on the site's host.
        """
        if json is not None and body is not None:
            msg = "pass either json or body, not both"
            raise ValueError(msg)
        url = self._resolve(path, params)
        payload = jsonlib.dumps(json) if json is not None else body
        self.requests.append(BatchRequest(method.upper(), url, dict(headers or {}), payload))
        return self

    def get(self, path: str, *, params: Params = None, headers: Mapping[str, str] | None = None) -> Batch:
        """Queue a `GET`; see `add` for the arguments."""
        return self.add("GET", path, params=params, headers=headers)

    def post(
        self,
        path: str,
        json: Any = None,
        *,
        params: Params = None,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Batch:
        """Queue a `POST` (create, or any action endpoint); see `add` for the arguments."""
        return self.add("POST", path, params=params, json=json, body=body, headers=headers)

    def merge(
        self,
        path: str,
        json: Any = None,
        *,
        params: Params = None,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Batch:
        """Queue a `MERGE` (partial update; omitted fields are untouched); see `add`."""
        return self.add("MERGE", path, params=params, json=json, body=body, headers=headers)

    def patch(
        self,
        path: str,
        json: Any = None,
        *,
        params: Params = None,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Batch:
        """Queue a `PATCH` (equivalent to `MERGE` on SharePoint); see `add`."""
        return self.add("PATCH", path, params=params, json=json, body=body, headers=headers)

    def delete(self, path: str, *, params: Params = None, headers: Mapping[str, str] | None = None) -> Batch:
        """Queue a `DELETE`; see `add` for the arguments."""
        return self.add("DELETE", path, params=params, headers=headers)

    # ---------------------------------------------------------------- send ----
    def send(self, *, digest: str | None = None, **kwargs: Any) -> list[BatchResponse]:
        """Send the queued requests in one `POST /_api/$batch`.

        The batch itself raising (`AuthError`, `SharePointError`) means the
        whole call failed; a failed sub-request is reported through its own
        `BatchResponse.ok`. An empty batch returns `[]` without a request.

        Args:
            digest: Form digest to send instead of the managed one.
            **kwargs: Passed to `Site.request` (e.g. `timeout`).

        Returns:
            One `BatchResponse` per request, in order.

        Raises:
            ResponseFormatError: if the response is not multipart or the part count differs.
        """
        if not self.requests:
            return []
        boundary = new_boundary("batch")
        body = build_batch_body(self.requests, boundary).encode("utf-8")
        r = self.site.request(
            "post",
            "_api/$batch",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": f"multipart/mixed; boundary={boundary}"},
            data=body,
            digest=digest or True,
            **kwargs,
        )
        responses = parse_batch_response(r.text, r.headers.get("Content-Type"))
        if len(responses) != len(self.requests):
            msg = f"Batch response count: expected {len(self.requests)}, received {len(responses)}"
            raise ResponseFormatError(msg)
        return responses

    # ------------------------------------------------------------- helpers ----
    def _resolve(self, path: str, params: Params) -> str:
        """Turn a site-relative path or same-host URL into the absolute sub-request URL."""
        if _SCHEME_RE.match(path):
            wanted = urlsplit(self.site.host)
            got = urlsplit(path)
            if (got.scheme.lower(), got.netloc.lower()) != (wanted.scheme.lower(), wanted.netloc.lower()):
                msg = f"batch sub-request must be on {self.site.host} (got {path!r})"
                raise ConfigurationError(msg)
            url = path
        else:
            url = f"{self.site.site_path}/{path.lstrip('/')}"
        if params:
            query = urlencode(list(params.items()) if isinstance(params, Mapping) else list(params))
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        return url


# ------------------------------------------------------------- encoding ----
def new_boundary(prefix: str) -> str:
    """Return a unique multipart boundary, e.g. `batch_<uuid>`."""
    return f"{prefix}_{uuid.uuid4()}"


def _http_part(req: BatchRequest) -> str:
    """Encode one `application/http` part containing a single sub-request."""
    headers: dict[str, str] = {"Accept": JSON_NOMETADATA}
    if req.body is not None:
        headers["Content-Type"] = JSON_VERBOSE
    if req.method in ("PATCH", "MERGE", "DELETE"):
        headers["If-Match"] = "*"
    headers.update(req.headers)

    lines = [
        "Content-Type: application/http",
        "Content-Transfer-Encoding: binary",
        "",
        f"{req.method} {req.url} HTTP/1.1",
        *(f"{k}: {v}" for k, v in headers.items()),
        "",
    ]
    if req.body is not None:
        lines.append(req.body)
    lines.append("")
    return CRLF.join(lines)


def build_batch_body(requests: list[BatchRequest], boundary: str) -> str:
    """Build the multipart body for `/_api/$batch`.

    Reads are individual parts; each run of consecutive writes is wrapped in
    one changeset, as OData requires. Order is preserved so responses can be
    matched to requests.
    """
    parts: list[str] = []
    i = 0
    while i < len(requests):
        req = requests[i]
        if req.method not in WRITE_METHODS:
            parts.append(f"--{boundary}{CRLF}{_http_part(req)}")
            i += 1
            continue
        changeset = new_boundary("changeset")
        inner: list[str] = []
        while i < len(requests) and requests[i].method in WRITE_METHODS:
            inner.append(f"--{changeset}{CRLF}{_http_part(requests[i])}")
            i += 1
        parts.append(
            f"--{boundary}{CRLF}Content-Type: multipart/mixed; boundary={changeset}{CRLF}{CRLF}"
            + "".join(inner)
            + f"--{changeset}--{CRLF}"
        )
    return "".join(parts) + f"--{boundary}--{CRLF}"


# ------------------------------------------------------------- decoding ----
def multipart_boundary(content_type: str | None) -> str | None:
    """Extract `boundary=...` from a multipart `Content-Type` header, or `None`."""
    if not content_type:
        return None
    match = _BOUNDARY_RE.search(content_type)
    return match.group(1) if match else None


def _split_head_body(text: str) -> tuple[str, str]:
    """Split a part at its first blank line into (headers, body)."""
    idx = text.find("\n\n")
    if idx == -1:
        return text, ""
    return text[:idx], text[idx + 2 :]


def _parse_headers(block: str) -> dict[str, str]:
    """Parse `Name: value` lines into a dict with lower-cased names."""
    out: dict[str, str] = {}
    for line in block.split("\n"):
        i = line.find(":")
        if i > 0:
            out[line[:i].strip().lower()] = line[i + 1 :].strip()
    return out


def _parse_http_part(text: str) -> BatchResponse:
    """Parse one `application/http` response part."""
    head, raw_body = _split_head_body(text)
    status_line, _, header_block = head.partition("\n")
    match = _STATUS_RE.match(status_line)
    status = int(match.group(1)) if match else 0
    headers = _parse_headers(header_block)
    body = raw_body.rstrip("\n")
    response = BatchResponse(status=status, headers=headers, body=body)
    if body and "json" in headers.get("content-type", "").lower():
        # On unparsable JSON leave json None; body is still available.
        with contextlib.suppress(ValueError):
            response.json = jsonlib.loads(body)
    return response


def _parse_multipart(text: str, boundary: str) -> list[BatchResponse]:
    """Parse a multipart body (LF line endings), descending into changesets."""
    results: list[BatchResponse] = []
    delimiter = f"--{boundary}"
    # segments[0] is the preamble; the last is the epilogue after "--".
    for segment in text.split(delimiter)[1:]:
        if segment.startswith("--"):
            break
        part = segment[1:] if segment.startswith("\n") else segment
        head, body = _split_head_body(part)
        headers = _parse_headers(head)
        content_type = headers.get("content-type", "")
        if "multipart/mixed" in content_type.lower():
            inner = multipart_boundary(content_type)
            if inner:
                results.extend(_parse_multipart(body, inner))
        elif "application/http" in content_type.lower():
            results.append(_parse_http_part(body))
    return results


def parse_batch_response(body: str, content_type: str | None) -> list[BatchResponse]:
    """Parse a `$batch` response body into one `BatchResponse` per sub-request.

    Changeset responses are flattened; order is preserved.

    Raises:
        ResponseFormatError: if the response is not `multipart/mixed`.
    """
    boundary = multipart_boundary(content_type)
    if not boundary:
        msg = "Batch response is not multipart/mixed"
        raise ResponseFormatError(msg)
    return _parse_multipart(body.replace("\r\n", "\n"), boundary)
