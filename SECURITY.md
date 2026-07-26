# Security Policy

## Supported Versions

Only the most recent published [release](https://github.com/disposabledominik/wiim-rew-sync/releases)
and the latest state of the `development` branch (and `main`, once synced from `development`) are
supported. Older tags do not receive fixes — please confirm the issue is present on the latest
release or commit before reporting it.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for a security vulnerability. Instead, use GitHub's
private vulnerability reporting: go to the repository's **Security** tab → **Report a vulnerability**.
This lets the report and any fix be reviewed privately before disclosure.

Since this tool writes configuration to devices on your local network (see the safety protocol in
[docs/architecture.md](docs/architecture.md)), please include any details relevant to device safety
(e.g. a malformed or spoofed device response triggering the issue) in your report.
