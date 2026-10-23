![GitHub Actions CI](https://github.com/B-Jones-RFD/sppyte/actions/workflows/CI.yml/badge.svg)
![PyPI - License](https://img.shields.io/pypi/l/sppyte)
[![PyPI - Version](https://img.shields.io/pypi/v/sppyte.svg)](https://pypi.org/project/sppyte)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/sppyte)](https://pypi.org/project/sppyte)
[![Supported Versions](https://img.shields.io/pypi/pyversions/sppyte.svg)](https://pypi.org/project/sppyte)

# Sppyte

A tiny, explicit Python helper for working with a SharePoint site through the legacy **SharePoint REST** endpoints with **NTLM** authentication. Sppyte[^1] keeps a very thin abstraction so you can reason about the underlying HTTP calls without surprises.

> ⚠️ This client uses **NTLM** (`requests-ntlm`) and is for **SharePoint on-premises** (2013, 2016, 2019, Subscription Edition). SharePoint Online does not accept NTLM.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Usage](#usage)
  - [Connecting](#connecting)
  - [Write operations and the request digest](#write-operations-and-the-request-digest)
  - [Paging](#paging)
  - [CAML queries and the 5,000-item threshold](#caml-queries-and-the-5000-item-threshold)
  - [Batching requests](#batching-requests)
  - [Large files](#large-files)
  - [Errors](#errors)
  - [Retrying transient failures](#retrying-transient-failures)
  - [Timeouts, TLS and proxies](#timeouts-tls-and-proxies)
  - [Special characters](#special-characters)
  - [Extension requests](#extension-requests)
- [API](#api)
  - [Site](#site)
  - [List](#list)
  - [Library](#library)
- [Migrating to 1.0](#migrating-to-10)
- [Notes](#notes)
- [License](#license)

## Features

- `Site` connection with NTLM auth, lazy session creation and a **managed form digest** (fetched, cached, refreshed before expiry, and retried once if SharePoint rejects it).
- `List` helper to:
  - Add / update / delete items
  - Iterate every item across pages (`iter_items`, `get_all_items`)
  - Run CAML queries (`query`, `iter_query`) to get past the 5,000-item view threshold
  - Use [OData](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service) params to control item responses
  - Add **attachments** to items
- `Library` helper to:
  - Add / delete **folders**
  - Upload / download / delete **documents**, streaming large files in both directions
  - List files and folders, page through them, and control output with [OData](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service) params
- `Site.batch()` to send several REST calls in one `/_api/$batch` round trip (SharePoint 2016+).
- Exceptions that carry SharePoint's own error message, status code and `Retry-After`.
- Opt-in retry of transient read failures with exponential backoff, honouring `Retry-After`.
- Access other [SharePoint REST service](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/get-to-know-the-sharepoint-rest-service) endpoints as needed.
- Fully typed (`py.typed`).

## Installation

```console
pip install sppyte
```

## Quickstart

```py
from sppyte import Site

HOST = "https://sharepoint.example.com"
SITE = "/sites/parrots"  # server-relative URL of the site
USER = "norwegian"
PASS = "••••••••"

with Site(HOST, SITE, USER, PASS, domain="CONTOSO") as site:
    # ---------------- Lists ----------------
    pets = site.list("Pets")

    # Add an item (entity type metadata is added for you)
    new_id = pets.add_item({"Title": "Norwegian Blue"})["Id"]

    # Update the item (uses MERGE)
    pets.update_item(new_id, {"Title": "Polly"})

    # Attach a file
    with open("notes.txt", "rb") as file_handle:
        pets.add_attachment(new_id, "notes.txt", file_handle)

    # Fetch one item
    item = pets.get_item(new_id)

    # Query one page of items (use any OData params you need)
    items = pets.get_contents({
        "$select": "Id,Title,Created",
        "$top": 5,
        "$orderby": "Created desc",
    })

    # Or walk every item, page by page
    for item in pets.iter_items({"$select": "Id,Title", "$top": 500}):
        ...

    # Delete the item
    pets.delete_item(new_id)

    # --------------- Libraries -------------
    shared_docs = site.library("Shared Documents")

    # Ensure a nested folder path exists
    shared_docs.add_folder("Napping", "2025")

    # Upload a document from a path (streamed), bytes, or an open file
    uploaded = shared_docs.add_document("report.pdf", "local/report.pdf", "Napping", "2025")
    print(uploaded["ServerRelativeUrl"], uploaded["UniqueId"])

    # List files in the library root, and in a subfolder
    files = shared_docs.list_contents(params={"$select": "Name,TimeCreated"})
    folder_files = shared_docs.list_contents("Napping", "2025", params={"$select": "Name"})
    subfolders = shared_docs.list_folders("Napping")

    # Download a document (bytes), or stream it to disk
    report = shared_docs.get_document("report.pdf", "Napping", "2025")
    shared_docs.download("report.pdf", "local/report-copy.pdf", "Napping", "2025")

    # Delete a document
    shared_docs.delete_document("report.pdf", "Napping", "2025")
```

## Usage

### Connecting

`Site(host, site_relative_url, username, password, *, domain=None, timeout=30.0, verify=None, cert=None, session=None, retry=None)`

- `host` is scheme and host only: `"https://sharepoint.example.com"`.
- `site_relative_url` is the server-relative URL of the site (web): `"/sites/parrots"`, or `""` / `"/"` for the root site.
- `domain` is the NTLM (NetBIOS) domain, e.g. `"CONTOSO"`. Leave it out for a local account.

Creating a `Site` performs no network I/O; the HTTP session is created on the first request. Malformed options (a path inside `host`, a `site_relative_url` without a leading `/`, a full URL where a path was expected) raise `ConfigurationError` immediately rather than surfacing later as an opaque 404.

A `Site` owns the HTTP session. Use it as a context manager to connect eagerly (which also verifies the credentials) and close the session afterwards, or call `connect()` / `close()` yourself:

```py
site = Site(HOST, SITE, USER, PASS)
try:
    site.connect()   # optional: NTLM handshake + first form digest now, not on first use
    ...
finally:
    site.close()
```

`site.list(name)` and `site.library(name)` return lightweight helpers bound to the site. They hold no resources of their own.

### Write operations and the request digest

SharePoint requires a form digest (`X-RequestDigest`) on every write. Sppyte manages it for you:

- it is fetched from `/_api/contextinfo` on the first write (or on `connect()`),
- cached until a minute before SharePoint says it expires (30 minutes by default),
- shared between threads using the same `Site` (one fetch at a time),
- and, if SharePoint still rejects it with **403**, refreshed and the write **retried once**, provided the body can be re-sent (bytes, JSON, or a seekable file; a non-seekable stream is not retried).

To take control yourself, pass `digest=` to any write method; the value is sent as-is with no retry:

```py
digest = site.get_form_digest()        # always fetches a fresh one
pets.add_item({"Title": "x"}, digest=digest)
```

`site.digest()` returns the cached digest (refreshing if needed) and `site.invalidate_digest()` drops it.

### Paging

SharePoint caps a collection response (100 list items by default, or `$top`) and points at the rest with `odata.nextLink`. `get_contents`, `list_contents` and `list_folders` return a `Page` — a plain `list` with a `next_link` attribute, so existing code that iterates or indexes the result is unchanged:

```py
page = tasks.get_contents({"$top": 500})
while page.next_link:
    page = site.get_page(page.next_link)
```

Usually you want the helpers that do this for you:

| | one page | every page, lazily | every page, collected |
|---|---|---|---|
| `List` | `get_contents(params)` | `iter_items(params)` / `iter_pages(params)` | `get_all_items(params)` |
| `Library` | `list_contents(*folders, params=)` | `iter_files(...)` / `iter_pages(...)` | `get_all_files(...)` |

All accept `max_pages=` to stop early. `iter_*` issue one request per page as you consume them. `Site.get_page(next_link)` refuses a link that is not on the site's host, so credentials are never sent elsewhere.

> `$filter` on a non-indexed column fails on lists above the 5,000-item view threshold regardless of paging; use a [CAML query](#caml-queries-and-the-5000-item-threshold) for those.

### CAML queries and the 5,000-item threshold

`List.query(view_xml)` posts a CAML `<View>` to `GetItems`. A `<Where>` on an **indexed** column is evaluated by SQL Server, so it works on lists far above the threshold where `$filter` returns an error. `$select` / `$expand` still go in `params`; `$filter` and `$top` belong in the CAML (`<Where>`, `<RowLimit>`).

```py
view = """
<View>
  <Query>
    <Where><Eq><FieldRef Name='Status'/><Value Type='Text'>Open</Value></Eq></Where>
    <OrderBy><FieldRef Name='ID'/></OrderBy>
  </Query>
  <RowLimit>500</RowLimit>
</View>
"""

page = tasks.query(view, params={"$select": "Id,Title"})            # first 500
page = tasks.query(view, paging_info=f"Paged=TRUE&p_ID={page[-1]['Id']}")  # next 500

for task in tasks.iter_query(view, params={"$select": "Id,Title"}):  # all of them
    ...
everything = tasks.query_all(view)
```

`iter_query` / `query_all` require a `<RowLimit>` and page by the `Id` of the last item returned, which assumes the view is ordered by ID ascending (the default). Keep `Id` in `$select` if you restrict columns.

### Batching requests

`site.batch()` collects sub-requests and sends them as one `POST /_api/$batch` (SharePoint 2016+ and Subscription Edition; not 2013). Consecutive writes are grouped into one changeset, which SharePoint applies atomically; reads are separate parts. Each sub-request gets its own `BatchResponse`, and a failing sub-request does **not** fail the batch — check `ok` on each.

```py
batch = site.batch()
batch.get(f"{tasks.path}/items", params={"$select": "Id,Title", "$top": 5})
batch.post(f"{tasks.path}/items", {"__metadata": {"type": tasks.item_type}, "Title": "A"})
batch.merge(f"{tasks.path}/items(7)", {"__metadata": {"type": tasks.item_type}, "Title": "B"})
batch.delete(f"{tasks.path}/items(8)")

for res in batch.send():
    if res.ok:
        print(res.status, res.json)
    else:
        print(res.status, res.error.message if res.error else res.body)
```

Paths are site-relative (`_api/...`) or absolute URLs on the site's host; `List.path`, `Library.folder_path(...)` and `Library.file_path(...)` give you escaped paths to build on. Defaults per part: `Accept: application/json;odata=nometadata`, `Content-Type: application/json;odata=verbose` when there is a body, and `If-Match: *` for `MERGE` / `PATCH` / `DELETE`; pass `headers=` to override. `BatchResponse` has `status`, `ok`, `headers` (lower-cased), `body`, `json` (parsed when the part is JSON) and `error` (SharePoint's parsed error for a failed part).

### Large files

Uploads stream: pass a path (opened for you), an open binary file object, or `bytes`. If the managed digest has to be refreshed mid-upload, a path or seekable file is re-sent from the start; a non-seekable stream cannot be and the `AuthError` propagates.

Downloads: `get_document` returns `bytes`; for anything big use `iter_document` (a generator of chunks) or `download(file_name, dest, *folders)`, which writes to a path or an open binary file object and returns the byte count. HTTP errors are raised before the first chunk.

```py
docs.download("backup.iso", "/mnt/backups/backup.iso", "ISOs", chunk_size=1 << 20)

with open("out.bin", "wb") as fh:
    for chunk in docs.iter_document("big.bin", "Exports"):
        fh.write(chunk)
```

### Errors

```
SppyteError
├── ConfigurationError   (also a ValueError) — bad Site options
├── ResponseFormatError  — a 2xx response did not contain the expected field
├── SessionError         — kept for compatibility; no longer raised
└── SharePointError      (also a requests.HTTPError) — any 4xx/5xx
    └── AuthError        — 401 or 403
```

`SharePointError` parses the SharePoint error body, so the message reads `HTTP 400: Column 'Foo' does not exist. ...` instead of `400 Client Error: Bad Request for url: ...`. It exposes:

| attribute | |
|---|---|
| `status` | HTTP status code |
| `code` | SharePoint error code, e.g. `-2130575338, Microsoft.SharePoint.SPException` |
| `message` | SharePoint's message |
| `retry_after` | seconds from a `Retry-After` header (429/503), or `None` |
| `response` | the underlying `requests.Response` |

```py
from sppyte import AuthError, SharePointError

try:
    pets.add_item({"Title": "x"})
except AuthError as e:
    print("check credentials / permissions:", e)
except SharePointError as e:
    if e.status == 429 and e.retry_after:
        time.sleep(e.retry_after)
    else:
        raise
```

Because `SharePointError` subclasses `requests.HTTPError`, existing `except HTTPError` handlers keep working. Transport failures (DNS, connection refused, timeouts) are still raised by `requests` as `requests.ConnectionError` / `requests.Timeout`.

### Retrying transient failures

Off by default. `Site(..., retry=True)` retries **reads** — `GET` requests (list/library reads, `get_page`, the `iter_*` helpers) and CAML `query` — that fail with a connection error, a timeout, or HTTP 429 / 502 / 503 / 504. Writes and `$batch` are never retried. Delays use exponential backoff with full jitter (`random(0, min(max_delay, base_delay·2ⁿ))`); when SharePoint sends `Retry-After` that wait is used instead, and if it exceeds `max_delay` the error is raised immediately so you can decide.

```py
from sppyte import RetryOptions, Site

site = Site(HOST, SITE, USER, PASS, retry=True)                               # 2 retries, 0.2 s base, 5 s cap
site = Site(HOST, SITE, USER, PASS, retry=RetryOptions(retries=4, base_delay=0.5, max_delay=20))

# Custom predicate: (exception, attempt_number) -> bool
site = Site(..., retry=RetryOptions(retry_on=lambda exc, n: is_transient(exc) and n <= 3))
```

`site.request(..., retry=False)` opts a single read out; `retry=True` opts an idempotent `POST` in.

### Timeouts, TLS and proxies

- `timeout` (default `30.0` seconds) applies to every request and can be a `(connect, read)` tuple. Pass `timeout=None` to disable (not recommended). Individual calls to `site.request(...)` can override it.
- `verify` is forwarded to `requests`: `False` to skip TLS verification, or a path to a CA bundle for an internal certificate authority — no more `REQUESTS_CA_BUNDLE` hacks.
- `cert` is forwarded to `requests` for client certificates.
- `session` lets you supply your own `requests.Session` (proxies, adapters, retries). Sppyte adds NTLM auth to it only if it has no `auth`, and never closes it.

```py
site = Site(HOST, SITE, USER, PASS, verify="/etc/pki/corp-root-ca.pem", timeout=(5, 120))
```

### Special characters

List titles, folder names and file names are escaped for OData string literals automatically, so names containing spaces, `'`, `#`, `%`, `?` or `&` work as-is. The helpers are available as `sppyte.odata.odata_literal` and `sppyte.odata.odata_path` if you build your own paths.

### Extension requests

Endpoints not wrapped by sppyte are reachable through `site.request(method, path, **kwargs)`. It uses the site's session, raises `SharePointError` / `AuthError` for non-2xx, applies the default `timeout`, and takes a **site-relative** path instead of a full URL. Pass `digest=True` for writes to get the managed digest (with the 403 refresh-and-retry), or `digest="..."` to send a specific one:

```py
r = site.request("get", "_api/web/lists", headers={"Accept": "application/json;odata=nometadata"})
lists = r.json()["value"]

site.request(
    "post",
    "_api/web/lists/GetByTitle('Pets')/recycle",
    headers={"Accept": "application/json;odata=nometadata"},
    digest=True,
)
```

`List.item_type` gives the `ListItemEntityTypeFullName` needed in `__metadata.type` when you build list-item payloads yourself.

## API

### Site

#### `Site(host, site_relative_url, username, password, *, domain=None, timeout=30.0, verify=None, cert=None, session=None, retry=None)`

See [Connecting](#connecting), [Retrying transient failures](#retrying-transient-failures) and [Timeouts, TLS and proxies](#timeouts-tls-and-proxies). Raises `ConfigurationError` for malformed options.

| member | |
|---|---|
| `connect()` | Create the session and fetch a form digest now. |
| `close()` | Forget the digest and close the session (if sppyte created it). |
| `list(name)` | A `List` bound to this site. No I/O. |
| `library(name)` | A `Library` bound to this site. No I/O. |
| `request(method, path, *, digest=None, retry=None, **kwargs)` | Low-level request; see [Extension requests](#extension-requests). |
| `retry` | The `RetryOptions` in effect, or `None`. |
| `digest(*, refresh=False)` | The managed form digest, fetching/refreshing as needed. |
| `get_form_digest()` | Always fetch a fresh digest (and cache it). |
| `invalidate_digest()` | Drop the cached digest. |
| `get_page(next_link)` | Fetch the page a `Page.next_link` points at (same host only). |
| `batch()` | A `Batch` builder; see [Batching requests](#batching-requests). |
| `form_digest` | The cached digest, or `None`. |
| `session` | The `requests.Session`, or `None` before first use. |
| `site_path`, `host`, `relative_url`, `principal` | Normalised connection details (`principal` is `DOMAIN\user`). |

### List

Obtain with `site.list(name)` (or `List(name, site)`). `name` is the list **title** as shown in SharePoint.

| member | returns | |
|---|---|---|
| `get_contents(params=None)` | `Page` | One page of items (a `list` with `next_link`); at most 100 unless `$top` is given. |
| `iter_pages(params=None, *, max_pages=None)` | `Iterator[Page]` | Follow `next_link` page by page. |
| `iter_items(params=None, *, max_pages=None)` | `Iterator[dict]` | Every item across pages, lazily. |
| `get_all_items(params=None, *, max_pages=None)` | `list[dict]` | Every item across pages. |
| `get_item(sp_id)` | `dict` | One item by ID. |
| `query(view_xml, *, paging_info=None, params=None, digest=None)` | `Page` | CAML `GetItems`. |
| `iter_query(view_xml, *, params=None, max_pages=None, digest=None)` | `Iterator[dict]` | Every match, paging by last `Id`; needs `<RowLimit>`. |
| `query_all(view_xml, *, params=None, max_pages=None, digest=None)` | `list[dict]` | Every match, collected. |
| `add_item(item, *, digest=None)` | `dict` | The created item as SharePoint returned it, including `Id`. `__metadata.type` is added unless present; `item` is not modified. |
| `update_item(sp_id, patch, *, digest=None)` | `int` | MERGE-update; omitted fields are untouched. Returns `sp_id`. |
| `delete_item(sp_id, *, digest=None)` | `bool` | `True`; failures raise. |
| `add_attachment(sp_id, file_name, attachment, *, digest=None)` | `dict` | The `SP.Attachment` created (`FileName`, `ServerRelativeUrl`). `attachment` is `bytes` or a binary file object. |
| `item_type` | `str` | `ListItemEntityTypeFullName`, fetched once and cached. |
| `path` | `str` | Site-relative REST path, e.g. `_api/web/lists/GetByTitle('Tasks')`. |
| `get_item_type()` | `str` | Fetch it again and refresh the cache. |

`params` is a mapping (or sequence of pairs) of OData options, e.g. `{"$select": "Id,Title", "$filter": "Status eq 'Open'", "$top": 500}`.

### Library

Obtain with `site.library(name)` (or `Library(name, site)`). Folder arguments are path segments beneath the library: `("Reports", "2025")` addresses `Shared Documents/Reports/2025`.

| member | returns | |
|---|---|---|
| `list_contents(*subfolders, params=None)` | `Page` | Files directly in the folder (`SP.File`: `Name`, `ServerRelativeUrl`, `Length`, …). |
| `list_folders(*subfolders, params=None)` | `Page` | Folders directly in the folder (`SP.Folder`: `Name`, `ServerRelativeUrl`, `ItemCount`, …). |
| `iter_pages(*subfolders, params=None, max_pages=None)` | `Iterator[Page]` | Follow `next_link` for files, page by page. |
| `iter_files(*subfolders, params=None, max_pages=None)` | `Iterator[dict]` | Every file across pages, lazily. |
| `get_all_files(*subfolders, params=None, max_pages=None)` | `list[dict]` | Every file across pages. |
| `get_document(file_name, *subfolders)` | `bytes` | Download into memory. |
| `iter_document(file_name, *subfolders, chunk_size=65536)` | `Iterator[bytes]` | Stream the file as chunks. |
| `download(file_name, dest, *subfolders, chunk_size=65536)` | `int` | Stream to a path or binary file object; returns bytes written. |
| `folder_exists(folder, *subfolders)` | `bool` | Missing folder is `False`, not an error. |
| `add_folder(folder, *subfolders, digest=None)` | `dict` | Create a folder (parent must exist); returns the `SP.Folder`. Already existing is not an error. |
| `add_document(file_name, document, *subfolders, overwrite=True, digest=None)` | `dict` | Upload; returns the `SP.File` (`UniqueId`, `ServerRelativeUrl`, …). `document` is a path, a binary file object, or `bytes`. `overwrite=False` makes a clash a `SharePointError`. |
| `delete_document(file_name, *subfolders, digest=None)` | `bool` | |
| `delete_folder(folder, *subfolders, digest=None)` | `bool` | |
| `server_relative_url(*parts)` | `str` | e.g. `/sites/parrots/Shared Documents/Reports`. |
| `folder_path(*subfolders)` / `file_path(file_name, *subfolders)` | `str` | Escaped site-relative REST paths for extension and batch requests. |

## Migrating to 1.0

- **`List.add_item` returns the created item (`dict`) instead of the ID.** Replace `new_id = pets.add_item(...)` with `new_id = pets.add_item(...)["Id"]`.
- **`Library.add_folder`, `add_document` and `List.add_attachment` return SharePoint's object (`dict`)** instead of `Exists`, `UniqueId` and `sp_id` respectively: use `["Exists"]`, `["UniqueId"]`, `["ServerRelativeUrl"]`.
- **`get_contents` / `list_contents` return a `Page`**, a `list` subclass — no change needed unless you compared `type(...) is list`.
- **`Library.list_contents(params, *subfolders)` → `list_contents(*subfolders, params=None)`.** `params` is keyword-only: `docs.list_contents("A", "B", params={...})`.
- **`List` and `Library` no longer own the session.** `with site.list("X") as l:` and `List.connect()` / `close()` are gone — they closed the *shared* `Site` session. Use `with Site(...) as site:` (or `site.connect()` / `site.close()`).
- **HTTP errors are `SharePointError` / `AuthError`.** Both still subclass `requests.HTTPError`, so `except HTTPError` keeps working; `e.response` is still available.
- **Requests time out after 30 s by default.** Pass `timeout=None` to restore the old (no timeout) behaviour.
- **`site.list()` / `site.library()` / `Site(...)` no longer connect eagerly.** Call `site.connect()` or use `with` if you relied on the constructor to validate credentials.
- `add_attachment` now sends `Content-Type: application/octet-stream`.
- `sppyte.models` still re-exports `Site`, `List`, `Library` but is deprecated; import from `sppyte`. `sppyte.utils.build_path` / `odata_literal` / `odata_path` moved to `sppyte.odata` (re-exported from `utils`).

## Notes

- OData parameters: `get_contents` and `list_contents` accept any OData query options via `params` (`$select`, `$filter`, `$orderby`, `$top`, `$expand`). See [the docs](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service).
- SharePoint caps a list response at 100 items unless `$top` is given.
- One `Site` per thread is simplest; sharing one across threads is supported for the digest cache but `requests.Session` itself is not guaranteed thread-safe.
- Permissions: reads need read access; writes need Contribute or higher. Insufficient permissions raise `AuthError`.

## Contributing

This is a pet project to save me time at work and not open for contribution.

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/B-Jones-RFD/sppyte/tags) and the [CHANGELOG](CHANGELOG.md).

## Authors

- **B Jones RFD** - _Package Noob_ - [B-Jones-RFD](https://github.com/B-Jones-RFD)

## License

[MIT License](https://github.com/B-Jones-RFD/sppyte/blob/main/LICENSE)

[^1]: What's the deal with this name? <sub>(S)hare(P)oint</sub> <sup>(Py)thon</sup> <sub>Si(te)</sub>
