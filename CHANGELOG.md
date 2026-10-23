# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-23

### Changed

- Authentication is now handled by sppyte's own `SpPremAuth` (`sppyte.auth`), built directly on
  [pyspnego](https://pypi.org/project/pyspnego/). `requests-ntlm`, unmaintained since 2024, is no
  longer a dependency; runtime dependencies are `requests`, `pyspnego` and `cryptography`.
  Behaviour for existing NTLM users is unchanged.
- `Site.username` / `password` are optional (defaults `None`); `Site.principal` is `None` for
  single sign-on or a custom `auth`.

### Added

- Kerberos / Negotiate: `Site(..., protocol="negotiate")` (or `"kerberos"`), with or without
  credentials; single sign-on uses SSPI on Windows or the current ticket elsewhere.
  `pip install "sppyte[kerberos]"` adds the GSSAPI bindings for Linux/macOS.
- `Site(auth=...)` accepts any `requests.auth.AuthBase`.
- TLS channel bindings (`tls-server-end-point`) are sent over HTTPS for servers with Extended
  Protection (`SpPremAuth(send_cbt=False)` to disable).
- Handshake tests against an in-process fake NTLM server (`tests/fake_ntlm.py`).

## [1.0.0] - 2026-10-23

First stable release. Identical in code to 1.0.0b2, which was verified against an on-premises
SharePoint farm. Everything below under 1.0.0a1 through 1.0.0b2 applies, relative to 0.2.0; the
"Migrating to 1.0" section of the README summarises the breaking changes.

### Changed

- Development status classifier is now Production/Stable.

## [1.0.0b2] - 2026-10-23

### Changed

- Importing `sppyte.models` and calling `utils.parse_add_item` / `parse_add_document` now emit
  `DeprecationWarning`.
- All docstrings follow Google style (PEP 257), enforced by ruff's `pydocstyle` rules; `mypy`
  requires fully typed definitions in `sppyte`.

### Added

- Documentation site built with MkDocs (`hatch run docs:serve`), published to GitHub Pages.
- `Site.__exit__` is fully typed; `JSON_NOMETADATA` / `JSON_VERBOSE` constants in `sppyte.odata`.
- CI: `hatch fmt --check` (CI no longer silently reformats), `fail-fast: false`, least-privilege
  `permissions`, concurrency cancellation, a build + `twine check` job; the publish
  workflow verifies the release tag matches the package version and lints/type-checks/tests
  before building; Dependabot for GitHub Actions and pip.

## [1.0.0b1] - 2026-10-23

First beta: the planned 1.0 feature set is complete.

### Added

- Opt-in retry: `Site(retry=True | RetryOptions(...))` retries reads (`GET` requests, `get_page`, CAML
  `query`) on connection errors, timeouts and HTTP 429/502/503/504 with exponential backoff and full
  jitter, honouring `Retry-After` (and stopping when it exceeds `max_delay`). Writes and `$batch` are
  never retried. `Site.request(retry=...)` overrides per call. `sppyte.retry` exposes `RetryOptions`,
  `is_transient`, `with_retry`, `RETRYABLE_STATUSES`.

## [1.0.0a3] - 2026-10-23

### Added

- CAML queries: `List.query(view_xml, *, paging_info=None, params=None, digest=None)` (``GetItems``),
  `List.iter_query` and `List.query_all`, which page by the last item's `Id` using `<RowLimit>`.
- `$batch`: `Site.batch()` returns a `Batch` builder (`get` / `post` / `merge` / `patch` / `delete` / `add`,
  `send()`); consecutive writes share one changeset; one `BatchResponse` per sub-request with
  `status`, `ok`, `headers`, `body`, `json` and `error`. Sub-requests must be on the site's host.
  `sppyte.batch` also exposes `build_batch_body`, `parse_batch_response`, `multipart_boundary`.
- Public REST path helpers: `List.path`, `Library.folder_path(*subfolders)`,
  `Library.file_path(file_name, *subfolders)`.

## [1.0.0a2] - 2026-10-23

### Changed (breaking)

- `Library.add_folder` returns the `SP.Folder` object (`dict`) instead of the `Exists` bool.
- `Library.add_document` returns the `SP.File` object (`dict`) instead of the `UniqueId` string.
- `List.add_attachment` returns the `SP.Attachment` object (`dict`) instead of echoing `sp_id`.
- `List.get_contents` and `Library.list_contents` return a `Page` (a `list` subclass with `next_link`).
- `Library.get_document` sends `Accept: application/octet-stream`.

### Added

- Paging: `Page`, `Site.get_page(next_link)` (same-host only), `List.iter_pages` / `iter_items` / `get_all_items`,
  `Library.iter_pages` / `iter_files` / `get_all_files`, all with `max_pages=`.
- `Library.list_folders(*subfolders, params=None)`.
- Streaming downloads: `Library.iter_document(...)` and `Library.download(file_name, dest, *subfolders)`.
- `Library.add_document` accepts a path (`str` / `os.PathLike`) and streams it; new `overwrite=` keyword.
- `sppyte.odata.parse_page` / `follow_pages`; `sppyte.utils.parse_object`.
- `ruff` is pinned for `hatch fmt` so local and CI lint agree.


## [1.0.0a1] - 2026-10-23

### Changed (breaking)

- `List.add_item` returns the created item as a `dict` (including `Id`) instead of the integer ID.
- `Library.list_contents(params, *subfolders)` is now `list_contents(*subfolders, params=None)`; `params` is keyword-only.
- `List` and `Library` are no longer context managers and have no `connect()` / `close()`; the `Site` is the sole owner of the HTTP session.
- Non-2xx responses raise `SharePointError` (or `AuthError` for 401/403) instead of a bare `requests.HTTPError`. Both subclass `requests.HTTPError`, so existing handlers keep working. `SharePointError` exposes `status`, `code`, `message`, `retry_after` and `response`.
- Requests time out after 30 seconds by default (`Site(timeout=...)`; `None` disables).
- `Site(...)`, `site.list()` and `site.library()` no longer perform network I/O; the session is created on first request and the form digest on first write (or `connect()`).
- `Site.form_digest` is a read-only property.
- `List.add_attachment` sends `Content-Type: application/octet-stream`.
- `Site` validates its arguments and raises `ConfigurationError` (a `ValueError`) for a scheme-less or path-bearing `host`, a `site_relative_url` without a leading `/`, a full URL as the relative URL, or an empty username.

### Added

- Managed form digest: cached until shortly before SharePoint's `FormDigestTimeoutSeconds`, shared between threads with a lock, refreshed and the write retried once on 403 when the body can be re-sent (a non-seekable stream is not retried). `Site.digest()`, `Site.invalidate_digest()`.
- `digest=` keyword on every write method to supply your own digest (sent as-is, no retry).
- `List.item_type` cached property; the entity type is looked up once per `List` instead of on every write.
- `Site(domain=...)` for the NTLM domain, `verify=` / `cert=` TLS options, and `session=` to supply a pre-configured `requests.Session`.
- `Site.request(..., digest=True | "value")` for extension calls that need a digest.
- `Library.server_relative_url(*parts)`.
- Exceptions `SppyteError`, `ConfigurationError`, `AuthError`, `SharePointError`, `SharePointErrorDetails`; helpers `sppyte.errors.parse_sharepoint_error`, `parse_retry_after`, `raise_for_status`.
- `sppyte.utils.parse_context_info` and `parse_created_item`.
- `__repr__` on `Site`, `List` and `Library` (password not shown).
- Modules `sppyte.site`, `sppyte.lists`, `sppyte.libraries`, `sppyte.odata`; `sppyte.models` remains as a re-export shim.

### Fixed

- A write rejected with 403 for a stale digest is now retried with a **fresh** digest; previously the stale header was re-sent.
- Replaying a request with a consumed file body is no longer attempted (it sent an empty body).

### Deprecated

- `sppyte.models` (import from `sppyte`), `SessionError` (no longer raised), `sppyte.utils.parse_add_item` (superseded by `parse_created_item`).

## [0.2.0] - 2026-10-23

### Fixed

- `Library.delete_folder` built the path `_api/web/_api/web/...` and failed on every call.
- `Library.add_folder` sent a library-relative `ServerRelativeUrl`; it now includes the site
  relative URL like every other `Library` method, so it works on sub-sites (`/sites/...`).
- List titles, file names and folder paths are now escaped for OData string literals
  (apostrophes doubled, segments percent-encoded), so names containing `'`, `#`, `%`, `?`
  or `&` no longer break the request URL.
- `List.add_item` and `List.update_item` no longer modify the mapping passed in.
- `Site.session` and `Site.form_digest` are instance attributes instead of class attributes.
- The `Params` type alias now matches what the methods accept (a mapping or a sequence of
  pairs), and `get_contents` / `list_contents` are typed as returning `list[dict]`.
- pytest no longer puts `src/sppyte` itself on `sys.path`.

### Added

- `sppyte.utils.odata_literal` and `sppyte.utils.odata_path` escaping helpers.
- `py.typed` marker so type checkers use the package's annotations.
- `CHANGELOG.md`.
- Test coverage of `Site`, `List` and `Library` against a mocked HTTP layer (`responses`).

### Changed

- `Library.add_document` is typed to accept `bytes | IO[bytes]` (it always did; the README
  said so but the signature did not).
- `List.add_item` / `List.update_item` accept any `Mapping`, not just `dict`.

[Unreleased]: https://github.com/B-Jones-RFD/sppyte/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0b2...v1.0.0
[1.0.0b2]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0b1...v1.0.0b2
[1.0.0b1]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0a3...v1.0.0b1
[1.0.0a3]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0a2...v1.0.0a3
[1.0.0a2]: https://github.com/B-Jones-RFD/sppyte/compare/v1.0.0a1...v1.0.0a2
[1.0.0a1]: https://github.com/B-Jones-RFD/sppyte/compare/v0.2.0...v1.0.0a1
[0.2.0]: https://github.com/B-Jones-RFD/sppyte/compare/v0.1.7...v0.2.0
