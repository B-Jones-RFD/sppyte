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

Creating a `Site` performs no network I/O; the HTTP session is created on the first request. Malformed options raise [`ConfigurationError`][sppyte.errors.ConfigurationError] immediately, naming the option and the value it got: a path inside `host`, a `site_relative_url` without a leading `/` or given as a full URL, a missing NTLM username or password, or an invalid `timeout`, `verify`, `cert`, `session` or `retry`.

A `Site` owns the HTTP session. Use it as a context manager to connect eagerly (which also verifies the credentials) and close the session afterwards, or call `connect()` / `close()` yourself:

```python
site = Site(HOST, SITE, USER, PASSWORD, domain="CONTOSO")
try:
    site.connect()  # optional: authenticate and fetch the first form digest now
    ...
finally:
    site.close()
```

`site.list(name)` and `site.library(name)` return lightweight [`List`][sppyte.lists.List] and [`Library`][sppyte.libraries.Library] helpers bound to the site. They perform no I/O and hold no resources of their own.

## Authentication

sppyte speaks NTLM and Negotiate (SPNEGO / Kerberos) through [pyspnego](https://pypi.org/project/pyspnego/); see [`SpPremAuth`][sppyte.auth.SpPremAuth]. The handshake authenticates the TCP connection, so it runs once per pooled connection and later requests on that connection are already authenticated.

```python
Site(HOST, SITE, "jsmith", PASSWORD, domain="CONTOSO")                        # NTLM (default)
Site(HOST, SITE, "jsmith", PASSWORD, domain="CONTOSO", protocol="negotiate")  # Kerberos if possible, else NTLM
Site(HOST, SITE, protocol="negotiate")                                        # single sign-on
Site(HOST, SITE, auth=my_requests_auth_handler)                               # any requests AuthBase
```

- `protocol="ntlm"` requires `username` and `password`.
- `protocol="negotiate"` or `"kerberos"` works without credentials on a domain-joined machine (SSPI on Windows, a `kinit` ticket elsewhere); pass credentials to authenticate as someone else.
- Kerberos on Linux/macOS needs the system GSSAPI libraries and `pip install "sppyte[kerberos]"`; Windows uses SSPI.
- Over HTTPS, TLS channel bindings are sent automatically for servers with Extended Protection.
- Credentials go only to the configured host: a 401 challenge from another host, reached through a redirect, is returned unanswered.
- `SpPremAuth` is a plain `requests` auth handler, usable on your own `Session` too. Bad arguments (an unknown `protocol`, NTLM without a username and password) raise `ConfigurationError`.

## Write operations and the request digest

SharePoint requires a form digest (`X-RequestDigest`) on every write. sppyte manages it:

- fetched from `/_api/contextinfo` on the first write (or on `connect()`),
- cached until a minute before SharePoint says it expires (30 minutes by default),
- shared between threads using the same `Site` (one fetch at a time),
- and, if SharePoint still rejects it with **403**, refreshed and the write **retried once**, provided the body can be re-sent: JSON, bytes, a string, or a seekable file, including every file passed with `files=`. A non-seekable stream is not retried and the `AuthError` propagates.

Pass `digest=` to any write method to send your own value as-is, with no retry:

```python
digest = site.get_form_digest()  # always fetches a fresh one, and caches it
pets.add_item({"Title": "x"}, digest=digest)
```

[`site.digest()`][sppyte.site.Site.digest] returns the cached digest, fetching or refreshing it as needed (`refresh=True` forces a fetch). [`site.invalidate_digest()`][sppyte.site.Site.invalidate_digest] drops it so the next write fetches a fresh one. `site.form_digest` is the cached value, or `None`.

## Paging

SharePoint caps a collection response (100 list items by default, or `$top`) and points at the rest with `odata.nextLink`. `get_contents`, `list_contents` and `list_folders` return a [`Page`][sppyte.odata.Page]: a plain `list` with a `next_link` attribute. Follow it yourself with [`Site.get_page`][sppyte.site.Site.get_page]:

```python
page = tasks.get_contents({"$top": 500})
while page.next_link:
    page = site.get_page(page.next_link)
```

Usually you want the helpers that do this for you:

| | one page | every page, lazily | every page, collected |
|---|---|---|---|
| `List` | `get_contents(params)` | `iter_items(params)` / `iter_pages(params)` | `get_all_items(params)` |
| `Library` | `list_contents(*subfolders, params=)` | `iter_files(...)` / `iter_pages(...)` | `get_all_files(...)` |

All accept `max_pages=` to stop early. The `iter_*` helpers are lazy: no request is sent until you start iterating, so errors are raised on the first iteration rather than at the call, and each further page is one request as you consume it. `Site.get_page` refuses a link that is not on the site's host with `ConfigurationError`, so credentials are never sent elsewhere.

`$filter` on a non-indexed column fails on lists above the 5,000-item view threshold regardless of paging; use a [CAML query](#caml-queries-and-the-5000-item-threshold) for those.

## Working with lists

`site.list(name)` takes the list **title** as shown in SharePoint. Item IDs are SharePoint's integer `Id`.

```python
pets = site.list("Pets")

created = pets.add_item({"Title": "Norwegian Blue"})  # the new item, as SharePoint returned it
new_id = created["Id"]

pets.update_item(new_id, {"Title": "Polly"})           # MERGE: omitted fields are untouched
item = pets.get_item(new_id)                            # one item, as a dict

with open("notes.txt", "rb") as fh:
    attachment = pets.add_attachment(new_id, "notes.txt", fh)
print(attachment["ServerRelativeUrl"])

pets.delete_item(new_id)
```

- [`add_item`][sppyte.lists.List.add_item] returns the created item, including `Id`; a response without an integer `Id` raises `ResponseFormatError`.
- [`update_item`][sppyte.lists.List.update_item] sends a `MERGE` with `If-Match: *` and returns the `sp_id` you passed.
- [`delete_item`][sppyte.lists.List.delete_item] returns `True`; failures raise.
- [`get_item`][sppyte.lists.List.get_item] returns the item as a `dict`.
- [`add_attachment`][sppyte.lists.List.add_attachment] takes `bytes` or a binary file object and returns the `SP.Attachment` SharePoint created (`FileName`, `ServerRelativeUrl`).

### Item type and `__metadata`

SharePoint needs the list's entity type in `__metadata.type` on every item payload. `add_item` and `update_item` add it for you unless your mapping already has `__metadata`, and never modify the mapping you pass. The value comes from [`item_type`][sppyte.lists.List.item_type] (the list's `ListItemEntityTypeFullName`, e.g. `SP.Data.PetsListItem`), fetched once per `List` object and cached; concurrent callers share one fetch. `get_item_type()` fetches it again and refreshes the cache. Use `item_type` yourself when you build payloads for [`Site.request`](#extension-requests) or a [batch](#batching-requests).

### OData parameters

The read methods take `params`: a mapping (or sequence of pairs) of OData query options such as `$select`, `$filter`, `$orderby`, `$top` and `$expand`. See Microsoft's [OData query operators](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service).

```python
recent = pets.get_contents({
    "$select": "Id,Title,Created",
    "$filter": "Status eq 'Open'",
    "$orderby": "Created desc",
    "$top": 5,
})
```

## Working with libraries

`site.library(name)` takes the library name as it appears in its URL, e.g. `"Shared Documents"`. Folder arguments are path segments beneath the library: `("Reports", "2025")` addresses `Shared Documents/Reports/2025`, and no segments means the library root.

### Folders

```python
docs = site.library("Shared Documents")

docs.add_folder("Reports")
docs.add_folder("Reports", "2025")            # the parent must already exist

docs.folder_exists("Reports", "2025")         # True
docs.list_folders("Reports")                  # a Page of SP.Folder objects
docs.delete_folder("Reports", "2025")         # True; failures raise
```

- [`add_folder`][sppyte.libraries.Library.add_folder] creates one folder whose parent must exist, and returns the `SP.Folder` (`Name`, `ServerRelativeUrl`, `UniqueId`, `Exists`, ...). Creating a folder that already exists is not an error.
- [`folder_exists`][sppyte.libraries.Library.folder_exists] returns `False` for a missing folder rather than raising.
- [`list_folders`][sppyte.libraries.Library.list_folders] returns the folders directly inside a folder (`Name`, `ServerRelativeUrl`, `ItemCount`, ...), one [page](#paging) at a time, and takes `params=`.
- [`delete_folder`][sppyte.libraries.Library.delete_folder] returns `True`; failures raise.

### Uploading

[`add_document(file_name, document, *subfolders, overwrite=True)`][sppyte.libraries.Library.add_document] takes a path (opened and streamed for you), an open binary file object (streamed), or `bytes`, and returns the `SP.File` SharePoint created (`Name`, `ServerRelativeUrl`, `UniqueId`, `Length`, ...).

```python
uploaded = docs.add_document("report.pdf", "local/report.pdf", "Reports", "2025")
print(uploaded["ServerRelativeUrl"], uploaded["UniqueId"])

with open("local/notes.txt", "rb") as fh:
    docs.add_document("notes.txt", fh, "Reports")

docs.add_document("hello.txt", b"hello", overwrite=False)
```

By default an existing file with the same name is replaced. With `overwrite=False`, SharePoint answers 400 and the call raises `SharePointError` if the file exists.

### Listing files

[`list_contents(*subfolders, params=None)`][sppyte.libraries.Library.list_contents] returns the files directly inside a folder (not its subfolders) as a [page](#paging) of `SP.File` objects (`Name`, `ServerRelativeUrl`, `Length`, `TimeLastModified`, ...). `params` is keyword-only. `iter_files` and `get_all_files` follow the pages for you.

```python
root_files = docs.list_contents(params={"$select": "Name,TimeCreated"})
report_files = docs.list_contents("Reports", "2025", params={"$select": "Name"})
for f in docs.iter_files("Reports", params={"$select": "Name,Length"}):
    print(f["Name"], f["Length"])
```

### Downloading

```python
data = docs.get_document("report.pdf", "Reports", "2025")             # bytes, in memory

written = docs.download("report.pdf", "~/report.pdf", "Reports", "2025")  # path or binary file

with open("out.bin", "wb") as fh:
    for chunk in docs.iter_document("big.bin", "Exports"):
        fh.write(chunk)
```

[`get_document`][sppyte.libraries.Library.get_document] reads the whole file into memory. For large files use [`iter_document`][sppyte.libraries.Library.iter_document] or [`download`][sppyte.libraries.Library.download]; see [Large files](#large-files).

### Deleting

```python
docs.delete_document("report.pdf", "Reports", "2025")  # True; failures raise
```

[`delete_document`][sppyte.libraries.Library.delete_document] deletes one file by name.

## CAML queries and the 5,000-item threshold

`$filter` on a non-indexed column fails on lists above the 5,000-item view threshold. [`List.query`][sppyte.lists.List.query] posts a CAML `<View>` to `GetItems`; a `<Where>` on an **indexed** column is evaluated by SQL Server and works far above the threshold. `$select` and `$expand` still go in `params`; `$filter` and `$top` belong in the CAML (`<Where>`, `<RowLimit>`).

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

page = tasks.query(view, params={"$select": "Id,Title"})                    # first 500
page = tasks.query(view, paging_info=f"Paged=TRUE&p_ID={page[-1]['Id']}")  # next 500

for task in tasks.iter_query(view, params={"$select": "Id,Title"}):         # all of them
    ...
everything = tasks.query_all(view)
```

`iter_query` / `query_all` require a `<RowLimit>` (without one they raise `ConfigurationError`) and page by the `Id` of the last item returned, which assumes the view is ordered by ID ascending (the default). Keep `Id` in `$select` if you restrict columns; a page whose last item has no integer `Id` raises `ResponseFormatError`.

## Batching requests

[`Site.batch()`][sppyte.site.Site.batch] collects sub-requests and sends them as one `POST /_api/$batch` (SharePoint 2016+ and Subscription Edition; not 2013). Consecutive writes are grouped into one changeset, which SharePoint applies atomically; reads are separate parts. A failing sub-request does **not** fail the batch: check `ok` on each [`BatchResponse`][sppyte.batch.BatchResponse].

```python
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

Paths are site-relative (`_api/...`) or absolute URLs on the site's host. Defaults per part are `Accept: application/json;odata=nometadata`, `Content-Type: application/json;odata=verbose` when there is a body, and `If-Match: *` for `MERGE` / `PATCH` / `DELETE`; pass `headers=` to override. [`Batch.add`][sppyte.batch.Batch.add] raises `ConfigurationError` if you pass both `json` and `body`, or an absolute URL on another host. An empty batch returns `[]` without a request.

## Large files

Uploads stream: pass a path (opened for you), an open binary file object, or `bytes`. If the managed digest has to be refreshed mid-upload, a path or seekable file is re-sent from the start; a non-seekable stream cannot be, and the `AuthError` propagates.

Downloads: `get_document` returns `bytes`. For anything big use [`iter_document`][sppyte.libraries.Library.iter_document], a generator of chunks, or [`download`][sppyte.libraries.Library.download], which writes to a path or an open binary file object and returns the number of bytes written. Both take `chunk_size=` (64 KiB by default).

```python
docs.download("backup.iso", "/mnt/backups/backup.iso", "ISOs", chunk_size=1 << 20)
```

- HTTP errors are raised before the first chunk.
- `download` sends the request and checks its status before it opens the destination, so an HTTP error leaves an existing file untouched and creates no new one. A failure while the body is streaming, such as a dropped connection, may leave a partial file.
- A destination path has `~` expanded and is created or overwritten. A file object is written at its current position and left open.

## Errors

```
SppyteError
├── ConfigurationError   (also a ValueError)
├── SessionError         (deprecated; no longer raised)
├── ResponseFormatError
└── SharePointError      (also a requests.HTTPError)
    └── AuthError        (401 / 403)
```

- [`ConfigurationError`][sppyte.errors.ConfigurationError]: a malformed option or argument, raised before any request. That covers bad `Site` options, bad `SpPremAuth` arguments, a CAML view without `<RowLimit>` passed to `List.iter_query`, conflicting or off-host arguments to `Batch.add`, and a `next_link` passed to `Site.get_page` that is not on the site's host.
- [`ResponseFormatError`][sppyte.errors.ResponseFormatError]: SharePoint answered 2xx, but the body is not JSON (for example an HTML login page from a proxy), is not in the expected shape, or lacks an expected field (an item `Id`, a non-empty form digest or list item type). A `$batch` response that is not multipart or has the wrong number of parts raises it too.
- [`SharePointError`][sppyte.errors.SharePointError]: any 4xx/5xx. [`AuthError`][sppyte.errors.AuthError] is the subclass for 401 and 403: bad credentials, a rejected handshake, missing permissions, or a digest still rejected after the refresh. A handshake that cannot complete also raises `AuthError` for the 401 (or a proxy's 407) it was answering: a malformed or non-base64 challenge from the server, or Kerberos single sign-on without a ticket. Its message reads `HTTP 401: Unauthorized: NTLM handshake failed: ...`, and the original pyspnego (or `binascii`) error is its `__cause__`.
- `SessionError` is kept for compatibility with 0.x and is no longer raised. Accessing it emits a `DeprecationWarning`; it will be removed in 2.0.

`SharePointError` parses the SharePoint error body, so `str(e)` reads `HTTP 400: Column 'Foo' does not exist` instead of `400 Client Error: Bad Request for url: ...`. It exposes:

| attribute | |
|---|---|
| `status` | HTTP status code |
| `code` | SharePoint error code, e.g. `-2130575338, Microsoft.SharePoint.SPException` |
| `message` | SharePoint's message |
| `retry_after` | seconds from a `Retry-After` header, or `None` |
| `response` | the underlying `requests.Response` |

```python
import time

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

Because `SharePointError` subclasses `requests.HTTPError`, `except HTTPError` handlers catch it. Transport failures (DNS, connection refused, timeouts) are raised by `requests` as `requests.ConnectionError` / `requests.Timeout`.

## Retrying transient failures

Off by default. `Site(..., retry=True)` retries **reads** (`GET` requests, including `get_page` and the `iter_*` helpers, and CAML `query`) that fail with a connection error, a timeout, or HTTP 429 / 502 / 503 / 504. Writes and `$batch` are never retried. Delays use exponential backoff with full jitter, `random(0, min(max_delay, base_delay * 2**attempt))`. When SharePoint sends `Retry-After`, that wait is used instead; if it exceeds `max_delay`, the error is raised immediately so you can decide.

Tune with [`RetryOptions`][sppyte.retry.RetryOptions]. `retry_on` receives the exception and the 1-based attempt number; the default is [`is_transient`][sppyte.retry.is_transient].

```python
from sppyte import RetryOptions, Site, is_transient

site = Site(HOST, SITE, USER, PASSWORD, retry=True)  # 2 retries, 0.2 s base, 5 s cap
site = Site(HOST, SITE, USER, PASSWORD, retry=RetryOptions(retries=4, base_delay=0.5, max_delay=20))
site = Site(HOST, SITE, USER, PASSWORD, retry=RetryOptions(retry_on=lambda exc, n: is_transient(exc) and n <= 3))
```

On a single call, `site.request(..., retry=False)` opts a read out of the policy and `retry=True` opts an idempotent `POST` in. It has no effect unless the `Site` was created with `retry`.

## Timeouts, TLS and proxies

- `timeout` (default 30 s) applies to every request; a `(connect, read)` tuple is accepted; `None` disables it (not recommended). Individual `site.request(...)` calls can override it.
- `verify` is forwarded to `requests`: `False` to skip TLS verification, or a path to a CA bundle for an internal certificate authority.
- `cert` is forwarded to `requests` for client certificates: a path, or a `(cert, key)` pair of paths.
- `session` lets you supply your own `requests.Session` (proxies, adapters). sppyte attaches its `SpPremAuth` handler only if the session has no `auth`, and never closes it.
- `Site` checks these when it is created: a `timeout` that is not `None`, a positive number or a pair of positive numbers, a `verify` that is not `None`, a `bool` or a `str`, a `cert` that is not `None`, a `str` or a pair of `str`, a `session` that is not a `requests.Session`, or a `retry` that is not `None`, a `bool` or a `RetryOptions` raises `ConfigurationError`.

```python
site = Site(HOST, SITE, USER, PASSWORD, verify="/etc/pki/corp-root-ca.pem", timeout=(5, 120))
```

Set proxy credentials on the `requests.Session` you pass to `Site`. `SpPremAuth` answers a proxy's `407` with the SharePoint credentials, but that is deprecated: it emits a `DeprecationWarning` and will be removed in 2.0.

## Special characters

List titles, folder names and file names are escaped for OData string literals automatically, so names containing spaces, `'`, `#`, `%`, `?` or `&` work as-is. See [`odata_literal`][sppyte.odata.odata_literal] and [`odata_path`][sppyte.odata.odata_path] if you build your own paths.

## Extension requests

Endpoints not wrapped by sppyte are reachable through [`Site.request(method, path, **kwargs)`][sppyte.site.Site.request]. It uses the site's session, applies the default `timeout`, raises `SharePointError` / `AuthError` for non-2xx, and takes a **site-relative** path instead of a full URL. Pass `digest=True` for writes to get the managed digest (with the 403 refresh-and-retry), or `digest="..."` to send a specific one. Other keyword arguments go to `requests.Session.request`.

```python
r = site.request("get", "_api/web/lists", headers={"Accept": "application/json;odata=nometadata"})
lists = r.json()["value"]

site.request(
    "post",
    "_api/web/lists/GetByTitle('Pets')/recycle",
    headers={"Accept": "application/json;odata=nometadata"},
    digest=True,
)
```

[`List.path`][sppyte.lists.List.path], [`Library.folder_path`][sppyte.libraries.Library.folder_path] and [`Library.file_path`][sppyte.libraries.Library.file_path] give you escaped paths to build on, and [`List.item_type`][sppyte.lists.List.item_type] the entity type for `__metadata.type` in list-item payloads.

## Notes

- **Threads.** One `Site` per thread is simplest. Sharing one across threads is supported for the session set-up, the digest cache and the list item-type lookup, but `requests.Session` itself is not guaranteed thread-safe.
- **Permissions.** Reads need read access to the list or library; writes need Contribute or higher. Insufficient permissions raise `AuthError`.
- **Page size.** SharePoint returns at most 100 list items per page unless you pass `$top`; see [Paging](#paging).
