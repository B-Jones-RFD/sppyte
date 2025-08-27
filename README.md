[![PyPI - Version](https://img.shields.io/pypi/v/init.svg)](https://pypi.org/project/sppyte)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/init.svg)](https://pypi.org/project/sppyte)

# Sppyte

A tiny, explicit Python helper for working with legacy **SharePoint REST** endpoints using and **NTLM** authentication. Sppyte keeps a very thin abstraction so you can reason about the underlying HTTP calls without surprises.

> ⚠️ This client uses **NTLM** (`requests-ntlm`) and is thus best suited for **SharePoint on-prem** or environments where NTLM is configured. SharePoint Online typically uses different auth flows.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [API Overview](#quickstart)
- [Notes](#notes)
- [License](#license)

## Features

- Simple `Site` connection with NTLM auth and automatic **form digest** retrieval.
- `List` helper for:
  - Add / update (MERGE) / delete items
  - Use OData params to control item responses
  - Add **attachments** to items
- `Library` helper for:
  - Add / delete **folders**
  - Upload / download / delete **documents**
  - List folder contents and control output with OData params
- Small, readable codebase with explicit error types.

## Installation

```console
pip install sppyte
```

## Quickstart

```py
from sppyte import Site

HOST = "https://sharepoint.example.com"
SITE = "sites/Engineering"       # relative path
USER = "EXAMPLE\\alice"          # or alice@example.com depending on your setup
PASS = "••••••••"

with Site(HOST, SITE, USER, PASS) as sp:
    # ---------------- Lists ----------------
    tasks = sp.list("Tasks")

    # Add an item (metadata type is auto-inferred if omitted)
    new_id = tasks.add_item({"Title": "Ship Sppyte"})
    print("Created item:", new_id)

    # Update (MERGE) the item
    tasks.update_item(new_id, {"Title": "Ship Sppyte v1"})

    # Attach a file
    with open("notes.txt", "rb") as fh:
        tasks.add_attachment(new_id, "notes.txt", fh)

    # Fetch one item
    item = tasks.get_item(new_id)

    # Query contents (use any OData params you need)
    res = tasks.get_contents(**{
        "$select": "Id,Title,Created",
        "$top": 5,
        "$orderby": "Created desc",
    })
    print(res)

    # Delete the item
    tasks.delete_item(new_id)

    # --------------- Libraries -------------
    docs = sp.library("Shared Documents")

    # Ensure a nested folder path exists
    docs.add_folder("Reports", "2025")

    # Upload a document
    with open("report.pdf", "rb") as fh:
        unique_id = docs.add_document("report.pdf", fh, "Reports", "2025")
        print("Uploaded doc UniqueId:", unique_id)

    # List files in folder
    files = docs.list_contents("Reports", "2025", **{"$select": "Name,TimeCreated"})
    print(files)

    # Download a document (bytes)
    pdf_bytes = docs.get_document("report.pdf", "Reports", "2025")

    # Delete a document
    docs.delete_document("report.pdf", "Reports", "2025")
```

## API Overview

Site

- Site(host, site_relative_url, username, password)
- request(method, path, \*\*kwargs) -> requests.Response
- get_form_digest() -> str
- connect(), close()
- list(name) -> List
- library(name) -> Library

List

- add_item(item: dict) -> int
- add_attachment(sp_id: int, file_name: str, attachment: bytes | IO[bytes]) -> int
- delete_item(sp_id: int) -> bool
- get_contents(\*\*params) -> dict
- get_item_type() -> str
- get_item(sp_id: int) -> dict
- update_item(sp_id: int, patch: dict) -> int

Library

- add_folder(folder: str, \*subfolders: str) -> bool
- add_document(file_name: str, document: IO[bytes], \*subfolders: str) -> str
- folder_exists(folder: str, \*subfolders: str) -> bool
- delete_document(file_name: str, \*subfolders: str) -> bool
- delete_folder(folder: str, \*subfolders: str) -> bool
- list_contents(\*folders: str, \*\*params) -> list[dict]
- get_document(file_name: str, \*folders: str) -> bytes

Errors

- SessionError: raised when an HTTP session isn’t available.
- ResponseFormatError: raised when an expected JSON field is missing
  (e.g., FormDigestValue, ListItemEntityTypeFullName, ID, UniqueId).
- Raised requests library errors are passed through for HTTP requests

Handle them as you would any exception:

```py
from sppyte import ResponseFormatError, SessionError

try:
    ...
except (ResponseFormatError, SessionError) as e:
    print("Sppyte error:", e)
```

## Notes

- OData Parameters: Methods like get_contents and list_contents accept any OData
  parameters via \*\*params (e.g., $select, $filter, $orderby, $top).

## License

`sppyte` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
