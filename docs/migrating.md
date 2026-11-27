# Migrating

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
