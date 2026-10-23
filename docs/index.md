# sppyte

A tiny, explicit Python helper for working with a SharePoint site through the legacy **SharePoint REST** endpoints with **NTLM** or **Kerberos** (Negotiate) authentication. It keeps a very thin abstraction so you can reason about the underlying HTTP calls without surprises.

!!! warning "On-premises only"
    sppyte targets **SharePoint on-premises** (2013, 2016, 2019, Subscription Edition). SharePoint Online does not accept NTLM or Kerberos.

## Installation

```console
pip install sppyte
```

Python 3.10 or later. Runtime dependencies: `requests`, `pyspnego` and `cryptography`. Add `sppyte[kerberos]` for Kerberos on Linux/macOS.

## Quickstart

```python
from sppyte import Site

with Site("https://sharepoint.example.com", "/sites/parrots", "jsmith", PASSWORD, domain="CONTOSO") as site:
    pets = site.list("Pets")

    created = pets.add_item({"Title": "Norwegian Blue"})
    pets.update_item(created["Id"], {"Title": "Polly"})

    for item in pets.iter_items({"$select": "Id,Title", "$top": 500}):
        print(item["Title"])

    docs = site.library("Shared Documents")
    docs.add_folder("Reports", "2025")
    docs.add_document("report.pdf", "local/report.pdf", "Reports", "2025")
    docs.download("report.pdf", "local/copy.pdf", "Reports", "2025")
```

## What you get

| | |
|---|---|
| `Site` | NTLM or Kerberos session, argument validation, timeouts, TLS options, a managed form digest that is cached, refreshed and retried once on 403, and opt-in retry of transient read failures. |
| `List` | Add / update / delete items, attachments, OData reads with paging, CAML queries for lists above the 5,000-item threshold. |
| `Library` | Folders, uploads from bytes / file objects / paths, streamed downloads, listing files and folders with paging. |
| `Batch` | Several REST calls in one `/_api/$batch` round trip, writes grouped into a changeset. |
| Errors | `SharePointError` / `AuthError` carry SharePoint's own message, status and `Retry-After`, and still subclass `requests.HTTPError`. |

Continue with the [guide](guide.md) or jump to the [API reference](api/site.md).
