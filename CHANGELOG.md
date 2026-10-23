# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/B-Jones-RFD/sppyte/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/B-Jones-RFD/sppyte/compare/v0.1.7...v0.2.0
