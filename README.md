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
  - [Errors](#errors)
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
  - Use [OData](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service) params to control item responses
  - Add **attachments** to items
- `Library` helper to:
  - Add / delete **folders**
  - Upload / download / delete **documents**
  - List folder contents and control output with [OData](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service) params
- Exceptions that carry SharePoint's own error message, status code and `Retry-After`.
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
    created = pets.add_item({"Title": "Norwegian Blue"})
    new_id = created["Id"]

    # Update the item (uses MERGE)
    pets.update_item(new_id, {"Title": "Polly"})

    # Attach a file
    with open("notes.txt", "rb") as file_handle:
        pets.add_attachment(new_id, "notes.txt", file_handle)

    # Fetch one item
    item = pets.get_item(new_id)

    # Query contents (use any OData params you need)
    items = pets.get_contents({
        "$select": "Id,Title,Created",
        "$top": 5,
        "$orderby": "Created desc",
    })

    # Delete the item
    pets.delete_item(new_id)

    # --------------- Libraries -------------
    shared_docs = site.library("Shared Documents")

    # Ensure a nested folder path exists
    shared_docs.add_folder("Napping", "2025")

    # Upload a document
    with open("report.pdf", "rb") as file_handle:
        unique_id = shared_docs.add_document("report.pdf", file_handle, "Napping", "2025")

    # List files in the library root, and in a subfolder
    files = shared_docs.list_contents(params={"$select": "Name,TimeCreated"})
    folder_files = shared_docs.list_contents("Napping", "2025", params={"$select": "Name"})

    # Download a document (bytes)
    report = shared_docs.get_document("report.pdf", "Napping", "2025")

    # Delete a document
    shared_docs.delete_document("report.pdf", "Napping", "2025")
```

## Usage

### Connecting

`Site(host, site_relative_url, username, password, *, domain=None, timeout=30.0, verify=None, cert=None, session=None)`

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

#### `Site(host, site_relative_url, username, password, *, domain=None, timeout=30.0, verify=None, cert=None, session=None)`

See [Connecting](#connecting) and [Timeouts, TLS and proxies](#timeouts-tls-and-proxies). Raises `ConfigurationError` for malformed options.

| member | |
|---|---|
| `connect()` | Create the session and fetch a form digest now. |
| `close()` | Forget the digest and close the session (if sppyte created it). |
| `list(name)` | A `List` bound to this site. No I/O. |
| `library(name)` | A `Library` bound to this site. No I/O. |
| `request(method, path, *, digest=None, **kwargs)` | Low-level request; see [Extension requests](#extension-requests). |
| `digest(*, refresh=False)` | The managed form digest, fetching/refreshing as needed. |
| `get_form_digest()` | Always fetch a fresh digest (and cache it). |
| `invalidate_digest()` | Drop the cached digest. |
| `form_digest` | The cached digest, or `None`. |
| `session` | The `requests.Session`, or `None` before first use. |
| `site_path`, `host`, `relative_url`, `principal` | Normalised connection details (`principal` is `DOMAIN\user`). |

### List

Obtain with `site.list(name)` (or `List(name, site)`). `name` is the list **title** as shown in SharePoint.

| member | returns | |
|---|---|---|
| `get_contents(params=None)` | `list[dict]` | Items; at most 100 unless `$top` is given. |
| `get_item(sp_id)` | `dict` | One item by ID. |
| `add_item(item, *, digest=None)` | `dict` | The created item as SharePoint returned it, including `Id`. `__metadata.type` is added unless present; `item` is not modified. |
| `update_item(sp_id, patch, *, digest=None)` | `int` | MERGE-update; omitted fields are untouched. Returns `sp_id`. |
| `delete_item(sp_id, *, digest=None)` | `bool` | `True`; failures raise. |
| `add_attachment(sp_id, file_name, attachment, *, digest=None)` | `int` | `attachment` is `bytes` or a binary file object. Returns `sp_id`. |
| `item_type` | `str` | `ListItemEntityTypeFullName`, fetched once and cached. |
| `get_item_type()` | `str` | Fetch it again and refresh the cache. |

`params` is a mapping (or sequence of pairs) of OData options, e.g. `{"$select": "Id,Title", "$filter": "Status eq 'Open'", "$top": 500}`.

### Library

Obtain with `site.library(name)` (or `Library(name, site)`). Folder arguments are path segments beneath the library: `("Reports", "2025")` addresses `Shared Documents/Reports/2025`.

| member | returns | |
|---|---|---|
| `list_contents(*subfolders, params=None)` | `list[dict]` | Files directly in the folder (`SP.File` objects: `Name`, `ServerRelativeUrl`, `Length`, …). |
| `get_document(file_name, *subfolders)` | `bytes` | Download into memory. |
| `folder_exists(folder, *subfolders)` | `bool` | Missing folder is `False`, not an error. |
| `add_folder(folder, *subfolders, digest=None)` | `bool` | Create a folder (parent must exist). |
| `add_document(file_name, document, *subfolders, digest=None)` | `str` | Upload (overwrites); returns `UniqueId`. `document` is `bytes` or a binary file object (streamed). |
| `delete_document(file_name, *subfolders, digest=None)` | `bool` | |
| `delete_folder(folder, *subfolders, digest=None)` | `bool` | |
| `server_relative_url(*parts)` | `str` | e.g. `/sites/parrots/Shared Documents/Reports`. |

## Migrating to 1.0

- **`List.add_item` returns the created item (`dict`) instead of the ID.** Replace `new_id = pets.add_item(...)` with `new_id = pets.add_item(...)["Id"]`.
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
