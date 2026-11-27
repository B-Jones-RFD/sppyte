# Security policy

## Supported versions

Security fixes go into the latest release of the current major version.

| Version | Supported |
|---|---|
| 1.x | Yes |
| older | No |

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (<https://github.com/B-Jones-RFD/sppyte/security/advisories/new>). Do not open a public issue.

## Scope

- **Credentials.** `Site` and `SpPremAuth` keep the username and password in memory for the life of the object. sppyte does no logging and never writes credentials to disk; `repr()` shows the username but not the password. Without a password, single sign-on uses the current user's Kerberos ticket (SSPI on Windows), through pyspnego.
- **Host.** sppyte sends credentials only to the host the `Site` was created for: every request URL is built from it, `Site.get_page` and `Batch` refuse links and sub-requests on another scheme or host with `ConfigurationError`, and the NTLM/Kerberos handshake is not answered for a host a redirect leads to. An `auth` handler passed to `Site`, or one already set on a `session` passed to it, is the caller's own: the redirect check is part of sppyte's `SpPremAuth` and does not apply to it.
- **Proxies.** In 1.x a proxy that answers `407` with an NTLM or Negotiate challenge still receives the SharePoint credentials, with a `DeprecationWarning`; this is removed in 2.0. Configure proxy credentials on a `requests.Session` passed to `Site` instead.
- **TLS.** Certificate verification is on by default. `verify` (a CA bundle path, or `False`) and `cert` change it for one `Site`'s session only. `verify=False` is the caller's choice and is not recommended.
- **Files.** Uploads read only the path, file object or bytes the caller passes. `download(…, dest)` writes only to the path or file object the caller passes. sppyte creates no temporary files.
