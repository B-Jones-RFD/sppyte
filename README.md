![GitHub Actions CI](https://github.com/B-Jones-RFD/sppyte/actions/workflows/CI.yml/badge.svg)
![PyPI - License](https://img.shields.io/pypi/l/sppyte)
[![PyPI - Version](https://img.shields.io/pypi/v/sppyte.svg)](https://pypi.org/project/sppyte)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/sppyte)](https://pypi.org/project/sppyte)
[![Supported Versions](https://img.shields.io/pypi/pyversions/sppyte.svg)](https://pypi.org/project/sppyte)

# Sppyte

A tiny, explicit Python helper for working with legacy **SharePoint REST** endpoints using and **NTLM** authentication. Sppyte keeps a very thin abstraction so you can reason about the underlying HTTP calls without surprises.

> ⚠️ This client uses **NTLM** (`requests-ntlm`) and is best suited for **SharePoint on-prem** or environments where NTLM is configured. SharePoint Online typically uses different auth flows.

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

## Installation

```console
pip install sppyte
```

## Quickstart

```py
from sppyte import Site

HOST = "https://sharepoint.example.com"
SITE = "/sites/parrots" # relative path
USER = "norweigian"
PASS = "••••••••"

with Site(HOST, SITE, USER, PASS) as site:
    # ---------------- Lists ----------------
    pets = site.list("Pets")

    # Add an item (metadata type is auto-inferred if omitted)
    new_id = pets.add_item({"Title": "Norweigian Blue"})
    print("Created item:", new_id)

    # Update (MERGE) the item
    pets.update_item(new_id, {"Title": "Polly"})

    # Attach a file
    with open("notes.txt", "rb") as file_handle:
        pets.add_attachment(new_id, "notes.txt", file_handle)

    # Fetch one item
    item = pets.get_item(new_id)

    # Query contents (use any OData params you need)
    r = pets.get_contents({
        "$select": "Id,Title,Created",
        "$top": 5,
        "$orderby": "Created desc",
    })

    # Delete the item
    pets.delete_item(new_id)

    # --------------- Libraries -------------
    docs = site.library("Shared Documents")

    # Ensure a nested folder path exists
    docs.add_folder("Napping", "2025")

    # Upload a document
    with open("report.pdf", "rb") as file_handle:
        unique_id = docs.add_document("report.txt", file_handle, "Napping", "2025")
        print("Uploaded doc UniqueId:", unique_id)

    # List files in folder
    files = docs.list_contents({"$select": "Name,TimeCreated"}, "Napping", "2025")

    # Download a document
    document = docs.get_document("report.txt", "Napping", "2025")
    contents = document.decode()

    # Delete a document
    docs.delete_document("report.txt", "Napping", "2025")
```

## API Overview

### Site

Models a session connected to a SharePoint site.

#### sppyte.Site(host, site, username, password)

Initiate a SharePoint site session.

**Parameters**
- __host__: str - SharePoint site host (protocol://domain)
- __site__: str - SharePoint site relative url
- __username__: str - SharePoint site username
- __password__: str - SharePoint site password

**Returns:**
__Site__ object

*Usage:*

```py
from sppyte import Site

HOST = "https://sharepoint.example.com"
SITE = "/sites/Parrots" # relative path
USER = "norweigen"
PASS = "••••••••"

site = Site(HOST, SITE, USER, PASS)
try:
  connection.connect() # Start session
  # Do cool stuff
except HTTPError as e:
  # Deal with errors
finally:
  connection.close() # Close session

# With context managment is preferred
with Site(HOST, SITE, USER, PASS) as connection:
  # Do cool stuff
```
**Notes**
- User should have permissions to the site, library, or list to be accessed. Updates require contribute or higher level access.
- Unauthorized user will return an `HTTPError` Unauthorized (401) exception
- For user managed connections, call the `close` method to end the session

#### Site.connect()

Start a connected session.

#### Site.close()

Close connected session.

#### Site.list(name)

Get a List class instance.

**Parameters**
- __name__: str -  SharePoint list name

**Returns:**
sppyte.List

*Usage:*
```py
# Given a list named 'Pets'
pets = connection.list('Pets')
```

#### Site.library(name)

Get a Library class instance.

**Parameters**
- __name__ (str): SharePoint document library name

**Returns:**
sppyte.Library

*Usage:*

```py
# Given a document library named 'Contracts'
contracts = connection.library('Contracts')
```

### List

Models a SharePoint site list.

#### List(name, site)

Create a list connection directly.

**Parameters**
- __name__ (str): SharePoint list name
- __site__ (Site): sppyte Site

**Returns:**
__List__ object

*Usage:*
```py
from sppyte import Site, List

HOST = "https://sharepoint.example.com"
SITE = "/sites/Parrots" # relative path
USER = "norweigian"
PASS = "••••••••"

# Given a list named 'Pets'
site = Site(HOST, SITE, USER, PASS)
pets = List('Pets', site)

try:
  pets.connect()
  # Do cool stuff
except HTTPError as e:
  # Deal with errors
finally:
  pets.close() # Close session

# With context managment is preferred
with List('Pets', site) as pets:
  # Do cool stuff
```

#### List.connect()

Start a connected session.

#### List.close()

Close the session.

#### List.add_item(item)

Add an item to a SharePoint list. Returns the added item ID.

**Parameters**
- __item__ (dict[str, str | int]): Item to be added

**Returns:**
int

*Usage:*

```py
# Given a item with Title and breed fields
new_item = {
  "Title": "Sonny",
  "breed": "Norwiegen Blue"
}
pet_id = pets.add_item(new_item)
```

**Notes**
- Required SharePoint metadata is added automatically.


#### List.add_attachment(sp_id, file_name, attachment)

Add an attachment to an existing list item.

**Parameters**
- __sp_id__: int - Item to append attachment
- __file_name__: str - Attachment file name (include file extension)
- __attachment__: bytes | IO[bytes] - Stream file content

**Returns:**
int - SharePoint item id

*Usage:*

```py
# Given a item with ID of 23
pet_id = 23
with open("notes.txt", "rb") as fh:
    pets.add_attachment(pet_id, "notes.txt", fh)
```

#### List.delete_item(sp_id: int)

**Parameters**
- __sp_id__: int - Item to delete

**Returns:**
bool

*Usage:*

```py
# Given a item with ID of 23
pet_id = 23
delete_success = pets.delete_item(pet_id)
```

#### List.get_contents(params)

Get contents of a SharePoint list

**Parameters**
__params__: dict[str, str | int] - OData params

**Returns:**
list[dict[str, str | int]] - JSON decoded list items

*Usage:*
```py
pet_items = pets.get_contents({
    "$select": "Id,Title,Created",
    "$top": 500,
    "$orderby": "Created desc",
})
```

#### List.get_item(sp_id)

Get SharePoint list item by ID.

**Parameters**
- __sp_id__: int - SharePoint ID to retrieve

**Returns:**
dict[str, str | int] - JSON decoded item contents

*Usage:*
```py
pet_id = 23
pet_item = pets.get(pet_id)
```

#### List.update_item(sp_id: int, patch: dict)

Update an existing list item merging properties from a patch.

**Parameters**
- __sp_id__: int - SharePoint ID to update
- __patch__: dict[str, str | int] - Dictionary of fields and values to update

**Returns:**
int - Updated SharePoint ID

*Usage:*
```py
pet_id = 23
patch = {
  "Title": "Polly",
}
pets.update_item(pet_id, patch)
```

### Library

Models a SharePoint site document library.

#### Library(name, site)

Create a document library connection directly.

**Parameters**
- __name__ (str): SharePoint library name
- __site__ (Site): sppyte Site

**Returns:**
__Library__ object

*Usage:*
```py
from sppyte import Site, Library

HOST = "https://sharepoint.example.com"
SITE = "/sites/Parrots" # relative path
USER = "norweigen"
PASS = "••••••••"

# Given a document library named 'Contracts'
site = Site(HOST, SITE, USER, PASS)
contracts = Library('Contracts', site)

try:
  contracts.connect()
  # Do cool stuff
except HTTPError as e:
  # Deal with errors
finally:
  constracts.close() # Close session

# With context managment is preferred
with Library('Contracts', site) as contracts:
  # Do cool stuff
```

#### Library.connect()

Start a connected session.

#### Library.close()

Close the session.

#### Library.add_folder(folder, \*subfolders)

Add a folder to a SharePoint document library.

**Parameters**
- __folder__: str - folder to add
- __*subfolders__: str - additional path folder names for nested folders

**Returns:**
bool - Add succeeded

*Usage:*
```py
contracts.add_folder('2025', 'January')
```

#### Library.add_document(file_name, document, \*subfolders)

Load a document to a SharePoint document library.

**Parameters**
- __file_name__: str - file name add
- __document__: bytes | IO[bytes] - Streamed file content
- __*subfolders__: str - additional path folder names for nested folders

**Returns:**
str - Unique ID

*Usage:*
```py
with open("notes.txt", "rb") as file_handler:
    contracts.add_document("notes.txt", file_handler, '2025', 'January')
```

#### Library.folder_exists(folder, \*subfolders)

Check if a folder exists in a SharePoint document library.

**Parameters**
- __folder__: str - Folder to add
- __*subfolders__: str - Additional path folder names for nested folders

**Returns:**
bool - Folder exists

*Usage:*
```py
contracts.folder_exists('2025', 'January')
```

#### Library.delete_document(file_name, \*subfolders)

Delete a document from a SharePoint document library.

**Parameters**
- __file_name__: str - File name to delete
- __*subfolders__: str - Additional path folder names for nested folders

**Returns:**
bool - Delete succeeded

*Usage:*
```py
contracts.delete_document("notes.txt", '2025', 'January')
```

#### Library.delete_folder(folder, \*subfolders)

Delete a folder from a SharePoint document library.

**Parameters**
- __folder__: str - Folder to add
- __*subfolders__: str - Additional path folder names for nested folders

**Returns:**
bool - Delete succeeded

*Usage:*
```py
contracts.delete_folder('2025', 'January')
```

#### Library.list_contents(params, \*folders)

List contents of a SharePoint document library.

**Parameters**
- __params__: dict[str, str | int] - OData params
- __*folders__: str - Additional path folder names for nested folders

**Returns:**
list[dict[str, Any]] - JSON decoded list metadata

*Usage:*
```py
files = contracts.list_contents({
    "$select": "Name,TimeCreated"
  }, "January", "2025")
```

#### Library.get_document(file_name, \*subfolders)

Read a document from a SharePoint document library.

**Parameters**
- __file_name__: str - File name to delete
- __*subfolders__: str - Additional path folder names for nested folders

**Returns:**
bytes - Streamed contents

*Usage:*
```py
document = constracts.get_document("notes.txt", "2025", "January")
contents = document.decode()
```

## Errors

- `SessionError`: raised when an HTTP session isn’t available.
- `ResponseFormatError`: raised when an expected JSON field is missing
  (e.g., FormDigestValue, ListItemEntityTypeFullName, ID, UniqueId).

Handle them as you would any exception:

```py
from sppyte import ResponseFormatError, SessionError

try:
    ...
except (ResponseFormatError, SessionError) as e:
    print("Sppyte error:", e)
```

### Extension methods 

SharePoint REST services endpoints not explicitly implemented can be accessed through the `request` method exposed on `Site`. This methods uses authentication from the current Site session and shadows `request` from the requests library, using a site relative url.

The `get_form_digest` method is provided to obtain the bearer token passed in the `X-RequestDigest` header for update requests.

List exposes the `get_item_type` method to obtain the required list item type metadata for list updates.

## Notes

- OData Parameters: Methods like get_contents and list_contents accept any OData parameters via params (e.g., $select, $filter, $orderby, $top). See [the docs](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests#odata-query-operators-supported-in-the-sharepoint-rest-service) for supported OData params.
- HTTP request errors are passed through from the requests library unhandled for transparency. See [the docs](https://requests.readthedocs.io/en/latest/user/quickstart/#errors-and-exceptions) for more information.
- SharePoint limits list responses to 100 records by default. Use the $top OData param for larger response counts.

## Contributing

This is a pet project to save me time at work and not open for contribution.

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/B-Jones-RFD/sppyte/tags).

## Authors

- **B Jones RFD** - _Package Noob_ - [B-Jones-RFD](https://github.com/B-Jones-RFD)

## License

[MIT License](https://github.com/B-Jones-RFD/sp-rest-connect/blob/main/LICENSE)
