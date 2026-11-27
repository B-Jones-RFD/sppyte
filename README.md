![GitHub Actions CI](https://github.com/B-Jones-RFD/sppyte/actions/workflows/CI.yml/badge.svg)
![PyPI - License](https://img.shields.io/pypi/l/sppyte)
[![PyPI - Version](https://img.shields.io/pypi/v/sppyte.svg)](https://pypi.org/project/sppyte)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/sppyte)](https://pypi.org/project/sppyte)
[![Supported Versions](https://img.shields.io/pypi/pyversions/sppyte.svg)](https://pypi.org/project/sppyte)

# Sppyte

A tiny, explicit Python helper for working with a SharePoint site through the legacy **SharePoint REST** endpoints with **NTLM** or **Kerberos** (Negotiate) authentication. Sppyte[^1] keeps a very thin abstraction so you can reason about the underlying HTTP calls without surprises.

> ⚠️ This client is for **SharePoint on-premises** (2013, 2016, 2019, Subscription Edition). SharePoint Online does not accept NTLM or Kerberos.

Full documentation, including the API reference, is at **<https://b-jones-rfd.github.io/sppyte/>**.

## Features

- `Site` connection with NTLM or Kerberos single sign-on (via [pyspnego](https://pypi.org/project/pyspnego/)), lazy session creation and a **managed form digest** (fetched, cached, refreshed before expiry, and retried once if SharePoint rejects it).
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

## Requirements

- Python 3.11 or later.
- SharePoint on-premises 2013, 2016, 2019 or Subscription Edition (`$batch` needs 2016 or later). SharePoint Online is not supported.
- Runtime dependencies: `requests` (HTTP), `pyspnego` (NTLM and Kerberos authentication) and `cryptography` (TLS channel bindings).
- Optional extra: `kerberos`, for Kerberos on Linux or macOS together with the system GSSAPI libraries. Windows uses the built-in SSPI and needs no extra.

## Installation

```console
pip install sppyte
```

For Kerberos on Linux or macOS, install the system GSSAPI libraries (`libkrb5-dev` / `krb5`) and the extra:

```console
pip install "sppyte[kerberos]"
```

Windows uses the built-in SSPI; nothing extra is needed.

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

## Documentation

- [Guide](https://b-jones-rfd.github.io/sppyte/guide/)
- [Home and API reference](https://b-jones-rfd.github.io/sppyte/)
- [Migrating](https://b-jones-rfd.github.io/sppyte/migrating/)
- [Changelog](CHANGELOG.md)

## Contributing

This is a personal project and is not open to contributions. Bug reports are welcome as [GitHub issues](https://github.com/B-Jones-RFD/sppyte/issues). Please report security problems privately, as described in [SECURITY.md](SECURITY.md).

## Versioning

This project uses [Semantic Versioning](https://semver.org/). See the [tags on this repository](https://github.com/B-Jones-RFD/sppyte/tags) and the [CHANGELOG](CHANGELOG.md) for the versions available.

## License

[MIT License](https://github.com/B-Jones-RFD/sppyte/blob/main/LICENSE)

[^1]: What's the deal with this name? <sub>(S)hare(P)oint</sub> <sup>(Py)thon</sup> <sub>Si(te)</sub>
