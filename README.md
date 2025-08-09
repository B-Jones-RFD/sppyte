# sppyte

Perform common tasks with SharePoint REST service.

# Model

This library supports working with on premise SharePoint site Lists and Document Libraries.
Abstrations are available for adding, updating, and removing items from lists or files from
libraries. The model mirrors these SharePoint entities providing site connection sessions
for authenticating and working with a site.

## Site

Represents a SharePoint site. Since permissions are typically managed at a site level, sessions
are created for connections to a specifc site. If you need to connect to a Document Library or List with
unique permissions see these examples below.

### Planned API

```py
class Site:
    connect: () -> None # Start a connection session
    list: (name: str) -> List # Create a list connection
    library: (name: str) -> Library # Create a library connection

class List:
    add: (item: str) -> int # Add list item, returns SharePoint ID
    add_attachment: (id: int, attachment) -> int # Add attachment to List Item, returns SharePoint ID
    delete: (id: int) -> None: # Delete a list item
    update: (id: int, item: str) -> int # Update a list item
    get: (id: int) -> None: # Get list item
    get_contents: () -> List: # Get list contents

class Library:
    add: (folder: str, file_name: str, document) -> bool # Add document to Library
    add_folder: (folder: str) -> bool # Add folder to Library
    delete_documen: (folder: str, file_name: str) -> bool # Delete document from Libary
    get: (folder: str, file_name: str) -> document
    get_contents: (folder: str) -> List
```

### Planned Usage

The library exposes a help

```py

import sppyte

def get_list_contents():
    host = 'https://my.sharepoint.site.com'
    site_relative_url = '/sites/path/to/mysite'
    username = 'parrot'
    password = 'norwegian_blue'

    with sppyte.site_connection(host, site_relative_url, username, password) as session:
        contents = session.list('deceased').get()
        return contents
```
