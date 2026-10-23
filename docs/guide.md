# Guide

## Connecting

```python
Site(host, site_relative_url, username=None, password=None, *,
     domain=None, protocol="ntlm", auth=None,
     timeout=30.0, verify=None, cert=None, session=None, retry=None)
```

- `host` is scheme and host only: `"https://sharepoint.example.com"`.
- `site_relative_url` is the server-relative URL of the site (web): `"/sites/parrots"`, or `""` / `"/"` for the root site.
- `domain` is the NTLM (NetBIOS) domain, e.g. `"CONTOSO"`. Leave it out for a local account.

Creating a `Site` performs no network I/O; the HTTP session is created on the first request. Malformed options raise [`ConfigurationError`][sppyte.errors.ConfigurationError] immediately instead of surfacing later as an opaque 404.

A `Site` owns the HTTP session. Use it as a context manager to connect eagerly (which also verifies the credentials) and close the session afterwards, or call `connect()` / `close()` yourself. `site.list(name)` and `site.library(name)` return lightweight helpers bound to the site that hold no resources of their own.

## Authentication

sppyte speaks NTLM and Negotiate (SPNEGO / Kerberos) through [pyspnego](https://pypi.org/project/pyspnego/); see [`SpPremAuth`][sppyte.auth.SpPremAuth]. The handshake authenticates the TCP connection, so it runs once per pooled connection.

```python
Site(HOST, SITE, "jsmith", PASSWORD, domain="CONTOSO")                        # NTLM (default)
Site(HOST, SITE, "jsmith", PASSWORD, domain="CONTOSO", protocol="negotiate")  # Kerberos if possible
Site(HOST, SITE, protocol="negotiate")                                        # single sign-on
Site(HOST, SITE, auth=my_requests_auth_handler)                               # any requests AuthBase
```

Kerberos on Linux/macOS needs the system GSSAPI libraries and `pip install "sppyte[kerberos]"`; Windows uses SSPI. Over HTTPS, TLS channel bindings are sent automatically for servers with Extended Protection.

## Write operations and the request digest

SharePoint requires a form digest (`X-RequestDigest`) on every write. sppyte manages it:

- fetched from `/_api/contextinfo` on the first write (or on `connect()`),
- cached until a minute before SharePoint says it expires (30 minutes by default),
- shared between threads using the same `Site` (one fetch at a time),
- and, if SharePoint still rejects it with **403**, refreshed and the write **retried once**, provided the body can be re-sent (bytes, JSON, or a seekable file; a non-seekable stream is not retried).

Pass `digest=` to any write method to send your own value as-is, with no retry:

```python
digest = site.get_form_digest()
pets.add_item({"Title": "x"}, digest=digest)
```

## Paging

SharePoint caps a collection response (100 list items by default, or `$top`) and points at the rest with `odata.nextLink`. `get_contents`, `list_contents` and `list_folders` return a [`Page`][sppyte.odata.Page] — a plain `list` with a `next_link` attribute.

| | one page | every page, lazily | every page, collected |
|---|---|---|---|
| `List` | `get_contents(params)` | `iter_items(params)` / `iter_pages(params)` | `get_all_items(params)` |
| `Library` | `list_contents(*folders, params=)` | `iter_files(...)` / `iter_pages(...)` | `get_all_files(...)` |

All accept `max_pages=`. [`Site.get_page`][sppyte.site.Site.get_page] refuses a link that is not on the site's host, so credentials are never sent elsewhere.

## CAML queries and the 5,000-item threshold

`$filter` on a non-indexed column fails on lists above the 5,000-item view threshold. [`List.query`][sppyte.lists.List.query] posts a CAML `<View>` to `GetItems`; a `<Where>` on an **indexed** column is evaluated by SQL Server and works far above the threshold.

```python
view = """
<View>
  <Query>
    <Where><Eq><FieldRef Name='Status'/><Value Type='Text'>Open</Value></Eq></Where>
    <OrderBy><FieldRef Name='ID'/></OrderBy>
  </Query>
  <RowLimit>500</RowLimit>
</View>
"""
for task in tasks.iter_query(view, params={"$select": "Id,Title"}):
    ...
```

`iter_query` / `query_all` require a `<RowLimit>` and page by the `Id` of the last item returned, which assumes the view is ordered by ID ascending. Keep `Id` in `$select` if you restrict columns.

## Batching requests

[`Site.batch()`][sppyte.site.Site.batch] collects sub-requests and sends them as one `POST /_api/$batch` (SharePoint 2016+). Consecutive writes are grouped into one changeset, which SharePoint applies atomically. A failing sub-request does **not** fail the batch — check `ok` on each [`BatchResponse`][sppyte.batch.BatchResponse].

```python
batch = site.batch()
batch.get(f"{tasks.path}/items", params={"$select": "Id,Title", "$top": 5})
batch.post(f"{tasks.path}/items", {"__metadata": {"type": tasks.item_type}, "Title": "A"})
batch.merge(f"{tasks.path}/items(7)", {"__metadata": {"type": tasks.item_type}, "Title": "B"})
for res in batch.send():
    print(res.status, res.json if res.ok else res.error)
```

## Large files

Uploads stream: pass a path (opened for you), an open binary file object, or `bytes`. Downloads: `get_document` returns `bytes`; for anything big use [`iter_document`][sppyte.libraries.Library.iter_document] or [`download`][sppyte.libraries.Library.download], which writes to a path or an open binary file object. HTTP errors are raised before the first chunk.

## Errors

```
SppyteError
├── ConfigurationError   (also a ValueError)
├── ResponseFormatError
└── SharePointError      (also a requests.HTTPError)
    └── AuthError        (401 / 403)
```

[`SharePointError`][sppyte.errors.SharePointError] parses the SharePoint error body, so `str(e)` reads `HTTP 400: Column 'Foo' does not exist`, and exposes `status`, `code`, `message`, `retry_after` and `response`. Transport failures (DNS, connection refused, timeouts) are still raised by `requests`.

## Retrying transient failures

Off by default. `Site(..., retry=True)` retries **reads** — `GET` requests and CAML `query` — that fail with a connection error, a timeout, or HTTP 429 / 502 / 503 / 504, with exponential backoff and full jitter; `Retry-After` is honoured. Writes and `$batch` are never retried. Tune with [`RetryOptions`][sppyte.retry.RetryOptions].

## Timeouts, TLS and proxies

- `timeout` (default 30 s) applies to every request; a `(connect, read)` tuple is accepted; `None` disables it.
- `verify` and `cert` are forwarded to `requests` (internal CA bundles, client certificates).
- `session` lets you supply your own `requests.Session` (proxies, adapters). sppyte adds NTLM auth to it only if it has no `auth`, and never closes it.

## Special characters

List titles, folder names and file names are escaped for OData string literals automatically, so names containing spaces, `'`, `#`, `%`, `?` or `&` work as-is. See [`odata_literal`][sppyte.odata.odata_literal] and [`odata_path`][sppyte.odata.odata_path].

## Extension requests

Endpoints not wrapped by sppyte are reachable through [`Site.request`][sppyte.site.Site.request]; pass `digest=True` for writes. [`List.path`][sppyte.lists.List.path], [`Library.folder_path`][sppyte.libraries.Library.folder_path] and [`Library.file_path`][sppyte.libraries.Library.file_path] give you escaped paths to build on.
