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
- **Host.** sppyte builds every request URL from the configured host and site. `Site.get_page` refuses a `next_link` on another scheme or host with `ConfigurationError`.
- **TLS.** Certificate verification is on by default. `verify` (a CA bundle path, or `False`) and `cert` change it for one `Site`'s session only. `verify=False` is the caller's choice and is not recommended.
- **Files.** Uploads read only the path, file object or bytes the caller passes. `download(…, dest)` writes only to the path or file object the caller passes. sppyte creates no temporary files.
